"""Run a file-backed analysis job through the public proxy API."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from provider_cli_proxy import Client, Prompt, RunRequest

EXAMPLE_DIR = Path(__file__).resolve().parent


class ArgumentParser(argparse.ArgumentParser):
    """Print the example summary before the command's usage."""

    def format_help(self) -> str:
        """Format the command help with the project usage header."""
        help_text = super().format_help().removeprefix("usage:")
        return f"{__doc__}\n\nUsage:{help_text}"


def parse_args() -> argparse.Namespace:
    """Parse the requested run mode and provider settings."""
    parser = ArgumentParser(prog="python analyze.py")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--provider", choices=("codex", "claude"), required=True)
    shared.add_argument("--prompt-file", type=Path, default=EXAMPLE_DIR / "task.md")
    shared.add_argument("--cwd", type=Path, default=EXAMPLE_DIR)
    shared.add_argument("--model", help="Provider model name or alias")
    shared.add_argument("--effort", help="Provider reasoning effort")
    shared.add_argument(
        "--live",
        action="store_true",
        help="Use the installed provider CLI and its login",
    )
    shared.add_argument(
        "--provider-read",
        action="store_true",
        help="Let the CLI read the prompt file inside --cwd (requires --live)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", parents=[shared], help="Wait for the final answer")
    commands.add_parser(
        "stream", parents=[shared], help="Display updates while waiting for the answer"
    )
    args = parser.parse_args()
    if args.provider_read and not args.live:
        parser.error("--provider-read requires --live")
    return args


def workspace_prompt(cwd: Path, prompt_file: Path) -> Prompt:
    """Build a prompt that refers to a checked file inside the workspace."""
    workspace = cwd.resolve(strict=True)
    path = (workspace / prompt_file).resolve(strict=True)
    relative_path = path.relative_to(workspace)
    if not path.is_file():
        raise ValueError("The prompt must be a regular file.")
    quoted_path = json.dumps(relative_path.as_posix(), ensure_ascii=False)
    return Prompt.text(f"Read {quoted_path} and follow its instructions.")


async def analyze(args: argparse.Namespace, client: Client) -> int:
    """Run the task and return a status suitable for shell callers."""
    try:
        if args.provider_read:
            prompt = workspace_prompt(args.cwd, args.prompt_file)
        else:
            prompt = Prompt.from_file(args.prompt_file)
    except (OSError, RuntimeError, ValueError):
        message = (
            "Choose a prompt file inside the working directory."
            if args.provider_read
            else "Could not read the prompt file."
        )
        print(message, file=sys.stderr)
        return 1

    request = RunRequest(
        provider=args.provider,
        prompt=prompt,
        cwd=args.cwd,
        permissions="workspace_read" if args.provider_read else "prompt_only",
        model=args.model,
        effort=args.effort,
        deadline_seconds=60,
    )
    if args.command == "stream":
        async with client.start(request) as session:
            async for event in session.events():
                if event.kind in {"answer_delta", "answer_snapshot"} and event.text:
                    print(f"{event.kind}: {event.text}", file=sys.stderr, flush=True)
                elif event.kind == "activity" and event.activity:
                    print(event.activity, file=sys.stderr, flush=True)
                elif event.kind == "started":
                    print("Provider process started.", file=sys.stderr, flush=True)
            result = await session.wait()
    else:
        result = await client.run(request)

    if result.status != "succeeded":
        error = result.error
        detail = f"{error.code}: {error.message}" if error else result.status
        print(detail, file=sys.stderr)
        return 1
    print(result.text)
    return 0


def main() -> int:
    """Use a local fixture unless the caller requests a live provider."""
    args = parse_args()
    try:
        if args.live:
            return asyncio.run(analyze(args, Client()))
        executable = (
            sys.executable,
            str(EXAMPLE_DIR / "fake_provider.py"),
            args.provider,
        )
        return asyncio.run(
            analyze(args, Client(executables={args.provider: executable}))
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
