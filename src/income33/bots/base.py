from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class BotSnapshot:
    bot_id: str
    bot_type: str
    status: str
    current_step: str
    success_count: int
    failure_count: int


class BaseBotRunner:
    def __init__(self, bot_id: str, bot_type: str, steps: Iterable[str]) -> None:
        self.bot_id = bot_id
        self.bot_type = bot_type
        self._steps = list(steps)
        self._index = 0
        self.status = "running"
        self.success_count = 0
        self.failure_count = 0

    def start(self) -> None:
        self.status = "running"

    def stop(self) -> None:
        self.status = "stopped"

    def restart(self) -> None:
        self.status = "restarting"
        self._index = 0
        self.status = "running"

    def tick(self) -> BotSnapshot:
        if self.status == "stopped":
            current_step = "stopped"
        else:
            if not self._steps:
                current_step = "idle"
            else:
                current_step = self._steps[self._index]
                self._index = (self._index + 1) % len(self._steps)

            if self.status == "running" and current_step in {"done", "completed"}:
                self.success_count += 1

        return BotSnapshot(
            bot_id=self.bot_id,
            bot_type=self.bot_type,
            status=self.status,
            current_step=current_step,
            success_count=self.success_count,
            failure_count=self.failure_count,
        )
