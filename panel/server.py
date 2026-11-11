#!/usr/bin/env python3
"""Loopback-only web panel for Codex Skill Manager."""

from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PANEL_DIR = Path(__file__).resolve().parent
STATIC_DIR = PANEL_DIR / "static"
MANAGER_SCRIPT = PANEL_DIR.parent / "scripts" / "skill_manager.py"
MAX_BODY_BYTES = 64 * 1024
PREVIEW_TTL_SECONDS = 5 * 60


@dataclass(frozen=True)
class PanelConfig:
    codex_home: Path
    agents_home: Path
    history_db: Path
    token: str


class SkillPanelServer(ThreadingHTTPServer):
    config: PanelConfig
    previews: dict[str, dict[str, Any]]
    preview_lock: threading.Lock


def cli_command(config: PanelConfig, command: list[str]) -> list[str]:
    return [
        sys.executable,
        str(MANAGER_SCRIPT),
        "--codex-home",
        str(config.codex_home),
        "--agents-home",
        str(config.agents_home),
        "--history-db",
        str(config.history_db),
        *command,
    ]


def run_manager(config: PanelConfig, command: list[str], timeout: int = 120) -> tuple[int, Any, str]:
    try:
        result = subprocess.run(
            cli_command(config, command),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, None, "操作超时"
    stdout = result.stdout.strip()
    parsed: Any = stdout
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            pass
    return result.returncode, parsed, result.stderr.strip()


def list_trash(config: PanelConfig) -> list[dict[str, Any]]:
    root = config.codex_home / "skill-trash"
    entries: list[dict[str, Any]] = []
    if not root.is_dir():
        return entries
    for entry in sorted(root.iterdir(), reverse=True):
        metadata_path = entry / "metadata.json"
        payload = entry / "payload"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append(
            {
                "trash_id": entry.name,
                "skill": metadata.get("skill", entry.name),
                "original_path": metadata.get("original_path"),
                "trashed_at": metadata.get("trashed_at"),
                "restored_at": metadata.get("restored_at"),
                "restorable": payload.exists() or payload.is_symlink(),
            }
        )
    return entries


def action_command(payload: dict[str, Any], apply: bool = False) -> tuple[list[str], str]:
    action = payload.get("action")
    if action in {"update", "uninstall"}:
        name = payload.get("name")
        path = payload.get("path")
        if not isinstance(name, str) or not name or not isinstance(path, str) or not path:
            raise ValueError("缺少 Skill 名称或路径")
        command = [action, name, "--path", path]
        phrase = f"{'UPDATE' if action == 'update' else 'UNINSTALL'} {name}"
    elif action == "restore":
        trash_id = payload.get("trash_id")
        if not isinstance(trash_id, str) or not trash_id:
            raise ValueError("缺少回收站条目 ID")
        command = ["restore", trash_id]
        phrase = f"RESTORE {trash_id}"
    else:
        raise ValueError("不支持的操作")
    if apply:
        command.extend(["--apply", "--yes"])
    return command, phrase


class PanelHandler(BaseHTTPRequestHandler):
    server: SkillPanelServer

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'",
        )
        super().end_headers()

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def require_token(self) -> bool:
        supplied = self.headers.get("X-Skill-Manager-Token", "")
        if not secrets.compare_digest(supplied, self.server.config.token):
            self.send_json({"error": "会话令牌无效，请刷新页面"}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("请求内容为空或过大")
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("请求不是有效 JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("请求必须是 JSON 对象")
        return data

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/config":
            self.send_json({"token": self.server.config.token, "preview_ttl_seconds": PREVIEW_TTL_SECONDS})
            return
        if parsed.path == "/api/inventory":
            if not self.require_token():
                return
            query = urllib.parse.parse_qs(parsed.query)
            command = ["inventory", "--json", "--no-plugins"]
            refresh_stars = query.get("refresh_stars", ["0"])[0]
            if refresh_stars == "1":
                command.append("--refresh-stars")
            elif refresh_stars == "missing":
                command.append("--refresh-missing-stars")
            code, output, error = run_manager(self.server.config, command, timeout=180)
            if code != 0:
                self.send_json({"error": error or output or "盘点失败"}, HTTPStatus.BAD_GATEWAY)
                return
            if not isinstance(output, list):
                self.send_json({"error": "盘点结果格式无效"}, HTTPStatus.BAD_GATEWAY)
                return
            visible_skills = [
                skill for skill in output
                if skill.get("uninstall") != "protected"
                or str(skill.get("update", "")).startswith("git pull")
            ]
            self.send_json({
                "skills": visible_skills,
                "warnings": error,
            })
            return
        if parsed.path == "/api/trash":
            if self.require_token():
                self.send_json({"entries": list_trash(self.server.config)})
            return
        if parsed.path.startswith("/api/"):
            self.send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if not self.require_token():
            return
        try:
            payload = self.read_json()
            if parsed.path == "/api/preview":
                self.handle_preview(payload)
                return
            if parsed.path == "/api/apply":
                self.handle_apply(payload)
                return
            self.send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_preview(self, payload: dict[str, Any]) -> None:
        command, phrase = action_command(payload)
        code, output, error = run_manager(self.server.config, command)
        if code != 0:
            self.send_json({"error": error or output or "无法生成操作预览"}, HTTPStatus.CONFLICT)
            return
        preview_id = secrets.token_urlsafe(24)
        record = {
            "payload": payload,
            "phrase": phrase,
            "created_at": time.monotonic(),
        }
        with self.server.preview_lock:
            self.server.previews[preview_id] = record
        self.send_json({"preview_id": preview_id, "confirmation_phrase": phrase, "plan": output})

    def handle_apply(self, payload: dict[str, Any]) -> None:
        preview_id = payload.get("preview_id")
        confirmation = payload.get("confirmation")
        if not isinstance(preview_id, str) or not isinstance(confirmation, str):
            raise ValueError("缺少预览凭证或确认短语")
        with self.server.preview_lock:
            record = self.server.previews.get(preview_id)
        if not record:
            raise ValueError("预览凭证无效或已经使用")
        if time.monotonic() - record["created_at"] > PREVIEW_TTL_SECONDS:
            with self.server.preview_lock:
                self.server.previews.pop(preview_id, None)
            raise ValueError("预览已过期，请重新预览")
        if not secrets.compare_digest(confirmation, record["phrase"]):
            raise ValueError("确认短语不匹配")
        with self.server.preview_lock:
            self.server.previews.pop(preview_id, None)
        command, _phrase = action_command(record["payload"], apply=True)
        code, output, error = run_manager(self.server.config, command, timeout=180)
        if code != 0:
            self.send_json({"error": error or output or "操作失败"}, HTTPStatus.CONFLICT)
            return
        self.send_json({"result": output, "warnings": error})

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(host: str, port: int, config: PanelConfig) -> SkillPanelServer:
    server = SkillPanelServer((host, port), PanelHandler)
    server.config = config
    server.previews = {}
    server.preview_lock = threading.Lock()
    return server


def parse_args() -> argparse.Namespace:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the panel in the default browser")
    parser.add_argument("--allow-non-loopback", action="store_true")
    parser.add_argument("--codex-home", type=Path, default=home / ".codex")
    parser.add_argument("--agents-home", type=Path, default=home / ".agents")
    parser.add_argument("--history-db", type=Path, default=home / ".codex" / "thread_history_1.sqlite")
    return parser.parse_args()


def host_is_allowed(host: str, allow_non_loopback: bool) -> bool:
    return allow_non_loopback or host in {"127.0.0.1", "::1"}


def main() -> int:
    args = parse_args()
    if not host_is_allowed(args.host, args.allow_non_loopback):
        print("拒绝非本机监听；如确有需要，请显式添加 --allow-non-loopback", file=sys.stderr)
        return 2
    config = PanelConfig(
        codex_home=args.codex_home.expanduser(),
        agents_home=args.agents_home.expanduser(),
        history_db=args.history_db.expanduser(),
        token=secrets.token_urlsafe(32),
    )
    server = build_server(args.host, args.port, config)
    actual_port = server.server_address[1]
    url = f"http://{args.host}:{actual_port}"
    print(f"Codex Skill Manager: {url}", flush=True)
    if args.open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
