from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

try:
    from market_data.types import normalize_symbol
    from research.entry_blind_review import (
        BlindBatchItem,
        BlindJudgmentInput,
        BlindReviewBatch,
        BlindedEntryReviewItem,
        EntryJudgmentLabel,
        EntryJudgmentVersion,
        EntrySeedReceipt,
        EntrySeedSource,
        OriginalEntryAction,
        RevealedEntryReviewItem,
        RevealedCandidateAudit,
        RevealedCandidateReference,
        RevealedOriginalEntryAction,
        ReviewPhase,
        ReviewStatus,
    )
    from research.market_episodes import MarketEpisodeService
    from services.blind_review_market_data import (
        BlindReviewMarketData,
        DEFAULT_CHART_LOOKBACK_BARS,
        actual_action_timing,
    )
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import normalize_symbol
    from ..research.entry_blind_review import (
        BlindBatchItem,
        BlindJudgmentInput,
        BlindReviewBatch,
        BlindedEntryReviewItem,
        EntryJudgmentLabel,
        EntryJudgmentVersion,
        EntrySeedReceipt,
        EntrySeedSource,
        OriginalEntryAction,
        RevealedEntryReviewItem,
        RevealedCandidateAudit,
        RevealedCandidateReference,
        RevealedOriginalEntryAction,
        ReviewPhase,
        ReviewStatus,
    )
    from ..research.market_episodes import MarketEpisodeService
    from .blind_review_market_data import (
        BlindReviewMarketData,
        DEFAULT_CHART_LOOKBACK_BARS,
        actual_action_timing,
    )


MAX_BLIND_BATCH_SIZE = 20
ENTRY_BLIND_REVIEW_STORAGE_METHODS = (
    "create_entry_review_batch",
    "fetch_event",
    "fetch_klines_for_range",
    "fetch_trade",
    "get_entry_decision_event_by_source",
    "get_entry_original_action",
    "get_entry_review_batch_item",
    "get_entry_review_reveal",
    "get_episode_grouping",
    "get_setup_version",
    "insert_entry_decision_event",
    "insert_entry_judgment",
    "insert_entry_review_reveal",
    "list_actual_open_episode_member_ids",
    "list_entry_judgments",
    "list_pending_entry_decision_events",
    "get_entry_candidate_audit_for_event",
    "list_entry_candidate_exclusions",
)


def supports_entry_blind_review_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None))
        for method in ENTRY_BLIND_REVIEW_STORAGE_METHODS
    )


