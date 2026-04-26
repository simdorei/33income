from __future__ import annotations

import argparse
import time

from income33.agent.client import ControlTowerClient
from income33.bots.reporter import ReporterBotRunner
from income33.bots.sender import SenderBotRunner
from income33.config import AgentConfig, load_config


def _build_bot_runner(agent: AgentConfig):
    if agent.bot_type == "reporter":
        return ReporterBotRunner(bot_id=agent.bot_id)
    return SenderBotRunner(bot_id=agent.bot_id)


class MockAgentRunner:
    def __init__(self, agent: AgentConfig, client: ControlTowerClient) -> None:
        self.agent = agent
        self.client = client
        self.bot = _build_bot_runner(agent)

    def run_once(self) -> None:
        snapshot = self.bot.tick()
        heartbeat_payload = {
            "pc_id": self.agent.pc_id,
            "hostname": self.agent.hostname,
            "ip_address": self.agent.ip_address,
            "agent_status": "online",
            "bot_id": snapshot.bot_id,
            "bot_status": snapshot.status,
            "current_step": snapshot.current_step,
            "success_count": snapshot.success_count,
            "failure_count": snapshot.failure_count,
        }
        self.client.send_heartbeat(heartbeat_payload)

        commands = self.client.poll_commands(self.agent.pc_id, limit=5)
        for command in commands:
            command_name = command["command"]
            command_id = command["id"]
            if command_name == "start":
                self.bot.start()
            elif command_name == "stop":
                self.bot.stop()
            elif command_name == "restart":
                self.bot.restart()
            # status command is heartbeat-only
            self.client.complete_command(command_id=command_id, status="done")

    def run_forever(self) -> None:
        interval = max(1, int(self.agent.heartbeat_interval_seconds))
        print(
            f"[agent] running pc_id={self.agent.pc_id} "
            f"bot_id={self.agent.bot_id} tower={self.agent.control_tower_url}"
        )
        while True:
            try:
                self.run_once()
            except Exception as exc:  # pragma: no cover (network/runtime dependent)
                print(f"[agent] warning: {exc}")
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run income33 mock local agent")
    parser.add_argument("--once", action="store_true", help="heartbeat/poll only once")
    args = parser.parse_args()

    config = load_config()
    client = ControlTowerClient(base_url=config.agent.control_tower_url)
    runner = MockAgentRunner(agent=config.agent, client=client)

    if args.once:
        runner.run_once()
        print("[agent] run_once complete")
        return

    runner.run_forever()


if __name__ == "__main__":
    main()
