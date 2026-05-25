from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReplayState:
    cursor: int = 0
    playing: bool = False
    follow_latest: bool = False
    speed: float = 1.0


@dataclass
class DataLoadState:
    loading: bool = False
    source: str = "-"
    bar_count: int = 0
    quality_status: str = "-"
    status_message: str = ""


@dataclass
class SessionState:
    session_id: str | None = None
    symbol: str = "BTCUSDT"
    interval: str = "1m"


@dataclass
class PremiumState:
    inflight: bool = False
    last_error: str | None = None


@dataclass
class ExportState:
    running: bool = False
    output_dir: str | None = None
    last_error: str | None = None


@dataclass
class AppState:
    replay: ReplayState = field(default_factory=ReplayState)
    data_load: DataLoadState = field(default_factory=DataLoadState)
    session: SessionState = field(default_factory=SessionState)
    premium: PremiumState = field(default_factory=PremiumState)
    export: ExportState = field(default_factory=ExportState)
