import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from ._models import EventKind, Permission, Provider, RunError, RunRequest

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,199}", re.ASCII)
_NONESSENTIAL_ENV = {
    "DO_NOT_TRACK": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED": "1",
}
_ENV_KEYS = {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "LOGNAME", "PATH", "TMPDIR", "USER"}
_WINDOWS_ENV_KEYS = {
    "APPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
}
_WORKSPACE_READ_SUPPORTED = sys.platform == "darwin"
CLI_VERSIONS = {
    "codex": b"codex-cli 0.171.0",
    "claude": b"2.1.330 (Claude Code)",
}
_CLAUDE_READ_TOOLS = ("Read", "Glob", "Grep")

_CODEX_CONFIG = (
    "approval_policy='never'",
    "model_provider='openai'",
    "cli_auth_credentials_store='auto'",
    "check_for_update_on_startup=false",
    "analytics.enabled=false",
    "feedback.enabled=false",
    "otel.exporter='none'",
    "otel.trace_exporter='none'",
    "otel.metrics_exporter='none'",
    "web_search='disabled'",
    "project_doc_max_bytes=0",
    "project_root_markers=[]",
    "features.apps=false",
    "features.apply_patch_freeform=false",
    "features.browser_use=false",
    "features.code_mode=false",
    "features.computer_use=false",
    "features.fast_mode=false",
    "features.goals=false",
    "features.hooks=false",
    "features.memories=false",
    "features.multi_agent=false",
    "features.remote_control=false",
    "features.shell_snapshot=false",
    "features.ultrafast_mode=false",
    "features.view_image=false",
)

_CODEX_ACTIVITY = {
    "command_execution": "command",
    "file_change": "file_change",
    "mcp_tool_call": "tool",
    "web_search": "web_search",
    "todo_list": "plan",
}
_USAGE_FIELDS = {
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "reasoning_output_tokens",
}


