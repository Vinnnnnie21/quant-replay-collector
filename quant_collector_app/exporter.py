from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from accounting import build_equity_curve
from app_config import APP_VERSION, BJT, DEFAULT_INITIAL_EQUITY, DEFAULT_TRADE_NOTIONAL, EXPORT_DIR
from app_logger import get_logger
from analysis.binning import build_binning_report
from analysis.data_audit import audit_export_tables, write_audit_report
from analysis.feature_engineering import build_enhanced_event_features
from analysis.label_builder import build_strategy_labels
from analysis.report_writer import write_strategy_research_report
from analysis.rule_mining import generate_candidate_rules
from dataset_builder import build_ml_datasets
from event_study import build_event_study_summary
from performance import build_performance_summary, flatten_performance_summary
from strategy_consistency.consistency import analyze_strategy_consistency
from strategy_consistency.profile import default_reversal_long_profile
from strategy_consistency.report import write_strategy_consistency_report
from time_series_analysis.regime import build_regime_features
from time_series_analysis.report import build_time_series_report, write_time_series_report
from time_series_analysis.returns import build_event_window_return_series, build_return_series


logger = get_logger(__name__)

LABEL_COLUMNS = [
    "fwd_ret_1",
    "fwd_ret_3",
    "fwd_ret_5",
    "fwd_ret_10",
    "fwd_ret_1_side_adj",
    "fwd_ret_3_side_adj",
    "fwd_ret_5_side_adj",
    "fwd_ret_10_side_adj",
    "mfe_10",
    "mae_10",
    "manual_trade_final_return_pct",
    "manual_trade_holding_bars",
]