class EntryBlindReviewService:
    """Public entry-review use cases with a hard blinded payload boundary."""

    def __init__(self, storage: Any) -> None:
        if not supports_entry_blind_review_storage(storage):
            raise TypeError(
                "storage does not implement the entry blind-review contract"
            )
        self._storage = storage
        self._episodes = MarketEpisodeService(storage)
        self._market_data = BlindReviewMarketData(storage)

    def enqueue_actual_open(
        self,
        *,
        trade_event_id: str,
        setup_version_id: str,
        grouping_version_id: str,
    ) -> EntrySeedReceipt:
        source_id = _required_text(trade_event_id, "trade_event_id")
        setup_id = _required_text(setup_version_id, "setup_version_id")
        grouping_id = _required_text(
            grouping_version_id,
            "grouping_version_id",
        )
        existing = self._existing_seed_receipt(
            source_id,
            setup_id,
            grouping_id,
        )
        if existing is not None:
            return existing
        trade_event = self._storage.fetch_event(source_id)
        if trade_event is None:
            raise KeyError(f"Unknown trade event: {source_id}")
        if str(trade_event.get("event_type") or "").upper() != "OPEN":
            raise ValueError("Only actual OPEN events can enter this seed path")
        setup = self._storage.get_setup_version(setup_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {setup_id}")
        direction = str(trade_event.get("side") or "").upper()
        if direction != setup.direction.value:
            raise ValueError(
                "Actual OPEN direction does not match the selected Setup version"
            )
        assignment = self._episodes.resolve_episode_ids(
            grouping_id,
            (source_id,),
        )[0]
        trade = self._storage.fetch_trade(str(trade_event.get("trade_id") or ""))
        timing = actual_action_timing(
            trade_event,
            trade,
            trade_bar_time_field="entry_bar_time_bjt",
            trade_real_time_field="entry_real_time_bjt",
        )
        decision_time_ms = int(timing.decision_time_utc.timestamp() * 1_000)
        observed_time_ms = (
            int(timing.observed_time_utc.timestamp() * 1_000)
            if timing.observed_time_utc is not None
            else None
        )
        return self._persist_seed(
            source_id=source_id,
            setup=setup,
            grouping_version_id=grouping_id,
            episode_id=assignment.episode_id,
            session_id=trade_event.get("session_id"),
            symbol=normalize_symbol(trade_event.get("symbol")),
            direction=direction,
            decision_time_utc_ms=decision_time_ms,
            observed_action_time_utc_ms=observed_time_ms,
            source_time_is_approximate=timing.timing_approximate,
            seed_source=EntrySeedSource.ACTUAL_OPEN,
            original_action=(
                OriginalEntryAction.OPEN_LONG
                if direction == "LONG"
                else OriginalEntryAction.OPEN_SHORT
            ),
            source_event_id=source_id,
        )

    def enqueue_manual_position(
        self,
        *,
        manual_seed_id: str,
        setup_version_id: str,
        grouping_version_id: str,
        symbol: str,
        direction: str,
        decision_time: datetime | str,
        session_id: str | None = None,
    ) -> EntrySeedReceipt:
        source_id = _required_text(manual_seed_id, "manual_seed_id")
        setup_id = _required_text(setup_version_id, "setup_version_id")
        grouping_id = _required_text(
            grouping_version_id,
            "grouping_version_id",
        )
        existing = self._existing_seed_receipt(
            source_id,
            setup_id,
            grouping_id,
        )
        if existing is not None:
            return existing
        setup = self._storage.get_setup_version(setup_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {setup_id}")
        normalized_direction = _required_text(direction, "direction").upper()
        if normalized_direction != setup.direction.value:
            raise ValueError(
                "Manual position direction does not match the selected Setup version"
            )
        assignment = self._episodes.resolve_episode_ids(
            grouping_id,
            (source_id,),
        )[0]
        selected_time = _aware_datetime(decision_time)
        selected_time_ms = int(selected_time.timestamp() * 1000)
        return self._persist_seed(
            source_id=source_id,
            setup=setup,
            grouping_version_id=grouping_id,
            episode_id=assignment.episode_id,
            session_id=session_id,
            symbol=normalize_symbol(symbol),
            direction=normalized_direction,
            decision_time_utc_ms=selected_time_ms,
            observed_action_time_utc_ms=None,
            source_time_is_approximate=False,
            seed_source=EntrySeedSource.MANUAL_POSITION,
            original_action=OriginalEntryAction.NONE,
            source_event_id=None,
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
        for trade_event_id in self._storage.list_actual_open_episode_member_ids(
            setup_version_id=setup_id,
            grouping_version_id=grouping_id,
            direction=setup.direction.value,
            limit=size,
        ):
            self.enqueue_actual_open(
                trade_event_id=trade_event_id,
                setup_version_id=setup_id,
                grouping_version_id=grouping_id,
            )
        pending = self._storage.list_pending_entry_decision_events(
            setup_version_id=setup_id,
            grouping_version_id=grouping_id,
            limit=size,
        )
        if pending:
            first_batch = self._episodes.build_isolated_batches(
                grouping_id,
                tuple(str(row["source_sample_id"]) for row in pending),
                batch_size=size,
            )[0]
            pending_by_sample = {
                str(row["source_sample_id"]): row
                for row in pending
            }
            selected = [
                pending_by_sample[sample_id]
                for sample_id in first_batch.sample_ids
            ]
        else:
            selected = []
        batch_id = "entry_batch_" + uuid.uuid4().hex
        rows = [
            {
                "blind_item_id": _stable_id(
                    "blind_item",
                    batch_id,
                    str(row["decision_event_id"]),
                ),
                "decision_event_id": row["decision_event_id"],
            }
            for row in selected
        ]
        rows.sort(key=lambda row: row["blind_item_id"])
        persisted_items = [
            {**row, "display_order": index}
            for index, row in enumerate(rows)
        ]
        created_at = datetime.now(UTC).isoformat(timespec="microseconds")
        self._storage.create_entry_review_batch(
            batch={
                "batch_id": batch_id,
                "setup_version_id": setup_id,
                "grouping_version_id": grouping_id,
                "created_at": created_at,
            },
            items=persisted_items,
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
                for row in persisted_items
            ),
        )

    def get_blinded_item(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
    ) -> BlindedEntryReviewItem:
        row = self._batch_item(batch_id, blind_item_id)
        judgments = self.list_judgments(row["decision_event_id"])
        blind_judgment = next(
            (
                judgment
                for judgment in judgments
                if judgment.phase is ReviewPhase.BLIND
            ),
            None,
        )
        return BlindedEntryReviewItem(
            blind_item_id=blind_item_id,
            decision_event_id=row["decision_event_id"],
            setup_version_id=row["setup_version_id"],
            symbol=row["symbol"],
            direction=row["direction"],
            decision_cutoff_utc_ms=int(row["decision_cutoff_utc_ms"]),
            charts=self._market_data.blinded_charts(row),
            status=self._status(row["decision_event_id"]),
            judgment=blind_judgment,
        )

    def save_blind_judgment(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
        judgment: BlindJudgmentInput,
    ) -> EntryJudgmentVersion:
        if not isinstance(judgment, BlindJudgmentInput):
            raise TypeError("judgment must be BlindJudgmentInput")
        row = self._batch_item(batch_id, blind_item_id)
        decision_event_id = row["decision_event_id"]
        if self._storage.get_entry_review_reveal(decision_event_id) is not None:
            raise ValueError("A revealed review cannot accept a blind judgment")
        if self.list_judgments(decision_event_id):
            raise ValueError("The blind judgment has already been saved")
        created_at = datetime.now(UTC).isoformat(timespec="microseconds")
        persisted = {
            "judgment_id": "entry_judgment_" + uuid.uuid4().hex,
            "decision_event_id": decision_event_id,
            "version_number": 1,
            "phase": ReviewPhase.BLIND.value,
            "label": judgment.label.value,
            "reason_tags": judgment.reason_tags,
            "confidence": judgment.confidence,
            "note": judgment.note,
            "previous_judgment_id": None,
            "eligible_for_primary_research": True,
            "created_at": created_at,
        }
        inserted = self._storage.insert_entry_judgment(persisted)
        if not inserted:
            if row["source_sample_id"] in set(
                self._storage.list_entry_candidate_exclusions()
            ):
                raise PermissionError(
                    "A candidate revealed in free browse cannot accept a blind judgment"
                )
            raise ValueError("The blind judgment has already been saved")
        return _judgment_version(persisted)

    def list_judgments(
        self,
        decision_event_id: str,
    ) -> tuple[EntryJudgmentVersion, ...]:
        return tuple(
            _judgment_version(row)
            for row in self._storage.list_entry_judgments(
                decision_event_id
            )
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
                "candidate audit requires a saved blind judgment"
            )
        row = self._storage.get_entry_candidate_audit_for_event(event_id)
        return None if row is None else _candidate_audit(row)

    def reveal(
        self,
        *,
        batch_id: str,
        blind_item_id: str,
    ) -> RevealedEntryReviewItem:
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
        if blind is None:
            raise ValueError("Save the blind judgment before revealing")
        reveal = self._storage.get_entry_review_reveal(
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
            inserted = self._storage.insert_entry_review_reveal(reveal)
            if not inserted:
                reveal = self._storage.get_entry_review_reveal(
                    row["decision_event_id"]
                )
                if reveal is None:
                    raise RuntimeError(
                        "Entry review reveal could not be persisted"
                    )
        original = self._storage.get_entry_original_action(
            row["decision_event_id"]
        )
        candidate = self._storage.get_entry_candidate_audit_for_event(
            row["decision_event_id"]
        )
        if original is None and candidate is None:
            raise RuntimeError("Entry review source audit is missing")
        if original is None:
            original_view = RevealedOriginalEntryAction(
                seed_source=EntrySeedSource.SIMILAR_CANDIDATE,
                original_action=OriginalEntryAction.NONE,
                source_event_id=None,
                action_time_utc_ms=None,
                timing_approximate=False,
            )
        else:
            original_view = RevealedOriginalEntryAction(
                seed_source=EntrySeedSource(original["seed_source"]),
                original_action=OriginalEntryAction(original["original_action"]),
                source_event_id=original.get("source_event_id"),
                action_time_utc_ms=original.get("action_time_utc_ms"),
                timing_approximate=bool(original["timing_approximate"]),
            )
        return RevealedEntryReviewItem(
            blind_item_id=blind_item_id,
            decision_event_id=row["decision_event_id"],
            status=ReviewStatus.REVEALED,
            original=original_view,
            blind_judgment=blind,
            future_charts=self._market_data.future_charts(row),
            revealed_at=reveal["revealed_at"],
            candidate_audit=(
                None if candidate is None else _candidate_audit(candidate)
            ),
        )

    def relabel_after_reveal(
        self,
        *,
        decision_event_id: str,
        judgment: BlindJudgmentInput,
    ) -> EntryJudgmentVersion:
        if not isinstance(judgment, BlindJudgmentInput):
            raise TypeError("judgment must be BlindJudgmentInput")
        event_id = _required_text(
            decision_event_id,
            "decision_event_id",
        )
        if self._storage.get_entry_review_reveal(event_id) is None:
            raise ValueError("Post-outcome relabel requires an explicit reveal")
        versions = self.list_judgments(event_id)
        if not versions:
            raise RuntimeError("Revealed entry review has no blind judgment")
        previous = versions[-1]
        persisted = {
            "judgment_id": "entry_judgment_" + uuid.uuid4().hex,
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
        self._storage.insert_entry_judgment(persisted)
        return _judgment_version(persisted)

    def list_primary_research_judgments(
        self,
        decision_event_id: str,
    ) -> tuple[EntryJudgmentVersion, ...]:
        return tuple(
            judgment
            for judgment in self.list_judgments(decision_event_id)
            if judgment.eligible_for_primary_research
        )

    def _batch_item(
        self,
        batch_id: str,
        blind_item_id: str,
    ) -> dict[str, Any]:
        row = self._storage.get_entry_review_batch_item(
            batch_id=_required_text(batch_id, "batch_id"),
            blind_item_id=_required_text(blind_item_id, "blind_item_id"),
        )
        if row is None:
            raise KeyError("Unknown blind-review batch item")
        return row

    def _existing_seed_receipt(
        self,
        source_sample_id: str,
        setup_version_id: str,
        grouping_version_id: str,
    ) -> EntrySeedReceipt | None:
        existing = self._storage.get_entry_decision_event_by_source(
            source_sample_id=source_sample_id,
            setup_version_id=setup_version_id,
            grouping_version_id=grouping_version_id,
        )
        if existing is None:
            return None
        decision_event_id = str(existing["decision_event_id"])
        return EntrySeedReceipt(
            decision_event_id=decision_event_id,
            status=self._status(decision_event_id),
        )

    def _persist_seed(
        self,
        *,
        source_id: str,
        setup: Any,
        grouping_version_id: str,
        episode_id: str,
        session_id: str | None,
        symbol: str,
        direction: str,
        decision_time_utc_ms: int,
        observed_action_time_utc_ms: int | None,
        source_time_is_approximate: bool,
        seed_source: EntrySeedSource,
        original_action: OriginalEntryAction,
        source_event_id: str | None,
    ) -> EntrySeedReceipt:
        decision_bar_open_ms, cutoff_ms = self._market_data.decision_bar_boundary(
            symbol=symbol,
            interval=setup.timeframes.decision,
            decision_time_utc_ms=decision_time_utc_ms,
        )
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        decision_event_id = _stable_id(
            "entry_decision",
            source_id,
            setup.setup_version_id,
            grouping_version_id,
        )
        created = self._storage.insert_entry_decision_event(
            event={
                "decision_event_id": decision_event_id,
                "source_sample_id": source_id,
                "setup_version_id": setup.setup_version_id,
                "grouping_version_id": grouping_version_id,
                "episode_id": episode_id,
                "session_id": session_id,
                "symbol": symbol,
                "direction": direction,
                "decision_timeframe": setup.timeframes.decision,
                "context_timeframe_one": setup.timeframes.context_one,
                "context_timeframe_two": setup.timeframes.context_two,
                "decision_cutoff_utc_ms": cutoff_ms,
                "decision_bar_open_time_utc_ms": decision_bar_open_ms,
                "observed_action_time_utc_ms": observed_action_time_utc_ms,
                "timing_approximate": (
                    source_time_is_approximate
                    or (
                        observed_action_time_utc_ms is not None
                        and observed_action_time_utc_ms - cutoff_ms > 0
                    )
                ),
                "created_at": now,
            },
            original_action={
                "seed_source": seed_source.value,
                "original_action": original_action.value,
                "source_event_id": source_event_id,
                "action_time_utc_ms": observed_action_time_utc_ms,
                "created_at": now,
            },
        )
        return EntrySeedReceipt(
            decision_event_id=decision_event_id,
            status=(
                ReviewStatus.PENDING_CONFIRMATION
                if created
                else self._status(decision_event_id)
            ),
        )

    def _status(self, decision_event_id: str) -> ReviewStatus:
        if self._storage.get_entry_review_reveal(decision_event_id) is not None:
            return ReviewStatus.REVEALED
        if self._storage.list_entry_judgments(decision_event_id):
            return ReviewStatus.JUDGED_BLIND
        return ReviewStatus.PENDING_CONFIRMATION

def _judgment_version(row: dict[str, Any]) -> EntryJudgmentVersion:
    return EntryJudgmentVersion(
        judgment_id=row["judgment_id"],
        decision_event_id=row["decision_event_id"],
        version_number=int(row["version_number"]),
        phase=ReviewPhase(row["phase"]),
        label=EntryJudgmentLabel(row["label"]),
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
    return RevealedCandidateAudit(
        similarity=float(row["similarity"]),
        group_distances=tuple(json.loads(row["diversity_vector_json"])),
        references=tuple(
            RevealedCandidateReference(
                decision_event_id=item["decision_event_id"],
                episode_id=item["episode_id"],
                similarity=float(item["similarity"]),
            )
            for item in references
        ),
        enqueue_reason="STRUCTURAL_SIMILARITY",
        selection_reason=str(row["selection_reason"]),
    )


def _aware_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Decision times must include an explicit timezone")
    return parsed.astimezone(UTC)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _stable_id(prefix: str, *values: str) -> str:
    payload = "|".join(values)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


__all__ = [
    "DEFAULT_CHART_LOOKBACK_BARS",
    "ENTRY_BLIND_REVIEW_STORAGE_METHODS",
    "EntryBlindReviewService",
    "MAX_BLIND_BATCH_SIZE",
    "supports_entry_blind_review_storage",
]
