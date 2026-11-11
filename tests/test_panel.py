from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


SERVER_PATH = Path(__file__).parents[1] / "panel" / "server.py"
SPEC = importlib.util.spec_from_file_location("skill_panel_server", SERVER_PATH)
assert SPEC and SPEC.loader
SERVER_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SERVER_MODULE
SPEC.loader.exec_module(SERVER_MODULE)


class PanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.codex = root / ".codex"
        self.agents = root / ".agents"
        self.history = self.codex / "thread_history_1.sqlite"
        skill = self.codex / "skills" / "panel-test"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: panel-test\ndescription: Test the local panel.\n---\n", encoding="utf-8"
        )
        system_skill = self.codex / "skills" / ".system" / "core-test"
        system_skill.mkdir(parents=True)
        (system_skill / "SKILL.md").write_text(
            "---\nname: core-test\ndescription: Codex core skill.\n---\n", encoding="utf-8"
        )
        plugin_skill = self.codex / "plugins" / "cache" / "example" / "skills" / "plugin-test"
        plugin_skill.mkdir(parents=True)
        (plugin_skill / "SKILL.md").write_text(
            "---\nname: plugin-test\ndescription: Provider managed skill.\n---\n", encoding="utf-8"
        )
        with sqlite3.connect(self.history) as connection:
            connection.execute(
                "CREATE TABLE thread_items (created_at_ms INTEGER, item_json TEXT, item_type TEXT)"
            )
        config = SERVER_MODULE.PanelConfig(
            codex_home=self.codex,
            agents_home=self.agents,
            history_db=self.history,
            token="test-token",
        )
        self.server = SERVER_MODULE.build_server("127.0.0.1", 0, config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path: str, method: str = "GET", body: dict | None = None, token: bool = True):
        headers = {"X-Skill-Manager-Token": "test-token"} if token else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, method=method, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), json.load(response)

    def test_non_loopback_hosts_are_blocked_without_explicit_override(self) -> None:
        self.assertTrue(SERVER_MODULE.host_is_allowed("127.0.0.1", False))
        self.assertTrue(SERVER_MODULE.host_is_allowed("::1", False))
        self.assertFalse(SERVER_MODULE.host_is_allowed("0.0.0.0", False))
        self.assertFalse(SERVER_MODULE.host_is_allowed("192.168.1.10", False))
        self.assertTrue(SERVER_MODULE.host_is_allowed("0.0.0.0", True))

    def test_static_panel_and_inventory_endpoint(self) -> None:
        with urllib.request.urlopen(self.base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("Codex Skills", html)
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        status, _headers, data = self.request("/api/inventory")
        self.assertEqual(status, 200)
        self.assertEqual([skill["name"] for skill in data["skills"]], ["panel-test"])
        self.assertTrue(all(
            skill["uninstall"] != "protected" or str(skill["update"]).startswith("git pull")
            for skill in data["skills"]
        ))

    def test_inventory_requires_session_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/inventory", token=False)
        self.assertEqual(raised.exception.code, 403)

    def test_discovery_routes_are_not_part_of_local_manager(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/discover?q=test&sort=stars")
        self.assertEqual(raised.exception.code, 404)

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/preview", "POST", {
                "action": "install",
                "name": "remote-new",
                "repo": "example/skills",
                "skill_path": "skills/remote-new",
                "ref": "main",
            })
        self.assertEqual(raised.exception.code, 400)

    def test_uninstall_requires_preview_and_exact_confirmation_then_restores(self) -> None:
        payload = {
            "action": "uninstall",
            "name": "panel-test",
            "path": str(self.codex / "skills" / "panel-test"),
        }
        _status, _headers, preview = self.request("/api/preview", "POST", payload)
        self.assertEqual(preview["confirmation_phrase"], "UNINSTALL panel-test")

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request(
                "/api/apply",
                "POST",
                {"preview_id": preview["preview_id"], "confirmation": "wrong"},
            )
        self.assertEqual(raised.exception.code, 400)
        self.assertTrue((self.codex / "skills" / "panel-test").exists())

        _status, _headers, applied = self.request(
            "/api/apply",
            "POST",
            {"preview_id": preview["preview_id"], "confirmation": "UNINSTALL panel-test"},
        )
        trash_id = applied["result"]["trash_id"]
        self.assertFalse((self.codex / "skills" / "panel-test").exists())

        _status, _headers, restore_preview = self.request(
            "/api/preview", "POST", {"action": "restore", "trash_id": trash_id}
        )
        self.request(
            "/api/apply",
            "POST",
            {
                "preview_id": restore_preview["preview_id"],
                "confirmation": restore_preview["confirmation_phrase"],
            },
        )
        self.assertTrue((self.codex / "skills" / "panel-test" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
