from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable


HEARTBEAT_FILENAME = "bot_heartbeat"


def heartbeat_path(data_path: str | Path) -> Path:
    return Path(data_path).parent / HEARTBEAT_FILENAME


def heartbeat_is_fresh(
    data_path: str | Path,
    max_age: float = 120,
    now: float | None = None,
) -> bool:
    path = heartbeat_path(data_path)
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False
    age = (time.time() if now is None else float(now)) - modified_at
    return 0 <= age <= max(1.0, float(max_age))


class Heartbeat:
    def __init__(
        self,
        data_path: str | Path,
        min_interval: float = 10,
        clock: Callable[[], float] = time.time,
    ):
        self.path = heartbeat_path(data_path)
        self.min_interval = max(1.0, float(min_interval))
        self.clock = clock
        self.last_touch_at: float | None = None

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self.last_touch_at = None

    def touch(self, force: bool = False) -> bool:
        now = float(self.clock())
        if not force and self.last_touch_at is not None and now - self.last_touch_at < self.min_interval:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        os.utime(self.path, (now, now))
        self.last_touch_at = now
        return True
