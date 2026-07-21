from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol, TypeVar

try:
    from errors import DatabaseError
    from market_data.types import (
        VALID_INTERVALS,
        interval_to_ms,
        normalize_interval,
    )
except ImportError:  # pragma: no cover - package import path
    from ..errors import DatabaseError
    from ..market_data.types import (
        VALID_INTERVALS,
        interval_to_ms,
        normalize_interval,
    )


class SetupDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class DecisionProtocol(str, Enum):
    CURRENT_BAR_CLOSE = "CURRENT_BAR_CLOSE"
    NEXT_BAR_CONFIRMATION = "NEXT_BAR_CONFIRMATION"


class SetupErrorCode(str, Enum):
    INVALID_NAME = "invalid_name"
    INVALID_DIRECTION = "invalid_direction"
    INVALID_PROTOCOL = "invalid_protocol"
    INVALID_RULES = "invalid_rules"
    UNSUPPORTED_TIMEFRAME = "unsupported_timeframe"
    TIMEFRAME_ORDER = "timeframe_order"
    NO_HIGHER_TIMEFRAMES = "no_higher_timeframes"
    SETUP_ARCHIVED = "setup_archived"
    STALE_VERSION = "stale_version"
    NO_SEMANTIC_CHANGE = "no_semantic_change"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    SETUP_NOT_FOUND = "setup_not_found"
    VERSION_NOT_FOUND = "version_not_found"
    PERSISTENCE = "persistence"


