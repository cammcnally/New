from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


class MCPError(RuntimeError):
    """Raised when Codex MCP communication fails."""


class CodexMCPBackend:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.process: Optional[subprocess.Popen[bytes]] = None
        self._stderr_tail = b""
        self._stderr_lock = threading.Lock()
        self.command = self._resolve_command()

    def _resolve_command(self) -> list[str]:
        local_cmd = self.project_root / "node_modules" / ".bin" / ("codex.cmd" if shutil.which("cmd") else "codex")
        if local_cmd.exists():
            if os.name == "nt" and local_cmd.suffix.lower() in {".cmd", ".bat"}:
                return ["cmd", "/c", str(local_cmd), "mcp-server"]
            return [str(local_cmd), "mcp-server"]

        npx_path = shutil.which("npx")
        if npx_path:
            return [npx_path, "codex", "mcp-server"]

        raise MCPError(
            "Unable to resolve a repo-local Codex CLI for MCP startup. "
            "Expected node_modules/.bin/codex(.cmd) or local npx."
        )

    def __enter__(self) -> "CodexMCPBackend":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _drain_stderr_bg(self) -> None:
        proc = self.process
        if proc is None or proc.stderr is None:
            return

        def run() -> None:
            assert proc.stderr is not None
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                with self._stderr_lock:
                    self._stderr_tail = (self._stderr_tail + chunk)[-8000:]

        threading.Thread(target=run, daemon=True).start()

    def _format_stderr(self) -> str:
        with self._stderr_lock:
            return self._stderr_tail.decode("utf-8", errors="replace")

    def start(self) -> None:
        if self.process is not None:
            return
        self._stderr_tail = b""
        self.process = subprocess.Popen(
            self.command,
            cwd=self.project_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        self._drain_stderr_bg()
        self.initialize()

    def close(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise MCPError("Codex MCP backend is not running")
        return self.process

    def _send(self, payload: Mapping[str, Any]) -> None:
        """Send one JSON-RPC message using newline-delimited JSON (stdio MCP).

        The Codex CLI expects each message as a single JSON object terminated by
        ``\\n``, not HTTP-style ``Content-Length`` framing on stdin.
        """
        process = self._require_process()
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        process.stdin.write(encoded + b"\n")
        process.stdin.flush()

    def _recv(self) -> Mapping[str, Any]:
        """Read one JSON-RPC response from the Codex MCP server.

        The official Codex CLI (stdio) emits newline-delimited JSON. Some servers
        use Content-Length framing; support both so the client does not block
        waiting for ``\\r\\n\\r\\n`` that never arrives.
        """
        process = self._require_process()
        stdout = process.stdout

        def _read_stderr() -> str:
            # stderr is consumed by _drain_stderr_bg; do not read the pipe here.
            return self._format_stderr()

        first_line = b""
        while True:
            line = stdout.readline()
            if not line:
                raise MCPError(f"Unexpected EOF from Codex MCP server: {_read_stderr()}")
            if line.strip():
                first_line = line
                break

        trimmed = first_line.lstrip()
        if trimmed.startswith(b"{"):
            payload = json.loads(first_line.rstrip(b"\r\n").decode("utf-8"))
        elif trimmed.lower().startswith(b"content-length:"):
            header = first_line
            while b"\r\n\r\n" not in header:
                chunk = stdout.read(1)
                if not chunk:
                    raise MCPError(f"Unexpected EOF from Codex MCP server: {_read_stderr()}")
                header += chunk
            head, remainder = header.split(b"\r\n\r\n", 1)
            length: Optional[int] = None
            for hl in head.decode("ascii", errors="replace").split("\r\n"):
                if hl.lower().startswith("content-length:"):
                    length = int(hl.split(":", 1)[1].strip())
                    break
            if length is None:
                raise MCPError("MCP response missing Content-Length")
            body = remainder
            while len(body) < length:
                chunk = stdout.read(length - len(body))
                if not chunk:
                    raise MCPError(f"Unexpected EOF while reading MCP body: {_read_stderr()}")
                body += chunk
            payload = json.loads(body[:length].decode("utf-8"))
        else:
            raise MCPError(f"Unexpected MCP response prefix: {first_line[:200]!r}")

        if "error" in payload:
            raise MCPError(json.dumps(payload["error"], sort_keys=True))
        return payload

    def initialize(self) -> Mapping[str, Any]:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "repo-control-plane", "version": "1.0.0"},
                },
            }
        )
        response = self._recv()
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return response

    def list_tools(self) -> list[Mapping[str, Any]]:
        self._send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        response = self._recv()
        tools = response.get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            raise MCPError("Invalid tools/list response")
        return tools

    def list_tool_names(self) -> list[str]:
        names: list[str] = []
        for tool in self.list_tools():
            name = tool.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        return names

    def ensure_expected_tools(self, expected_tools: Sequence[str]) -> list[str]:
        available = self.list_tool_names()
        missing = [tool for tool in expected_tools if tool not in available]
        unexpected = [tool for tool in available if tool not in expected_tools]
        if missing:
            raise MCPError(
                "Codex MCP server is missing expected tools: "
                + ", ".join(missing)
                + f" (available: {', '.join(sorted(available))})"
            )
        if unexpected:
            raise MCPError(
                "Codex MCP server exposed unexpected tools: "
                + ", ".join(sorted(unexpected))
                + f" (expected only: {', '.join(sorted(expected_tools))})"
            )
        return available

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments)},
            }
        )
        response = self._recv()
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise MCPError("Invalid tools/call response")
        return result
