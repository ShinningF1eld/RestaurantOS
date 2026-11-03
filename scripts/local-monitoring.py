"""Initialize and control optional developer monitoring; shutdown retains data."""

import argparse
from pathlib import Path

from test_support.monitoring_environment import ROOT, Monitoring


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "config", "up", "status", "down"])
    parser.add_argument("--grafana-port", type=int, default=3001)
    parser.add_argument("--otlp-port", type=int, default=4318)
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Opt in at init to PostgreSQL/Redis receivers; provision identities and secret files before up",
    )
    args = parser.parse_args()
    directory = ROOT / ".local-monitoring"
    if args.action == "init":
        Monitoring.initialize(
            directory,
            grafana_port=args.grafana_port,
            otlp_port=args.otlp_port,
            diagnostics=args.diagnostics,
        )
        print(
            "Initialized private .local-monitoring state; credentials are in that directory."
        )
        return
    stack = Monitoring(Path(directory))
    if args.action == "up":
        stack.up()
        print(f"Grafana ready on http://localhost:{stack.port('grafana', 3000)}")
    elif args.action == "down":
        stack.down()
        print("Stopped monitoring; data volumes retained.")
    elif args.action == "config":
        stack.compose("config", "--quiet")
        print("Compose configuration valid.")
    else:
        print(stack.compose("ps"))


if __name__ == "__main__":
    main()
