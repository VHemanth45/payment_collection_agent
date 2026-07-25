"""Interactive command-line entry point for the payment collection agent."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TextIO

from agent import Agent
from api_client import ApiClient


def build_agent() -> Agent:
    """Build the conversational CLI agent backed by the supplied HTTP API."""

    return Agent(api_client=ApiClient())


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
        print("You: ", end="", file=output_stream, flush=True)
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
        if response["message"].startswith("Payment successful."):
            return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an interactive payment-collection conversation."
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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="log safe state and parser diagnostics to stderr",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.evaluate:
        from evaluation import main as evaluation_main

        return evaluation_main([])
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s %(name)s: %(message)s",
        )
    return run_cli(
        build_agent(),
        show_banner=not args.no_banner,
    )


if __name__ == "__main__":
    raise SystemExit(main())
