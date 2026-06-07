from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

try:
    from app_config import DB_PATH
    from errors import DatabaseError
except ImportError:  # pragma: no cover - package import path
    from .app_config import DB_PATH
    from .errors import DatabaseError
try:
    from storage_core.connection import connect_db, require_rowcount
    from storage_core import migrations
    from storage_core import event_repository
    from storage_core import market_repository
    from storage_core import premium_repository
    from storage_core import research_repository
    from storage_core import session_repository
    from storage_core import trade_repository
except ImportError:  # pragma: no cover - package import path
    from .storage_core.connection import connect_db, require_rowcount
    from .storage_core import migrations
    from .storage_core import event_repository
    from .storage_core import market_repository
    from .storage_core import premium_repository
    from .storage_core import research_repository
    from .storage_core import session_repository
    from .storage_core import trade_repository


class StorageManager:
    SCHEMA_VERSION = 5
    MANUAL_RESEARCH_TABLES = (
        "research_outcome_labels",
        "event_context_features",
        "strategy_samples",
        "observation_universe",
        "account_equity",
        "event_features",
        "event_windows",
        "trade_events",
        "trades",
        "sessions",
    )
    ALLOWED_TABLES = {
        "sessions",
        "trades",
        "trade_events",
        "event_windows",
        "event_features",
        "account_equity",
        "usdt_premium_history",
        "klines",
        "data_quality_reports",
        "strategy_profiles",
        "observation_universe",
        "strategy_samples",
        "event_context_features",
        "research_outcome_labels",
    }
    TRADE_COLUMNS = [
        "trade_id", "session_id", "symbol", "interval", "side", "status",
        "entry_event_id", "exit_event_id", "entry_bar_index", "exit_bar_index",
        "entry_bar_time_bjt", "exit_bar_time_bjt", "entry_real_time_bjt", "exit_real_time_bjt",
        "entry_price_proxy", "exit_price_proxy", "holding_bars", "final_return_pct",
        "fill_mode", "fee_bps", "slippage_bps", "notional_quote", "quantity",
        "entry_price_raw", "exit_price_raw", "entry_fill_price", "exit_fill_price",
        "entry_fee_quote", "exit_fee_quote", "gross_pnl_quote", "net_pnl_quote",
        "gross_return_pct", "net_return_pct", "fee_return_pct",
        "created_at", "updated_at",
    ]

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = str(db_path)
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
        except OSError as exc:
            raise DatabaseError(f"Database directory is not writable: {exc}") from exc

    def connect(self):
        return connect_db(self.db_path)

    def _init_db(self):
        with self.connect() as conn:
            version = migrations.schema_version(conn)
        if version > self.SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than supported version {self.SCHEMA_VERSION}."
            )
        # Version 0 databases predate migration metadata. The v1 repair is
        # idempotent and also completes partially upgraded legacy databases.
        self._migrate_to_v1()
        if version < 2:
            self._migrate_to_v2()
        self._migrate_to_v3()
        self._migrate_to_v4()
        self._migrate_to_v5()
        with self.connect() as conn:
            migrations.set_schema_version(conn, self.SCHEMA_VERSION)

    def _migrate_to_v1(self):
        with self.connect() as conn:
            migrations.migrate_to_v1(conn)

    def _migrate_to_v2(self):
        with self.connect() as conn:
            migrations.migrate_to_v2(conn)

    def _migrate_to_v3(self):
        with self.connect() as conn:
            migrations.migrate_to_v3(conn)

    def _migrate_to_v4(self):
        with self.connect() as conn:
            migrations.migrate_to_v4(conn)

    def _migrate_to_v5(self):
        with self.connect() as conn:
            migrations.migrate_to_v5(conn)

    def schema_version(self) -> int:
        with self.connect() as conn:
            return migrations.schema_version(conn)

    def _ensure_column(self, conn, table: str, column: str, column_type: str):
        migrations.ensure_column(conn, table, column, column_type)

    def _require_rowcount(self, cursor, expected: int, message: str):
        require_rowcount(cursor, expected, message)

    def _insert_trade_row(self, conn, row: dict[str, Any]):
        trade_repository.insert_trade_row(conn, row, self.TRADE_COLUMNS)

    def upsert_session(self, row: dict[str, Any]):
        with self.connect() as conn:
            session_repository.upsert_session(conn, row)

    def get_latest_session(self):
        with self.connect() as conn:
            return session_repository.get_latest_session(conn)

    def clear_manual_research_records(self) -> dict[str, int]:
        """Delete manually recorded trade research data while retaining market data."""
        with self.connect() as conn:
            return session_repository.clear_manual_research_records(conn, self.MANUAL_RESEARCH_TABLES)

    def insert_trade(self, row: dict[str, Any]):
        with self.connect() as conn:
            self._insert_trade_row(conn, row)

    def update_trade_close(self, row: dict[str, Any]):
        with self.connect() as conn:
            trade_repository.update_trade_close(conn, row)

    def reopen_trade(self, row: dict[str, Any]):
        with self.connect() as conn:
            trade_repository.reopen_trade(conn, row)

    def delete_trade(self, trade_id: str):
        with self.connect() as conn:
            trade_repository.delete_trade(conn, trade_id)

    def insert_event(self, row: dict[str, Any]):
        with self.connect() as conn:
            event_repository.insert_event(conn, row)

    def update_event_labels(self, event_id: str, label_tags: list[str], note: str):
        with self.connect() as conn:
            event_repository.update_event_labels(conn, event_id, label_tags, note)

    def delete_event(self, event_id: str):
        with self.connect() as conn:
            event_repository.delete_event(conn, event_id)

    def save_event_windows(self, session_id: str, event_id: str, rows: Iterable[dict[str, Any]]):
        with self.connect() as conn:
            event_repository.save_event_windows(conn, session_id, event_id, rows)

    def delete_event_windows(self, event_id: str):
        with self.connect() as conn:
            event_repository.delete_event_windows(conn, event_id)

    def save_event_features(self, row: dict[str, Any]):
        with self.connect() as conn:
            event_repository.save_event_features(conn, row)

    def delete_event_features(self, event_id: str):
        with self.connect() as conn:
            event_repository.delete_event_features(conn, event_id)

    def insert_open_trade_bundle(
        self,
        trade_row: dict[str, Any],
        event_row: dict[str, Any],
        window_rows: Iterable[dict[str, Any]],
        feature_row: dict[str, Any],
    ):
        with self.connect() as conn:
            trade_repository.insert_open_trade_bundle(
                conn,
                trade_row,
                event_row,
                window_rows,
                feature_row,
                self.TRADE_COLUMNS,
            )

    def undo_open_trade_bundle(self, trade_id: str, event_id: str):
        with self.connect() as conn:
            trade_repository.undo_open_trade_bundle(conn, trade_id, event_id)

    def close_trade_bundle(
        self,
        event_row: dict[str, Any],
        window_rows: Iterable[dict[str, Any]],
        feature_row: dict[str, Any],
        close_update: dict[str, Any],
        entry_event_id: str,
        final_return_pct: float | None,
        holding_bars: int | None,
    ):
        with self.connect() as conn:
            trade_repository.close_trade_bundle(
                conn,
                event_row,
                window_rows,
                feature_row,
                close_update,
                entry_event_id,
                final_return_pct,
                holding_bars,
            )

    def undo_close_trade_bundle(self, trade_id: str, event_id: str, entry_event_id: str, updated_at: str):
        with self.connect() as conn:
            trade_repository.undo_close_trade_bundle(conn, trade_id, event_id, entry_event_id, updated_at)

    def _insert_event_windows(self, conn, session_id: str, event_id: str, rows: Iterable[dict[str, Any]]):
        event_repository.save_event_windows(conn, session_id, event_id, rows)

    def _insert_event_features(self, conn, row: dict[str, Any]):
        event_repository.save_event_features(conn, row)

    def update_event_trade_outcome(self, event_id: str, final_return_pct: float | None, holding_bars: int | None):
        with self.connect() as conn:
            event_repository.update_event_trade_outcome(conn, event_id, final_return_pct, holding_bars)

    def replace_equity_curve(self, session_id: str, rows: Iterable[dict[str, Any]]):
        with self.connect() as conn:
            trade_repository.replace_equity_curve(conn, session_id, rows)

    def insert_premium_sample(self, row: dict[str, Any]):
        with self.connect() as conn:
            premium_repository.insert_premium_sample(conn, row)

    def fetch_recent_premium_samples(self, limit: int = 240) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return premium_repository.fetch_recent_premium_samples(conn, limit)

    def upsert_klines(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            market_repository.upsert_klines(conn, rows)

    def save_data_quality_report(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            market_repository.save_data_quality_report(conn, row)

    def save_event_context_feature(self, row: dict[str, Any]) -> None:
        self.save_event_context_features([row])

    def save_event_context_features(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            research_repository.save_event_context_features(conn, rows)

    def list_event_context_features(
        self,
        sample_id: str | None = None,
        session_id: str | None = None,
        feature_version: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return research_repository.list_event_context_features(
                conn,
                sample_id=sample_id,
                session_id=session_id,
                feature_version=feature_version,
            )

    def save_research_outcome_label(self, row: dict[str, Any]) -> None:
        self.save_research_outcome_labels([row])

    def save_research_outcome_labels(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            research_repository.save_research_outcome_labels(conn, rows)

    def list_research_outcome_labels(
        self,
        sample_id: str | None = None,
        session_id: str | None = None,
        label_version: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return research_repository.list_research_outcome_labels(
                conn,
                sample_id=sample_id,
                session_id=session_id,
                label_version=label_version,
            )

    def save_strategy_profile(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            research_repository.save_strategy_profile(conn, row)

    def load_strategy_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return research_repository.load_strategy_profile(conn, profile_id)

    def list_strategy_profiles(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return research_repository.list_strategy_profiles(conn)

    def save_observation_sample(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            research_repository.save_observation_sample(conn, row)

    def list_observation_samples(
        self,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return research_repository.list_observation_samples(
                conn,
                session_id=session_id,
                profile_id=profile_id,
            )

    def save_strategy_sample(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            research_repository.save_strategy_sample(conn, row)

    def list_strategy_samples_for_experiment(self, experiment_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return research_repository.list_strategy_samples_for_experiment(conn, experiment_id)

    def fetch_table(self, table: str, where: str = "", params: tuple[Any, ...] = ()):
        if table not in self.ALLOWED_TABLES:
            raise ValueError(f"不允许读取未知表：{table}")
        query = f"SELECT * FROM {table}"
        if where:
            query += f" WHERE {where}"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def fetch_trade(self, trade_id: str):
        with self.connect() as conn:
            return trade_repository.fetch_trade(conn, trade_id)

    def fetch_event(self, event_id: str):
        with self.connect() as conn:
            return event_repository.fetch_event(conn, event_id)

    def load_session_snapshot(self, session_id: str):
        with self.connect() as conn:
            return session_repository.load_session_snapshot(conn, session_id)
