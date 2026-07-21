from __future__ import annotations

from dataclasses import dataclass, replace

try:
    from market_data.types import VALID_INTERVALS
except ImportError:  # pragma: no cover - package import path
    from .market_data.types import VALID_INTERVALS


PRIMARY_TABS = ("entry", "exit")
RESEARCH_STEPS = (
    "sample_review",
    "similar_candidates",
    "behavior_model",
    "outcome_comparison",
    "version_report",
)
DIRECTIONS = ("LONG", "SHORT")
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m")
COMPLETENESS_STATES = ("not_audited", "incomplete", "complete")
MATURITY_STATES = ("not_ready", "mature")
RESEARCH_TIMEFRAMES = tuple(
    sorted(
        VALID_INTERVALS,
        key=lambda interval: (
            "mhdw".index(interval[-1]),
            int(interval[:-1]),
        ),
    )
)
_STEP_CONTEXT_REQUIREMENTS = {
    "sample_review": ("setup",),
    "similar_candidates": ("setup", "completeness"),
    "behavior_model": ("setup", "completeness", "maturity"),
    "outcome_comparison": ("setup", "completeness"),
    "version_report": ("setup",),
}


@dataclass(frozen=True, slots=True)
class DecisionResearchModeState:
    setup_id: str | None = None
    setup_version_id: str | None = None
    direction: str = DIRECTIONS[0]
    timeframes: tuple[str, str, str] = DEFAULT_TIMEFRAMES
    data_completeness: str = "not_audited"
    maturity: str = "not_ready"
    grouping_version_id: str | None = None
    blind_batch_id: str | None = None
    candidate_run_id: str | None = None
    behavior_snapshot_id: str | None = None
    outcome_comparison_id: str | None = None
    loading: bool = False
    error: str | None = None
    stale_dependencies: tuple[str, ...] = ()


_UNSET = object()
_DOWNSTREAM_DEPENDENCIES = (
    "blind_batch",
    "candidate_run",
    "behavior_snapshot",
    "outcome_comparison",
)


