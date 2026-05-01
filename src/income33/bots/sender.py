from __future__ import annotations

import argparse
import json
import logging
import os
import time

from income33.bots.base import BaseBotRunner
from income33.logging_utils import setup_component_logger


class SenderBotRunner(BaseBotRunner):
    def __init__(self, bot_id: str = "sender-01") -> None:
        super().__init__(
            bot_id=bot_id,
            bot_type="sender",
            steps=[
                "fetch_targets",
                "send_message",
                "record_result",
                "done",
            ],
        )


def main() -> None:
    setup_component_logger("income33.sender", "sender.log")
    logger = logging.getLogger("income33.sender.runner")

    parser = argparse.ArgumentParser(description="33income sender bot runner")
    parser.add_argument("--bot-id", default=os.getenv("INCOME33_AGENT_BOT_ID", "sender-01"))
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    runner = SenderBotRunner(bot_id=args.bot_id)

    if args.once:
        snapshot = runner.tick()
        logger.info("sender_once_snapshot=%s", json.dumps(snapshot.__dict__, ensure_ascii=False))
        return

    logger.info("sender_runner_started bot_id=%s interval=%s", args.bot_id, args.interval)
    while True:
        try:
            snapshot = runner.tick()
            logger.debug("sender_snapshot=%s", json.dumps(snapshot.__dict__, ensure_ascii=False))
        except Exception:
            logger.exception("sender_tick_failed bot_id=%s", args.bot_id)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
