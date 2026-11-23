import asyncio
import errno
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _process_fixture import lock_byte
from provider_cli_proxy import Client, Prompt, RunRequest


CODEX_RESULT = """
emit({'type': 'thread.started', 'thread_id': 'test-thread'})
emit({'type': 'turn.started'})
emit({'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'hidden'}})
emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Ready.'}})
emit({'type': 'turn.completed', 'usage': {'input_tokens': 2, 'internal': 42}})
"""

CLAUDE_INIT = """
emit({'type': 'system', 'subtype': 'init', 'session_id': 'test-session',
      'model': 'test-model', 'tools': [], 'mcp_servers': []})
"""

CLAUDE_ANSWER = """
emit({'type': 'stream_event', 'event': {'type': 'content_block_delta',
      'delta': {'type': 'thinking_delta', 'thinking': 'hidden'}}})
emit({'type': 'stream_event', 'parent_tool_use_id': 'sub', 'event': {
      'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'hidden'}}})
emit({'type': 'stream_event', 'event': {'type': 'content_block_delta',
      'delta': {'type': 'text_delta', 'text': 'Read'}}})
emit({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Ready.',
      'usage': {'output_tokens': 2, 'internal': 42}})
"""

CLI_VERSIONS = {"codex": "codex-cli 0.171.0", "claude": "2.1.330 (Claude Code)"}
WORKSPACE_POLICY = "provider_cli_proxy._providers._WORKSPACE_READ_SUPPORTED"
PROCESS_FIXTURE = Path(__file__).with_name("_process_fixture.py").resolve()
CODEX_ACCOUNT = {
    "account": {"type": "chatgpt", "planType": "prolite"},
    "requiresOpenaiAuth": True,
}
CLAUDE_ACCOUNT = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "subscriptionType": "max",
}


def auth_fixture(provider, status):
    if provider == "codex":
        return f"""
if sys.argv[1:2] == ['app-server']:
    initialize = json.loads(sys.stdin.readline())
    assert initialize['method'] == 'initialize'
    assert 'forced_login_method' not in ' '.join(sys.argv)
    assert os.getenv('CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED') == '1'
    emit({{'id': initialize['id'], 'result': {{}}}})
    assert json.loads(sys.stdin.readline()) == {{'method': 'initialized'}}
    check = json.loads(sys.stdin.readline())
    assert check['method'] == 'account/read' and check['params'] == {{'refreshToken': False}}
    result = {status!r}
    if isinstance(result, str):
        print(result, flush=True)
    else:
        emit({{'id': check['id'], 'result': result}})
    assert not sys.stdin.read()
    sys.exit()
"""
    return f"""
if sys.argv[-3:] == ['auth', 'status', '--json']:
    assert not sys.stdin.read()
    result = {status!r}
    print(result if isinstance(result, str) else json.dumps(result, indent=2))
    sys.exit(int(isinstance(result, dict) and result.get('loggedIn') is False))
"""


class SessionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / "workspace.with spaces"
        self.workspace.mkdir()

    def fake(self, body, *, provider="codex", version=None, auth=None):
        script = self.root / "fake_cli.py"
        if version is None:
            version = CLI_VERSIONS[provider]
        if auth is None:
            auth = CODEX_ACCOUNT if provider == "codex" else CLAUDE_ACCOUNT
        script.write_text(
            "import json, os, signal, subprocess, sys, time\n"
            "from pathlib import Path\n"
            "def emit(event): print(json.dumps(event), flush=True)\n"
            "if sys.argv[1:] == ['--version']:\n"
            f"    print({version!r})\n"
            "    sys.exit()\n" + auth_fixture(provider, auth) + body,
            encoding="utf-8",
        )
        return sys.executable, str(script)

    def request(self, provider="codex", **kwargs):
        kwargs.setdefault("prompt", Prompt.text("Follow the synthetic instructions."))
        kwargs.setdefault("deadline_seconds", 10)
        return RunRequest(provider, self.workspace, **kwargs)

    async def stream(self, client, request):
        async with client.start(request) as session:
            events = [event async for event in session.events()]
            self.assertEqual(
                [event.sequence for event in events], list(range(1, len(events) + 1))
            )
            self.assertTrue(all(event.run_id == session.run_id for event in events))
            self.assertEqual([event.kind for event in events].count("finished"), 1)
            self.assertEqual(events[-1].kind, "finished")
            result = await session.wait()
            self.assertIs(events[-1].result, result)
        return events, result

    async def test_codex_inline_prompt_and_arguments(self):
        capture = self.root / "invocation.json"
        binary = self.fake(
            f"""
Path({str(capture)!r}).write_text(json.dumps({{
    'args': sys.argv[1:], 'cwd': os.getcwd(), 'prompt': sys.stdin.buffer.read().decode('utf-8'),
    'secret_inherited': 'FAKE_APP_PRIVATE_VAR' in os.environ,
    'telemetry_off': os.getenv('DO_NOT_TRACK'),
}}))
"""
            + CODEX_RESULT
        )
        client = Client(executables={"codex": binary})
        request = self.request(
            model="test-model", effort="low", prompt=Prompt.text("A Unicode ✓ prompt")
        )
        with patch.dict(os.environ, {"FAKE_APP_PRIVATE_VAR": "synthetic"}):
            events, result = await self.stream(client, request)
        invocation = json.loads(capture.read_text())
        self.assertEqual(invocation["prompt"], "A Unicode ✓ prompt")
        self.assertEqual(invocation["cwd"], str(self.workspace))
        self.assertFalse(invocation["secret_inherited"])
        self.assertEqual(invocation["telemetry_off"], "1")
        options = invocation["args"]
        self.assertEqual(options[-3:], ["--model", "test-model", "-"])
        for option in (
            "--ignore-user-config",
            "--ephemeral",
            'model_reasoning_effort="low"',
            "features.shell_tool=false",
            "project_doc_max_bytes=0",
            "approval_policy='never'",
        ):
            self.assertIn(option, options)
        self.assertEqual(
            [e.kind for e in events],
            ["started", "activity", "answer_snapshot", "finished"],
        )
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.text, "Ready.")
        self.assertEqual(result.native_session_id, "test-thread")
        self.assertEqual(result.usage, {"input_tokens": 2})
        self.assertIsNone(result.actual_model)

    async def test_claude_file_prompt_deltas_and_final_snapshot(self):
        instructions = self.workspace / "task.md"
        instructions.write_bytes(b"Instructions from a file.\r\n")
        binary = self.fake(
            """
assert sys.stdin.buffer.read() == b'Instructions from a file.\\r\\n'
assert '--safe-mode' in sys.argv and '--restricted' in sys.argv
assert '--disable-slash-commands' in sys.argv and '--strict-mcp-config' in sys.argv
assert sys.argv[sys.argv.index('--tools') + 1] == ''
assert sys.argv[sys.argv.index('--permission-prompts') + 1] == 'none'
assert sys.argv[sys.argv.index('--model') + 1] == 'haiku'
assert sys.argv[sys.argv.index('--effort') + 1] == 'low'
assert os.getenv('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC') == '1'
"""
            + CLAUDE_INIT
            + CLAUDE_ANSWER,
            provider="claude",
        )
        client = Client(executables={"claude": binary})
        request = self.request(
            "claude", model="haiku", effort="low", prompt=Prompt.from_file(instructions)
        )
        events, result = await self.stream(client, request)
        self.assertEqual(result.status, "succeeded", result.error)
        self.assertEqual([e.text for e in events if e.text], ["Read", "Ready."])
        self.assertEqual(result.actual_model, "test-model")
        self.assertEqual(result.native_session_id, "test-session")
        self.assertEqual(result.usage, {"output_tokens": 2})

    async def test_read_policy_arguments(self):
        for provider in CLI_VERSIONS:
            with self.subTest(provider=provider), patch(WORKSPACE_POLICY, True):
                program = """
assert sys.stdin.buffer.read().startswith(b'Read task.md')
"""
                if provider == "codex":
                    program += (
                        """
assert 'features.shell_tool=true' in sys.argv and '--sandbox' not in sys.argv
assert "permissions.provider-proxy.network.enabled=false" in sys.argv
assert "shell_environment_policy.inherit='none'" in sys.argv
assert any("':workspace_roots'={'.'='read'}" in arg for arg in sys.argv)
"""
                        + CODEX_RESULT
                    )
                else:
                    program += (
                        """
assert sys.argv[sys.argv.index('--tools') + 1] == 'Read,Glob,Grep'
assert sys.argv[sys.argv.index('--allowedTools') + 1] == 'Read,Glob,Grep'
assert sys.argv[sys.argv.index('--permission-mode') + 1] == 'dontAsk'
"""
                        + CLAUDE_INIT
                        + CLAUDE_ANSWER
                    )
                client = Client(
                    executables={provider: self.fake(program, provider=provider)}
                )
                request = self.request(
                    provider,
                    prompt=Prompt.text("Read task.md."),
                    permissions="workspace_read",
                )
                result = await client.run(request)
                self.assertEqual(result.status, "succeeded")

    async def test_missing_or_unsupported_versions_never_receive_prompt(self):
        marker = self.root / "inference-started"
        for provider in CLI_VERSIONS:
            for permissions in ("prompt_only", "workspace_read"):
                for version in ("", "unknown version"):
                    binary = self.fake(
                        f"Path({str(marker)!r}).touch()\n",
                        provider=provider,
                        version=version,
                    )
                    with patch(WORKSPACE_POLICY, True):
                        events, result = await self.stream(
                            Client(executables={provider: binary}),
                            self.request(provider, permissions=permissions),
                        )
                    self.assertEqual([e.kind for e in events], ["finished"])
                    self.assertEqual(result.error.code, "unsupported_setting")
                    self.assertFalse(marker.exists())

    async def test_unsupported_workspace_platform(self):
        with patch(WORKSPACE_POLICY, False):
            events, result = await self.stream(
                Client(), self.request(permissions="workspace_read")
            )
        self.assertEqual([e.kind for e in events], ["finished"])
        self.assertEqual(result.error.code, "unsupported_setting")

    async def test_codex_project_config_refused_without_launch(self):
        (self.root / ".codex").mkdir()
        client = Client(executables={"codex": self.root / "absent.exe"})
        events, result = await self.stream(client, self.request())
        self.assertEqual([e.kind for e in events], ["finished"])
        self.assertEqual(result.error.code, "permission_denied")

    async def test_claude_unexpected_tool_or_mcp_is_refused(self):
        for tools, servers in ((["Bash"], []), ([], [{"name": "unapproved"}])):
            event = {
                "type": "system",
                "subtype": "init",
                "tools": tools,
                "mcp_servers": servers,
            }
            binary = self.fake(f"emit({event!r})\n" + CLAUDE_ANSWER, provider="claude")
            _, result = await self.stream(
                Client(executables={"claude": binary}), self.request("claude")
            )
            self.assertEqual(result.error.code, "permission_denied")
            self.assertIsNone(result.text)

    async def test_claude_missing_or_malformed_init_rejects_success(self):
        invalid_metadata = (
            None,
            {},
            {"tools": []},
            {"mcp_servers": []},
            {"tools": {}, "mcp_servers": []},
            {"tools": [], "mcp_servers": {}},
            {"tools": [0], "mcp_servers": []},
        )
        for metadata in invalid_metadata:
            with self.subTest(metadata=metadata):
                init = ""
                if metadata is not None:
                    event = {"type": "system", "subtype": "init", **metadata}
                    init = f"emit({event!r})\n"
                binary = self.fake(init + CLAUDE_ANSWER, provider="claude")
                events, result = await self.stream(
                    Client(executables={"claude": binary}), self.request("claude")
                )
                self.assertEqual(result.error.code, "protocol_error")
                self.assertTrue(all(event.text is None for event in events))

    async def test_claude_unauthorized_tool_after_valid_init_fails(self):
        tool = {
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "fixture-only"},
        }
        events = (
            {"type": "assistant", "message": {"content": [tool]}},
            {
                "type": "stream_event",
                "event": {"type": "content_block_start", "content_block": tool},
            },
        )
        for event in events:
            with self.subTest(kind=event["type"]):
                binary = self.fake(
                    CLAUDE_INIT + f"emit({event!r})\n" + CLAUDE_ANSWER,
                    provider="claude",
                )
                items, result = await self.stream(
                    Client(executables={"claude": binary}), self.request("claude")
                )
                self.assertEqual(result.error.code, "permission_denied")
                self.assertTrue(all(item.text is None for item in items))
                self.assertNotIn("fixture-only", str(result.error))

    async def test_claude_auth_and_quota_failure_before_init(self):
        for result_text, stderr, code in (
            ("login required", "", "auth_required"),
            ("error", "usage limit reached", "quota_exceeded"),
        ):
            event = {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "result": result_text,
            }
            binary = self.fake(
                f"emit({event!r})\nsys.stderr.write({stderr!r}); sys.exit(1)\n",
                provider="claude",
            )
            events, result = await self.stream(
                Client(executables={"claude": binary}), self.request("claude")
            )
            self.assertEqual(result.error.code, code)
            self.assertEqual([event.kind for event in events], ["started", "finished"])

    async def test_expected_startup_failures_have_terminal_events(self):
        for request, expected in (
            (self.request(), "cli_missing"),
            (self.request(model="--dangerous"), "invalid_request"),
            (self.request(deadline_seconds=float("inf")), "invalid_request"),
        ):
            events, result = await self.stream(
                Client(executables={"codex": self.root / "absent.exe"}), request
            )
            self.assertEqual([e.kind for e in events], ["finished"])
            self.assertEqual(result.error.code, expected)

    async def test_no_discovery_candidate_returns_cli_missing(self):
        with patch(
            "provider_cli_proxy._discovery._candidate_paths", return_value=iter(())
        ):
            _, result = await self.stream(Client(), self.request())
        self.assertEqual(result.error.code, "cli_missing")

    async def test_path_with_only_batch_shim_returns_cli_missing(self):
        shim = self.root / "codex.cmd"
        shim.write_text("@exit /b 1\n", encoding="utf-8")
        with patch(
            "provider_cli_proxy._discovery._candidate_paths", return_value=iter((shim,))
        ):
            _, result = await self.stream(Client(), self.request())
        self.assertEqual(result.error.code, "cli_missing")

    async def test_auto_discovery_skips_unusable_and_unsupported_launchers(self):
        unusable, unsupported, verified = (
            self.root / name for name in ("unusable", "unsupported", "verified")
        )
        attempted = []

        async def run_fixture(
            command, cwd, prompt, on_record, stop, deadline, on_started=None
        ):
            binary = Path(command[0])
            attempted.append(binary)
            if binary == unusable:
                raise OSError("synthetic launch error")
            if command[-1] == "--version":
                on_record(
                    b"unsupported"
                    if binary == unsupported
                    else CLI_VERSIONS["codex"].encode()
                )
            else:
                on_started()
                on_record(
                    b'{"type":"item.completed","item":{"type":"agent_message","text":"Ready."}}'
                )
                on_record(b'{"type":"turn.completed"}')
            return 0, ""

        with (
            patch(
                "provider_cli_proxy._client.executable_candidates",
                return_value=iter((unusable, unsupported, verified)),
            ),
            patch("provider_cli_proxy._client.run_child", side_effect=run_fixture),
            patch("provider_cli_proxy._client.check_subscription") as check,
        ):
            result = await Client().run(self.request())
        self.assertEqual(result.text, "Ready.")
        self.assertEqual(attempted, [unusable, unsupported, verified, verified])
        self.assertEqual(check.call_args.args[1], (str(verified),))

    async def test_unverified_subscription_never_receives_prompt(self):
        fixtures = [
            ("codex", {**CODEX_ACCOUNT, "account": None}, "auth_required"),
            (
                "codex",
                {**CODEX_ACCOUNT, "account": {"type": "apiKey"}},
                "subscription_required",
            ),
            (
                "codex",
                {**CODEX_ACCOUNT, "account": {"type": "chatgpt", "planType": "free"}},
                "subscription_required",
            ),
            (
                "codex",
                {**CODEX_ACCOUNT, "requiresOpenaiAuth": False},
                "subscription_required",
            ),
            ("codex", "invalid private-status", "auth_check_failed"),
            ("claude", {"loggedIn": False}, "auth_required"),
            (
                "claude",
                {**CLAUDE_ACCOUNT, "authMethod": "api-key", "apiProvider": "anthropic"},
                "subscription_required",
            ),
            (
                "claude",
                {**CLAUDE_ACCOUNT, "subscriptionType": "free"},
                "subscription_required",
            ),
            ("claude", "invalid private-status", "auth_check_failed"),
        ]
        for provider, auth, expected in fixtures:
            with self.subTest(provider=provider, expected=expected):
                marker = self.root / "inference-started"
                binary = self.fake(
                    f"Path({str(marker)!r}).touch()\n",
                    provider=provider,
                    auth=auth,
                )
                events, result = await self.stream(
                    Client(executables={provider: binary}), self.request(provider)
                )
                self.assertEqual([event.kind for event in events], ["finished"])
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.error.code, expected)
                self.assertNotIn("private-status", str(result.error))
                self.assertFalse(marker.exists())

    async def test_normalizes_provider_failure_without_disclosing_details(self):
        for diagnostic, expected in (
            ("login required", "auth_required"),
            ("usage limit reached", "quota_exceeded"),
            ("unknown option", "unsupported_setting"),
        ):
            body = f"sys.stderr.write({diagnostic!r} + ' private-diagnostic'); sys.exit(2)\n"
            binary = self.fake(body)
            _, result = await self.stream(
                Client(executables={"codex": binary}), self.request()
            )
            self.assertEqual(result.error.code, expected)
            self.assertNotIn("private-diagnostic", str(result.error))

    async def test_invalid_protocol_and_missing_terminal_are_failures(self):
        for body in (
            "print('malformed')\n",
            "print('x' * 1_200_000)\n",
            "emit({'type': 'new_event'})\n",
            "emit({'type': 'turn.completed'}); emit({'type': 'turn.completed'})\n",
        ):
            binary = self.fake(body)
            _, result = await self.stream(
                Client(executables={"codex": binary}), self.request()
            )
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error.code, "protocol_error")

    async def test_stream_and_result_survive_stderr_and_backlog(self):
        binary = self.fake(
            """
sys.stderr.write('x' * 500_000)
for i in range(300): emit({'type': 'turn.started'})
"""
            + CODEX_RESULT
        )
        client = Client(executables={"codex": binary})
        async with client.start(self.request()) as session:
            result = await session.wait()
            events = [event async for event in session.events()]
        self.assertEqual(result.text, "Ready.")
        self.assertEqual(events[-2].activity, "stream_truncated")
        self.assertIs(events[-1].result, result)
        self.assertLessEqual(len(events), 130)

    async def test_stdout_split_at_arbitrary_byte_boundaries(self):
        binary = self.fake("""
data = (json.dumps({'type': 'item.completed',
                    'item': {'type': 'agent_message', 'text': 'Café'}}, ensure_ascii=False) + '\\n').encode()
for pos in range(len(data)):
    sys.stdout.buffer.write(data[pos:pos+1]); sys.stdout.buffer.flush()
emit({'type': 'turn.completed'})
""")
        result = await Client(executables={"codex": binary}).run(self.request())
        self.assertEqual(result.text, "Café")

    async def test_explicit_cancel_and_context_cleanup(self):
        binary = self.fake("emit({'type': 'turn.started'}); time.sleep(60)\n")
        client = Client(executables={"codex": binary})
        async with client.start(self.request()) as session:
            events = session.events()
            self.assertEqual((await anext(events)).kind, "started")
            result = await session.cancel()
            self.assertIs(await session.cancel(), result)
            self.assertEqual(result.status, "cancelled")
            self.assertEqual(result.error.code, "cancelled")
            self.assertIs([item async for item in events][-1].result, result)
        async with client.start(self.request()) as session:
            self.assertEqual((await anext(session.events())).kind, "started")
        self.assertEqual((await session.wait()).status, "cancelled")

    def locked_process(self, name):
        lock = self.root / f"{name}.lock"
        lock.write_bytes(b"0")
        ready = self.root / f"{name}.started"
        source = f"""
import runpy
from pathlib import Path
lock_byte = runpy.run_path({str(PROCESS_FIXTURE)!r})['lock_byte']
locked = open({str(lock)!r}, 'r+b')
lock_byte(locked)
Path({str(ready)!r}).touch()
"""
        return lock, ready, source

    async def assert_lock_released(self, lock):
        for _ in range(40):
            try:
                with lock.open("r+b") as stream:
                    lock_byte(stream)
                return
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                await asyncio.sleep(0.025)
        self.fail(f"The provider process still holds {lock.name}.")

    async def test_process_tree_is_cleaned_up_when_leader_exits(self):
        lock, ready, source = self.locked_process("descendant")
        child_code = source + "\nimport time\ntime.sleep(60)\n"
        # The output pipes stay open until the proxy stops the descendant.
        binary = self.fake(
            f"""
subprocess.Popen([sys.executable, '-c', {child_code!r}], stdout=sys.stdout, stderr=sys.stderr)
while not Path({str(ready)!r}).exists(): time.sleep(0.01)
"""
            + CODEX_RESULT
        )
        result = await Client(executables={"codex": binary}).run(self.request())
        self.assertEqual(result.status, "succeeded", result.error)
        self.assertTrue(ready.exists())
        await self.assert_lock_released(lock)

    async def test_timeout_terminates_active_process(self):
        binary = self.fake("emit({'type': 'turn.started'}); time.sleep(60)\n")
        events, result = await self.stream(
            Client(executables={"codex": binary}),
            self.request(deadline_seconds=3 if os.name == "nt" else 0.35),
        )
        self.assertEqual(result.status, "timed_out")
        self.assertEqual(result.error.code, "timeout")
        self.assertIn("activity", [event.kind for event in events])

    async def test_timeout_after_early_pipe_close_does_not_cancel_process_exit(self):
        lock, ready, source = self.locked_process("early-pipe-close")
        binary = self.fake(
            source
            + """
if os.name != 'nt': signal.signal(signal.SIGTERM, signal.SIG_IGN)
for fd in (0, 1, 2): os.close(fd)
time.sleep(60)
"""
        )
        client = Client(executables={"codex": binary})
        loop = asyncio.get_running_loop()
        original_handler = loop.get_exception_handler()
        loop_errors = []
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        try:
            _, result = await self.stream(
                client, self.request(deadline_seconds=3 if os.name == "nt" else 0.35)
            )
        finally:
            loop.set_exception_handler(original_handler)
        self.assertEqual(result.status, "timed_out")
        self.assertFalse(loop_errors)
        self.assertTrue(ready.exists())
        await self.assert_lock_released(lock)

    @unittest.skipUnless(os.name == "nt", "Requires Windows Job Objects.")
    async def test_windows_job_assignment_failure_stops_bootstrap(self):
        marker = self.root / "provider-started"
        script = self.root / "startup_probe.py"
        script.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
            encoding="utf-8",
        )
        loop = asyncio.get_running_loop()
        launch = loop.subprocess_exec
        launched = []

        async def capture_startup(*args, **kwargs):
            transport, protocol = await launch(*args, **kwargs)
            launched.append(transport)
            return transport, protocol

        client = Client(executables={"codex": (sys.executable, str(script))})
        with (
            patch("provider_cli_proxy._windows.WindowsJob", side_effect=OSError),
            patch.object(loop, "subprocess_exec", capture_startup),
        ):
            events, result = await self.stream(client, self.request())

        self.assertEqual(result.error.code, "provider_error")
        self.assertEqual([event.kind for event in events], ["finished"])
        self.assertFalse(marker.exists())
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].get_returncode())

    async def test_cancel_while_spawn_is_returning(self):
        marker = self.root / "inference-started"
        binary = self.fake(f"Path({str(marker)!r}).touch(); time.sleep(60)\n")
        loop = asyncio.get_running_loop()
        launch = loop.subprocess_exec
        launched = asyncio.Future()
        release = asyncio.Event()

        async def delay_startup(*args, **kwargs):
            transport, protocol = await launch(*args, **kwargs)
            if "exec" in args:
                launched.set_result(transport)
                await release.wait()
            return transport, protocol

        client = Client(executables={"codex": binary})
        with patch.object(loop, "subprocess_exec", delay_startup):
            async with client.start(self.request()) as session:
                try:
                    transport = await asyncio.wait_for(
                        asyncio.shield(launched), timeout=10
                    )
                    cancellation = asyncio.create_task(session.cancel())
                    await asyncio.sleep(0)
                finally:
                    release.set()
                result = await cancellation
                events = [event async for event in session.events()]
        self.assertEqual(result.status, "cancelled")
        self.assertEqual([event.kind for event in events], ["finished"])
        self.assertIsNotNone(transport.get_returncode())
        if os.name == "nt":
            self.assertFalse(marker.exists())

    async def test_cumulative_answer_size_is_bounded(self):
        binary = self.fake(
            CLAUDE_INIT
            + """
for _ in range(10):
    emit({'type': 'stream_event', 'event': {'type': 'content_block_delta',
          'delta': {'type': 'text_delta', 'text': 'a' * 500_000}}})
"""
            + CLAUDE_ANSWER,
            provider="claude",
        )
        result = await Client(executables={"claude": binary}).run(
            self.request("claude")
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error.code, "protocol_error")
        self.assertIn("answer limit", result.error.message)

    def test_prompt_file_size_and_encoding(self):
        path = self.root / "prompt.txt"
        path.write_bytes(b"a" * 1_048_577)
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            Prompt.from_file(path)
        path.write_bytes(b"\xff")
        with self.assertRaises(UnicodeError):
            Prompt.from_file(path)
