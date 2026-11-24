"""Smoke-test the public Python API from the example application."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from analyze import workspace_prompt


class AnalysisJobTest(unittest.TestCase):
    """Exercise both providers through the example's normal commands."""

    def test_minimal_example_runs_outside_the_checkout(self) -> None:
        """The minimal script finds its fixture and prompt beside the script."""
        script = Path(__file__).with_name("minimal.py").resolve()
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "18 tickets closed. Wednesday had the highest count with 9.\n",
        )
        self.assertEqual(result.stderr, "")

    def test_offline_results_and_events(self) -> None:
        """Keep final text separate from progress for both providers."""
        script = Path(__file__).with_name("analyze.py")
        updates = {"codex": "answer_snapshot", "claude": "answer_delta"}
        for provider, update in updates.items():
            for command in ("run", "stream"):
                with self.subTest(provider=provider, command=command):
                    result = subprocess.run(
                        [sys.executable, str(script), command, "--provider", provider],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        result.stdout,
                        "18 tickets closed. Wednesday had the highest count with 9.\n",
                    )
                    if command == "stream":
                        self.assertIn("Provider process started.", result.stderr)
                        self.assertIn(update, result.stderr)
                    else:
                        self.assertEqual(result.stderr, "")

    def test_provider_side_read_requires_live_opt_in(self) -> None:
        """Require explicit approval before choosing provider-side file reads."""
        script = Path(__file__).with_name("analyze.py")
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "run",
                "--provider",
                "claude",
                "--provider-read",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--provider-read requires --live", result.stderr)

    def test_provider_side_read_keeps_the_file_inside_the_workspace(self) -> None:
        """Use a relative path and reject paths that leave the workspace."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            prompt_file = workspace / "task with spaces.md"
            prompt_file.write_text("Example.", encoding="utf-8")

            prompt = workspace_prompt(workspace, Path(prompt_file.name))
            self.assertEqual(
                prompt.content,
                'Read "task with spaces.md" and follow its instructions.',
            )

            outside = root / "outside.md"
            outside.write_text("Outside the job workspace.", encoding="utf-8")
            with self.assertRaises(ValueError):
                workspace_prompt(workspace, Path("..") / outside.name)

    def test_provider_side_read_rejects_symlink_escape(self) -> None:
        """Resolve a symlink before accepting the prompt path."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.md"
            outside.write_text("Outside the job workspace.", encoding="utf-8")
            link = workspace / "linked.md"
            try:
                link.symlink_to(outside)
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows host cannot create symlinks.")
                raise
            with self.assertRaises(ValueError):
                workspace_prompt(workspace, Path(link.name))
