from __future__ import annotations

import argparse
import json
import logging
import os
import time

from income33.bots.base import BaseBotRunner
from income33.logging_utils import setup_component_logger


class ReporterBotRunner(BaseBotRunner):
    def __init__(self, bot_id: str = "reporter-01") -> None:
        super().__init__(
            bot_id=bot_id,
            bot_type="reporter",
            steps=[
                "fetch_items",
                "check_business_count",
                "adjust",
                "national_tax",
                "local_tax",
                "done",
            ],
        )


def main() -> None:
    setup_component_logger("income33.reporter", "reporter.log")
    logger = logging.getLogger("income33.reporter.runner")

    parser = argparse.ArgumentParser(description="Mock reporter bot runner")
    parser.add_argument("--bot-id", default=os.getenv("INCOME33_AGENT_BOT_ID", "reporter-01"))
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    runner = ReporterBotRunner(bot_id=args.bot_id)

    if args.once:
        snapshot = runner.tick()
        logger.info("reporter_once_snapshot=%s", json.dumps(snapshot.__dict__, ensure_ascii=False))
        return

    logger.info("reporter_runner_started bot_id=%s interval=%s", args.bot_id, args.interval)
    while True:
        try:
            snapshot = runner.tick()
            logger.debug("reporter_snapshot=%s", json.dumps(snapshot.__dict__, ensure_ascii=False))
        except Exception:
            logger.exception("reporter_tick_failed bot_id=%s", args.bot_id)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