class SetupValidationError(ValueError):
    def __init__(
        self,
        code: SetupErrorCode,
        *,
        field: str,
        detail: str,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.field = field
        self.detail = detail


class SetupPersistenceError(RuntimeError):
    code = SetupErrorCode.PERSISTENCE


_T = TypeVar("_T")


def _storage_call(
    operation: Callable[[], _T],
    message: str,
) -> _T:
    try:
        return operation()
    except DatabaseError as exc:
        raise SetupPersistenceError(message) from exc


class SetupLookupError(LookupError):
    def __init__(
        self,
        code: SetupErrorCode,
        *,
        identity: str,
    ) -> None:
        super().__init__(f"{code.value}: {identity}")
        self.code = code
        self.identity = identity


@dataclass(frozen=True)
class TimeframeProfile:
    decision: str
    context_one: str
    context_two: str

    def __post_init__(self) -> None:
        try:
            normalized = tuple(
                normalize_interval(interval)
                for interval in (
                    self.decision,
                    self.context_one,
                    self.context_two,
                )
            )
        except ValueError as exc:
            raise SetupValidationError(
                SetupErrorCode.UNSUPPORTED_TIMEFRAME,
                field="timeframes",
                detail=str(exc),
            ) from exc
        if not (
            interval_to_ms(normalized[0])
            < interval_to_ms(normalized[1])
            < interval_to_ms(normalized[2])
        ):
            raise SetupValidationError(
                SetupErrorCode.TIMEFRAME_ORDER,
                field="timeframes",
                detail=(
                    "Setup timeframes must be strictly increasing and unique"
                ),
            )
        object.__setattr__(self, "decision", normalized[0])
        object.__setattr__(self, "context_one", normalized[1])
        object.__setattr__(self, "context_two", normalized[2])

    def as_tuple(self) -> tuple[str, str, str]:
        return self.decision, self.context_one, self.context_two


@dataclass(frozen=True)
class SetupVersionSpec:
    direction: SetupDirection | str
    decision_protocol: DecisionProtocol | str
    decision_rules: str
    timeframes: TimeframeProfile

    def __post_init__(self) -> None:
        try:
            direction = (
                self.direction
                if isinstance(self.direction, SetupDirection)
                else SetupDirection(str(self.direction).upper())
            )
        except ValueError as exc:
            raise SetupValidationError(
                SetupErrorCode.INVALID_DIRECTION,
                field="direction",
                detail=f"Unsupported Setup direction: {self.direction}",
            ) from exc
        try:
            protocol = (
                self.decision_protocol
                if isinstance(self.decision_protocol, DecisionProtocol)
                else DecisionProtocol(str(self.decision_protocol).upper())
            )
        except ValueError as exc:
            raise SetupValidationError(
                SetupErrorCode.INVALID_PROTOCOL,
                field="decision_protocol",
                detail=(
                    "Unsupported Setup decision protocol: "
                    f"{self.decision_protocol}"
                ),
            ) from exc
        rules = str(self.decision_rules or "").strip()
        if not rules:
            raise SetupValidationError(
                SetupErrorCode.INVALID_RULES,
                field="decision_rules",
                detail="Setup decision rules must be non-empty",
            )
        if not isinstance(self.timeframes, TimeframeProfile):
            raise TypeError("Setup timeframes must be a TimeframeProfile")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "decision_protocol", protocol)
        object.__setattr__(self, "decision_rules", rules)

    def fingerprint(self) -> str:
        payload = "|".join(
            (
                self.direction.value,
                self.decision_protocol.value,
                self.decision_rules,
                *self.timeframes.as_tuple(),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Setup:
    setup_id: str
    display_name: str
    is_archived: bool
    created_at: str
    updated_at: str
    archived_at: str | None = None


@dataclass(frozen=True)
class SetupVersion:
    setup_version_id: str
    setup_id: str
    version_number: int
    direction: SetupDirection
    decision_protocol: DecisionProtocol
    decision_rules: str
    timeframes: TimeframeProfile
    created_at: str
    parent_version_id: str | None = None

    @property
    def spec(self) -> SetupVersionSpec:
        return SetupVersionSpec(
            direction=self.direction,
            decision_protocol=self.decision_protocol,
            decision_rules=self.decision_rules,
            timeframes=self.timeframes,
        )


@dataclass(frozen=True)
class SetupWithVersion:
    setup: Setup
    version: SetupVersion


@dataclass(frozen=True)
class SetupVersionExport:
    setup_id: str
    setup_version_id: str
    version_number: int
    direction: str
    decision_protocol: str
    decision_rules: str
    decision_timeframe: str
    context_timeframe_one: str
    context_timeframe_two: str
    created_at: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "setup_id": self.setup_id,
            "setup_version_id": self.setup_version_id,
            "version_number": self.version_number,
            "direction": self.direction,
            "decision_protocol": self.decision_protocol,
            "decision_rules": self.decision_rules,
            "decision_timeframe": self.decision_timeframe,
            "context_timeframe_one": self.context_timeframe_one,
            "context_timeframe_two": self.context_timeframe_two,
            "created_at": self.created_at,
        }


def _creation_token() -> str:
    return "setup_create_" + uuid.uuid4().hex


@dataclass(frozen=True)
class CreateSetup:
    display_name: str
    version: SetupVersionSpec
    creation_token: str = field(default_factory=_creation_token)

    def __post_init__(self) -> None:
        name = str(self.display_name or "").strip()
        token = str(self.creation_token or "").strip()
        if not name:
            raise SetupValidationError(
                SetupErrorCode.INVALID_NAME,
                field="display_name",
                detail="Setup display name must be non-empty",
            )
        if not isinstance(self.version, SetupVersionSpec):
            raise TypeError("Setup version must be a SetupVersionSpec")
        if not token:
            raise ValueError("Setup creation token must be non-empty")
        object.__setattr__(self, "display_name", name)
        object.__setattr__(self, "creation_token", token)


@dataclass(frozen=True)
class CreateSetupVersion:
    setup_id: str
    based_on_version_id: str
    version: SetupVersionSpec

    def __post_init__(self) -> None:
        setup_id = str(self.setup_id or "").strip()
        based_on = str(self.based_on_version_id or "").strip()
        if not setup_id:
            raise ValueError("setup_id must be non-empty")
        if not based_on:
            raise ValueError("based_on_version_id must be non-empty")
        if not isinstance(self.version, SetupVersionSpec):
            raise TypeError("Setup version must be a SetupVersionSpec")
        object.__setattr__(self, "setup_id", setup_id)
        object.__setattr__(self, "based_on_version_id", based_on)


class SetupStorage(Protocol):
    def create_setup_with_version(
        self,
        *,
        setup: Setup,
        version: SetupVersion,
        creation_token: str,
        semantic_fingerprint: str,
    ) -> SetupWithVersion: ...

    def get_setup_version(
        self,
        setup_version_id: str,
    ) -> SetupVersion | None: ...

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
    ) -> SetupVersion: ...

    def list_setup_versions(
        self,
        setup_id: str,
    ) -> tuple[SetupVersion, ...]: ...

    def get_setup(self, setup_id: str) -> Setup | None: ...

    def list_setups(
        self,
        *,
        include_archived: bool,
    ) -> tuple[Setup, ...]: ...

    def rename_setup(
        self,
        setup_id: str,
        display_name: str,
        updated_at: str,
    ) -> Setup | None: ...

    def archive_setup(
        self,
        setup_id: str,
        archived_at: str,
    ) -> Setup | None: ...


