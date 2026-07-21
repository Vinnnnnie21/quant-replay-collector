from __future__ import annotations

import hashlib
import math
import uuid
from datetime import UTC, datetime
from typing import Any

try:
    from market_data.types import interval_to_ms, normalize_symbol
    from research.entry_blind_review import (
        BlindBatchItem,
        BlindReviewBatch,
        ReviewPhase,
        ReviewStatus,
    )
    from research.exit_blind_review import (
        AccountPressureSnapshot,
        BlindedExitReviewItem,
        ExitBlindJudgmentInput,
        ExitJudgmentLabel,
        ExitJudgmentVersion,
        ExitPositionSnapshot,
        ExitSeedReceipt,
        ExitSeedSource,
        OptionalRiskLevelStatus,
        OriginalExitAction,
        RevealedExitReviewItem,
        RevealedCandidateAudit,
        RevealedCandidateReference,
        RevealedOriginalExitAction,
    )
    from research.market_episodes import MarketEpisodeService
    from services.blind_review_market_data import (
        BlindReviewMarketData,
        actual_action_timing,
    )
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms, normalize_symbol
    from ..research.entry_blind_review import (
        BlindBatchItem,
        BlindReviewBatch,
        ReviewPhase,
        ReviewStatus,
    )
    from ..research.exit_blind_review import (
        AccountPressureSnapshot,
        BlindedExitReviewItem,
        ExitBlindJudgmentInput,
        ExitJudgmentLabel,
        ExitJudgmentVersion,
        ExitPositionSnapshot,
        ExitSeedReceipt,
        ExitSeedSource,
        OptionalRiskLevelStatus,
        OriginalExitAction,
        RevealedExitReviewItem,
        RevealedCandidateAudit,
        RevealedCandidateReference,
        RevealedOriginalExitAction,
    )
    from ..research.market_episodes import MarketEpisodeService
    from .blind_review_market_data import (
        BlindReviewMarketData,
        actual_action_timing,
    )


MAX_BLIND_BATCH_SIZE = 20
EXIT_BLIND_REVIEW_STORAGE_METHODS = (
    "create_exit_review_batch",
    "fetch_event",
    "fetch_klines_for_range",
    "fetch_table",
    "fetch_trade",
    "get_exit_decision_event_by_source",
    "get_exit_original_action",
    "get_exit_review_batch_item",
    "get_exit_review_reveal",
    "get_episode_grouping",
    "get_setup_version",
    "insert_exit_decision_event",
    "insert_exit_judgment",
    "insert_exit_review_reveal",
    "list_actual_close_episode_member_ids",
    "list_entry_setup_links",
    "list_exit_judgments",
    "list_pending_exit_decision_events",
)


class PartialExitUnsupportedError(ValueError):
    """Raised when a partial reduction is submitted to the v1.6 exit study."""

    code = "partial_exit_unsupported"
    user_message_key = "decision_research.exit_review.partial_unsupported"


def supports_exit_blind_review_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None))
        for method in EXIT_BLIND_REVIEW_STORAGE_METHODS
    )


