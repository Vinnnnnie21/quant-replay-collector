# Stability Policy

## Data Safety

Local databases, exported studies and user settings are never deleted by application startup or clean-release generation. Git ignores local databases, caches, logs, settings and backup folders.

SQLite schema migrations are additive. Version 3 adds indexes only. Connections enable `PRAGMA foreign_keys=ON`, WAL, `synchronous=NORMAL` and a 5 second busy timeout. This setting does not imply that every legacy table declares a foreign-key constraint. A persistent database lock is surfaced as a readable retry message.

## Failure Handling

- Invalid `app_settings.json` and `theme_settings.json` load defaults and preserve a timestamped `.broken.json` copy.
- Logging configuration occurs during application startup, not during import. If a log file cannot be created, logging falls back without preventing startup.
- Kline downloads use retries and cache fallback. Invalid OHLC, negative volume, duplicate, missing or out-of-order bars are recorded in data-quality results.
- Non-GUI market-data modules are separated from pyqtgraph and Qt workers, so quality and cache behavior can be tested without creating a desktop window.
- Background export failures are returned to the UI and restore the export button state.

## Health Check

```powershell
python quant_collector_app/self_check.py --core
```

不带参数时默认执行 `--core`。核心模式使用临时文件验证核心依赖、可写运行目录、SQLite 初始化、事件存储和 CSV 导出；缺少 Parquet 引擎只产生 warning。安装桌面依赖后，可执行：

```powershell
python quant_collector_app/self_check.py --gui
python quant_collector_app/self_check.py --all
```

`--gui` 检查 `PySide6`、`pyqtgraph` 和离屏 Qt 应用初始化；`--all` 同时报告核心与 GUI 检查结果。
