import os
import platform
import sys
from collections.abc import Iterator, Mapping
from itertools import islice
from pathlib import Path

from ._models import Provider

_SYSTEM_BIN_DIRS = {
    "darwin": ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"),
    "linux": ("/home/linuxbrew/.linuxbrew/bin", "/usr/local/bin", "/usr/bin", "/bin"),
}
_MAC_APPLICATIONS = Path("/Applications")
_MAC_BUNDLE_ENTRIES = (
    "codex-cli/bin/codex",
    "codex-cli/CodexCLI.app/Contents/MacOS/codex",
    "codex",
)
_NPM_TARGETS = {
    "darwin": {"x64": "x86_64-apple-darwin", "arm64": "aarch64-apple-darwin"},
    "linux": {
        "x64": "x86_64-unknown-linux-musl",
        "arm64": "aarch64-unknown-linux-musl",
    },
    "win32": {"x64": "x86_64-pc-windows-msvc", "arm64": "aarch64-pc-windows-msvc"},
}
_WINGET_PACKAGES = {"codex": "OpenAI.Codex", "claude": "Anthropic.ClaudeCode"}
_MAX_WINGET_PACKAGES = 16


def _absolute_path(value: str | None) -> Path | None:
    path = Path(value) if value else None
    return path if path is not None and path.is_absolute() else None


def _machine() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)


def _binary_names(provider: Provider, target: str | None) -> tuple[str, ...]:
    suffix = ".exe" if sys.platform == "win32" else ""
    name = provider + suffix
    if provider == "codex" and target:
        return name, f"codex-{target}{suffix}"
    return (name,)


def _winget_paths(
    root: Path, provider: Provider, names: tuple[str, ...]
) -> Iterator[Path]:
    yield root / "Links" / names[0]
    packages = root / "Packages"
    package = _WINGET_PACKAGES[provider]
    try:
        matches = islice(packages.glob(f"{package}_*"), _MAX_WINGET_PACKAGES)
        for directory in sorted(matches):
            for name in names:
                yield directory / name
    except OSError:
        # A machine-wide package directory can be inaccessible to this worker.
        pass


def _npm_paths(
    modules: Path, provider: Provider, machine: str, target: str | None, name: str
) -> Iterator[Path]:
    if provider == "claude":
        # The npm installer uses this filename on POSIX as well as Windows.
        yield modules / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    elif target:
        scope = modules / "@openai"
        package = scope / "codex"
        payload = f"codex-{sys.platform}-{machine}"
        for directory in (
            package / "node_modules" / "@openai" / payload,
            scope / payload,
            package,
        ):
            yield directory / "vendor" / target / "bin" / name


def _npm_modules(bin_dir: Path) -> Path:
    prefix = bin_dir if sys.platform == "win32" else bin_dir.parent / "lib"
    return prefix / "node_modules"


def _candidate_paths(provider: Provider, env: Mapping[str, str]) -> Iterator[Path]:
    windows = sys.platform == "win32"
    machine = _machine()
    target = _NPM_TARGETS.get(sys.platform, {}).get(machine)
    names = _binary_names(provider, target)
    home = _absolute_path(env.get("USERPROFILE" if windows else "HOME"))
    path_dirs = dict.fromkeys(
        path
        for entry in env.get("PATH", "").split(os.pathsep)
        if (path := _absolute_path(entry.strip('"') if windows else entry)) is not None
    )
    for directory in path_dirs:
        for name in names:
            yield directory / name
    for directory in path_dirs:
        yield from _npm_paths(
            _npm_modules(directory), provider, machine, target, names[0]
        )

    bin_dirs = []
    if home:
        bin_dirs.extend((home / ".local" / "bin", home / "bin"))
    if provider == "codex" and (
        install_dir := _absolute_path(env.get("CODEX_INSTALL_DIR"))
    ):
        bin_dirs.append(install_dir)
    if not windows:
        if brew := _absolute_path(env.get("HOMEBREW_PREFIX")):
            bin_dirs.append(brew / "bin")
        if sys.platform == "linux" and home:
            bin_dirs.append(home / ".linuxbrew" / "bin")
        bin_dirs.extend(Path(path) for path in _SYSTEM_BIN_DIRS.get(sys.platform, ()))
    elif provider == "codex" and (local := _absolute_path(env.get("LOCALAPPDATA"))):
        bin_dirs.append(local / "Programs" / "OpenAI" / "Codex" / "bin")

    for directory in dict.fromkeys(bin_dirs):
        for name in names:
            yield directory / name

    if provider == "codex" and home:
        standalone = home / ".codex" / "packages" / "standalone" / "current"
        yield standalone / "bin" / names[0]
        yield standalone / names[0]

    if windows:
        if local := _absolute_path(env.get("LOCALAPPDATA")):
            yield from _winget_paths(local / "Microsoft" / "WinGet", provider, names)
        for key in ("PROGRAMFILES", "PROGRAMW6432"):
            if program_files := _absolute_path(env.get(key)):
                yield from _winget_paths(program_files / "WinGet", provider, names)

    if sys.platform == "darwin" and provider == "codex":
        applications = (
            (_MAC_APPLICATIONS, home / "Applications") if home else (_MAC_APPLICATIONS,)
        )
        for directory in applications:
            for app in ("ChatGPT.app", "Codex.app"):
                for entry in _MAC_BUNDLE_ENTRIES:
                    yield directory / app / "Contents" / "Resources" / entry

    modules_dirs = [_npm_modules(directory) for directory in bin_dirs]
    if prefix := _absolute_path(env.get("NPM_CONFIG_PREFIX")):
        modules_dirs.append(
            prefix / "node_modules" if windows else prefix / "lib" / "node_modules"
        )
    if windows and (app_data := _absolute_path(env.get("APPDATA"))):
        modules_dirs.append(app_data / "npm" / "node_modules")
    for modules in dict.fromkeys(modules_dirs):
        yield from _npm_paths(modules, provider, machine, target, names[0])


def executable_candidates(provider: Provider, env: Mapping[str, str]) -> Iterator[Path]:
    """Yield resolved launchers from PATH and known installation directories."""
    seen: set[Path] = set()
    for path in _candidate_paths(provider, env):
        try:
            binary = path.resolve(strict=True)
            if binary in seen or not binary.is_file():
                continue
            if sys.platform == "win32":
                if binary.suffix.lower() != ".exe":
                    continue
            elif not os.access(binary, os.X_OK):
                continue
        except (OSError, RuntimeError, ValueError):
            continue
        seen.add(binary)
        yield binary