class ExitBlindReviewService:
    """Public full-exit review use cases with a blinded payload boundary."""

    def __init__(self, storage: Any) -> None:
        if not supports_exit_blind_review_storage(storage):
            raise TypeError(
                "storage does not implement the exit blind-review contract"
            )
        self._storage = storage
        self._episodes = MarketEpisodeService(storage)
        self._market_data = BlindReviewMarketData(storage)

    def enqueue_actual_close(
        self,
        *,
        trade_event_id: str,
        grouping_version_id: str,
        close_scope: str = "FULL",
        legacy_review_setup_version_id: str | None = None,
    ) -> ExitSeedReceipt:
        if str(close_scope).strip().upper() != "FULL":
            raise PartialExitUnsupportedError(
                "v1.6 exit research supports full closes only"
            )
        source_id = _required_text(trade_event_id, "trade_event_id")
        grouping_id = _required_text(
            grouping_version_id,
            "grouping_version_id",
        )
        trade_event = self._storage.fetch_event(source_id)
        if trade_event is None:
            raise KeyError(f"Unknown trade event: {source_id}")
        if str(trade_event.get("event_type") or "").upper() != "CLOSE":
            raise ValueError("Only actual CLOSE events can enter this seed path")
        trade_id = _required_text(trade_event.get("trade_id"), "trade_id")
        trade = self._storage.fetch_trade(trade_id)
        if trade is None:
            raise KeyError(f"Unknown trade: {trade_id}")
        if (
            str(trade.get("status") or "").upper() != "CLOSED"
            or str(trade.get("exit_event_id") or "") != source_id
        ):
            raise ValueError("Actual CLOSE must be the trade's full close event")

        setup_link = self._entry_setup_link(trade)
        if setup_link is None:
            if legacy_review_setup_version_id is None:
                raise ValueError(
                    "The closed position is not linked to an entry Setup version"
                )
            setup_id = _required_text(
                legacy_review_setup_version_id,
                "legacy_review_setup_version_id",
            )
            setup_link_status = "LEGACY_UNLINKED"
        else:
            setup_id = str(setup_link["setup_version_id"])
            if (
                legacy_review_setup_version_id is not None
                and str(legacy_review_setup_version_id) != setup_id
            ):
                raise ValueError(
                    "Legacy review Setup cannot replace an existing entry Setup link"
                )
            setup_link_status = "LINKED"
        existing = self._storage.get_exit_decision_event_by_source(
            source_sample_id=source_id,
            review_setup_version_id=setup_id,
            grouping_version_id=grouping_id,
        )
        if existing is not None:
            return ExitSeedReceipt(
                decision_event_id=existing["decision_event_id"],
                status=self._status(existing["decision_event_id"]),
            )
        setup = self._storage.get_setup_version(setup_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {setup_id}")
        direction = str(trade.get("side") or "").upper()
        if direction != setup.direction.value:
            raise ValueError(
                "Closed position direction does not match its entry Setup version"
            )
        assignment = self._episodes.resolve_episode_ids(
            grouping_id,
            (source_id,),
        )[0]
        timing = actual_action_timing(
            trade_event,
            trade,
            trade_bar_time_field="exit_bar_time_bjt",
            trade_real_time_field="exit_real_time_bjt",
        )
        decision_time_ms = int(timing.decision_time_utc.timestamp() * 1_000)
        observed_time_ms = (
            int(timing.observed_time_utc.timestamp() * 1_000)
            if timing.observed_time_utc is not None
            else None
        )
        decision_bar_open_ms, cutoff_ms = self._market_data.decision_bar_boundary(
            symbol=normalize_symbol(trade_event.get("symbol")),
            interval=setup.timeframes.decision,
            decision_time_utc_ms=decision_time_ms,
        )
        if setup_link is None:
            entry_time = _aware_datetime(
                trade.get("entry_bar_time_bjt")
                or trade.get("entry_real_time_bjt")
            )
            _, entry_cutoff_ms = self._market_data.decision_bar_boundary(
                symbol=normalize_symbol(trade_event.get("symbol")),
                interval=setup.timeframes.decision,
                decision_time_utc_ms=int(entry_time.timestamp() * 1_000),
            )
        else:
            entry_cutoff_ms = int(setup_link["decision_cutoff_utc_ms"])
        entry_atr20 = self._entry_atr20(
            symbol=normalize_symbol(trade_event.get("symbol")),
            interval=setup.timeframes.decision,
            entry_cutoff_utc_ms=entry_cutoff_ms,
        )
        entry_price, entry_price_source = _entry_price(trade)
        take_status, take_price = _risk_level(
            trade.get("take_profit_pct"),
            trade.get("take_profit_price"),
        )
        stop_status, stop_price = _risk_level(
            trade.get("stop_loss_pct"),
            trade.get("stop_loss_price"),
        )
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        decision_event_id = _stable_id(
            "exit_decision",
            source_id,
            setup_id,
            grouping_id,
        )
        account_pressure = self._account_pressure(
            trade=trade,
            close_event_id=source_id,
            decision_bar_index=_optional_int(trade_event.get("bar_index")),
        )
        created = self._storage.insert_exit_decision_event(
            event={
                "decision_event_id": decision_event_id,
                "source_sample_id": source_id,
                "setup_version_id": (
                    setup_id if setup_link_status == "LINKED" else None
                ),
                "review_setup_version_id": setup_id,
                "grouping_version_id": grouping_id,
                "episode_id": assignment.episode_id,
                "trade_id": trade_id,
                "entry_event_id": trade.get("entry_event_id"),
                "session_id": trade_event.get("session_id"),
                "symbol": normalize_symbol(trade_event.get("symbol")),
                "direction": direction,
                "decision_timeframe": setup.timeframes.decision,
                "context_timeframe_one": setup.timeframes.context_one,
                "context_timeframe_two": setup.timeframes.context_two,
                "decision_cutoff_utc_ms": cutoff_ms,
                "decision_bar_open_time_utc_ms": decision_bar_open_ms,
                "observed_action_time_utc_ms": observed_time_ms,
                "timing_approximate": (
                    timing.timing_approximate
                    or (
                        observed_time_ms is not None
                        and observed_time_ms > cutoff_ms
                    )
                ),
                "setup_link_status": setup_link_status,
                "eligible_for_formal_research": bool(
                    setup_link_status == "LINKED"
                    and entry_price is not None
                    and entry_atr20 is not None
                ),
                "created_at": now,
            },
            position={
                "actual_entry_price": entry_price,
                "entry_price_source": entry_price_source,
                "entry_atr20": entry_atr20,
                "entry_atr_status": (
                    "AVAILABLE" if entry_atr20 is not None else "MISSING"
                ),
                "entry_bar_index": _optional_int(trade.get("entry_bar_index")),
                "decision_bar_index": _optional_int(trade_event.get("bar_index")),
                "take_profit_status": take_status.value,
                "take_profit_price": take_price,
                "stop_loss_status": stop_status.value,
                "stop_loss_price": stop_price,
                "created_at": now,
            },
            account_pressure={**account_pressure, "created_at": now},
            original_action={
                "seed_source": ExitSeedSource.ACTUAL_CLOSE.value,
                "original_action": OriginalExitAction.FULL_CLOSE.value,
                "source_event_id": source_id,
                "action_time_utc_ms": observed_time_ms,
                "realized_pnl_quote": _finite_or_none(
                    trade.get("net_pnl_quote")
                ),
                "created_at": now,
            },
        )
        return ExitSeedReceipt(
            decision_event_id=decision_event_id,
            status=(
                ReviewStatus.PENDING_CONFIRMATION
                if created
                else self._status(decision_event_id)
            ),
        )

    def enqueue_manual_position(
        self,
        *,
        manual_seed_id: str,
        trade_id: str,
        grouping_version_id: str,
        decision_time: datetime | str,
    ) -> ExitSeedReceipt:
        source_id = _required_text(manual_seed_id, "manual_seed_id")
        position_id = _required_text(trade_id, "trade_id")
        grouping_id = _required_text(
            grouping_version_id,
            "grouping_version_id",
        )
        trade = self._storage.fetch_trade(position_id)
        if trade is None:
            raise KeyError(f"Unknown trade: {position_id}")
        selected_time = _aware_datetime(decision_time)
        entry_time = _aware_datetime(
            trade.get("entry_real_time_bjt")
            or trade.get("entry_bar_time_bjt")
        )
        exit_value = trade.get("exit_real_time_bjt") or trade.get(
            "exit_bar_time_bjt"
        )
        if selected_time < entry_time:
            raise ValueError("Manual exit-review time cannot precede entry")
        if exit_value and selected_time >= _aware_datetime(exit_value):
            raise ValueError(
                "Manual exit-review time must be while the position is open"
            )
        setup_link = self._linked_entry_setup(trade)
        setup_id = str(setup_link["setup_version_id"])
        existing = self._storage.get_exit_decision_event_by_source(
            source_sample_id=source_id,
            review_setup_version_id=setup_id,
            grouping_version_id=grouping_id,
        )
        if existing is not None:
            return ExitSeedReceipt(
                decision_event_id=existing["decision_event_id"],
                status=self._status(existing["decision_event_id"]),
            )
        setup = self._storage.get_setup_version(setup_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {setup_id}")
        direction = str(trade.get("side") or "").upper()
        if direction != setup.direction.value:
            raise ValueError(
                "Position direction does not match its entry Setup version"
            )
        assignment = self._episodes.resolve_episode_ids(
            grouping_id,
            (source_id,),
        )[0]
        selected_time_ms = int(selected_time.timestamp() * 1_000)
        symbol = normalize_symbol(trade.get("symbol"))
        decision_bar_open_ms, cutoff_ms = self._market_data.decision_bar_boundary(
            symbol=symbol,
            interval=setup.timeframes.decision,
            decision_time_utc_ms=selected_time_ms,
        )
        entry_atr20 = self._entry_atr20(
            symbol=symbol,
            interval=setup.timeframes.decision,
            entry_cutoff_utc_ms=int(setup_link["decision_cutoff_utc_ms"]),
        )
        entry_price, entry_price_source = _entry_price(trade)
        take_status, take_price = _risk_level(
            trade.get("take_profit_pct"),
            trade.get("take_profit_price"),
        )
        stop_status, stop_price = _risk_level(
            trade.get("stop_loss_pct"),
            trade.get("stop_loss_price"),
        )
        decision_index = _manual_decision_bar_index(
            trade,
            entry_time=entry_time,
            decision_time=selected_time,
            decision_interval=setup.timeframes.decision,
        )
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        decision_event_id = _stable_id(
            "exit_decision",
            source_id,
            setup_id,
            grouping_id,
        )
        created = self._storage.insert_exit_decision_event(
            event={
                "decision_event_id": decision_event_id,
                "source_sample_id": source_id,
                "setup_version_id": setup_id,
                "review_setup_version_id": setup_id,
                "grouping_version_id": grouping_id,
                "episode_id": assignment.episode_id,
                "trade_id": position_id,
                "entry_event_id": trade.get("entry_event_id"),
                "session_id": trade.get("session_id"),
                "symbol": symbol,
                "direction": direction,
                "decision_timeframe": setup.timeframes.decision,
                "context_timeframe_one": setup.timeframes.context_one,
                "context_timeframe_two": setup.timeframes.context_two,
                "decision_cutoff_utc_ms": cutoff_ms,
                "decision_bar_open_time_utc_ms": decision_bar_open_ms,
                "observed_action_time_utc_ms": None,
                "timing_approximate": selected_time_ms > cutoff_ms,
                "setup_link_status": "LINKED",
                "eligible_for_formal_research": bool(
                    entry_price is not None and entry_atr20 is not None
                ),
                "created_at": now,
            },
            position={
                "actual_entry_price": entry_price,
                "entry_price_source": entry_price_source,
                "entry_atr20": entry_atr20,
                "entry_atr_status": (
                    "AVAILABLE" if entry_atr20 is not None else "MISSING"
                ),
                "entry_bar_index": _optional_int(trade.get("entry_bar_index")),
                "decision_bar_index": decision_index,
                "take_profit_status": take_status.value,
                "take_profit_price": take_price,
                "stop_loss_status": stop_status.value,
                "stop_loss_price": stop_price,
                "created_at": now,
            },
            account_pressure={
                **self._account_pressure(
                    trade=trade,
                    close_event_id="",
                    decision_bar_index=decision_index,
                ),
                "created_at": now,
            },
            original_action={
                "seed_source": ExitSeedSource.MANUAL_POSITION.value,
                "original_action": OriginalExitAction.NONE.value,
                "source_event_id": None,
                "action_time_utc_ms": None,
                "realized_pnl_quote": None,
                "created_at": now,
            },
        )
        return ExitSeedReceipt(
            decision_event_id=decision_event_id,
            status=(
                ReviewStatus.PENDING_CONFIRMATION
                if created
                else self._status(decision_event_id)
            ),
        )

    def create_batch(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        limit: int = MAX_BLIND_BATCH_SIZE,
    ) -> BlindReviewBatch:
        size = int(limit)
        if size < 1 or size > MAX_BLIND_BATCH_SIZE:
            raise ValueError(
                f"blind review batch limit must be between 1 and {MAX_BLIND_BATCH_SIZE}"
            )
        setup_id = _required_text(setup_version_id, "setup_version_id")
        grouping_id = _required_text(
            grouping_version_id,
            "grouping_version_id",
        )
        setup = self._storage.get_setup_version(setup_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {setup_id}")
        self._episodes.get_grouping(grouping_id)
        for trade_event_id in self._storage.list_actual_close_episode_member_ids(
            setup_version_id=setup_id,
            grouping_version_id=grouping_id,
            direction=setup.direction.value,
            limit=size,
        ):
            self.enqueue_actual_close(
                trade_event_id=trade_event_id,
                grouping_version_id=grouping_id,
            )
        pending = self._storage.list_pending_exit_decision_events(
            setup_version_id=setup_id,
            grouping_version_id=grouping_id,
            limit=size,
        )
        batch_id = "exit_batch_" + uuid.uuid4().hex
        items = [
            {
                "blind_item_id": _stable_id(
                    "exit_blind_item",
                    batch_id,
                    str(row["decision_event_id"]),
                ),
                "decision_event_id": row["decision_event_id"],
                "display_order": index,
            }
            for index, row in enumerate(pending)
        ]
        self._storage.create_exit_review_batch(
            batch={
                "batch_id": batch_id,
                "setup_version_id": setup_id,
                "grouping_version_id": grouping_id,
                "created_at": datetime.now(UTC).isoformat(
                    timespec="microseconds"
                ),
            },
            items=items,
        )
        return BlindReviewBatch(
            batch_id=batch_id,
            setup_version_id=setup_id,
            grouping_version_id=grouping_id,
            items=tuple(
                BlindBatchItem(
                    blind_item_id=row["blind_item_id"],
                    status=ReviewStatus.PENDING_CONFIRMATION,
                )
                for row in items
            ),
        )

    def get_blinded_item(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
    ) -> BlindedExitReviewItem:
        row = self._batch_item(batch_id, blind_item_id)
        judgments = self.list_judgments(row["decision_event_id"])
        blind = next(
            (
                judgment
                for judgment in judgments
                if judgment.phase is ReviewPhase.BLIND
            ),
            None,
        )
        return BlindedExitReviewItem(
            blind_item_id=blind_item_id,
            setup_version_id=row["review_setup_version_id"],
            symbol=row["symbol"],
            direction=row["direction"],
            decision_cutoff_utc_ms=int(row["decision_cutoff_utc_ms"]),
            charts=self._market_data.blinded_charts(row),
            position=ExitPositionSnapshot(
                anonymous_position_id=_stable_id(
                    "position",
                    blind_item_id,
                ),
                actual_entry_price=row.get("actual_entry_price"),
                entry_atr20=row.get("entry_atr20"),
                entry_bar_index=row.get("entry_bar_index"),
                decision_bar_index=row.get("decision_bar_index"),
                take_profit_status=OptionalRiskLevelStatus(
                    row["take_profit_status"]
                ),
                take_profit_price=row.get("take_profit_price"),
                stop_loss_status=OptionalRiskLevelStatus(
                    row["stop_loss_status"]
                ),
                stop_loss_price=row.get("stop_loss_price"),
            ),
            account_pressure=AccountPressureSnapshot(
                equity_before_decision=row.get("equity_before_decision"),
                position_notional_quote=row.get("position_notional_quote"),
                position_equity_ratio=row.get("position_equity_ratio"),
                total_open_notional_quote=row.get("total_open_notional_quote"),
                total_exposure_ratio=row.get("total_exposure_ratio"),
                open_position_count=int(row["open_position_count"]),
                account_drawdown_pct=row.get("account_drawdown_pct"),
                leverage=row.get("leverage"),
                margin_quote=row.get("margin_quote"),
                liquidation_price=row.get("liquidation_price"),
            ),
            setup_link_status=row["setup_link_status"],
            eligible_for_formal_research=bool(
                row["eligible_for_formal_research"]
            ),
            status=self._status(row["decision_event_id"]),
            judgment=blind,
        )

    def save_blind_judgment(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
        judgment: ExitBlindJudgmentInput,
    ) -> ExitJudgmentVersion:
        if not isinstance(judgment, ExitBlindJudgmentInput):
            raise TypeError("judgment must be ExitBlindJudgmentInput")
        row = self._batch_item(batch_id, blind_item_id)
        decision_event_id = row["decision_event_id"]
        if self._storage.get_exit_review_reveal(decision_event_id) is not None:
            raise ValueError("A revealed review cannot accept a blind judgment")
        if self.list_judgments(decision_event_id):
            raise ValueError("The blind judgment has already been saved")
        persisted = {
            "judgment_id": "exit_judgment_" + uuid.uuid4().hex,
            "decision_event_id": decision_event_id,
            "version_number": 1,
            "phase": ReviewPhase.BLIND.value,
            "label": judgment.label.value,
            "reason_tags": judgment.reason_tags,
            "confidence": judgment.confidence,
            "note": judgment.note,
            "previous_judgment_id": None,
            "eligible_for_primary_research": bool(
                row["eligible_for_formal_research"]
            ),
            "created_at": datetime.now(UTC).isoformat(
                timespec="microseconds"
            ),
        }
        if not self._storage.insert_exit_judgment(persisted):
            list_exclusions = getattr(
                self._storage,
                "list_exit_candidate_exclusions",
                None,
            )
            if callable(list_exclusions) and decision_event_id in set(
                list_exclusions()
            ):
                raise PermissionError(
                    "A candidate revealed in free browse cannot accept "
                    "a blind judgment"
                )
            raise ValueError("The blind judgment has already been saved")
        return _judgment_version(persisted)

    def list_judgments(
        self,
        decision_event_id: str,
    ) -> tuple[ExitJudgmentVersion, ...]:
        return tuple(
            _judgment_version(row)
            for row in self._storage.list_exit_judgments(decision_event_id)
        )

    def list_primary_research_judgments(
        self,
        decision_event_id: str,
    ) -> tuple[ExitJudgmentVersion, ...]:
        return tuple(
            judgment
            for judgment in self.list_judgments(decision_event_id)
            if judgment.eligible_for_primary_research
        )

    def get_candidate_audit_after_judgment(
        self,
        decision_event_id: str,
    ) -> RevealedCandidateAudit | None:
        event_id = _required_text(decision_event_id, "decision_event_id")
        if not any(
            judgment.phase is ReviewPhase.BLIND
            for judgment in self.list_judgments(event_id)
        ):
            raise PermissionError(
                "exit candidate audit requires a saved blind judgment"
            )
        load = getattr(self._storage, "get_exit_candidate_audit_for_event", None)
        if not callable(load):
            return None
        row = load(event_id)
        return None if row is None else _candidate_audit(row)

    def get_candidate_audit_for_batch_item_after_judgment(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
    ) -> RevealedCandidateAudit | None:
        row = self._batch_item(batch_id, blind_item_id)
        return self.get_candidate_audit_after_judgment(
            str(row["decision_event_id"])
        )

    def reveal(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
    ) -> RevealedExitReviewItem:
        row = self._batch_item(batch_id, blind_item_id)
        blind = next(
            (
                judgment
                for judgment in self.list_judgments(row["decision_event_id"])
                if judgment.phase is ReviewPhase.BLIND
            ),
            None,
        )
        if blind is None:
            raise ValueError("Save the blind judgment before revealing")
        reveal = self._storage.get_exit_review_reveal(
            row["decision_event_id"]
        )
        if reveal is None:
            reveal = {
                "decision_event_id": row["decision_event_id"],
                "blind_judgment_id": blind.judgment_id,
                "revealed_at": datetime.now(UTC).isoformat(
                    timespec="microseconds"
                ),
            }
            if not self._storage.insert_exit_review_reveal(reveal):
                reveal = self._storage.get_exit_review_reveal(
                    row["decision_event_id"]
                )
                if reveal is None:
                    raise RuntimeError(
                        "Exit review reveal could not be persisted"
                    )
        original = self._storage.get_exit_original_action(
            row["decision_event_id"]
        )
        if original is None:
            raise RuntimeError("Exit review source audit is missing")
        candidate = getattr(
            self._storage,
            "get_exit_candidate_audit_for_event",
            lambda _event_id: None,
        )(row["decision_event_id"])
        return RevealedExitReviewItem(
            blind_item_id=blind_item_id,
            decision_event_id=row["decision_event_id"],
            status=ReviewStatus.REVEALED,
            original=RevealedOriginalExitAction(
                seed_source=ExitSeedSource(original["seed_source"]),
                original_action=OriginalExitAction(
                    original["original_action"]
                ),
                source_event_id=original.get("source_event_id"),
                action_time_utc_ms=original.get("action_time_utc_ms"),
                timing_approximate=bool(row["timing_approximate"]),
                realized_pnl_quote=original.get("realized_pnl_quote"),
            ),
            blind_judgment=blind,
            future_charts=self._market_data.future_charts(row),
            revealed_at=reveal["revealed_at"],
            candidate_audit=(
                None if candidate is None else _candidate_audit(candidate)
            ),
            account_pressure=AccountPressureSnapshot(
                equity_before_decision=row.get("equity_before_decision"),
                position_notional_quote=row.get("position_notional_quote"),
                position_equity_ratio=row.get("position_equity_ratio"),
                total_open_notional_quote=row.get("total_open_notional_quote"),
                total_exposure_ratio=row.get("total_exposure_ratio"),
                open_position_count=int(row["open_position_count"]),
                account_drawdown_pct=row.get("account_drawdown_pct"),
                leverage=row.get("leverage"),
                margin_quote=row.get("margin_quote"),
                liquidation_price=row.get("liquidation_price"),
            ),
        )

    def relabel_after_reveal(
        self,
        *,
        decision_event_id: str,
        judgment: ExitBlindJudgmentInput,
    ) -> ExitJudgmentVersion:
        if not isinstance(judgment, ExitBlindJudgmentInput):
            raise TypeError("judgment must be ExitBlindJudgmentInput")
        event_id = _required_text(decision_event_id, "decision_event_id")
        if self._storage.get_exit_review_reveal(event_id) is None:
            raise ValueError("Post-outcome relabel requires an explicit reveal")
        versions = self.list_judgments(event_id)
        if not versions:
            raise RuntimeError("Revealed exit review has no blind judgment")
        previous = versions[-1]
        persisted = {
            "judgment_id": "exit_judgment_" + uuid.uuid4().hex,
            "decision_event_id": event_id,
            "version_number": previous.version_number + 1,
            "phase": ReviewPhase.POST_OUTCOME.value,
            "label": judgment.label.value,
            "reason_tags": judgment.reason_tags,
            "confidence": judgment.confidence,
            "note": judgment.note,
            "previous_judgment_id": previous.judgment_id,
            "eligible_for_primary_research": False,
            "created_at": datetime.now(UTC).isoformat(
                timespec="microseconds"
            ),
        }
        self._storage.insert_exit_judgment(persisted)
        return _judgment_version(persisted)

    def relabel_batch_item_after_reveal(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
        judgment: ExitBlindJudgmentInput,
    ) -> ExitJudgmentVersion:
        row = self._batch_item(batch_id, blind_item_id)
        return self.relabel_after_reveal(
            decision_event_id=row["decision_event_id"],
            judgment=judgment,
        )

    def _entry_setup_link(
        self,
        trade: dict[str, Any],
    ) -> dict[str, Any] | None:
        entry_event_id = _required_text(
            trade.get("entry_event_id"),
            "entry_event_id",
        )
        links = self._storage.list_entry_setup_links(
            source_sample_id=entry_event_id,
        )
        setup_ids = {str(row["setup_version_id"]) for row in links}
        if not links:
            return None
        if len(setup_ids) != 1:
            raise ValueError(
                "The closed position has ambiguous entry Setup versions"
            )
        return links[0]

    def _linked_entry_setup(self, trade: dict[str, Any]) -> dict[str, Any]:
        link = self._entry_setup_link(trade)
        if link is None:
            raise ValueError(
                "The position is not linked to an entry Setup version"
            )
        return link

    def _batch_item(self, batch_id: str, blind_item_id: str) -> dict[str, Any]:
        row = self._storage.get_exit_review_batch_item(
            batch_id=_required_text(batch_id, "batch_id"),
            blind_item_id=_required_text(blind_item_id, "blind_item_id"),
        )
        if row is None:
            raise KeyError("Unknown exit blind-review batch item")
        return row

    def _status(self, decision_event_id: str) -> ReviewStatus:
        if self._storage.get_exit_review_reveal(decision_event_id) is not None:
            return ReviewStatus.REVEALED
        if self._storage.list_exit_judgments(decision_event_id):
            return ReviewStatus.JUDGED_BLIND
        return ReviewStatus.PENDING_CONFIRMATION

    def _entry_atr20(
        self,
        *,
        symbol: str,
        interval: str,
        entry_cutoff_utc_ms: int,
    ) -> float | None:
        duration = interval_to_ms(interval)
        rows = self._storage.fetch_klines_for_range(
            symbol=symbol,
            interval=interval,
            start_time_utc_ms=max(0, entry_cutoff_utc_ms - duration * 32),
            end_time_utc_ms=entry_cutoff_utc_ms - 1,
        )
        rows = sorted(rows, key=lambda row: int(row["open_time_utc_ms"]))
        if len(rows) < 21:
            return None
        true_ranges = []
        for previous, current in zip(rows, rows[1:], strict=False):
            high = _finite_or_none(current.get("high"))
            low = _finite_or_none(current.get("low"))
            previous_close = _finite_or_none(previous.get("close"))
            if high is None or low is None or previous_close is None:
                return None
            true_ranges.append(
                max(
                    high - low,
                    abs(high - previous_close),
                    abs(low - previous_close),
                )
            )
        if len(true_ranges) < 20:
            return None
        atr = sum(true_ranges[-20:]) / 20.0
        return atr if math.isfinite(atr) and atr > 0 else None

    def _account_pressure(
        self,
        *,
        trade: dict[str, Any],
        close_event_id: str,
        decision_bar_index: int | None,
    ) -> dict[str, Any]:
        session_id = str(trade.get("session_id") or "")
        trades = (
            self._storage.fetch_table("trades", "session_id=?", (session_id,))
            if session_id
            else []
        )
        open_at_decision = []
        for candidate in trades:
            entry_index = _optional_int(candidate.get("entry_bar_index"))
            exit_index = _optional_int(candidate.get("exit_bar_index"))
            if decision_bar_index is None or entry_index is None:
                continue
            if entry_index <= decision_bar_index and (
                exit_index is None or exit_index >= decision_bar_index
            ):
                open_at_decision.append(candidate)
        notionals = [
            value
            for value in (
                _finite_or_none(candidate.get("notional_quote"))
                for candidate in open_at_decision
            )
            if value is not None and value >= 0
        ]
        total_open_notional = sum(notionals) if notionals else None
        equity_rows = (
            self._storage.fetch_table(
                "account_equity",
                "session_id=?",
                (session_id,),
            )
            if session_id
            else []
        )
        current_equity_row = next(
            (
                row
                for row in equity_rows
                if str(row.get("event_id") or "") == close_event_id
            ),
            None,
        )
        current_sequence = _optional_int(
            (current_equity_row or {}).get("sequence_no")
        )
        if current_sequence is not None:
            prior_equity_rows = [
                row
                for row in equity_rows
                if (
                    _optional_int(row.get("sequence_no")) is not None
                    and int(row["sequence_no"]) < current_sequence
                )
            ]
        else:
            closed_before_ids = {
                str(candidate.get("trade_id") or "")
                for candidate in trades
                if (
                    decision_bar_index is not None
                    and _optional_int(candidate.get("exit_bar_index")) is not None
                    and int(candidate["exit_bar_index"]) < decision_bar_index
                )
            }
            prior_equity_rows = [
                row
                for row in equity_rows
                if str(row.get("trade_id") or "") in closed_before_ids
            ]
        equity_before = _finite_or_none(
            (current_equity_row or {}).get("equity_before")
        )
        if equity_before is None and session_id:
            sessions = self._storage.fetch_table(
                "sessions",
                "session_id=?",
                (session_id,),
            )
            if sessions:
                equity_before = _finite_or_none(sessions[0].get("initial_equity"))
        if current_equity_row is None and prior_equity_rows:
            last_prior = max(
                prior_equity_rows,
                key=lambda row: int(row.get("sequence_no") or 0),
            )
            equity_before = _finite_or_none(last_prior.get("equity_after"))
        position_notional = _finite_or_none(trade.get("notional_quote"))
        ratio = (
            position_notional / equity_before
            if position_notional is not None and equity_before not in (None, 0.0)
            else None
        )
        total_ratio = (
            total_open_notional / equity_before
            if total_open_notional is not None and equity_before not in (None, 0.0)
            else None
        )
        prior_equities = [
            value
            for row in prior_equity_rows
            for value in [_finite_or_none(row.get("equity_after"))]
            if value is not None
        ]
        peak = max(
            prior_equities
            + ([equity_before] if equity_before is not None else []),
            default=None,
        )
        drawdown = (
            (equity_before / peak - 1.0) * 100.0
            if equity_before is not None and peak not in (None, 0.0)
            else None
        )
        return {
            "equity_before_decision": equity_before,
            "position_notional_quote": position_notional,
            "position_equity_ratio": ratio,
            "total_open_notional_quote": total_open_notional,
            "total_exposure_ratio": total_ratio,
            "open_position_count": len(open_at_decision),
            "account_drawdown_pct": drawdown,
            "leverage": None,
            "margin_quote": None,
            "liquidation_price": None,
        }


def _judgment_version(row: dict[str, Any]) -> ExitJudgmentVersion:
    return ExitJudgmentVersion(
        judgment_id=row["judgment_id"],
        decision_event_id=row["decision_event_id"],
        version_number=int(row["version_number"]),
        phase=ReviewPhase(row["phase"]),
        label=ExitJudgmentLabel(row["label"]),
        reason_tags=tuple(row["reason_tags"]),
        confidence=int(row["confidence"]),
        note=row["note"],
        previous_judgment_id=row.get("previous_judgment_id"),
        eligible_for_primary_research=bool(
            row["eligible_for_primary_research"]
        ),
        created_at=row["created_at"],
    )


def _candidate_audit(row: dict[str, Any]) -> RevealedCandidateAudit:
    import json

    references = json.loads(row["references_json"])
    distances = tuple(json.loads(row["diversity_vector_json"]))
    return RevealedCandidateAudit(
        similarity=float(row["similarity"]),
        group_distances=distances[:12],
        references=tuple(
            RevealedCandidateReference(
                decision_event_id=item["decision_event_id"],
                episode_id=item["holding_episode_id"],
                similarity=float(item["similarity"]),
            )
            for item in references
        ),
        enqueue_reason=str(row["enqueue_reason"]),
        selection_reason=str(row["selection_reason"]),
        research_target="EXIT",
        position_distance=(
            float(distances[12]) if len(distances) > 12 else None
        ),
    )


def _aware_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Decision times must include an explicit timezone")
    return parsed.astimezone(UTC)


def _entry_price(trade: dict[str, Any]) -> tuple[float | None, str]:
    fill = _finite_or_none(trade.get("entry_fill_price"))
    if fill is not None and fill > 0:
        return fill, "FILL"
    proxy = _finite_or_none(trade.get("entry_price_proxy"))
    if proxy is not None and proxy > 0:
        return proxy, "PROXY"
    return None, "MISSING"


def _risk_level(
    configured_pct: Any,
    configured_price: Any,
) -> tuple[OptionalRiskLevelStatus, float | None]:
    if configured_pct is None:
        return OptionalRiskLevelStatus.NOT_SET, None
    price = _finite_or_none(configured_price)
    if price is None or price <= 0:
        return OptionalRiskLevelStatus.MISSING, None
    return OptionalRiskLevelStatus.SET, price


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _manual_decision_bar_index(
    trade: dict[str, Any],
    *,
    entry_time: datetime,
    decision_time: datetime,
    decision_interval: str,
) -> int | None:
    entry_index = _optional_int(trade.get("entry_bar_index"))
    if entry_index is None:
        return None
    elapsed_ms = int((decision_time - entry_time).total_seconds() * 1_000)
    return entry_index + max(0, elapsed_ms // interval_to_ms(decision_interval))


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _stable_id(prefix: str, *values: str) -> str:
    digest = hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


__all__ = [
    "EXIT_BLIND_REVIEW_STORAGE_METHODS",
    "ExitBlindReviewService",
    "MAX_BLIND_BATCH_SIZE",
    "PartialExitUnsupportedError",
    "supports_exit_blind_review_storage",
]
