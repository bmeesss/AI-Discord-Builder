"""Interactive local/cloud AI setup CLI.

Examples::

    python -m setup                 # interactive menu
    python -m setup detect          # read-only inspection
    python -m setup setup           # ask before install/download/write
    python -m setup setup --yes     # explicit non-interactive approval
    python -m setup test            # test the provider in .env
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict

import config
from ai.client import AIClient, AIPlanError
from ai.providers.base import ProviderError
from setup.config_writer import build_local_ai_config, update_env_file
from setup.local_ai import LocalAIReport, LocalAISetupManager, SetupState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m setup",
        description="Set up and test the optional AI Discord Builder providers.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("menu", "detect", "setup", "cloud", "test"),
        default="menu",
        help="Operation to run (default: interactive menu).",
    )
    parser.add_argument("--model", help="Ollama model override.")
    parser.add_argument(
        "--base-url",
        help="Ollama URL override, for example http://localhost:11434.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Environment file to update (default: .env).",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help=(
            "Check Ollama on localhost but write the Docker service URL "
            "http://ollama:11434 to .env."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Explicitly approve installation, model download and config writing.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command

    if command == "menu":
        command = interactive_menu()
        if command is None:
            return 0

    if command == "detect":
        report = LocalAISetupManager(
            base_url=args.base_url or config.OLLAMA_BASE_URL,
            env_path=args.env_file,
        ).inspect(
            requested_model=args.model,
            auto_select_model=config.LOCAL_AI_AUTO_SELECT_MODEL,
        )
        print_report(report, as_json=args.json)
        # Detect-only is informational.  Missing software is not a command error.
        return 0

    if command == "setup":
        return run_setup(args)

    if command == "cloud":
        return run_cloud_setup(args)

    if command == "test":
        return run_provider_test(args)

    return 2


def interactive_menu() -> str | None:
    if not sys.stdin.isatty():
        print("Non-interactive input detected; use 'detect', 'setup', 'cloud' or 'test'.")
        return None

    print("AI Discord Builder setup")
    print("1. Configure Cloud AI")
    print("2. Set up Local AI with Ollama")
    print("3. Detect current local-AI setup")
    print("4. Test the configured AI connection")
    choice = input("Choose an option [1-4]: ").strip()
    return {
        "1": "cloud",
        "2": "setup",
        "3": "detect",
        "4": "test",
    }.get(choice)


def run_setup(args: argparse.Namespace) -> int:
    base_url = args.base_url or config.OLLAMA_BASE_URL
    # The setup CLI normally runs on the host, so it checks localhost even when
    # the resulting bot configuration will use the Docker service hostname.
    check_url = base_url

    manager = LocalAISetupManager(
        base_url=check_url,
        env_path=args.env_file,
    )
    initial = manager.inspect(
        requested_model=args.model,
        auto_select_model=config.LOCAL_AI_AUTO_SELECT_MODEL,
    )
    if not args.json:
        print_report(initial)

    allow_install = args.yes
    allow_download = args.yes
    write_config = args.yes

    if not args.yes and sys.stdin.isatty():
        if initial.state.value == "needs_install":
            allow_install = ask_yes_no(
                "Ollama is missing. Install it using the supported installer?"
            )
        if initial.state.value in {"needs_install", "needs_start"} or allow_install:
            # Installation/start is handled by the manager.  A failed install
            # will stop before a model download is attempted.
            pass
        if initial.model_selection and (
            not initial.ollama
            or initial.model_selection.model not in initial.ollama.models
        ):
            allow_download = ask_yes_no(
                f"Download model {initial.model_selection.model}?"
            )
        write_config = ask_yes_no(
            f"Write local-AI settings to {args.env_file}?"
        )

    report = manager.setup(
        requested_model=args.model,
        auto_select_model=config.LOCAL_AI_AUTO_SELECT_MODEL,
        allow_install=allow_install,
        allow_download=allow_download,
        # The CLI writes after the setup succeeds so --docker can target the
        # service hostname without using that hostname for host-side detection.
        write_config=False,
    )

    if report.success and write_config and report.model_selection:
        output_url = "http://ollama:11434" if args.docker else check_url
        report.config = build_local_ai_config(
            output_url,
            report.model_selection.model,
            auto_select_model=config.LOCAL_AI_AUTO_SELECT_MODEL,
        )
        try:
            update_env_file(args.env_file, report.config)
            report.messages.append(
                f"Updated local AI configuration in {args.env_file}."
            )
        except (OSError, ValueError) as exc:
            report.success = False
            report.state = SetupState.FAILED
            report.errors.append(f"Could not write configuration: {exc}")

    print_report(report, as_json=args.json)
    return 0 if report.success else 1


def run_cloud_setup(args: argparse.Namespace) -> int:
    if args.yes:
        provider = os.getenv("AI_PROVIDER", "groq").strip().lower()
    elif sys.stdin.isatty():
        print("1. Groq")
        print("2. OpenAI")
        provider = {"1": "groq", "2": "openai"}.get(
            input("Choose a cloud provider [1-2]: ").strip(),
            "",
        )
    else:
        provider = ""

    if provider not in {"groq", "openai"}:
        print("Choose either Groq or OpenAI. API keys are never written by this command.")
        return 1

    values = {"AI_PROVIDER": provider}
    if provider == "groq":
        values["GROQ_MODEL"] = args.model or config.GROQ_MODEL
        print("Set GROQ_API_KEY in .env; the setup command will not ask for or print it.")
    else:
        values["OPENAI_MODEL"] = args.model or config.OPENAI_MODEL
        print("Set OPENAI_API_KEY in .env; the setup command will not ask for or print it.")

    try:
        update_env_file(args.env_file, values)
    except (OSError, ValueError) as exc:
        print(f"Could not update {args.env_file}: {exc}")
        return 1
    print(f"Configured {provider}. Fill in its API key in {args.env_file}.")
    return 0


def run_provider_test(args: argparse.Namespace) -> int:
    try:
        config.validate_config(require_discord=False)
        client = AIClient()
        health = asyncio.run(client.healthcheck())
        model_test = asyncio.run(client.test_connection())
    except (RuntimeError, ProviderError, AIPlanError) as exc:
        print(f"AI connection test failed: {exc}")
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "health": asdict(health),
                    "model_test": asdict(model_test),
                },
                indent=2,
            )
        )
    else:
        print(health.message)
        print(model_test.message)
    return 0 if health.ok and model_test.ok else 1


def ask_yes_no(question: str) -> bool:
    answer = input(f"{question} [y/N]: ").strip().lower()
    return answer in {"y", "yes", "ja", "j"}


def print_report(report: LocalAIReport, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    print(f"State: {report.state.value}")
    for message in report.messages:
        print(f"- {message}")
    for warning in report.warnings:
        print(f"Warning: {warning}")
    for error in report.errors:
        print(f"Error: {error}")
    if report.model_selection:
        print(f"Selected model: {report.model_selection.model}")
    if report.config:
        print("Local-AI configuration is ready to be written.")


if __name__ == "__main__":
    raise SystemExit(main())
