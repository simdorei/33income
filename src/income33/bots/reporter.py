from __future__ import annotations

import argparse
import json
import os
import time

from income33.bots.base import BaseBotRunner


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
    parser = argparse.ArgumentParser(description="Mock reporter bot runner")
    parser.add_argument("--bot-id", default=os.getenv("INCOME33_AGENT_BOT_ID", "reporter-01"))
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    runner = ReporterBotRunner(bot_id=args.bot_id)

    if args.once:
        print(json.dumps(runner.tick().__dict__, ensure_ascii=False))
        return

    print(f"[reporter] start bot_id={args.bot_id}")
    while True:
        snapshot = runner.tick()
        print(json.dumps(snapshot.__dict__, ensure_ascii=False))
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
