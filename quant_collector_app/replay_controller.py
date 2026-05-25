from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReplayController:
    cursor: int = 0
    playing: bool = False
    follow_latest: bool = False
    accumulated_bars: float = 0.0

    def reset(self) -> None:
        self.cursor = 0
        self.playing = False
        self.accumulated_bars = 0.0

    def load_state(self, cursor: int, playing: bool, follow_latest: bool, accumulated_bars: float = 0.0) -> None:
        self.cursor = max(0, int(cursor))
        self.playing = bool(playing)
        self.follow_latest = bool(follow_latest)
        self.accumulated_bars = max(0.0, float(accumulated_bars))

    def tick(self, elapsed_seconds: float, length: int, speed: float, base_bars_per_second: float = 1.0) -> bool:
        if length <= 0 or not self.playing:
            return False
        old_cursor = self.cursor
        self.accumulated_bars += max(0.0, elapsed_seconds) * max(0.0, base_bars_per_second) * max(0.1, speed)
        step = int(self.accumulated_bars)
        if step:
            self.accumulated_bars -= step
            self.cursor = min(length - 1, self.cursor + step)
            if self.cursor >= length - 1:
                self.playing = False
                self.accumulated_bars = 0.0
        return self.cursor != old_cursor

    def toggle_play(self, length: int) -> bool:
        if length <= 0:
            return False
        self.playing = not self.playing
        return self.playing

    def step(self, length: int) -> int:
        self.playing = False
        if length > 0:
            self.cursor = min(length - 1, self.cursor + 1)
        return self.cursor

    def jump_end(self, length: int) -> int:
        self.playing = False
        self.cursor = max(0, length - 1)
        return self.cursor

    def toggle_follow(self) -> bool:
        self.follow_latest = not self.follow_latest
        return self.follow_latest
