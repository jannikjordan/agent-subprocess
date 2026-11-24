"""Show a complete Agent Subprocess run with a fake CLI and sample data."""

import asyncio
import sys
from pathlib import Path

from agent_subprocess import Client, Prompt, RunRequest


def main() -> int:
    """Print the offline answer and return the shell exit code."""
    workspace = Path(__file__).resolve().parent
    client = Client(
        executables={
            "codex": (sys.executable, str(workspace / "fake_provider.py"), "codex")
        }
    )
    request = RunRequest(
        provider="codex",
        cwd=workspace,
        prompt=Prompt.from_file(workspace / "task.md"),
        deadline_seconds=10,
    )

    result = asyncio.run(client.run(request))
    if result.error:
        print(f"{result.error.code}: {result.error.message}", file=sys.stderr)
        return 1
    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
