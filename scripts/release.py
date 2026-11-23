"""Prepare and publish the source release for an approved main push."""

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
COMMIT = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")


def git(*args: str) -> str:
    """Run Git against the workflow checkout."""
    return subprocess.check_output(["git", *args], encoding="utf-8").strip()


def main_push() -> tuple[str, str]:
    """Validate the event and checkout before reading release metadata."""
    if os.environ.get("GITHUB_EVENT_NAME") != "push":
        raise ValueError("Release automation requires a GitHub push event.")
    event = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    if (
        not isinstance(event, dict)
        or event.get("ref") != "refs/heads/main"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or any(
            event.get(flag) is not False for flag in ("created", "deleted", "forced")
        )
    ):
        raise ValueError("Release automation requires an ordinary update to main.")

    before, after = event.get("before"), event.get("after")
    if any(
        not isinstance(sha, str) or not COMMIT.fullmatch(sha) or sha == "0" * 40
        for sha in (before, after)
    ):
        raise ValueError("The push must specify two commit SHAs.")
    if after != os.environ.get("GITHUB_SHA") or after != git("rev-parse", "HEAD"):
        raise ValueError("The checkout must match the pushed commit.")
    git("merge-base", "--is-ancestor", before, after)
    return before, after


def package_version(metadata: str) -> str:
    """Read a stable three-part version from TOML package metadata."""
    version = tomllib.loads(metadata)["project"]["version"]
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("The package version must be a stable X.Y.Z version.")
    return version


def release_notes(changelog: str, version: str) -> str:
    """Select one nonempty changelog entry matching the package version."""
    sections = re.split(r"^## +([^\n]+)(?:\n|$)", changelog, flags=re.MULTILINE)
    entries = [
        notes.strip()
        for heading, notes in zip(sections[1::2], sections[2::2], strict=True)
        if heading.strip() == version
    ]
    if len(entries) != 1 or not entries[0]:
        raise ValueError(
            f"CHANGELOG.md needs exactly one nonempty '## {version}' entry."
        )
    return entries[0] + "\n"


def release_metadata() -> dict[str, str] | None:
    """Return release metadata only when the pushed version advances."""
    before, after = main_push()
    previous = package_version(git("show", f"{before}:pyproject.toml"))
    current = package_version(git("show", f"{after}:pyproject.toml"))
    if current == previous:
        return None
    if tuple(map(int, current.split("."))) < tuple(map(int, previous.split("."))):
        raise ValueError("The package version must advance on main.")
    notes = release_notes(git("show", f"{after}:CHANGELOG.md"), current)
    return {"tag": f"v{current}", "commit": after, "notes": notes}


def prepare(plan: Path, output: Path) -> None:
    """Write the tag and notes for a version bump, without GitHub credentials."""
    metadata = release_metadata()
    if metadata is not None:
        plan.write_text(json.dumps(metadata), encoding="utf-8")
    with output.open("a", encoding="utf-8") as stream:
        stream.write(f"publish={'true' if metadata is not None else 'false'}\n")


def github(*args: str, stdin: str | None = None) -> str:
    """Use the workflow token already supplied to GitHub CLI."""
    return subprocess.check_output(["gh", *args], input=stdin, encoding="utf-8").strip()


def tag_target(repository: str, tag: str) -> str | None:
    """Resolve the exact remote tag to a commit, including annotated tags."""
    refs = json.loads(github("api", f"repos/{repository}/git/matching-refs/tags/{tag}"))
    for ref in refs:
        if ref["ref"] == f"refs/tags/{tag}":
            obj = ref["object"]
            for _ in range(16):
                kind, sha = obj["type"], obj["sha"]
                if kind == "commit" and COMMIT.fullmatch(sha):
                    return sha
                if kind != "tag" or not COMMIT.fullmatch(sha):
                    break
                obj = json.loads(github("api", f"repos/{repository}/git/tags/{sha}"))[
                    "object"
                ]
            raise ValueError(f"Could not resolve {tag} to a commit.")
    return None


def publish(plan: Path, *, dry_run: bool = False) -> None:
    """Create the exact tag and publish its notes, preserving existing releases."""
    metadata = release_metadata()
    if metadata is None or metadata != json.loads(plan.read_text(encoding="utf-8")):
        raise ValueError("The prepared release must match the pushed metadata.")
    tag, commit, notes = metadata["tag"], metadata["commit"], metadata["notes"]
    if dry_run:
        print(f"Would publish {tag} at {commit}.")
        return

    repository = os.environ["GITHUB_REPOSITORY"]
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("The event repository name is invalid.")

    target = tag_target(repository, tag)
    if target is not None and target != commit:
        raise ValueError(f"Tag {tag} already points to a different commit.")

    existing = github(
        "api",
        f"repos/{repository}/releases?per_page=100",
        "--paginate",
        "--jq",
        f'.[] | select(.tag_name == "{tag}") | if .draft then "draft" else "published" end',
    ).splitlines()
    if existing:
        if existing != ["published"] or target != commit:
            raise ValueError(
                f"A draft or conflicting release already exists for {tag}."
            )
        print(f"{tag} is already published.")
        return

    if target is None:
        github(
            "api",
            "--method",
            "POST",
            f"repos/{repository}/git/refs",
            "-f",
            f"ref=refs/tags/{tag}",
            "-f",
            f"sha={commit}",
        )
    if tag_target(repository, tag) != commit:
        raise ValueError(f"Tag {tag} does not point to the pushed commit.")
    print(
        github(
            "release",
            "create",
            tag,
            "--repo",
            repository,
            "--verify-tag",
            "--title",
            tag,
            "--notes-file",
            "-",
            stdin=notes,
        )
    )


class ArgumentParser(argparse.ArgumentParser):
    """Format help consistently with the example CLI."""

    def format_help(self) -> str:
        """Place the script summary above the usage line."""
        return f"{__doc__}\n\nUsage:{super().format_help().removeprefix('usage:')}"


def main() -> int:
    """Prepare or publish the source release and return a CLI exit code."""
    parser = ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="select the version and notes")
    prepare_parser.add_argument("--plan", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    publish_parser = commands.add_parser(
        "publish", help="publish a previously prepared release"
    )
    publish_parser.add_argument("--plan", type=Path, required=True)
    publish_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.plan, args.output)
        else:
            publish(args.plan, dry_run=args.dry_run)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"Release failed. {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(
            f"Release failed. {error.cmd[0]} exited with status {error.returncode}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
