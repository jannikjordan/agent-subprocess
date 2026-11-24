import os
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

from agent_subprocess import _discovery


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.local_app_data = self.root / "Local AppData"
        self.app_data = self.root / "Roaming AppData"
        self.program_files = self.root / "Program Files"
        self.env = {
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "LOCALAPPDATA": str(self.local_app_data),
            "APPDATA": str(self.app_data),
            "PROGRAMFILES": str(self.program_files),
        }

    def binary(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        path.chmod(0o700)
        return path

    def candidates(self, provider, operating_system, machine="x64"):
        with (
            patch.object(_discovery.sys, "platform", operating_system),
            patch.object(_discovery, "_machine", return_value=machine),
            patch.object(_discovery, "_SYSTEM_BIN_DIRS", {}),
            patch.object(_discovery, "_MAC_APPLICATIONS", self.root / "Applications"),
        ):
            return list(_discovery.executable_candidates(provider, self.env))

    def test_path_first_followed_by_user_install_and_homebrew(self):
        direct = self.binary(self.root / "path with spaces" / "codex")
        standalone = self.binary(self.home / ".local/bin/codex")
        brew = self.root / "brew"
        homebrew = self.binary(brew / "bin/codex")
        self.env["PATH"] = os.pathsep.join(
            ["", ".", "relative", str(direct.parent), str(standalone.parent)]
        )
        self.env["HOMEBREW_PREFIX"] = str(brew)

        self.assertEqual(
            self.candidates("codex", "darwin"), [direct, standalone, homebrew]
        )

    def test_linux_homebrew_and_system_bins(self):
        linuxbrew = self.binary(self.home / ".linuxbrew/bin/claude")
        system = self.binary(self.root / "system/bin/claude")
        with (
            patch.object(_discovery.sys, "platform", "linux"),
            patch.object(
                _discovery, "_SYSTEM_BIN_DIRS", {"linux": (str(system.parent),)}
            ),
        ):
            self.assertEqual(
                list(_discovery.executable_candidates("claude", self.env)),
                [linuxbrew, system],
            )

    def test_codex_desktop_cli_entrypoints_in_both_applications_directories(self):
        system = self.binary(
            self.root
            / "Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
        )
        user = self.binary(
            self.home / "Applications/Codex.app/Contents/Resources/codex"
        )
        self.binary(
            self.home / "Applications/Codex.app/Contents/Resources/codex-app-server"
        )

        self.assertEqual(self.candidates("codex", "darwin"), [system, user])

    def test_windows_path_and_standard_installers(self):
        custom = self.root / "custom dir"
        direct = self.binary(custom / "codex.exe")
        self.binary(custom / "claude.cmd")
        self.env["PATH"] = f'"{custom}"'
        codex = self.binary(self.local_app_data / "Programs/OpenAI/Codex/bin/codex.exe")
        claude = self.binary(self.home / ".local/bin/claude.exe")

        self.assertEqual(self.candidates("codex", "win32"), [direct, codex])
        self.assertEqual(self.candidates("claude", "win32"), [claude])

    def test_winget_machine_link_and_user_package(self):
        user_packages = self.local_app_data / "Microsoft/WinGet/Packages"
        self.binary(user_packages / "OpenAI.Codex-other_source/codex.exe")
        codex = self.binary(
            user_packages
            / "OpenAI.Codex_Microsoft.Winget.Source/codex-x86_64-pc-windows-msvc.exe"
        )
        claude = self.binary(self.program_files / "WinGet/Links/claude.exe")

        self.assertEqual(self.candidates("codex", "win32"), [codex])
        self.assertEqual(self.candidates("claude", "win32"), [claude])

    def test_windows_npm_global_native_payloads(self):
        modules = self.app_data / "npm/node_modules"
        codex = self.binary(
            modules
            / "@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
        )
        claude = self.binary(modules / "@anthropic-ai/claude-code/bin/claude.exe")

        self.assertEqual(self.candidates("codex", "win32"), [codex])
        self.assertEqual(self.candidates("claude", "win32"), [claude])

    def test_windows_npm_nested_arm64_payload_in_custom_path(self):
        npm = self.root / "npm"
        self.binary(npm / "codex.cmd")
        self.env["PATH"] = str(npm)
        codex = self.binary(
            npm
            / "node_modules/@openai/codex/node_modules/@openai/codex-win32-arm64"
            / "vendor/aarch64-pc-windows-msvc/bin/codex.exe"
        )

        self.assertEqual(self.candidates("codex", "win32", "arm64"), [codex])
        self.assertEqual(self.candidates("codex", "win32", "x64"), [])

    def test_posix_npm_payloads(self):
        npm = self.root / "npm"
        self.env["NPM_CONFIG_PREFIX"] = str(npm)
        modules = npm / "lib/node_modules"
        codex = self.binary(
            modules / "@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex"
        )
        claude = self.binary(modules / "@anthropic-ai/claude-code/bin/claude.exe")

        self.assertEqual(self.candidates("codex", "darwin", "arm64"), [codex])
        self.assertEqual(self.candidates("claude", "darwin", "arm64"), [claude])

    def test_relative_path_entries_do_not_create_candidates(self):
        self.env["PATH"] = os.pathsep.join(["", ".", "relative"])
        for name in ("codex", "relative/codex", "claude.exe", "relative/claude.exe"):
            self.binary(self.root / name)

        with chdir(self.root):
            self.assertEqual(self.candidates("codex", "linux"), [])
            self.assertEqual(self.candidates("claude", "win32"), [])

    @unittest.skipIf(
        os.name == "nt", "Creating symlinks can require Windows privileges."
    )
    def test_symlinks_are_resolved_and_broken_links_skipped(self):
        broken = self.root / "stale"
        linked = self.root / "linked"
        broken.mkdir()
        linked.mkdir()
        (broken / "codex").symlink_to(self.root / "missing")
        target = self.binary(self.home / ".local/bin/codex")
        (linked / "codex").symlink_to(target)
        self.env["PATH"] = os.pathsep.join((str(broken), str(linked)))

        self.assertEqual(self.candidates("codex", "linux"), [target])