class Exporter:
    def __init__(self, storage):
        self.storage = storage

    def _to_df(self, rows):
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def _drop_available(self, df: pd.DataFrame, columns: set[str] | list[str]):
        return df.drop(columns=[c for c in columns if c in df.columns], errors="ignore")

    def _sort_df(self, name: str, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        sort_keys = {
            "trades": ["created_at", "trade_id"],
            "trade_events": ["created_at", "event_id"],
            "event_windows_long": ["event_id", "offset"],
            "event_features": ["created_at", "event_id"],
            "event_labels": ["event_id"],
            "event_features_full": ["created_at", "event_id"],
            "performance_summary": ["session_id"],
            "account_equity": ["sequence_no", "trade_id"],
            "event_study_summary": ["label_tag", "event_type", "side"],
            "enhanced_event_features": ["event_id"],
            "strategy_labels": ["event_id"],
            "feature_binning_summary": ["feature", "label", "bin_left"],
            "candidate_rules": ["sample_count", "win_rate_pct"],
            "time_series_returns": ["bar_index"],
            "time_series_regimes": ["bar_index"],
            "ml_features": ["created_at", "event_id"],
            "ml_labels": ["event_id"],
            "sample_index": ["created_at", "event_id"],
            "sessions": ["last_saved_at", "session_id"],
            "usdt_premium_history": ["sample_time_bjt", "id"],
        }
        keys = [c for c in sort_keys.get(name, []) if c in df.columns]
        return df.sort_values(keys).reset_index(drop=True) if keys else df.reset_index(drop=True)

    def _build_event_wide(self, windows: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
        if windows.empty:
            return pd.DataFrame(columns=["event_id"])

        base_cols = ["event_id", "offset", "open", "high", "low", "close", "volume", "bar_index", "bar_open_time_bjt"]
        missing = [c for c in base_cols if c not in windows.columns]
        if missing:
            raise ValueError(f"event_windows 缺少导出宽表所需字段：{', '.join(missing)}")

        w = windows[base_cols].copy()
        w["slot"] = w["offset"].apply(
            lambda x: "event_0" if int(x) == 0 else (f"pre_{abs(int(x))}" if int(x) < 0 else f"post_{int(x)}")
        )
        wide = w.pivot(index="event_id", columns="slot")
        wide.columns = [f"{col2}_{col1}" for col1, col2 in wide.columns]
        wide = wide.reset_index()
        if not events.empty and "event_id" in events.columns:
            wide = events.merge(wide, on="event_id", how="left")
        return wide.sort_values("event_id").reset_index(drop=True)

    def _write_dataframes(self, export_dir: Path, tables: dict[str, pd.DataFrame]) -> dict:
        files = {}
        for name, df in tables.items():
            csv_name = f"{name}.csv"
            parquet_name = f"{name}.parquet"
            csv_path = export_dir / csv_name
            parquet_path = export_dir / parquet_name

            df.to_csv(csv_path, index=False)
            info = {"csv": csv_name, "parquet": parquet_name, "parquet_status": "ok"}
            try:
                df.to_parquet(parquet_path, index=False)
            except Exception as e:
                logger.warning("Parquet 写入失败，CSV 已保留：%s", parquet_path, exc_info=True)
                info["parquet_status"] = "failed"
                info["parquet_error"] = f"{type(e).__name__}: {e}"
                info.pop("parquet", None)
            files[name] = info
        return files

    def _write_manifest(self, export_dir: Path, session_id: str, sessions: pd.DataFrame, tables: dict[str, pd.DataFrame], files: dict):
        session_row = sessions.iloc[0].to_dict() if not sessions.empty else {}
        manifest = {
            "app_version": APP_VERSION,
            "session_id": session_id,
            "symbol": session_row.get("symbol"),
            "interval": session_row.get("interval"),
            "export_time": datetime.now(BJT).isoformat(timespec="seconds"),
            "row_counts": {name: int(len(df)) for name, df in tables.items()},
            "files": files,
        }
        manifest["files"]["export_manifest"] = {"json": "export_manifest.json"}
        manifest["files"]["data_dictionary"] = {"markdown": "data_dictionary.md"}
        (export_dir / "export_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest

    def _empty_df(self, columns: list[str] | None = None) -> pd.DataFrame:
        return pd.DataFrame(columns=columns or [])

    def _safe_analysis_df(self, name: str, builder, fallback_columns: list[str] | None = None) -> pd.DataFrame:
        try:
            result = builder()
            return result if isinstance(result, pd.DataFrame) else self._empty_df(fallback_columns)
        except Exception as e:
            logger.warning("分析模块生成失败：%s: %s", name, e, exc_info=True)
            return self._empty_df(fallback_columns)

    def _write_records_json(self, export_dir: Path, files: dict, name: str, df: pd.DataFrame):
        json_name = f"{name}.json"
        path = export_dir / json_name
        records = [] if df.empty else df.where(pd.notna(df), None).to_dict("records")
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        files.setdefault(name, {})["json"] = json_name

    def _kline_from_event_windows(self, windows: pd.DataFrame) -> pd.DataFrame:
        columns = ["bar_index", "open_time_bjt", "open", "high", "low", "close", "volume"]
        if windows is None or windows.empty:
            return pd.DataFrame(columns=columns)
        required = ["bar_index", "open", "high", "low", "close", "volume"]
        missing = [c for c in required if c not in windows.columns]
        if missing:
            return pd.DataFrame(columns=columns)
        df = windows.copy()
        if "open_time_bjt" not in df.columns and "bar_open_time_bjt" in df.columns:
            df["open_time_bjt"] = df["bar_open_time_bjt"]
        if "open_time_bjt" not in df.columns:
            df["open_time_bjt"] = ""
        return (
            df[columns]
            .sort_values("bar_index")
            .drop_duplicates("bar_index")
            .reset_index(drop=True)
        )

    def _write_data_dictionary(self, export_dir: Path, tables: dict[str, pd.DataFrame]):
        descriptions = {
            "trades": ("手动交易记录", "每一笔开仓/平仓后的交易级记录，包括方向、状态、入场/出场时间、代理价格、持仓 bar 和最终收益。"),
            "trade_events": ("事件记录", "开仓、平仓等事件级记录，包含事件标签、备注、事件所在 K 线和代理价格。"),
            "event_windows_long": ("事件窗口长表", "默认保存事件前 20 根、事件后 20 根 K 线；offset 为负表示事件前，0 表示事件 bar，正数表示事件后。"),
            "event_wide": ("事件窗口宽表（建模输入版）", "以 event_id 为一行展开事件窗口，默认移除 post_* 未来窗口字段，降低建模时未来函数误用风险。"),
            "event_wide_full": ("事件窗口宽表（完整版）", "包含 pre_*、event_0 和 post_* 字段，适合人工复盘或标签分析，不建议直接作为模型输入。"),
            "event_features": ("事件特征（建模输入版）", "事件 bar 和事件前序走势提取的特征，默认不含未来收益、MFE/MAE 或人工最终结果字段。"),
            "event_labels": ("事件标签/结果字段", "从 event_features 拆出的未来收益、方向调整收益、MFE/MAE 和人工交易结果字段。"),
            "event_features_full": ("事件特征（完整版）", "包含输入特征和结果标签的完整特征表，适合审计和复盘。"),
            "performance_summary": ("交易绩效汇总", "基于手动回放交易记录生成的一行统计，包括总交易数、胜率、平均收益、最大盈利/亏损、平均持仓 K 线数、分方向统计和最近一次交易结果。"),
            "account_equity": ("账户权益曲线", "基于手动回放交易、成交模型、手续费和滑点参数生成的已实现权益曲线，不包含未平仓浮动盈亏。"),
            "event_study_summary": ("事件研究汇总", "按标签、事件类型、方向分组统计未来收益、方向调整收益、MFE/MAE 的样本数、均值、中位数和胜率。"),
            "enhanced_event_features": ("主观反转策略增强特征", "仅使用事件前 K 线和事件 K 线生成的可解释特征，用于研究大跌、承接、下影线、收回前低等主观概念。"),
            "strategy_labels": ("策略研究标签", "从未来收益、MFE/MAE 等结果字段构建的胜负、强反弹、失败反转、好交易/坏交易标签，不可作为模型输入。"),
            "feature_binning_summary": ("特征分箱分析", "按特征分位数分箱统计标签表现，帮助探索主观概念的量化边界。"),
            "candidate_rules": ("候选规则", "基于分位数阈值生成的单条件或双条件候选假设，只用于后续验证，不是交易信号。"),
            "ml_features": ("机器学习输入特征", "严格移除 fwd_*、MFE/MAE、人工交易结果等未来/标签字段后的样本输入候选。"),
            "ml_labels": ("机器学习标签", "未来收益、方向调整收益、MFE/MAE 和人工交易结果字段，不应作为模型输入。"),
            "sample_index": ("样本索引", "事件样本的稳定索引和元信息，用于连接特征、标签、原始事件和窗口。"),
            "sessions": ("会话记录", "当前导出 session 的品种、周期、日期范围、光标位置、速度和版本信息。"),
            "usdt_premium_history": ("USDT 溢价历史", "本地记录的 USDT/CNY P2P 价格、USD/CNY 汇率和溢价率采样。"),
        }
        lines = [
            "# Export Data Dictionary",
            "",
            "本文件由 Quant Replay Collector 导出时自动生成，用于说明导出目录中各文件的用途和主要字段。",
            "",
            "CSV 是保底格式；Parquet 是附加格式，若本机缺少可用 Parquet 引擎或写入失败，不影响 CSV 导出。",
            "",
        ]
        for name, df in tables.items():
            title, detail = descriptions.get(name, (name, "导出数据表。"))
            columns = ", ".join(df.columns.astype(str).tolist()) if len(df.columns) else "空表暂无列"
            lines.extend([
                f"## {name}",
                "",
                f"- 用途：{title}。",
                f"- 说明：{detail}",
                f"- 行数：{len(df)}",
                f"- 主要字段：{columns}",
                "",
            ])
        lines.extend([
            "## analysis_audit.json / analysis_audit.md",
            "",
            "- 用途：数据审计报告。",
            "- 说明：记录样本量、重复 `event_id`、缺失值、标签完整性、未来函数泄漏风险和样本量警告。",
            "",
            "## strategy_research_report.md",
            "",
            "- 用途：策略研究 Markdown 报告。",
            "- 说明：汇总数据质量、事件研究、特征分箱、候选规则、绩效摘要、未来函数隔离说明和研究限制。",
            "",
            "## feature_binning_summary.json / candidate_rules.json",
            "",
            "- 用途：给脚本或本地 API 读取的 JSON 版本分析结果。",
            "- 说明：内容与对应 CSV 保持一致，便于后续接入本地分析工具或大模型摘要上下文。",
            "",
        ])
        lines.extend([
            "## 字段使用提醒",
            "",
            "- `event_features.csv` 和 `event_wide.csv` 默认作为建模输入候选。",
            "- `ml_features.csv` 是更严格的建模输入候选，禁止包含 `fwd_*`、`post_*`、MFE/MAE 和人工最终交易结果字段。",
            "- `event_labels.csv`、`event_features_full.csv`、`event_wide_full.csv` 含有结果或未来窗口信息，建模时应谨慎使用。",
            "- `strategy_labels.csv`、`feature_binning_summary.csv`、`candidate_rules.csv` 都属于研究输出，不是实时交易建议。",
            "- `strategy_research_report.md` 是统计解释报告，不能把样本内结果当成确定盈利。",
            "- `price_proxy` 当前为事件 K 线 `high` 与 `low` 的中间价代理，不代表真实成交价。",
            "- 成交价、手续费、滑点和权益曲线均为回放研究口径，不代表真实账户成交或收益。",
            "- 本导出数据仅用于交易训练、复盘和研究，不构成投资建议。",
            "",
        ])
        (export_dir / "data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")

    def _append_data_dictionary_notes(self, export_dir: Path) -> None:
        notes = (
            "\n## strategy_consistency.json / strategy_consistency_report.md\n\n"
            "- 用途：策略一致性审计输出。\n"
            "- 说明：用于判断人工交易样本是否来自相对稳定的交易逻辑，是否适合继续做特征分析、规则挖掘和回测。\n"
            "- 注意：策略一致性不等于策略有效性，不构成投资建议。\n"
            "- 导出报告当前主要为中文，完整英文报告后续完善。\n"
            "\n## time_series_returns.csv / time_series_regimes.csv / time_series_summary.json / time_series_report.md\n\n"
            "- 用途：基础金融时间序列分析输出。\n"
            "- 说明：包含收益率分布、滚动波动率、回撤、市场状态、随机事件基准摘要。\n"
            "- 数据源：当前版本优先使用 event_windows_long 构建局部事件窗口级时间序列，source=event_windows_only；完整 session K 线后续再接入。\n"
            "- 注意：统计结果只用于研究，不构成投资建议。\n"
        )
        path = export_dir / "data_dictionary.md"
        path.write_text(path.read_text(encoding="utf-8") + notes, encoding="utf-8")

    def export_session(self, session_id: str, export_root: Path | str | None = None):
        export_root = Path(export_root or EXPORT_DIR)
        export_dir = export_root / f"session_{session_id}"
        export_dir.mkdir(parents=True, exist_ok=True)
        logger.info("开始导出 session=%s 到 %s", session_id, export_dir)

        trades = self._to_df(self.storage.fetch_table("trades", "session_id=?", (session_id,)))
        events = self._to_df(self.storage.fetch_table("trade_events", "session_id=?", (session_id,)))
        windows = self._to_df(self.storage.fetch_table("event_windows", "session_id=?", (session_id,)))
        features = self._to_df(self.storage.fetch_table("event_features", "session_id=?", (session_id,)))
        sessions = self._to_df(self.storage.fetch_table("sessions", "session_id=?", (session_id,)))
        equity = self._to_df(self.storage.fetch_table("account_equity", "session_id=?", (session_id,)))
        premium = self._to_df(self.storage.fetch_table("usdt_premium_history"))

        raw_tables = {
            "trades": trades,
            "trade_events": events,
            "event_windows_long": windows,
            "event_features_full": features,
            "account_equity": equity,
            "sessions": sessions,
            "usdt_premium_history": premium,
        }
        for name, df in raw_tables.items():
            raw_tables[name] = self._sort_df(name, df)

        trades = raw_tables["trades"]
        events = raw_tables["trade_events"]
        windows = raw_tables["event_windows_long"]
        features = raw_tables["event_features_full"]
        sessions = raw_tables["sessions"]
        equity = raw_tables["account_equity"]
        premium = raw_tables["usdt_premium_history"]

        model_features = self._drop_available(features, LABEL_COLUMNS) if not features.empty else features
        label_cols = [c for c in ["event_id", "session_id", "trade_id", "event_type", "side", "symbol", "interval", *LABEL_COLUMNS] if c in features.columns]
        labels = features[label_cols].copy() if label_cols else pd.DataFrame()
        wide_full = self._build_event_wide(windows, events)
        future_cols = [c for c in wide_full.columns if c.startswith("post_")]
        wide_model = self._drop_available(wide_full, future_cols)
        session_row = sessions.iloc[0].to_dict() if not sessions.empty else {}
        initial_equity = session_row.get("initial_equity") or DEFAULT_INITIAL_EQUITY
        trade_notional = session_row.get("trade_notional") or DEFAULT_TRADE_NOTIONAL
        if equity.empty:
            equity_rows = build_equity_curve(trades.to_dict("records"), session_id, initial_equity, trade_notional)
            equity = pd.DataFrame(equity_rows)
        event_study = build_event_study_summary(events, features)
        ml_tables = build_ml_datasets(features)
        enhanced_features = self._safe_analysis_df(
            "enhanced_event_features",
            lambda: build_enhanced_event_features(windows, events),
        )
        strategy_labels = self._safe_analysis_df(
            "strategy_labels",
            lambda: build_strategy_labels(labels if not labels.empty else features),
        )
        analysis_join = enhanced_features.copy()
        if not analysis_join.empty and not strategy_labels.empty and "event_id" in analysis_join.columns and "event_id" in strategy_labels.columns:
            analysis_join = analysis_join.merge(strategy_labels, on="event_id", how="left")
        if not analysis_join.empty and not labels.empty and "event_id" in labels.columns:
            analysis_join = analysis_join.merge(labels, on="event_id", how="left", suffixes=("", "_label_raw"))
        binning_summary = self._safe_analysis_df(
            "feature_binning_summary",
            lambda: build_binning_report(enhanced_features, strategy_labels.merge(labels, on="event_id", how="left") if not strategy_labels.empty and not labels.empty and "event_id" in labels.columns else strategy_labels)["feature_binning_summary"],
        )
        candidate_rules = self._safe_analysis_df(
            "candidate_rules",
            lambda: generate_candidate_rules(analysis_join, label_col="fwd_ret_10_side_adj", min_samples=30),
        )
        time_series_source = "event_windows_only"
        time_series_skipped_reason = None
        kline_df = self._kline_from_event_windows(windows)
        if kline_df.empty:
            time_series_source = "skipped"
            time_series_skipped_reason = "no full kline data available and event_windows_long is empty"
        time_series_returns = self._safe_analysis_df(
            "time_series_returns",
            lambda: build_event_window_return_series(windows) if time_series_source == "event_windows_only" else build_return_series(kline_df),
        )
        time_series_regimes = self._safe_analysis_df(
            "time_series_regimes",
            lambda: build_regime_features(time_series_returns),
        )
        try:
            time_series_summary = build_time_series_report(
                kline_df,
                labels if not labels.empty else features,
                source=time_series_source if time_series_source != "skipped" else "event_windows_only",
                returns_df=time_series_returns,
                regime_df=time_series_regimes,
            )
            time_series_summary["source"] = time_series_source
            if time_series_skipped_reason:
                time_series_summary.setdefault("warnings", []).append(time_series_skipped_reason)
        except Exception as e:
            logger.warning("时间序列分析生成失败：%s", e, exc_info=True)
            time_series_summary = {
                "source": "skipped",
                "warnings": [f"time series analysis skipped: {type(e).__name__}: {e}"],
                "limitations": ["Statistics are not investment advice."],
            }
            time_series_skipped_reason = f"{type(e).__name__}: {e}"
        consistency_features = enhanced_features if not enhanced_features.empty else model_features
        try:
            strategy_consistency = analyze_strategy_consistency(
                events,
                consistency_features,
                trades,
                default_reversal_long_profile(),
            )
        except Exception as e:
            logger.warning("策略一致性审计生成失败：%s", e, exc_info=True)
            strategy_consistency = {
                "sample_count": 0,
                "strategy_consistency_score": 0.0,
                "recommendation": "not_suitable_for_rule_mining",
                "warnings": [f"strategy consistency skipped: {type(e).__name__}: {e}"],
            }
        performance_row = flatten_performance_summary(
            build_performance_summary(trades.to_dict("records"), equity.to_dict("records"), initial_equity),
            {
                "app_version": APP_VERSION,
                "session_id": session_id,
                "symbol": session_row.get("symbol"),
                "interval": session_row.get("interval"),
                "export_time": datetime.now(BJT).isoformat(timespec="seconds"),
            },
        )
        performance_summary = pd.DataFrame([performance_row])

        tables = {
            "trades": trades,
            "trade_events": events,
            "event_windows_long": windows,
            "event_wide": wide_model,
            "event_features": model_features,
            "event_labels": labels,
            "event_features_full": features,
            "event_wide_full": wide_full,
            "account_equity": equity,
            "event_study_summary": event_study,
            "enhanced_event_features": enhanced_features,
            "strategy_labels": strategy_labels,
            "feature_binning_summary": binning_summary,
            "candidate_rules": candidate_rules,
            "time_series_returns": time_series_returns,
            "time_series_regimes": time_series_regimes,
            "ml_features": ml_tables["ml_features"],
            "ml_labels": ml_tables["ml_labels"],
            "sample_index": ml_tables["sample_index"],
            "performance_summary": performance_summary,
            "sessions": sessions,
            "usdt_premium_history": premium,
        }
        for name, df in list(tables.items()):
            tables[name] = self._sort_df(name, df)

        files = self._write_dataframes(export_dir, tables)
        self._write_records_json(export_dir, files, "feature_binning_summary", tables["feature_binning_summary"])
        self._write_records_json(export_dir, files, "candidate_rules", tables["candidate_rules"])
        (export_dir / "performance_summary.json").write_text(
            json.dumps(performance_row, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        files["performance_summary"]["json"] = "performance_summary.json"
        audit = audit_export_tables(tables)
        write_audit_report(audit, export_dir)
        files["analysis_audit"] = {"json": "analysis_audit.json", "markdown": "analysis_audit.md"}
        try:
            (export_dir / "strategy_consistency.json").write_text(
                json.dumps(strategy_consistency, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            consistency_report = write_strategy_consistency_report(
                strategy_consistency,
                export_dir / "strategy_consistency_report.md",
            )
            files["strategy_consistency"] = {"json": "strategy_consistency.json", "markdown": consistency_report.name}
        except Exception as e:
            logger.warning("策略一致性报告写入失败：%s", e, exc_info=True)
        try:
            report_path = write_strategy_research_report(
                export_dir,
                audit,
                tables["event_study_summary"],
                tables["feature_binning_summary"],
                tables["candidate_rules"],
                performance_summary,
                {
                    "app_version": APP_VERSION,
                    "session_id": session_id,
                    "symbol": session_row.get("symbol"),
                    "interval": session_row.get("interval"),
                    "export_time": datetime.now(BJT).isoformat(timespec="seconds"),
                },
            )
            files["strategy_research_report"] = {"markdown": report_path.name}
        except Exception as e:
            logger.warning("策略研究报告生成失败：%s", e, exc_info=True)
        try:
            (export_dir / "time_series_summary.json").write_text(
                json.dumps(time_series_summary, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            ts_report = write_time_series_report(time_series_summary, export_dir / "time_series_report.md")
            files["time_series_summary"] = {
                "json": "time_series_summary.json",
                "markdown": ts_report.name,
                "source": time_series_source,
                "limitations": time_series_summary.get("limitations", []),
            }
            if time_series_skipped_reason:
                files["time_series_summary"]["skipped_reason"] = time_series_skipped_reason
        except Exception as e:
            logger.warning("时间序列分析报告写入失败：%s", e, exc_info=True)
            files["time_series_summary"] = {
                "source": "skipped",
                "skipped_reason": f"{type(e).__name__}: {e}",
            }
        self._write_data_dictionary(export_dir, tables)
        self._append_data_dictionary_notes(export_dir)
        self._write_manifest(export_dir, session_id, sessions, tables, files)
        logger.info("导出完成 session=%s 目录=%s", session_id, export_dir)

        return export_dir
