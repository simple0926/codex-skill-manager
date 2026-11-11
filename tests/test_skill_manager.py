from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "skill_manager.py"
SPEC = importlib.util.spec_from_file_location("skill_manager_under_test", SCRIPT)
assert SPEC and SPEC.loader
SKILL_MANAGER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SKILL_MANAGER
SPEC.loader.exec_module(SKILL_MANAGER)


class SkillManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.codex = self.root / ".codex"
        self.agents = self.root / ".agents"
        self.history = self.codex / "thread_history_1.sqlite"
        skill = self.codex / "skills" / "alpha"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: Analyze product requirements.\nsource: https://github.com/example/alpha\n---\n",
            encoding="utf-8",
        )
        self.history.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.history) as connection:
            connection.execute(
                "CREATE TABLE thread_items (created_at_ms INTEGER, item_json TEXT, item_type TEXT)"
            )
            message = {"content": [{"type": "text", "text": "Use $alpha for this."}]}
            connection.execute(
                "INSERT INTO thread_items VALUES (?, ?, 'userMessage')",
                (4102444800000, json.dumps(message)),
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--codex-home",
                str(self.codex),
                "--agents-home",
                str(self.agents),
                "--history-db",
                str(self.history),
                *args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def git(self, directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(directory), *args], text=True, capture_output=True, check=True
        )

    def test_inventory_reports_category_source_and_explicit_usage(self) -> None:
        result = self.run_cli("inventory", "--no-plugins", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        [skill] = json.loads(result.stdout)
        self.assertEqual(skill["name"], "alpha")
        self.assertEqual(skill["category"], "产品与设计")
        self.assertEqual(skill["category_source"], "heuristic")
        self.assertEqual(skill["usage_all"], 1)
        self.assertEqual(skill["usage_basis"], "explicit-skill-token-mentions")
        self.assertEqual(skill["github_repo"], "example/alpha")
        self.assertIsNone(skill["stars"])

    def test_star_refresh_stops_after_rate_limit_and_warns_once(self) -> None:
        for name, repo in (("beta", "example/alpha"), ("gamma", "example/gamma")):
            skill = self.codex / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Test rate limit handling.\nsource: https://github.com/{repo}\n---\n",
                encoding="utf-8",
            )
        args = argparse.Namespace(
            codex_home=self.codex,
            agents_home=self.agents,
            history_db=self.history,
            no_plugins=True,
            star_cache=self.root / "stars.json",
            refresh_stars=True,
            refresh_missing_stars=False,
        )
        stderr = io.StringIO()
        with mock.patch.object(
            SKILL_MANAGER,
            "refresh_star",
            return_value=(None, None, "HTTP Error 403: rate limit exceeded"),
        ) as refresh, contextlib.redirect_stderr(stderr):
            SKILL_MANAGER.scan_skills(args)

        self.assertEqual(refresh.call_count, 1)
        self.assertEqual(stderr.getvalue().lower().count("rate limit"), 1)

    def test_uninstall_is_previewed_then_recoverable(self) -> None:
        preview = self.run_cli("uninstall", "alpha", "--no-plugins")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        plan = json.loads(preview.stdout)
        self.assertFalse(plan["applied"])
        self.assertTrue((self.codex / "skills" / "alpha").exists())

        applied = self.run_cli("uninstall", "alpha", "--no-plugins", "--apply", "--yes")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        applied_plan = json.loads(applied.stdout)
        self.assertFalse((self.codex / "skills" / "alpha").exists())

        restored = self.run_cli("restore", applied_plan["trash_id"], "--apply", "--yes")
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertTrue((self.codex / "skills" / "alpha" / "SKILL.md").exists())

    def test_github_install_is_previewed_and_validated(self) -> None:
        preview = self.run_cli(
            "install",
            "remote-skill",
            "--repo",
            "example/skills",
            "--skill-path",
            "skills/remote-skill",
            "--ref",
            "main",
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        plan = json.loads(preview.stdout)
        self.assertEqual(plan["action"], "install-from-github")
        self.assertFalse(plan["applied"])

        invalid = self.run_cli(
            "install",
            "remote-skill",
            "--repo",
            "example/skills",
            "--skill-path",
            "../escape",
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("invalid skill path", invalid.stderr)

        root_preview = self.run_cli(
            "install",
            "root-skill",
            "--repo",
            "example/root-skill",
            "--skill-path",
            ".",
        )
        self.assertEqual(root_preview.returncode, 0, root_preview.stderr)

    def test_github_install_delegates_to_system_installer(self) -> None:
        installer = (
            self.codex
            / "skills"
            / ".system"
            / "skill-installer"
            / "scripts"
            / "install-skill-from-github.py"
        )
        installer.parent.mkdir(parents=True)
        installer.write_text(
            """import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--repo'); p.add_argument('--path'); p.add_argument('--ref')
p.add_argument('--dest'); p.add_argument('--name')
a = p.parse_args()
d = Path(a.dest) / a.name
d.mkdir(parents=True)
(d / 'SKILL.md').write_text('---\\nname: remote-skill\\ndescription: Installed.\\n---\\n')
print(f'Installed {a.name}')
""",
            encoding="utf-8",
        )
        applied = self.run_cli(
            "install",
            "remote-skill",
            "--repo",
            "example/skills",
            "--skill-path",
            "skills/remote-skill",
            "--apply",
            "--yes",
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue((self.codex / "skills" / "remote-skill" / "SKILL.md").is_file())

    def test_system_skill_is_protected(self) -> None:
        system_skill = self.codex / "skills" / ".system" / "protected"
        system_skill.mkdir(parents=True)
        (system_skill / "SKILL.md").write_text(
            "---\nname: protected\ndescription: Protected.\n---\n", encoding="utf-8"
        )
        result = self.run_cli("uninstall", "protected", "--no-plugins", "--apply", "--yes")
        self.assertEqual(result.returncode, 2)
        self.assertIn("provider-managed", result.stderr)
        self.assertTrue(system_skill.exists())

    def test_codex_name_does_not_false_match_code_category(self) -> None:
        manager = self.codex / "skills" / "codex-skill-manager"
        manager.mkdir(parents=True)
        (manager / "SKILL.md").write_text(
            "---\nname: codex-skill-manager\ndescription: Manage installed skills.\n---\n",
            encoding="utf-8",
        )
        result = self.run_cli("inventory", "--no-plugins", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        skills = json.loads(result.stdout)
        [skill] = [item for item in skills if item["name"] == "codex-skill-manager"]
        self.assertEqual(skill["category"], "系统与管理")

    def test_git_linked_skill_updates_whole_repository(self) -> None:
        remote = self.root / "remote.git"
        seed = self.root / "seed"
        checkout = self.root / "checkout"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)
        self.git(seed, "config", "user.name", "Skill Test")
        self.git(seed, "config", "user.email", "skill-test@example.com")
        beta = seed / "beta"
        beta.mkdir()
        (beta / "SKILL.md").write_text(
            "---\nname: beta\ndescription: Test Git updates.\n---\n", encoding="utf-8"
        )
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-m", "initial")
        self.git(seed, "remote", "add", "origin", str(remote))
        self.git(seed, "push", "-u", "origin", "HEAD")
        subprocess.run(["git", "clone", str(remote), str(checkout)], check=True, capture_output=True)

        shared = self.agents / "skills"
        shared.mkdir(parents=True)
        os.symlink(checkout / "beta", shared / "beta")
        (beta / "updated.txt").write_text("updated\n", encoding="utf-8")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-m", "update")
        self.git(seed, "push")

        preview = self.run_cli("update", "beta", "--no-plugins")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertFalse(json.loads(preview.stdout)["applied"])
        applied = self.run_cli("update", "beta", "--no-plugins", "--apply", "--yes")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue(json.loads(applied.stdout)["applied"])
        self.assertTrue((checkout / "beta" / "updated.txt").exists())


if __name__ == "__main__":
    unittest.main()