class Failure(Exception):
    """A failure whose public text is safe for application-facing results."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.error = RunError(code, message)


def child_environment() -> dict[str, str]:
    keys = _ENV_KEYS | _WINDOWS_ENV_KEYS if os.name == "nt" else _ENV_KEYS
    env = {
        key: val for key, val in os.environ.items() if key in keys
    } | _NONESSENTIAL_ENV
    path = os.pathsep.join(
        entry
        for entry in env.get("PATH", "").split(os.pathsep)
        if Path(entry).is_absolute()
    )
    env["PATH"] = path or ("" if os.name == "nt" else os.defpath)
    return env


def _workspace_has_codex_config(cwd: Path) -> bool:
    # The user's default CLI configuration is suppressed by --ignore-user-config.
    return any(
        os.path.lexists(directory / ".codex")
        for directory in (cwd, *cwd.parents)
        if directory != Path.home().resolve()
    )


def codex_config_options(cwd: Path, *extra: str) -> list[str]:
    """Apply the same provider and credential routing to Codex subprocesses."""
    project_key = json.dumps(str(cwd), ensure_ascii=False)
    options = [
        *_CODEX_CONFIG,
        f"projects={{{project_key}={{trust_level='untrusted'}}}}",
        *extra,
    ]
    return [argument for setting in options for argument in ("-c", setting)]


def claude_command_options(
    permissions: Permission,
    model: str | None,
    effort: str | None,
    *,
    input_format: str = "text",
) -> list[str]:
    """Build a restricted local Claude process for a prompt or control messages."""
    args = [
        "--print",
        "--input-format",
        input_format,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--no-session-persistence",
        "--safe-mode",
        "--restricted",
        "--no-chrome",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--settings",
        '{"disableAllHooks":true,"disableClaudeAiConnectors":true,"fastMode":false}',
        "--permission-prompts",
        "none",
        "--permission-mode",
        "dontAsk",
    ]
    if permissions == "workspace_read":
        tools = ",".join(_CLAUDE_READ_TOOLS)
        args.extend(["--tools", tools, "--allowedTools", tools])
    else:
        args.extend(["--tools", ""])
    if model:
        args.extend(["--model", model])
    if effort:
        args.extend(["--effort", effort])
    return args


def command_options(request: RunRequest, cwd: Path) -> list[str]:
    for value in (request.model, request.effort):
        if value is not None and (
            not isinstance(value, str) or not _TOKEN.fullmatch(value)
        ):
            raise Failure(
                "invalid_request", "Model or effort is not a valid identifier."
            )
    if request.permissions not in ("prompt_only", "workspace_read"):
        raise Failure("unsupported_setting", "Unknown permission profile.")
    if request.permissions == "workspace_read" and not _WORKSPACE_READ_SUPPORTED:
        raise Failure(
            "unsupported_setting", "Workspace-only reads are supported on macOS."
        )

    if request.provider == "codex":
        if _workspace_has_codex_config(cwd):
            raise Failure(
                "permission_denied",
                "Choose a workspace without project Codex configuration.",
            )
        config = []
        if request.effort:
            config.append(f"model_reasoning_effort={json.dumps(request.effort)}")
        args = [
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--color",
            "never",
        ]
        if request.permissions == "workspace_read":
            config.extend(
                [
                    "features.shell_tool=true",
                    "default_permissions='provider-proxy'",
                    "permissions.provider-proxy.filesystem={':root'='deny', ':minimal'='read',"
                    " ':workspace_roots'={'.'='read'}}",
                    "permissions.provider-proxy.network.enabled=false",
                    "shell_environment_policy.inherit='none'",
                ]
            )
        else:
            args.extend(["--sandbox", "read-only"])
            config.append("features.shell_tool=false")
        args.extend(codex_config_options(cwd, *config))
        if request.model:
            args.extend(["--model", request.model])
        return [*args, "-"]

    if request.provider == "claude":
        return claude_command_options(
            request.permissions, request.model, request.effort
        )

    raise Failure("unsupported_setting", "Choose the codex or claude provider.")


def recognized_error(diagnostic: str) -> RunError | None:
    message = diagnostic.casefold()
    if any(
        phrase in message
        for phrase in (
            "unknown option",
            "unexpected argument",
            "invalid value",
            "invalid effort",
            "unknown model",
            "model not found",
            "model is not supported",
            "model is not available",
            "does not support this model",
            "not supported when using codex",
        )
    ):
        return RunError("unsupported_setting", "The CLI rejected a requested setting.")
    if any(
        phrase in message
        for phrase in (
            "not logged in",
            "please log in",
            "please login",
            "authentication required",
            "unauthorized",
            "invalid api key",
            "missing api key",
            "please run /login",
            "not authenticated",
            "authentication_error",
            "login required",
        )
    ):
        return RunError("auth_required", "Sign in using the provider CLI and retry.")
    if any(
        phrase in message
        for phrase in (
            "rate limit",
            "rate_limit",
            "usage limit",
            "hit your limit",
            "quota exceeded",
            "insufficient_quota",
            "credit balance",
            "resource_exhausted",
            "status 429",
        )
    ):
        return RunError(
            "quota_exceeded", "The provider reported a usage or rate limit."
        )
    return None


def _token(value: object) -> str | None:
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


def _usage(value: object) -> dict[str, int] | None:
    if isinstance(value, dict):
        return {
            key: count
            for key, count in value.items()
            if key in _USAGE_FIELDS and type(count) is int and count >= 0
        } or None
    return None


class Decoder:
    """Interpret native events without exporting raw diagnostics or reasoning."""

    def __init__(self, provider: Provider, permissions: Permission):
        self.provider = provider
        self.permissions = permissions
        self.text: str | None = None
        self.native_session_id: str | None = None
        self.actual_model: str | None = None
        self.usage: dict[str, int] | None = None
        self.error: RunError | None = None
        self.hint: RunError | None = None
        self.terminal = False
        self._claude_initialized = False
        self._claude_tools = (
            _CLAUDE_READ_TOOLS if permissions == "workspace_read" else ()
        )

    def decode(self, record: bytes) -> tuple[EventKind, str] | None:
        try:
            event = json.loads(record.decode("utf-8"))
        except (ValueError, RecursionError):
            raise Failure(
                "protocol_error", "The CLI sent an invalid event record."
            ) from None
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise Failure("protocol_error", "The CLI sent an invalid event record.")
        if self.provider == "codex":
            return self._codex(event)
        return self._claude(event)

    def _complete(self) -> None:
        if self.terminal:
            raise Failure(
                "protocol_error", "The CLI sent more than one terminal result."
            )
        self.terminal = True

    def _codex(self, event: dict[str, Any]) -> tuple[EventKind, str] | None:
        kind = event["type"]
        if kind == "thread.started":
            self.native_session_id = _token(event.get("thread_id"))
        elif kind == "turn.started":
            return "activity", "turn_started"
        elif kind == "turn.completed":
            self._complete()
            self.usage = _usage(event.get("usage"))
        elif kind == "turn.failed":
            self._complete()
            data = event.get("error")
            message = data.get("message") if isinstance(data, dict) else None
            if isinstance(message, str):
                self.error = recognized_error(message)
            self.error = (
                self.error
                or self.hint
                or RunError("provider_error", "Codex reported a failed turn.")
            )
        elif kind == "error" and isinstance(message := event.get("message"), str):
            self.hint = recognized_error(message) or self.hint
        elif kind in ("item.started", "item.completed") and isinstance(
            item := event.get("item"), dict
        ):
            item_type = item.get("type")
            if item_type == "agent_message" and kind == "item.completed":
                if self.terminal:
                    raise Failure(
                        "protocol_error",
                        "Codex sent assistant text after the turn ended.",
                    )
                text = item.get("text")
                if not isinstance(text, str):
                    raise Failure(
                        "protocol_error", "Codex emitted a malformed assistant message."
                    )
                self.text = text
                return "answer_snapshot", text
            if isinstance(item_type, str) and item_type in _CODEX_ACTIVITY:
                if item_type != "todo_list" and (
                    self.permissions == "prompt_only"
                    or item_type != "command_execution"
                ):
                    raise Failure(
                        "permission_denied",
                        "Codex used a tool outside the requested profile.",
                    )
                suffix = "started" if kind == "item.started" else "completed"
                return "activity", f"{_CODEX_ACTIVITY[item_type]}_{suffix}"
        return None

    def _claude(self, event: dict[str, Any]) -> tuple[EventKind, str] | None:
        kind = event["type"]
        if kind == "system" and event.get("subtype") == "init":
            tools = event.get("tools")
            servers = event.get("mcp_servers")
            if (
                self._claude_initialized
                or not isinstance(tools, list)
                or not all(isinstance(tool, str) for tool in tools)
                or not isinstance(servers, list)
            ):
                raise Failure(
                    "protocol_error", "Claude sent invalid tool capability metadata."
                )
            if any(tool not in self._claude_tools for tool in tools):
                raise Failure(
                    "permission_denied",
                    "Claude exposed tools outside the requested profile.",
                )
            if servers:
                raise Failure(
                    "permission_denied", "Claude loaded an unexpected tool server."
                )
            self.native_session_id = _token(event.get("session_id"))
            self.actual_model = _token(event.get("model"))
            self._claude_initialized = True
            return "activity", "turn_started"
        if kind == "result":
            self._complete()
            self.native_session_id = (
                _token(event.get("session_id")) or self.native_session_id
            )
            self.usage = _usage(event.get("usage"))
            text = event.get("result")
            subtype = event.get("subtype")
            if event.get("is_error") is True or (
                isinstance(subtype, str) and subtype != "success"
            ):
                errors = event.get("errors")
                safe_hint = recognized_error(text) if isinstance(text, str) else None
                if not safe_hint and isinstance(errors, list):
                    safe_hint = next(
                        (
                            hint
                            for error in errors
                            if isinstance(error, str)
                            and (hint := recognized_error(error))
                        ),
                        None,
                    )
                self.error = safe_hint or RunError(
                    "provider_error", "Claude reported a failed turn."
                )
            elif (
                subtype != "success"
                or event.get("is_error") is not False
                or not isinstance(text, str)
            ):
                raise Failure(
                    "protocol_error", "Claude emitted a malformed terminal result."
                )
            else:
                if not self._claude_initialized:
                    raise Failure(
                        "protocol_error", "Claude did not report its tool capabilities."
                    )
                self.text = text
                return "answer_snapshot", text
        if not self._claude_initialized:
            return None
        primary = event.get("parent_tool_use_id") is None
        if kind == "stream_event" and isinstance(stream := event.get("event"), dict):
            if stream.get("type") == "content_block_start":
                self._claude_tool_use(stream.get("content_block"))
            delta = stream.get("delta")
            if (
                primary
                and stream.get("type") == "content_block_delta"
                and isinstance(delta, dict)
            ):
                if delta.get("type") == "text_delta" and isinstance(
                    text := delta.get("text"), str
                ):
                    return "answer_delta", text
        if kind in ("assistant", "user") and isinstance(
            message := event.get("message"), dict
        ):
            content = message.get("content")
            if isinstance(content, list):
                if kind == "assistant":
                    tools_used = False
                    for item in content:
                        tools_used = self._claude_tool_use(item) or tools_used
                    if primary and tools_used:
                        return "activity", "tool_started"
                elif primary and any(
                    isinstance(item, dict) and item.get("type") == "tool_result"
                    for item in content
                ):
                    return "activity", "tool_completed"
        return None

    def _claude_tool_use(self, block: object) -> bool:
        if not isinstance(block, dict) or block.get("type") not in (
            "tool_use",
            "server_tool_use",
        ):
            return False
        if (
            block.get("type") != "tool_use"
            or block.get("name") not in self._claude_tools
        ):
            raise Failure(
                "permission_denied", "Claude used a tool outside the requested profile."
            )
        return True
