"""Serialized TCP bridge to one verified Unity project."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import config

logger = logging.getLogger(__name__)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6400
DEFAULT_TIMEOUT = 60.0
EXPECTED_HANDSHAKE = "WELCOME UNITY-MCP 1 FRAMING=1\n"
_HEARTBEAT_DIR = Path.home() / ".unity-mcp"

class ProjectSelectionError(ConnectionError):
    pass

class ExecutionUncertainError(ConnectionError):
    pass

def normalize_project_path(value: str) -> str:
    path = Path(value).expanduser().resolve()
    if path.name.lower() == "assets":
        path = path.parent
    return os.path.normcase(str(path))

def discover_unity_instances() -> list[dict[str, Any]]:
    instances = {}
    for path in Path(_HEARTBEAT_DIR).glob("unity-mcp-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - timestamp).total_seconds()
            if not 0 <= age <= 30 or not data.get("project_path"):
                continue
            data["project_path"] = normalize_project_path(data["project_path"])
            data["unity_port"] = int(data["unity_port"])
            if not 1 <= data["unity_port"] <= 65535:
                continue
            instances[(data["project_path"], data["unity_port"])] = data
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(instances.values(), key=lambda value: (value["project_path"], value["unity_port"]))

# Unknown actions remain non-retryable. These are inspections with no editor writes.
_READ_ONLY = {
    "run_tests": {"status"},
    "manage_editor": {"get_editor_state", "get_unity_logs", "check_compile_errors", "get_registered_actions", "get_game_object_info", "list_hierarchy"},
    "manage_scene": {"get_hierarchy", "get_active", "get_scene_context"},
    "manage_gameobject": {"get_info"},
    "manage_components": {"get"},
    "manage_script": {"read", "validate"},
    "read_console": {None, "get", "read"},
}

class UnityBridge:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT):
        self.host, self.port, self.timeout = host, port, timeout
        self._reader = None
        self._writer = None
        self._connected = False
        self._handshake_ok = False
        self._cmd_lock = asyncio.Lock()
        self._project_path = normalize_project_path(config.unity_project_path) if config.unity_project_path else None
        self._info: dict[str, Any] = {}

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and self._handshake_ok and self._writer and not self._writer.is_closing() and self._reader and not self._reader.at_eof())

    async def select_project(self, path: str) -> None:
        async with self._cmd_lock:
            self.close()
            self._project_path = normalize_project_path(path)
            config.unity_project_path = self._project_path
            self._info = {}

    def _get_effective_port(self) -> int:
        candidates = discover_unity_instances()
        if self._project_path:
            candidates = [item for item in candidates if item["project_path"] == self._project_path]
        if len(candidates) > 1:
            raise ProjectSelectionError("Multiple Unity instances; set UNITY_MCP_PROJECT_PATH or select a project. Candidates: " + json.dumps(candidates, ensure_ascii=False))
        if not candidates:
            if config.unity_port_explicit:
                return config.unity_port
            raise ProjectSelectionError("No fresh heartbeat for the selected Unity project. Start the Unity MCP plugin.")
        self._project_path = candidates[0]["project_path"]
        return candidates[0]["unity_port"]

    async def connect(self) -> None:
        if self.is_connected:
            return
        self.port = self._get_effective_port()
        try:
            self._reader, self._writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), self.timeout)
            sock = self._writer.get_extra_info("socket")
            if sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            handshake = await asyncio.wait_for(self._reader.readline(), min(self.timeout, 10))
            if handshake.decode("utf-8") != EXPECTED_HANDSHAKE:
                raise ConnectionError("Unsupported Unity handshake")
            await self._write_frame("get_info")
            response = json.loads(await asyncio.wait_for(self._read_frame(), self.timeout))
            info = response.get("result", {}) if response.get("status") == "success" else {}
            actual = normalize_project_path(info["project_path"]) if info.get("project_path") else None
            if not actual or actual != self._project_path:
                raise ProjectSelectionError(f"Unity project mismatch: expected {self._project_path}, received {actual}")
            self._info = info
            self._connected = self._handshake_ok = True
        except BaseException:
            self.close()
            raise

    async def send_command(self, tool: str, arguments: dict[str, Any] | None = None, timeout: float | None = None, max_retries: int = 5) -> dict[str, Any]:
        args = arguments or {}
        read_only = tool == "ping" or args.get("action") in _READ_ONLY.get(tool, set())
        payload = "ping" if tool == "ping" else json.dumps({"tool": tool, "arguments": args}, ensure_ascii=False)
        async with self._cmd_lock:
            for attempt in range(max(1, max_retries)):
                sent = False
                try:
                    await self.connect()
                    sent = True
                    await asyncio.wait_for(self._write_frame(payload), timeout or self.timeout)
                    result = json.loads(await asyncio.wait_for(self._read_frame(), timeout or self.timeout))
                    if not isinstance(result, dict) or result.get("status") not in {"success", "error"}:
                        raise ValueError("Invalid Unity response envelope")
                    if result.get("status") == "success" and isinstance(result.get("result"), dict) and result["result"].get("status") in {"success", "error"}:
                        result = result["result"]
                    return result
                except asyncio.CancelledError:
                    self.close()
                    raise
                except ProjectSelectionError:
                    self.close()
                    raise
                except (OSError, asyncio.IncompleteReadError, ValueError) as exc:
                    self.close()
                    if sent and not read_only:
                        raise ExecutionUncertainError(f"execution_uncertain: {tool} may have executed; inspect Unity before retrying. {exc}") from exc
                    if attempt + 1 >= max(1, max_retries):
                        raise ConnectionError(f"Unity request failed: {tool}: {exc}") from exc
                    await asyncio.sleep(min(0.25 * 2 ** attempt, 2))

    async def ping(self) -> bool:
        try:
            return (await self.send_command("ping", timeout=5, max_retries=1)).get("status") == "success"
        except ConnectionError:
            return False

    async def get_unity_info(self) -> dict[str, Any]:
        async with self._cmd_lock:
            await self.connect()
            return dict(self._info)

    def close(self) -> None:
        if self._writer:
            self._writer.close()
        self._reader = self._writer = None
        self._connected = self._handshake_ok = False

    async def _read_frame(self) -> str:
        header = await self._reader.readexactly(8)
        size = struct.unpack(">Q", header)[0]
        if not 0 < size <= 64 * 1024 * 1024:
            raise ValueError(f"Invalid Unity frame length: {size}")
        return (await self._reader.readexactly(size)).decode("utf-8")

    async def _write_frame(self, data: str) -> None:
        encoded = data.encode("utf-8")
        self._writer.write(struct.pack(">Q", len(encoded)) + encoded)
        await self._writer.drain()

_bridge_instance: UnityBridge | None = None

def get_bridge(host: str | None = None, port: int | None = None) -> UnityBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = UnityBridge(host or config.unity_host, port or config.unity_port)
    return _bridge_instance

async def send_to_unity(tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return await get_bridge().send_command(tool, arguments)

def close_bridge() -> None:
    global _bridge_instance
    if _bridge_instance:
        _bridge_instance.close()
        _bridge_instance = None
