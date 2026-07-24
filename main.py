"""Interactive command-line entry point for the payment collection agent."""

from __future__ import annotations

import argparse
import sys
from typing import Any, TextIO

from agent import Agent
from api_client import ApiClient


class DemoApiClient:
    """Small local service used by the CLI's safe default demo mode."""

    _ACCOUNTS = {
        "ACC1001": {
            "account_id": "ACC1001",
            "full_name": "Nithin Jain",
            "dob": "1990-05-14",
            "aadhaar_last4": "4321",
            "pincode": "400001",
            "balance": "1250.75",
        },
        "ACC2002": {
            "account_id": "ACC2002",
            "full_name": "Demo Customer",
            "dob": "2000-02-29",
            "aadhaar_last4": "9876",
            "pincode": "560001",
            "balance": "0.00",
        },
    }

    def lookup_account(self, account_id: str) -> dict[str, Any] | None:
        account = self._ACCOUNTS.get(account_id)
        return dict(account) if account is not None else None

    def process_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a deterministic demo transaction without displaying card data."""

        del payload
        return {"success": True, "transaction_id": "demo-txn-001"}


def build_agent(*, live: bool = False) -> Agent:
    """Build the CLI agent using either the local demo or the live API adapter."""

    return Agent(api_client=ApiClient() if live else DemoApiClient())


def run_cli(
    agent: Agent,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    show_banner: bool = True,
) -> int:
    """Run a line-oriented conversation and return a process exit code."""

    if show_banner:
        print("Payment Collection Agent", file=output_stream)
        print("Type :quit to exit.", file=output_stream)

    print(f"Agent: {agent.next('')['message']}", file=output_stream)
    while True:
        try:
            line = input_stream.readline()
        except KeyboardInterrupt:
            print("\nGoodbye.", file=output_stream)
            return 0
        if line == "":
            return 0
        user_input = line.rstrip("\r\n")
        if user_input.strip().lower() in {":quit", ":exit", "quit", "exit"}:
            print("Goodbye.", file=output_stream)
            return 0
        response = agent.next(user_input)
        print(f"Agent: {response['message']}", file=output_stream)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an interactive payment-collection conversation."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--demo",
        action="store_true",
        help="use deterministic local demo accounts (the default)",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="use the configured live payment API; see README prerequisites",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="omit the CLI heading and exit hint",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="run the local aggregate evaluation report instead of the CLI",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.evaluate:
        from evaluation import main as evaluation_main

        return evaluation_main([])
    return run_cli(
        build_agent(live=args.live),
        show_banner=not args.no_banner,
    )


if __name__ == "__main__":
    raise SystemExit(main())