class DecisionResearchPageState:
    """Navigation plus isolated immutable state for entry and exit research."""

    def __init__(
        self,
        *,
        primary_tab: str = PRIMARY_TABS[0],
        current_step: str = RESEARCH_STEPS[0],
        setup_id: str | None = None,
        setup_version: str | None = None,
        direction: str = DIRECTIONS[0],
        timeframes: tuple[str, str, str] = DEFAULT_TIMEFRAMES,
        completeness: str = "not_audited",
        maturity: str = "not_ready",
        entry: DecisionResearchModeState | None = None,
        exit: DecisionResearchModeState | None = None,
    ) -> None:
        self.primary_tab = PRIMARY_TABS[0]
        self.current_step = RESEARCH_STEPS[0]
        self.entry = entry or DecisionResearchModeState()
        self.exit = exit or DecisionResearchModeState()
        self.select_primary_tab(primary_tab)
        self.select_step(current_step)
        self.update_context(direction=direction, timeframes=timeframes)
        self.update_setup_identity(setup_id)
        self.update_readiness(
            setup_version=setup_version,
            completeness=completeness,
            maturity=maturity,
        )

    @property
    def active_mode(self) -> DecisionResearchModeState:
        return self.entry if self.primary_tab == "entry" else self.exit

    def _replace_active(self, **changes) -> None:
        updated = replace(self.active_mode, **changes)
        if self.primary_tab == "entry":
            self.entry = updated
        else:
            self.exit = updated

    @property
    def setup_id(self) -> str | None:
        return self.active_mode.setup_id

    @property
    def setup_version(self) -> str | None:
        return self.active_mode.setup_version_id

    @property
    def setup_version_id(self) -> str | None:
        return self.active_mode.setup_version_id

    @property
    def direction(self) -> str:
        return self.active_mode.direction

    @property
    def timeframes(self) -> tuple[str, str, str]:
        return self.active_mode.timeframes

    @property
    def completeness(self) -> str:
        return self.active_mode.data_completeness

    @property
    def maturity(self) -> str:
        return self.active_mode.maturity

    @property
    def grouping_version_id(self) -> str | None:
        return self.active_mode.grouping_version_id

    @property
    def blind_batch_id(self) -> str | None:
        return self.active_mode.blind_batch_id

    @property
    def candidate_run_id(self) -> str | None:
        return self.active_mode.candidate_run_id

    @property
    def behavior_snapshot_id(self) -> str | None:
        return self.active_mode.behavior_snapshot_id

    @property
    def outcome_comparison_id(self) -> str | None:
        return self.active_mode.outcome_comparison_id

    @property
    def stale_dependencies(self) -> tuple[str, ...]:
        return self.active_mode.stale_dependencies

    def update_setup_identity(self, setup_id: str | None) -> None:
        normalized = str(setup_id).strip() if setup_id is not None else None
        if normalized == "":
            raise ValueError("Setup id must be non-empty when provided")
        self._replace_active(setup_id=normalized)

    def update_readiness(
        self,
        *,
        setup_version: str | None,
        completeness: str,
        maturity: str,
    ) -> None:
        if setup_version is not None and not setup_version.strip():
            raise ValueError("Setup version must be non-empty when provided")
        if completeness not in COMPLETENESS_STATES:
            raise ValueError(
                "Unsupported decision-research completeness: "
                f"{completeness}"
            )
        if maturity not in MATURITY_STATES:
            raise ValueError(
                f"Unsupported decision-research maturity: {maturity}"
            )
        previous_version = self.setup_version
        changes = {
            "setup_version_id": setup_version,
            "data_completeness": completeness,
            "maturity": maturity,
        }
        if previous_version is not None and setup_version != previous_version:
            changes.update(
                grouping_version_id=None,
                blind_batch_id=None,
                candidate_run_id=None,
                behavior_snapshot_id=None,
                outcome_comparison_id=None,
                stale_dependencies=_DOWNSTREAM_DEPENDENCIES,
            )
        self._replace_active(**changes)

    def select_primary_tab(self, primary_tab: str) -> None:
        if primary_tab not in PRIMARY_TABS:
            raise ValueError(f"Unsupported decision-research tab: {primary_tab}")
        self.primary_tab = primary_tab

    def select_step(self, step: str) -> None:
        if step not in RESEARCH_STEPS:
            raise ValueError(f"Unsupported decision-research step: {step}")
        self.current_step = step

    def update_context(
        self,
        *,
        direction: str,
        timeframes: tuple[str, str, str],
    ) -> None:
        if direction not in DIRECTIONS:
            raise ValueError(f"Unsupported research direction: {direction}")
        if len(timeframes) != 3:
            raise ValueError("Decision research requires exactly three timeframes")
        unsupported = tuple(
            value for value in timeframes if value not in RESEARCH_TIMEFRAMES
        )
        if unsupported:
            raise ValueError(
                "Unsupported decision-research timeframes: "
                f"{', '.join(unsupported)}"
            )
        self._replace_active(direction=direction, timeframes=timeframes)

    def update_research_versions(
        self,
        *,
        grouping_version_id: str | None | object = _UNSET,
        blind_batch_id: str | None | object = _UNSET,
        candidate_run_id: str | None | object = _UNSET,
        behavior_snapshot_id: str | None | object = _UNSET,
        outcome_comparison_id: str | None | object = _UNSET,
    ) -> None:
        changes: dict[str, object] = {}
        if grouping_version_id is not _UNSET:
            normalized_grouping = _optional_id(
                grouping_version_id,
                "grouping_version_id",
            )
            changes["grouping_version_id"] = normalized_grouping
            if (
                self.grouping_version_id is not None
                and normalized_grouping != self.grouping_version_id
            ):
                changes.update(
                    blind_batch_id=None,
                    candidate_run_id=None,
                    behavior_snapshot_id=None,
                    outcome_comparison_id=None,
                    stale_dependencies=_DOWNSTREAM_DEPENDENCIES,
                )
        for name, value in (
            ("blind_batch_id", blind_batch_id),
            ("candidate_run_id", candidate_run_id),
            ("behavior_snapshot_id", behavior_snapshot_id),
            ("outcome_comparison_id", outcome_comparison_id),
        ):
            if value is not _UNSET:
                changes[name] = _optional_id(value, name)
        if changes:
            self._replace_active(**changes)

    def set_operation_state(
        self,
        *,
        loading: bool,
        error: str | None = None,
    ) -> None:
        self._replace_active(
            loading=bool(loading),
            error=str(error) if error else None,
        )

    def missing_conditions(self, step: str | None = None) -> tuple[str, ...]:
        selected_step = step or self.current_step
        if selected_step not in RESEARCH_STEPS:
            raise ValueError(
                f"Unsupported decision-research step: {selected_step}"
            )
        missing: list[str] = []
        for requirement in _STEP_CONTEXT_REQUIREMENTS[selected_step]:
            if requirement == "setup" and self.setup_version is None:
                missing.append("setup")
            elif requirement == "completeness" and self.completeness != "complete":
                missing.append("completeness")
            elif requirement == "maturity" and self.maturity == "not_ready":
                missing.append("maturity")
        return tuple(missing)


def _optional_id(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty when provided")
    return normalized


__all__ = [
    "COMPLETENESS_STATES",
    "DEFAULT_TIMEFRAMES",
    "DIRECTIONS",
    "DecisionResearchModeState",
    "DecisionResearchPageState",
    "MATURITY_STATES",
    "PRIMARY_TABS",
    "RESEARCH_STEPS",
    "RESEARCH_TIMEFRAMES",
]