class SetupLibrary:
    """Public use-case interface for Setup identity and immutable versions."""

    def __init__(self, storage: SetupStorage) -> None:
        self._storage = storage

    def create_setup(self, request: CreateSetup) -> SetupWithVersion:
        if not isinstance(request, CreateSetup):
            raise TypeError("request must be CreateSetup")
        created_at = datetime.now(UTC).isoformat(timespec="microseconds")
        setup_id = "setup_" + uuid.uuid4().hex
        version_id = "setup_version_" + uuid.uuid4().hex
        setup = Setup(
            setup_id=setup_id,
            display_name=request.display_name,
            is_archived=False,
            created_at=created_at,
            updated_at=created_at,
        )
        version = SetupVersion(
            setup_version_id=version_id,
            setup_id=setup_id,
            version_number=1,
            direction=request.version.direction,
            decision_protocol=request.version.decision_protocol,
            decision_rules=request.version.decision_rules,
            timeframes=request.version.timeframes,
            created_at=created_at,
        )
        return _storage_call(
            lambda: self._storage.create_setup_with_version(
                setup=setup,
                version=version,
                creation_token=request.creation_token,
                semantic_fingerprint=request.version.fingerprint(),
            ),
            "Setup and first version could not be saved",
        )

    def get_version(self, setup_version_id: str) -> SetupVersion:
        version_id = str(setup_version_id or "").strip()
        if not version_id:
            raise ValueError("setup_version_id must be non-empty")
        version = _storage_call(
            lambda: self._storage.get_setup_version(version_id),
            "Setup version could not be read",
        )
        if version is None:
            raise SetupLookupError(
                SetupErrorCode.VERSION_NOT_FOUND,
                identity=version_id,
            )
        return version

    def create_version(
        self,
        request: CreateSetupVersion,
    ) -> SetupVersion:
        if not isinstance(request, CreateSetupVersion):
            raise TypeError("request must be CreateSetupVersion")
        semantic_fingerprint = request.version.fingerprint()
        creation_payload = "|".join(
            (
                request.setup_id,
                request.based_on_version_id,
                semantic_fingerprint,
            )
        )
        creation_key = hashlib.sha256(
            creation_payload.encode("utf-8")
        ).hexdigest()
        return _storage_call(
            lambda: self._storage.create_setup_version(
                setup_version_id="setup_version_" + uuid.uuid4().hex,
                setup_id=request.setup_id,
                based_on_version_id=request.based_on_version_id,
                spec=request.version,
                semantic_fingerprint=semantic_fingerprint,
                creation_key=creation_key,
                created_at=datetime.now(UTC).isoformat(
                    timespec="microseconds"
                ),
            ),
            "Setup version could not be saved",
        )

    def list_versions(self, setup_id: str) -> tuple[SetupVersion, ...]:
        normalized = str(setup_id or "").strip()
        if not normalized:
            raise ValueError("setup_id must be non-empty")
        return _storage_call(
            lambda: self._storage.list_setup_versions(normalized),
            "Setup versions could not be listed",
        )

    def get_setup(self, setup_id: str) -> Setup:
        normalized = str(setup_id or "").strip()
        if not normalized:
            raise ValueError("setup_id must be non-empty")
        setup = _storage_call(
            lambda: self._storage.get_setup(normalized),
            "Setup could not be read",
        )
        if setup is None:
            raise SetupLookupError(
                SetupErrorCode.SETUP_NOT_FOUND,
                identity=normalized,
            )
        return setup

    def list_setups(
        self,
        *,
        include_archived: bool = False,
    ) -> tuple[Setup, ...]:
        return _storage_call(
            lambda: self._storage.list_setups(
                include_archived=bool(include_archived)
            ),
            "Setup catalog could not be listed",
        )

    def rename_setup(self, setup_id: str, display_name: str) -> Setup:
        name = str(display_name or "").strip()
        if not name:
            raise SetupValidationError(
                SetupErrorCode.INVALID_NAME,
                field="display_name",
                detail="Setup display name must be non-empty",
            )
        setup = _storage_call(
            lambda: self._storage.rename_setup(
                str(setup_id or "").strip(),
                name,
                datetime.now(UTC).isoformat(timespec="microseconds"),
            ),
            "Setup could not be renamed",
        )
        if setup is None:
            raise SetupLookupError(
                SetupErrorCode.SETUP_NOT_FOUND,
                identity=str(setup_id),
            )
        return setup

    def archive_setup(self, setup_id: str) -> Setup:
        archived_at = datetime.now(UTC).isoformat(timespec="microseconds")
        setup = _storage_call(
            lambda: self._storage.archive_setup(
                str(setup_id or "").strip(),
                archived_at,
            ),
            "Setup could not be archived",
        )
        if setup is None:
            raise SetupLookupError(
                SetupErrorCode.SETUP_NOT_FOUND,
                identity=str(setup_id),
            )
        return setup

    def export_version(
        self,
        setup_version_id: str,
    ) -> SetupVersionExport:
        version = self.get_version(setup_version_id)
        return SetupVersionExport(
            setup_id=version.setup_id,
            setup_version_id=version.setup_version_id,
            version_number=version.version_number,
            direction=version.direction.value,
            decision_protocol=version.decision_protocol.value,
            decision_rules=version.decision_rules,
            decision_timeframe=version.timeframes.decision,
            context_timeframe_one=version.timeframes.context_one,
            context_timeframe_two=version.timeframes.context_two,
            created_at=version.created_at,
        )


