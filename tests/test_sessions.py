import asyncio
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from provider_cli_proxy import Client, Prompt, RunRequest


CODEX_RESULT = """
emit({'type': 'thread.started', 'thread_id': 'test-thread'})
emit({'type': 'turn.started'})
emit({'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'hidden'}})
emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Ready.'}})
emit({'type': 'turn.completed', 'usage': {'input_tokens': 2, 'internal': 42}})
"""

CLAUDE_RESULT = """
emit({'type': 'system', 'subtype': 'init', 'session_id': 'test-session',
      'model': 'test-model', 'tools': [], 'mcp_servers': []})
emit({'type': 'stream_event', 'event': {'type': 'content_block_delta',
      'delta': {'type': 'thinking_delta', 'thinking': 'hidden'}}})
emit({'type': 'stream_event', 'parent_tool_use_id': 'sub', 'event': {
      'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'hidden'}}})
emit({'type': 'stream_event', 'event': {'type': 'content_block_delta',
      'delta': {'type': 'text_delta', 'text': 'Read'}}})
emit({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Ready.',
      'usage': {'output_tokens': 2, 'internal': 42}})
"""


class SessionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / "workspace.with spaces"
        self.workspace.mkdir()

    def fake(self, body):
        binary = self.root / "fake-cli"
        script = self.root / "fake_cli.py"
        script.write_text(
            "import json, os, signal, subprocess, sys, time\n"
            "from pathlib import Path\n"
            "def emit(event): print(json.dumps(event), flush=True)\n" + body,
            encoding="utf-8",
        )
        binary.write_text(
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"\n',
            encoding="utf-8",
        )
        binary.chmod(0o700)
        return binary

    def request(self, provider="codex", **kwargs):
        kwargs.setdefault("prompt", Prompt.text("Follow the synthetic instructions."))
        kwargs.setdefault("deadline_seconds", 2)
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
    'args': sys.argv[1:], 'cwd': os.getcwd(), 'prompt': sys.stdin.read(),
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
        instructions.write_text("Instructions from a file.\n", encoding="utf-8")
        binary = self.fake(
            """
assert sys.stdin.read() == 'Instructions from a file.\\n'
assert '--safe-mode' in sys.argv and '--restricted' in sys.argv
assert '--disable-slash-commands' in sys.argv and '--strict-mcp-config' in sys.argv
assert sys.argv[sys.argv.index('--tools') + 1] == ''
assert sys.argv[sys.argv.index('--permission-prompts') + 1] == 'none'
assert sys.argv[sys.argv.index('--effort') + 1] == 'low'
assert os.getenv('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC') == '1'
"""
            + CLAUDE_RESULT
        )
        client = Client(executables={"claude": binary})
        request = self.request(
            "claude", effort="low", prompt=Prompt.from_file(instructions)
        )
        events, result = await self.stream(client, request)
        self.assertEqual([e.text for e in events if e.text], ["Read", "Ready."])
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.actual_model, "test-model")
        self.assertEqual(result.native_session_id, "test-session")
        self.assertEqual(result.usage, {"output_tokens": 2})

    async def test_read_policy_arguments_and_version_gate(self):
        for provider, version in (
            ("codex", "codex-cli 0.171.0"),
            ("claude", "2.1.330 (Claude Code)"),
        ):
            with self.subTest(provider=provider), patch("sys.platform", "darwin"):
                program = f"""
if sys.argv[1:] == ['--version']:
    print({version!r})
    sys.exit()
assert sys.stdin.read().startswith('Read task.md')
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
                        + CLAUDE_RESULT
                    )
                client = Client(executables={provider: self.fake(program)})
                request = self.request(
                    provider,
                    prompt=Prompt.text("Read task.md."),
                    permissions="workspace_read",
                )
                result = await client.run(request)
                self.assertEqual(result.status, "succeeded")

        binary = self.fake("print('unknown version')\n")
        with patch("sys.platform", "darwin"):
            events, result = await self.stream(
                Client(executables={"codex": binary}),
                self.request(permissions="workspace_read"),
            )
        self.assertEqual([e.kind for e in events], ["finished"])
        self.assertEqual(result.error.code, "unsupported_setting")

    async def test_unsupported_workspace_platform(self):
        with patch("sys.platform", "linux"):
            events, result = await self.stream(
                Client(), self.request(permissions="workspace_read")
            )
        self.assertEqual([e.kind for e in events], ["finished"])
        self.assertEqual(result.error.code, "unsupported_setting")

    async def test_codex_project_config_refused_without_launch(self):
        (self.root / ".codex").mkdir()
        client = Client(executables={"codex": self.root / "absent"})
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
            binary = self.fake(f"emit({event!r})\n" + CLAUDE_RESULT)
            _, result = await self.stream(
                Client(executables={"claude": binary}), self.request("claude")
            )
            self.assertEqual(result.error.code, "permission_denied")
            self.assertIsNone(result.text)

    async def test_expected_startup_failures_have_terminal_events(self):
        for request, expected in (
            (self.request(), "cli_missing"),
            (self.request(model="--dangerous"), "invalid_request"),
            (self.request(deadline_seconds=float("inf")), "invalid_request"),
        ):
            events, result = await self.stream(
                Client(executables={"codex": self.root / "absent"}), request
            )
            self.assertEqual([e.kind for e in events], ["finished"])
            self.assertEqual(result.error.code, expected)

    async def test_no_path_returns_cli_missing(self):
        with (
            patch.dict(os.environ, {"HOME": str(self.root)}, clear=True),
            patch("shutil.which", return_value=None) as which,
        ):
            _, result = await self.stream(Client(), self.request())
        which.assert_called_once_with("codex", path=os.defpath)
        self.assertEqual(result.error.code, "cli_missing")

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

    async def test_deadline_kills_group_when_leader_exits(self):
        # This child holds both output descriptors after its parent has printed a result.
        binary = self.fake(
            """
subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
"""
            + CODEX_RESULT
        )
        request = self.request(deadline_seconds=1)
        result = await Client(executables={"codex": binary}).run(request)
        self.assertEqual(result.status, "succeeded")

    async def test_timeout_terminates_active_process(self):
        binary = self.fake("emit({'type': 'turn.started'}); time.sleep(60)\n")
        _, result = await self.stream(
            Client(executables={"codex": binary}), self.request(deadline_seconds=0.15)
        )
        self.assertEqual(result.status, "timed_out")
        self.assertEqual(result.error.code, "timeout")

    async def test_cancel_while_spawn_is_returning(self):
        binary = self.fake("time.sleep(60)\n")
        loop = asyncio.get_running_loop()
        launch = loop.subprocess_exec
        launched = asyncio.Future()
        release = asyncio.Event()

        async def delay_startup(*args, **kwargs):
            transport, protocol = await launch(*args, **kwargs)
            launched.set_result(transport.get_pid())
            await release.wait()
            return transport, protocol

        client = Client(executables={"codex": binary})
        with patch.object(loop, "subprocess_exec", delay_startup):
            async with client.start(self.request()) as session:
                pid = await launched
                cancellation = asyncio.create_task(session.cancel())
                await asyncio.sleep(0)
                release.set()
                result = await cancellation
                events = [event async for event in session.events()]
        self.assertEqual(result.status, "cancelled")
        self.assertEqual([event.kind for event in events], ["finished"])
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    async def test_cumulative_answer_size_is_bounded(self):
        binary = self.fake(
            """
for _ in range(10):
    emit({'type': 'stream_event', 'event': {'type': 'content_block_delta',
          'delta': {'type': 'text_delta', 'text': 'a' * 500_000}}})
"""
            + CLAUDE_RESULT
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
