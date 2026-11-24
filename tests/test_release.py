import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import call, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release_script", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

BEFORE = "a" * 40
AFTER = "b" * 40
TAG = "v0.2.1"
REPO = "example/agent-subprocess"
NOTES = "### Added\n\n- Café release notes.\n"
CHANGELOG = f"# Changelog\n\n## 0.2.10\n\nOther notes\n\n## 0.2.1\n\n{NOTES}\n## 0.2.0\n\nOlder notes"


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.event_path = root / "push.json"
        self.plan = root / "plan.json"
        self.output = root / "output"
        self.event = {
            "ref": "refs/heads/main",
            "created": False,
            "deleted": False,
            "forced": False,
            "before": BEFORE,
            "after": AFTER,
        }
        self.save_event()
        environment = {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_EVENT_PATH": str(self.event_path),
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": AFTER,
            "GITHUB_REPOSITORY": REPO,
        }
        self.enterContext(patch.dict(os.environ, environment))
        self.git_output = {
            ("rev-parse", "HEAD"): AFTER,
            ("merge-base", "--is-ancestor", BEFORE, AFTER): "",
            ("show", f"{BEFORE}:pyproject.toml"): '[project]\nversion="0.2.0"',
            ("show", f"{AFTER}:pyproject.toml"): '[project]\nversion="0.2.1"',
            ("show", f"{AFTER}:CHANGELOG.md"): CHANGELOG,
        }
        self.git = self.enterContext(patch.object(release, "git", self.read_git))
        self.target = None
        self.existing_release = ""
        self.github = self.enterContext(
            patch.object(release, "github", side_effect=self.gh)
        )

    def save_event(self):
        self.event_path.write_text(json.dumps(self.event), encoding="utf-8")

    def read_git(self, *args):
        if args not in self.git_output:
            raise subprocess.CalledProcessError(1, ["git", *args])
        return self.git_output[args]

    def gh(self, *args, stdin=None):
        if args == ("api", f"repos/{REPO}/git/matching-refs/tags/{TAG}"):
            refs = [
                {
                    "ref": f"refs/tags/{TAG}0",
                    "object": {"type": "commit", "sha": BEFORE},
                }
            ]
            if self.target is not None:
                refs.append({"ref": f"refs/tags/{TAG}", "object": self.target})
            return json.dumps(refs)
        if args == ("api", f"repos/{REPO}/git/tags/{BEFORE}"):
            return json.dumps({"object": {"type": "commit", "sha": AFTER}})
        if args[:3] == ("api", f"repos/{REPO}/releases?per_page=100", "--paginate"):
            self.assertEqual(args[3], "--jq")
            self.assertIn(f'.tag_name == "{TAG}"', args[4])
            return self.existing_release
        if args[:5] == ("api", "--method", "POST", f"repos/{REPO}/git/refs", "-f"):
            self.assertEqual(args[5:], (f"ref=refs/tags/{TAG}", "-f", f"sha={AFTER}"))
            self.assertIsNone(self.target)
            self.target = {"type": "commit", "sha": AFTER}
            return ""
        if args[:2] == ("release", "create"):
            self.assertEqual(
                args[2:],
                (
                    TAG,
                    "--repo",
                    REPO,
                    "--verify-tag",
                    "--title",
                    TAG,
                    "--notes-file",
                    "-",
                ),
            )
            self.assertEqual(stdin, NOTES)
            self.assertEqual(self.target["sha"], AFTER)
            return "https://example.com/release"
        self.fail(f"Unexpected GitHub command: {args}")

    def test_entrypoint_prepares_the_exact_tag_and_notes(self):
        args = [
            str(SCRIPT),
            "prepare",
            "--plan",
            str(self.plan),
            "--output",
            str(self.output),
        ]
        with patch.object(sys, "argv", args):
            self.assertEqual(release.main(), 0)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "publish=true\n")
        self.assertEqual(
            json.loads(self.plan.read_text(encoding="utf-8")),
            {"tag": TAG, "commit": AFTER, "notes": NOTES},
        )
        self.github.assert_not_called()

    def test_unchanged_versions_skip_the_changelog(self):
        self.git_output["show", f"{AFTER}:pyproject.toml"] = (
            '[project]\nversion="0.2.0"'
        )
        del self.git_output["show", f"{AFTER}:CHANGELOG.md"]
        release.prepare(self.plan, self.output)
        self.assertFalse(self.plan.exists())
        self.assertEqual(self.output.read_text(encoding="utf-8"), "publish=false\n")
        self.github.assert_not_called()

    def test_invalid_or_backward_versions_fail(self):
        for version in ("0.1.9", "0.2.1-rc1", "00.2.1"):
            with self.subTest(version=version):
                self.git_output["show", f"{AFTER}:pyproject.toml"] = (
                    f'[project]\nversion="{version}"'
                )
                with self.assertRaisesRegex(ValueError, "version"):
                    release.prepare(self.plan, self.output)
        self.assertFalse(self.plan.exists())
        self.github.assert_not_called()

    def test_missing_empty_or_duplicate_changelog_entries_fail(self):
        for changelog in (
            "## 0.2.10\n\nOther notes",
            "## 0.2.1",
            CHANGELOG + "\n\n## 0.2.1",
        ):
            with self.subTest(changelog=changelog):
                self.git_output["show", f"{AFTER}:CHANGELOG.md"] = changelog
                with self.assertRaisesRegex(ValueError, "exactly one nonempty"):
                    release.prepare(self.plan, self.output)
        self.assertFalse(self.plan.exists())
        self.github.assert_not_called()

    def test_untrusted_push_events_fail(self):
        for key, value in (
            ("ref", "refs/heads/dev"),
            ("created", True),
            ("deleted", True),
            ("forced", True),
            ("after", "0" * 40),
            ("before", "HEAD"),
        ):
            with (
                self.subTest(key=key, value=value),
                patch.dict(self.event, {key: value}),
            ):
                self.save_event()
                with self.assertRaises(ValueError):
                    release.prepare(self.plan, self.output)
        self.assertFalse(self.plan.exists())
        self.github.assert_not_called()

    def test_mismatched_checkout_and_unrelated_before_fail(self):
        self.git_output["rev-parse", "HEAD"] = BEFORE
        with self.assertRaisesRegex(ValueError, "checkout"):
            release.prepare(self.plan, self.output)
        self.git_output["rev-parse", "HEAD"] = AFTER
        del self.git_output["merge-base", "--is-ancestor", BEFORE, AFTER]
        with self.assertRaises(subprocess.CalledProcessError):
            release.prepare(self.plan, self.output)
        self.assertFalse(self.plan.exists())
        self.github.assert_not_called()

    def test_publish_creates_the_tag_then_the_source_release(self):
        release.prepare(self.plan, self.output)
        with redirect_stdout(io.StringIO()):
            release.publish(self.plan)
        kind = [args[0][:2] for args in self.github.call_args_list]
        self.assertEqual(
            kind,
            [
                ("api", f"repos/{REPO}/git/matching-refs/tags/{TAG}"),
                ("api", f"repos/{REPO}/releases?per_page=100"),
                ("api", "--method"),
                ("api", f"repos/{REPO}/git/matching-refs/tags/{TAG}"),
                ("release", "create"),
            ],
        )

    def test_publish_reuses_a_matching_tag(self):
        self.target = {"type": "commit", "sha": AFTER}
        release.prepare(self.plan, self.output)
        with redirect_stdout(io.StringIO()):
            release.publish(self.plan)
        self.assertEqual(self.github.call_args.args[:2], ("release", "create"))
        self.assertEqual(self.github.call_count, 4)

    def test_published_release_with_matching_annotated_tag_is_a_no_op(self):
        self.target = {"type": "tag", "sha": BEFORE}
        self.existing_release = "published"
        release.prepare(self.plan, self.output)
        with redirect_stdout(io.StringIO()):
            release.publish(self.plan)
        self.assertEqual(self.github.call_count, 3)
        self.assertEqual(
            self.github.call_args_list[1],
            call("api", f"repos/{REPO}/git/tags/{BEFORE}"),
        )

    def test_publish_rejects_conflicting_tags_and_drafts(self):
        release.prepare(self.plan, self.output)
        self.target = {"type": "commit", "sha": BEFORE}
        with self.assertRaisesRegex(ValueError, "different commit"):
            release.publish(self.plan)
        self.assertEqual(self.github.call_count, 1)
        self.github.reset_mock()
        self.target = None
        self.existing_release = "draft"
        with self.assertRaisesRegex(ValueError, "draft"):
            release.publish(self.plan)
        self.assertEqual(self.github.call_count, 2)

    def test_publish_rejects_a_changed_plan_and_dry_run_uses_no_credentials(self):
        release.prepare(self.plan, self.output)
        with redirect_stdout(io.StringIO()):
            release.publish(self.plan, dry_run=True)
        self.plan.write_text(
            json.dumps({"tag": TAG, "commit": AFTER, "notes": "Other notes"}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "pushed metadata"):
            release.publish(self.plan)
        self.github.assert_not_called()
