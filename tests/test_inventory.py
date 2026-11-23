import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from provider_cli_proxy import Client, ProviderInfo, RateLimitWindow

CODEX_VERSION = "codex-cli 0.171.0"
CLAUDE_VERSION = "2.1.330 (Claude Code)"
CODEX_PAID = {
    "account": {
        "type": "chatgpt",
        "planType": "prolite",
        "email": "private-user@example.com",
    },
    "requiresOpenaiAuth": True,
}
CLAUDE_PAID = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "subscriptionType": "max",
    "email": "private-user@example.com",
}
CODEX_USAGE = {
    "rateLimitsByLimitId": {
        "codex": {
            "primary": {"usedPercent": 12.5, "windowDurationMins": 10080},
            "secondary": {
                "usedPercent": 0,
                "windowDurationMins": 300,
                "resetsAt": 1_730_947_200,
            },
        },
        "other": {"primary": {"usedPercent": 99, "windowDurationMins": 300}},
    }
}
CLAUDE_USAGE = {
    "subscription_type": "max",
    "rate_limits_available": True,
    "rate_limits": {
        "five_hour": {"utilization": 0, "resets_at": "2026-06-15T20:00:00+02:00"},
        "limits": [
            {"kind": "weekly_scoped", "percent": 123, "scope": {"model": "Haiku"}},
            {"kind": "weekly_all", "percent": 58.5},
        ],
    },
}


class InventoryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def fake(self, provider, *, version=None, status=None, limits=None):
        version = version or (CODEX_VERSION if provider == "codex" else CLAUDE_VERSION)
        if status is None:
            status = CODEX_PAID if provider == "codex" else CLAUDE_PAID
        path = self.root / f"{provider}.py"
        usage_marker = self.root / f"{provider}-usage"
        account_marker = self.root / f"{provider}-account"
        path.write_text(
            f"""
import json
import sys
from pathlib import Path

def emit(value):
    print(json.dumps(value), flush=True)

status = {status!r}
limits = {limits!r}
if sys.argv[1:] == ['--version']:
    print({version!r})
elif sys.argv[1:2] == ['app-server']:
    Path({str(account_marker)!r}).touch()
    request = json.loads(sys.stdin.readline())
    assert request['method'] == 'initialize'
    emit({{'id': request['id'], 'result': {{}}}})
    assert json.loads(sys.stdin.readline()) == {{'method': 'initialized'}}
    request = json.loads(sys.stdin.readline())
    assert request['method'] == 'account/read'
    emit({{'id': request['id'], 'result': status}})
    request = sys.stdin.readline()
    if request:
        request = json.loads(request)
        assert request['method'] == 'account/rateLimits/read'
        Path({str(usage_marker)!r}).touch()
        if limits is None:
            emit({{'id': request['id'], 'error': {{'message': 'private-status'}}}})
        else:
            emit({{'id': request['id'], 'result': limits}})
        assert not sys.stdin.read()
elif sys.argv[-3:] == ['auth', 'status', '--json']:
    Path({str(account_marker)!r}).touch()
    assert not sys.stdin.read()
    emit(status)
else:
    assert '--safe-mode' in sys.argv and '--restricted' in sys.argv
    assert '--no-session-persistence' in sys.argv and '--strict-mcp-config' in sys.argv
    assert sys.argv[sys.argv.index('--model') + 1] == 'haiku'
    assert sys.argv[sys.argv.index('--tools') + 1] == ''
    assert sys.argv[sys.argv.index('--input-format') + 1] == 'stream-json'
    Path({str(usage_marker)!r}).touch()
    request = json.loads(sys.stdin.readline())
    assert request['type'] == 'control_request' and request['request'] == {{'subtype': 'initialize'}}
    emit({{'type': 'control_response', 'response': {{
        'request_id': request['request_id'], 'subtype': 'success', 'response': {{}},
    }}}})
    request = json.loads(sys.stdin.readline())
    assert request['type'] == 'control_request'
    assert request['request'] == {{'subtype': 'get_usage', 'skip_behaviors': True}}
    if limits is None:
        emit({{'type': 'control_response', 'response': {{
            'request_id': request['request_id'], 'subtype': 'error', 'error': 'private-status',
        }}}})
    else:
        emit({{'type': 'control_response', 'response': {{
            'request_id': request['request_id'], 'subtype': 'success', 'response': limits,
        }}}})
    assert not sys.stdin.read()
""",
            encoding="utf-8",
        )
        return sys.executable, str(path)

    def client(self, **kwargs):
        return Client(
            executables={
                provider: self.fake(provider, **kwargs.get(provider, {}))
                for provider in ("codex", "claude")
            }
        )

    async def test_typed_signed_in_inventory_excludes_identity_and_skips_default_usage(
        self,
    ):
        codex, claude = await self.client().list_providers()
        for info, provider, version, plan in (
            (codex, "codex", CODEX_VERSION, "prolite"),
            (claude, "claude", CLAUDE_VERSION, "max"),
        ):
            self.assertIsInstance(info, ProviderInfo)
            self.assertEqual(info.provider, provider)
            self.assertEqual(info.executable, Path(sys.executable).resolve())
            self.assertEqual(info.version, version)
            self.assertTrue(info.compatible)
            self.assertEqual((info.auth_status, info.plan), ("signed_in", plan))
            self.assertIsNone(info.error)
            self.assertFalse(info.limits)
            self.assertEqual(info.usage_status, "not_requested")
            self.assertNotIn("private-user", repr(info))
            self.assertFalse((self.root / f"{provider}-usage").exists())

    async def test_opt_in_usage_normalizes_zero_percent_and_utc_resets(self):
        codex, claude = await self.client(
            codex={"limits": CODEX_USAGE}, claude={"limits": CLAUDE_USAGE}
        ).list_providers(include_usage=True)
        self.assertEqual(
            codex.limits,
            (
                RateLimitWindow(
                    "session",
                    0.0,
                    datetime.fromtimestamp(1_730_947_200, timezone.utc),
                    300,
                ),
                RateLimitWindow("weekly", 12.5, None, 10080),
            ),
        )
        self.assertEqual(
            claude.limits,
            (
                RateLimitWindow(
                    "session", 0.0, datetime(2026, 6, 15, 18, tzinfo=timezone.utc), 300
                ),
                RateLimitWindow("weekly", 58.5, None, 10080),
            ),
        )
        for info in (codex, claude):
            self.assertEqual(
                (info.auth_status, info.usage_status), ("signed_in", "available")
            )
            self.assertTrue((self.root / f"{info.provider}-usage").exists())

    async def test_usage_errors_leave_subscription_verified(self):
        for info in await self.client().list_providers(include_usage=True):
            self.assertEqual(
                (info.auth_status, info.usage_status), ("signed_in", "unavailable")
            )
            self.assertFalse(info.limits)
            self.assertIsNone(info.error)
            self.assertNotIn("private-status", repr(info))

    async def test_inventory_reports_incompatible_and_missing_cli_without_probing_auth(
        self,
    ):
        codex, claude = await Client(
            executables={
                "codex": self.fake("codex", version="codex-cli 0.170.0"),
                "claude": self.root / "missing.exe",
            }
        ).list_providers(include_usage=True)
        self.assertEqual(codex.version, "codex-cli 0.170.0")
        self.assertEqual(codex.executable, Path(sys.executable).resolve())
        self.assertFalse(codex.compatible)
        self.assertFalse((self.root / "codex-account").exists())
        self.assertEqual(codex.error.code, "unsupported_setting")
        self.assertIsNone(claude.executable)
        self.assertIsNone(claude.version)
        self.assertEqual(claude.error.code, "cli_missing")
        for info in (codex, claude):
            self.assertEqual(
                (info.auth_status, info.usage_status), ("unknown", "unavailable")
            )

    async def test_usage_requires_subscription(self):
        codex, claude = await self.client(
            codex={"status": {**CODEX_PAID, "account": None}},
            claude={"status": {**CLAUDE_PAID, "authMethod": "api-key"}},
        ).list_providers(include_usage=True)
        self.assertEqual(
            (codex.auth_status, codex.error.code), ("signed_out", "auth_required")
        )
        self.assertEqual(
            (claude.auth_status, claude.error.code),
            ("subscription_required", "subscription_required"),
        )
        for provider in ("codex", "claude"):
            self.assertFalse((self.root / f"{provider}-usage").exists())
