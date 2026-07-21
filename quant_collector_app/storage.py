from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    try:
        from research.setups import (
            Setup,
            SetupVersion,
            SetupVersionSpec,
            SetupWithVersion,
        )
    except ImportError:  # pragma: no cover - package import path
        from .research.setups import (
            Setup,
            SetupVersion,
            SetupVersionSpec,
            SetupWithVersion,
        )
    try:
        from research.market_episodes import EpisodeAuditRecord, EpisodeGrouping
    except ImportError:  # pragma: no cover - package import path
        from .research.market_episodes import EpisodeAuditRecord, EpisodeGrouping

try:
    from app_config import BACKUP_DIR, DB_PATH
    from database_backup import backup_database_before_upgrade
    from errors import DatabaseError, DatabaseSchemaTooNewError
except ImportError:  # pragma: no cover - package import path
    from .app_config import BACKUP_DIR, DB_PATH
    from .database_backup import backup_database_before_upgrade
    from .errors import DatabaseError, DatabaseSchemaTooNewError
try:
    from storage_core.connection import connect_db, require_rowcount
    from storage_core import migrations
    from storage_core import event_repository
    from storage_core import episode_repository
    from storage_core import entry_behavior_repository
    from storage_core import entry_outcome_repository
    from storage_core import entry_review_repository
    from storage_core import exit_review_repository
    from storage_core import exit_outcome_repository
    from storage_core import exit_candidate_repository
    from storage_core import market_repository
    from storage_core import premium_repository
    from storage_core import research_repository
    from storage_core import setup_repository
    from storage_core import session_repository
    from storage_core import snapshot_repository
    from storage_core import trade_management_repository
    from storage_core import trade_repository
except ImportError:  # pragma: no cover - package import path
    from .storage_core.connection import connect_db, require_rowcount
    from .storage_core import migrations
    from .storage_core import event_repository
    from .storage_core import episode_repository
    from .storage_core import entry_behavior_repository
    from .storage_core import entry_outcome_repository
    from .storage_core import entry_review_repository
    from .storage_core import exit_review_repository
    from .storage_core import exit_outcome_repository
    from .storage_core import exit_candidate_repository
    from .storage_core import market_repository
    from .storage_core import premium_repository
    from .storage_core import research_repository
    from .storage_core import setup_repository
    from .storage_core import session_repository
    from .storage_core import snapshot_repository
    from .storage_core import trade_management_repository
    from .storage_core import trade_repository