def ordered_supported_timeframes() -> tuple[str, ...]:
    return tuple(sorted(VALID_INTERVALS, key=interval_to_ms))


_PREFERRED_HIGHER_TIMEFRAMES = {
    "1m": ("5m", "15m"),
    "3m": ("15m", "1h"),
    "5m": ("15m", "1h"),
    "15m": ("1h", "4h"),
    "30m": ("1h", "4h"),
    "1h": ("4h", "1d"),
    "2h": ("6h", "1d"),
    "4h": ("12h", "1d"),
    "6h": ("1d", "3d"),
    "8h": ("1d", "3d"),
    "12h": ("1d", "3d"),
    "1d": ("3d", "1w"),
}


def recommend_timeframe_profile(
    decision_timeframe: str,
    supported_intervals: Iterable[str] = VALID_INTERVALS,
) -> TimeframeProfile:
    try:
        decision = normalize_interval(decision_timeframe)
        supported = {
            normalize_interval(interval)
            for interval in supported_intervals
        }
    except ValueError as exc:
        raise SetupValidationError(
            SetupErrorCode.UNSUPPORTED_TIMEFRAME,
            field="decision_timeframe",
            detail=str(exc),
        ) from exc
    if decision not in supported:
        raise SetupValidationError(
            SetupErrorCode.UNSUPPORTED_TIMEFRAME,
            field="decision_timeframe",
            detail=f"Decision timeframe is not exchange-supported: {decision}",
        )
    preferred = _PREFERRED_HIGHER_TIMEFRAMES.get(decision, ())
    if len(preferred) == 2 and all(
        interval in supported for interval in preferred
    ):
        return TimeframeProfile(decision, preferred[0], preferred[1])
    higher = tuple(
        interval
        for interval in sorted(supported, key=interval_to_ms)
        if interval_to_ms(interval) > interval_to_ms(decision)
    )
    if len(higher) < 2:
        raise SetupValidationError(
            SetupErrorCode.NO_HIGHER_TIMEFRAMES,
            field="decision_timeframe",
            detail=(
                "Two higher exchange-supported timeframes are required for "
                f"{decision}"
            ),
        )
    return TimeframeProfile(decision, higher[0], higher[1])


__all__ = [
    "CreateSetup",
    "CreateSetupVersion",
    "DecisionProtocol",
    "Setup",
    "SetupDirection",
    "SetupErrorCode",
    "SetupLibrary",
    "SetupLookupError",
    "SetupPersistenceError",
    "SetupValidationError",
    "SetupVersion",
    "SetupVersionExport",
    "SetupVersionSpec",
    "SetupWithVersion",
    "TimeframeProfile",
    "ordered_supported_timeframes",
    "recommend_timeframe_profile",
]