class StorageManager:
    SCHEMA_VERSION = 19
    MANUAL_RESEARCH_TABLES = (
        "account_equity",
        "event_features",
        "event_windows",
        "trade_events",
        "trades",
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
        "entry_annotations",
        "entry_annotation_history",
        "setups",
        "setup_versions",
        "episode_grouping_versions",
        "market_episodes",
        "market_episode_memberships",
        "market_episode_audit",
        "entry_decision_events",
        "entry_original_actions",
        "entry_review_batches",
        "entry_review_batch_items",
        "entry_judgment_versions",
        "entry_review_reveals",
        "entry_similarity_audits",
        "entry_candidate_scans",
        "entry_candidate_scores",
        "entry_candidate_batches",
        "entry_candidate_batch_items",
        "entry_candidate_exclusions",
        "entry_behavior_experiments",
        "entry_behavior_model_versions",
        "entry_outcome_comparisons",
        "entry_outcome_matches",
        "exit_behavior_experiments",
        "exit_behavior_model_versions",
        "exit_decision_events",
        "exit_position_snapshots",
        "exit_account_pressure_snapshots",
        "exit_original_actions",
        "exit_review_batches",
        "exit_review_batch_items",
        "exit_judgment_versions",
        "exit_review_reveals",
        "exit_candidate_scans",
        "exit_candidate_scores",
        "exit_candidate_batches",
        "exit_candidate_batch_items",
        "exit_candidate_exclusions",
        "exit_outcome_comparisons",
        "exit_outcome_matches",
        "research_snapshots",
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
        "take_profit_pct", "stop_loss_pct", "take_profit_price", "stop_loss_price", "exit_reason",
        "created_at", "updated_at",
    ]

    def __init__(self, db_path: Path | str = DB_PATH, *, backup_dir: Path | str | None = None):
        self.db_path = str(db_path)
        path = Path(self.db_path)
        existed_before_init = path.exists()
        self.backup_dir = Path(backup_dir) if backup_dir is not None else (
            Path(BACKUP_DIR) if path == Path(DB_PATH) else path.parent / "backups"
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db(existed_before_init=existed_before_init)
        except OSError as exc:
            raise DatabaseError(f"Database directory is not writable: {exc}") from exc

    def connect(self):
        return connect_db(self.db_path)

    def _init_db(self, *, existed_before_init: bool = True):
        with self.connect() as conn:
            version = migrations.schema_version(conn)
        if version > self.SCHEMA_VERSION:
            raise DatabaseSchemaTooNewError(
                database_schema_version=version,
                supported_schema_version=self.SCHEMA_VERSION,
                database_path=self.db_path,
            )
        if version == self.SCHEMA_VERSION:
            return
        if existed_before_init and version < self.SCHEMA_VERSION:
            backup_database_before_upgrade(
                self.db_path,
                self.backup_dir,
                from_version=version,
                to_version=self.SCHEMA_VERSION,
            )
        migration_steps = (
            (1, migrations.migrate_to_v1),
            (2, migrations.migrate_to_v2),
            (3, migrations.migrate_to_v3),
            (4, migrations.migrate_to_v4),
            (5, migrations.migrate_to_v5),
            (6, migrations.migrate_to_v6),
            (7, migrations.migrate_to_v7),
            (8, migrations.migrate_to_v8),
            (9, migrations.migrate_to_v9),
            (10, migrations.migrate_to_v10),
            (11, migrations.migrate_to_v11),
            (12, migrations.migrate_to_v12),
            (13, migrations.migrate_to_v13),
            (14, migrations.migrate_to_v14),
            (15, migrations.migrate_to_v15),
            (16, migrations.migrate_to_v16),
            (17, migrations.migrate_to_v17),
            (18, migrations.migrate_to_v18),
            (19, migrations.migrate_to_v19),
        )
        with self.connect() as conn:
            for target_version, migrate in migration_steps:
                # Legacy databases sometimes carry a later user_version while
                # missing an earlier table.  Preserve the established repair
                # pass for every step except v2, whose historical migration is
                # only safe for pre-v2 databases.
                if target_version != 2 or version < 2:
                    migrate(conn)
            research_repository.ensure_entry_annotation_storage(conn)
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

    def _migrate_to_v6(self):
        with self.connect() as conn:
            migrations.migrate_to_v6(conn)
            research_repository.ensure_entry_annotation_storage(conn)

    def _migrate_to_v7(self):
        with self.connect() as conn:
            migrations.migrate_to_v7(conn)

    def _migrate_to_v8(self):
        with self.connect() as conn:
            migrations.migrate_to_v8(conn)

    def _migrate_to_v9(self):
        with self.connect() as conn:
            migrations.migrate_to_v9(conn)

    def _migrate_to_v10(self):
        with self.connect() as conn:
            migrations.migrate_to_v10(conn)

    def _migrate_to_v11(self):
        with self.connect() as conn:
            migrations.migrate_to_v11(conn)

    def _migrate_to_v12(self):
        with self.connect() as conn:
            migrations.migrate_to_v12(conn)

    def _migrate_to_v13(self):
        with self.connect() as conn:
            migrations.migrate_to_v13(conn)

    def _migrate_to_v14(self):
        with self.connect() as conn:
            migrations.migrate_to_v14(conn)

    def _migrate_to_v15(self):
        with self.connect() as conn:
            migrations.migrate_to_v15(conn)

    def _migrate_to_v16(self):
        with self.connect() as conn:
            migrations.migrate_to_v16(conn)

    def _migrate_to_v17(self):
        with self.connect() as conn:
            migrations.migrate_to_v17(conn)

    def _migrate_to_v18(self):
        with self.connect() as conn:
            migrations.migrate_to_v18(conn)

    def _migrate_to_v19(self):
        with self.connect() as conn:
            migrations.migrate_to_v19(conn)

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

    def get_session(self, session_id: str):
        with self.connect() as conn:
            return session_repository.get_session(conn, session_id)

    def list_performance_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return session_repository.list_performance_sessions(conn)

    def clear_manual_research_records(self) -> dict[str, Any]:
        """Delete all trade samples while retaining sessions and market data."""
        with self.connect() as conn:
            return trade_management_repository.clear_all_trade_samples(conn)

    def preview_all_trade_sample_deletion(self) -> dict[str, Any]:
        with self.connect() as conn:
            return trade_management_repository.preview_all_trade_sample_deletion(conn)

    def list_trade_samples_for_management(
        self,
        *,
        start_time: str,
        end_time: str,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return trade_management_repository.list_trade_samples_for_time_range(
                conn,
                start_time=start_time,
                end_time=end_time,
                session_id=session_id,
            )

    def list_trade_samples_for_session(
        self,
        session_id: str,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return trade_management_repository.list_trade_samples_for_session(
                conn,
                session_id,
                limit=limit,
            )

    def preview_trade_sample_deletion(
        self,
        trade_ids: list[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        with self.connect() as conn:
            return trade_management_repository.preview_delete_trade_samples(
                conn,
                trade_ids,
            )

    def delete_trade_samples(
        self,
        trade_ids: list[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        with self.connect() as conn:
            return trade_management_repository.delete_trade_samples(conn, trade_ids)

    def preview_performance_session_deletion(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            return trade_management_repository.preview_performance_session_deletion(
                conn,
                session_id,
            )

    def delete_performance_session(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            return trade_management_repository.delete_performance_session(
                conn,
                session_id,
            )

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

    def list_trade_events_for_session(
        self,
        session_id: str,
        *,
        event_types: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return event_repository.list_events_for_session(
                conn,
                session_id,
                event_types=event_types,
            )

    def update_event_labels(self, event_id: str, label_tags: list[str], note: str):
        with self.connect() as conn:
            event_repository.update_event_labels(conn, event_id, label_tags, note)

    def delete_event(self, event_id: str):
        with self.connect() as conn:
            event_repository.delete_event(conn, event_id)

    def save_event_windows(self, session_id: str, event_id: str, rows: Iterable[dict[str, Any]]):
        with self.connect() as conn:
            event_repository.save_event_windows(conn, session_id, event_id, rows)

    def fetch_event_windows_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return event_repository.list_event_windows_for_session(conn, session_id)

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

    def fetch_klines_for_range(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_utc_ms: int,
        end_time_utc_ms: int,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return market_repository.fetch_klines_for_range(
                conn,
                symbol=symbol,
                interval=interval,
                start_time_utc_ms=start_time_utc_ms,
                end_time_utc_ms=end_time_utc_ms,
                cancelled=cancelled,
            )

    def fetch_kline_ancillary_rows_for_range(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_utc_ms: int,
        end_time_utc_ms: int,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return market_repository.fetch_kline_ancillary_rows_for_range(
                conn,
                symbol=symbol,
                interval=interval,
                start_time_utc_ms=start_time_utc_ms,
                end_time_utc_ms=end_time_utc_ms,
                cancelled=cancelled,
            )

    def audit_kline_ancillary_completeness(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_utc_ms: int,
        end_time_utc_ms: int,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            return market_repository.audit_kline_ancillary_completeness(
                conn,
                symbol=symbol,
                interval=interval,
                start_time_utc_ms=start_time_utc_ms,
                end_time_utc_ms=end_time_utc_ms,
            )

    def list_kline_series_ranges(
        self,
        *,
        ancillary_incomplete_only: bool = False,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return market_repository.list_kline_series_ranges(
                conn,
                ancillary_incomplete_only=ancillary_incomplete_only,
            )

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

    def save_entry_annotation(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.save_or_update_annotation(row)

    def save_or_update_annotation(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            return research_repository.save_or_update_entry_annotation(conn, row)

    def save_entry_annotations(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            research_repository.save_entry_annotations(conn, rows)

    def get_active_annotation_for_observation(
        self,
        *,
        session_id: str | None,
        symbol: str | None,
        interval: str | None,
        decision_bar_index: int | None,
        observation_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return research_repository.get_active_annotation_for_observation(
                conn,
                session_id=session_id,
                symbol=symbol,
                interval=interval,
                decision_bar_index=decision_bar_index,
                observation_id=observation_id,
            )

    def update_active_annotation_for_observation(
        self,
        *,
        session_id: str,
        symbol: str,
        interval: str,
        decision_bar_index: int,
        observation_id: str | None = None,
        human_decision: str,
        confidence: int | None,
        reason_tags: list[str] | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            return research_repository.update_active_annotation_for_observation(
                conn,
                session_id=session_id,
                symbol=symbol,
                interval=interval,
                decision_bar_index=decision_bar_index,
                observation_id=observation_id,
                human_decision=human_decision,
                confidence=confidence,
                reason_tags=reason_tags,
                note=note,
            )

    def list_entry_annotations(
        self,
        annotation_id: str | None = None,
        session_id: str | None = None,
        human_decision: str | None = None,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return research_repository.list_entry_annotations(
                conn,
                annotation_id=annotation_id,
                session_id=session_id,
                human_decision=human_decision,
                include_inactive=include_inactive,
            )

    def delete_entry_annotation(self, annotation_id: str) -> int:
        return self.soft_delete_annotation(annotation_id)

    def soft_delete_annotation(self, annotation_id: str, reason: str | None = None) -> int:
        with self.connect() as conn:
            return research_repository.soft_delete_annotation(conn, annotation_id, reason=reason)

    def list_entry_annotation_history(
        self,
        annotation_id: str | None = None,
        session_id: str | None = None,
        observation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return research_repository.list_entry_annotation_history(
                conn,
                annotation_id=annotation_id,
                session_id=session_id,
                observation_id=observation_id,
            )

    def list_annotation_history(
        self,
        annotation_id: str | None = None,
        session_id: str | None = None,
        observation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.list_entry_annotation_history(
            annotation_id=annotation_id,
            session_id=session_id,
            observation_id=observation_id,
        )

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

    def create_setup_with_version(
        self,
        *,
        setup: Setup,
        version: SetupVersion,
        creation_token: str,
        semantic_fingerprint: str,
    ) -> SetupWithVersion:
        with self.connect() as conn:
            return setup_repository.create_setup_with_version(
                conn,
                setup=setup,
                version=version,
                creation_token=creation_token,
                semantic_fingerprint=semantic_fingerprint,
            )

    def get_setup_version(
        self,
        setup_version_id: str,
    ) -> SetupVersion | None:
        with self.connect() as conn:
            return setup_repository.get_setup_version(
                conn,
                setup_version_id,
            )

    def create_setup_version(
        self,
        *,
        setup_version_id: str,
        setup_id: str,
        based_on_version_id: str,
        spec: SetupVersionSpec,
        semantic_fingerprint: str,
        creation_key: str,
        created_at: str,
    ) -> SetupVersion:
        with self.connect() as conn:
            return setup_repository.create_setup_version(
                conn,
                setup_version_id=setup_version_id,
                setup_id=setup_id,
                based_on_version_id=based_on_version_id,
                spec=spec,
                semantic_fingerprint=semantic_fingerprint,
                creation_key=creation_key,
                created_at=created_at,
            )

    def list_setup_versions(
        self,
        setup_id: str,
    ) -> tuple[SetupVersion, ...]:
        with self.connect() as conn:
            return setup_repository.list_setup_versions(conn, setup_id)

    def get_setup(self, setup_id: str) -> Setup | None:
        with self.connect() as conn:
            return setup_repository.get_setup(conn, setup_id)

    def list_setups(
        self,
        *,
        include_archived: bool = False,
    ) -> tuple[Setup, ...]:
        with self.connect() as conn:
            return setup_repository.list_setups(
                conn,
                include_archived=include_archived,
            )

    def rename_setup(
        self,
        setup_id: str,
        display_name: str,
        updated_at: str,
    ) -> Setup | None:
        with self.connect() as conn:
            return setup_repository.rename_setup(
                conn,
                setup_id,
                display_name,
                updated_at,
            )

    def archive_setup(
        self,
        setup_id: str,
        archived_at: str,
    ) -> Setup | None:
        with self.connect() as conn:
            return setup_repository.archive_setup(
                conn,
                setup_id,
                archived_at,
            )

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

    def save_episode_grouping(self, grouping: EpisodeGrouping) -> None:
        with self.connect() as conn:
            episode_repository.save_episode_grouping(conn, grouping)

    def get_episode_grouping(self, grouping_version_id: str) -> EpisodeGrouping | None:
        with self.connect() as conn:
            return episode_repository.get_episode_grouping(conn, grouping_version_id)

    def save_episode_revision(
        self,
        grouping: EpisodeGrouping,
        audit: EpisodeAuditRecord,
    ) -> None:
        with self.connect() as conn:
            episode_repository.save_episode_revision(conn, grouping, audit)

    def list_episode_audit(
        self,
        grouping_version_id: str,
    ) -> tuple[EpisodeAuditRecord, ...]:
        with self.connect() as conn:
            return episode_repository.list_episode_audit(conn, grouping_version_id)

    def insert_entry_decision_event(
        self,
        *,
        event: dict[str, Any],
        original_action: dict[str, Any],
    ) -> bool:
        with self.connect() as conn:
            return entry_review_repository.insert_decision_event_with_original_action(
                conn,
                event=event,
                original_action=original_action,
            )

    def get_entry_decision_event_by_source(
        self,
        *,
        source_sample_id: str,
        setup_version_id: str,
        grouping_version_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return entry_review_repository.get_decision_event_by_source(
                conn,
                source_sample_id=source_sample_id,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
            )

    def list_pending_entry_decision_events(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return entry_review_repository.list_pending_decision_events(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                limit=limit,
            )

    def list_actual_open_episode_member_ids(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
        limit: int,
    ) -> tuple[str, ...]:
        with self.connect() as conn:
            return entry_review_repository.list_actual_open_episode_member_ids(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
                limit=limit,
            )

    def create_entry_review_batch(
        self,
        *,
        batch: dict[str, Any],
        items: Iterable[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            entry_review_repository.create_batch(
                conn,
                batch=batch,
                items=items,
            )

    def get_entry_review_batch_item(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return entry_review_repository.get_batch_item(
                conn,
                batch_id=batch_id,
                blind_item_id=blind_item_id,
            )

    def insert_entry_judgment(self, row: dict[str, Any]) -> bool:
        with self.connect() as conn:
            return entry_review_repository.insert_judgment(conn, row)

    def list_entry_judgments(
        self,
        decision_event_id: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return entry_review_repository.list_judgments(
                conn,
                decision_event_id,
            )

    def get_entry_review_reveal(
        self,
        decision_event_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return entry_review_repository.get_reveal(
                conn,
                decision_event_id,
            )

    def insert_entry_review_reveal(self, row: dict[str, Any]) -> bool:
        with self.connect() as conn:
            return entry_review_repository.insert_reveal(conn, row)

    def get_entry_original_action(
        self,
        decision_event_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return entry_review_repository.get_original_action(
                conn,
                decision_event_id,
            )

    def get_entry_decision_event(
        self,
        decision_event_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return entry_review_repository.get_decision_event(
                conn,
                decision_event_id,
            )

    def list_entry_setup_links(
        self,
        *,
        source_sample_id: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return exit_review_repository.list_entry_setup_links(
                conn,
                source_sample_id=source_sample_id,
            )

    def get_exit_decision_event_by_source(
        self,
        *,
        source_sample_id: str,
        review_setup_version_id: str,
        grouping_version_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return exit_review_repository.get_decision_event_by_source(
                conn,
                source_sample_id=source_sample_id,
                review_setup_version_id=review_setup_version_id,
                grouping_version_id=grouping_version_id,
            )

    def insert_exit_decision_event(
        self,
        *,
        event: dict[str, Any],
        position: dict[str, Any],
        account_pressure: dict[str, Any],
        original_action: dict[str, Any],
    ) -> bool:
        with self.connect() as conn:
            return exit_review_repository.insert_decision_event_bundle(
                conn,
                event=event,
                position=position,
                account_pressure=account_pressure,
                original_action=original_action,
            )

    def list_pending_exit_decision_events(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return exit_review_repository.list_pending_decision_events(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                limit=limit,
            )

    def list_actual_close_episode_member_ids(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
        limit: int,
    ) -> tuple[str, ...]:
        with self.connect() as conn:
            return exit_review_repository.list_actual_close_episode_member_ids(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
                limit=limit,
            )

    def create_exit_review_batch(
        self,
        *,
        batch: dict[str, Any],
        items: Iterable[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            exit_review_repository.create_batch(
                conn,
                batch=batch,
                items=items,
            )

    def get_exit_review_batch_item(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return exit_review_repository.get_batch_item(
                conn,
                batch_id=batch_id,
                blind_item_id=blind_item_id,
            )

    def insert_exit_judgment(self, row: dict[str, Any]) -> bool:
        with self.connect() as conn:
            return exit_review_repository.insert_judgment(conn, row)

    def list_exit_judgments(
        self,
        decision_event_id: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return exit_review_repository.list_judgments(
                conn,
                decision_event_id,
            )

    def get_exit_review_reveal(
        self,
        decision_event_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return exit_review_repository.get_reveal(
                conn,
                decision_event_id,
            )

    def insert_exit_review_reveal(self, row: dict[str, Any]) -> bool:
        with self.connect() as conn:
            return exit_review_repository.insert_reveal(conn, row)

    def get_exit_original_action(
        self,
        decision_event_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return exit_review_repository.get_original_action(
                conn,
                decision_event_id,
            )

    def save_exit_candidate_scan(
        self,
        *,
        scan: dict[str, Any],
        candidates: Iterable[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            exit_candidate_repository.save_scan(
                conn,
                scan=scan,
                candidates=candidates,
            )

    def list_confirmed_exit_candidate_references(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return exit_candidate_repository.list_confirmed_references(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
            )

    def list_exit_candidate_observations(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return exit_candidate_repository.list_open_position_observations(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
                limit=limit,
            )

    def get_exit_candidate_scan(self, scan_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return exit_candidate_repository.get_scan(conn, scan_id)

    def create_exit_candidate_batch(
        self,
        *,
        batch: dict[str, Any],
        items: Iterable[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            exit_candidate_repository.create_batch(
                conn,
                batch=batch,
                items=items,
            )

    def get_exit_candidate_audit_for_event(
        self,
        decision_event_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return exit_candidate_repository.get_audit_for_event(
                conn,
                decision_event_id,
            )

    def exclude_exit_candidate(self, row: dict[str, Any]) -> bool:
        with self.connect() as conn:
            return exit_candidate_repository.insert_exclusion(conn, row)

    def list_exit_candidate_exclusions(self) -> tuple[str, ...]:
        with self.connect() as conn:
            return exit_candidate_repository.list_exclusions(conn)

    def list_batched_exit_candidate_ids(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
    ) -> tuple[str, ...]:
        with self.connect() as conn:
            return exit_candidate_repository.list_batched_ids(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
            )

    def save_entry_similarity_audit(self, row: dict[str, Any]) -> bool:
        with self.connect() as conn:
            return entry_review_repository.insert_similarity_audit(conn, row)

    def get_entry_similarity_audit(
        self,
        result_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return entry_review_repository.get_similarity_audit(conn, result_id)

    def list_revealed_entry_decision_events(
        self,
        *,
        setup_version_id: str,
        direction: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return entry_review_repository.list_revealed_decision_events(
                conn,
                setup_version_id=setup_version_id,
                direction=direction,
                limit=limit,
            )

    def list_confirmed_entry_reference_events(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return entry_review_repository.list_confirmed_entry_reference_events(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
            )

    def list_entry_candidate_observations(
        self,
        *,
        setup_version_id: str,
        limit: int = 5_000,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return research_repository.list_entry_candidate_observations(
                conn,
                setup_version_id=setup_version_id,
                limit=limit,
            )

    def save_entry_candidate_scan(
        self,
        *,
        scan: dict[str, Any],
        candidates: Iterable[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            entry_review_repository.save_candidate_scan(
                conn,
                scan=scan,
                candidates=candidates,
            )

    def get_entry_candidate_scan(self, scan_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return entry_review_repository.get_candidate_scan(conn, scan_id)

    def create_entry_candidate_batch(
        self,
        *,
        batch: dict[str, Any],
        items: Iterable[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            entry_review_repository.create_candidate_batch(
                conn,
                batch=batch,
                items=items,
            )

    def get_entry_candidate_audit_for_event(
        self,
        decision_event_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return entry_review_repository.get_candidate_audit_for_event(
                conn,
                decision_event_id,
            )

    def exclude_entry_candidate(self, row: dict[str, Any]) -> bool:
        with self.connect() as conn:
            return entry_review_repository.insert_candidate_exclusion(conn, row)

    def list_entry_candidate_exclusions(self) -> tuple[str, ...]:
        with self.connect() as conn:
            return entry_review_repository.list_candidate_exclusions(conn)

    def list_batched_entry_candidate_ids(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
    ) -> tuple[str, ...]:
        with self.connect() as conn:
            return entry_review_repository.list_batched_candidate_ids(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
            )

    def list_entry_behavior_training_events(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return entry_behavior_repository.list_training_events(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
            )

    def list_behavior_training_events(
        self,
        *,
        target: Any,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return entry_behavior_repository.list_training_events(
                conn,
                target=target,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
            )

    def save_entry_behavior_training_result(self, result: Any) -> None:
        with self.connect() as conn:
            entry_behavior_repository.save_training_result(conn, result)

    def save_behavior_training_result(self, result: Any) -> None:
        with self.connect() as conn:
            entry_behavior_repository.save_training_result(conn, result)

    def get_entry_behavior_training_result(
        self,
        experiment_id: str,
    ) -> Any | None:
        with self.connect() as conn:
            return entry_behavior_repository.get_training_result(
                conn,
                experiment_id,
            )

    def get_behavior_training_result(
        self,
        experiment_id: str,
        *,
        target: Any,
    ) -> Any | None:
        with self.connect() as conn:
            return entry_behavior_repository.get_training_result(
                conn,
                experiment_id,
                target=target,
            )

    def get_entry_behavior_model_version(
        self,
        model_version_id: str,
    ) -> Any | None:
        with self.connect() as conn:
            return entry_behavior_repository.get_model_version(
                conn,
                model_version_id,
            )

    def get_behavior_model_version(
        self,
        model_version_id: str,
        *,
        target: Any,
    ) -> Any | None:
        with self.connect() as conn:
            return entry_behavior_repository.get_model_version(
                conn,
                model_version_id,
                target=target,
            )

    def list_entry_behavior_model_versions(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> tuple[Any, ...]:
        with self.connect() as conn:
            return entry_behavior_repository.list_model_versions(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
            )

    def list_behavior_model_versions(
        self,
        *,
        target: Any,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> tuple[Any, ...]:
        with self.connect() as conn:
            return entry_behavior_repository.list_model_versions(
                conn,
                target=target,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
            )

    def list_entry_outcome_events(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return entry_outcome_repository.list_eligible_events(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
            )

    def save_entry_outcome_result(self, result: Any) -> None:
        with self.connect() as conn:
            entry_outcome_repository.save_result(conn, result)

    def get_entry_outcome_result(self, comparison_id: str) -> Any | None:
        with self.connect() as conn:
            return entry_outcome_repository.get_result(conn, comparison_id)

    def list_exit_outcome_events(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return exit_outcome_repository.list_eligible_events(
                conn,
                setup_version_id=setup_version_id,
                grouping_version_id=grouping_version_id,
                direction=direction,
            )

    def save_exit_outcome_result(self, result: Any) -> None:
        with self.connect() as conn:
            exit_outcome_repository.save_result(conn, result)

    def get_exit_outcome_result(self, comparison_id: str) -> Any | None:
        with self.connect() as conn:
            return exit_outcome_repository.get_result(conn, comparison_id)

    def save_strategy_sample(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            research_repository.save_strategy_sample(conn, row)

    def save_research_snapshot(self, snapshot) -> None:
        with self.connect() as conn:
            snapshot_repository.save_snapshot(conn, snapshot)

    def save_research_snapshot_with_publish(self, snapshot, publish):
        with self.connect() as conn:
            snapshot_repository.save_snapshot(conn, snapshot)
            return publish()

    def get_research_snapshot(self, snapshot_id: str):
        with self.connect() as conn:
            return snapshot_repository.get_snapshot(conn, snapshot_id)

    def get_research_snapshot_by_content_hash(self, content_hash: str):
        with self.connect() as conn:
            return snapshot_repository.get_snapshot_by_content_hash(
                conn,
                content_hash,
            )

    def list_research_snapshots(self, setup_version_id: str):
        with self.connect() as conn:
            return snapshot_repository.list_snapshots(conn, setup_version_id)

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
