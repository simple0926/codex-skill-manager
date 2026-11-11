#!/usr/bin/env python3
"""Inventory and safely manage locally installed Codex skills."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("图像与视觉", ("image", "visual", "poster", "illustration", "logo", "icon", "photo", "画", "海报", "视觉", "插图", "头像")),
    ("产品与设计", ("product", "prototype", "ui", "ux", "design", "requirement", "产品", "原型", "需求", "设计")),
    ("开发与代码", ("code", "git", "test", "debug", "engineering", "frontend", "api", "代码", "开发", "测试")),
    ("文档与数据", ("document", "pdf", "spreadsheet", "excel", "slide", "presentation", "data", "文档", "表格", "演示")),
    ("内容与写作", ("write", "article", "resume", "wechat", "content", "copy", "写作", "文章", "简历", "内容")),
    ("研究与分析", ("research", "analy", "audit", "review", "perspective", "研究", "分析", "评审")),
    ("运营与自动化", ("publish", "media", "video", "automation", "workflow", "运营", "发布", "视频", "自动化")),
    ("系统与管理", ("skill", "plugin", "install", "organizer", "manager", "系统", "管理", "安装")),
]


@dataclass
class Skill:
    name: str
    description: str
    path: str
    scope: str
    category: str
    category_source: str
    source_url: str | None
    github_repo: str | None
    stars: int | None
    stars_updated_at: str | None
    usage_30d: int = 0
    usage_90d: int = 0
    usage_all: int = 0
    last_used: str | None = None
    usage_basis: str = "explicit-skill-token-mentions"
    update: str = "blocked: unknown provenance"
    uninstall: str = "trash"
    symlink: bool = False
    git_root: str | None = None


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    result: dict[str, str] = {}
    for line in parts[1].splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        if value and value not in {"|", ">"}:
            result[key] = value.strip().strip('"\'')
    return result


def walk_skill_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    seen: set[tuple[int, int]] = set()
    for current, dirs, files in os.walk(root, followlinks=True):
        try:
            stat = os.stat(current)
        except OSError:
            dirs[:] = []
            continue
        inode = (stat.st_dev, stat.st_ino)
        if inode in seen:
            dirs[:] = []
            continue
        seen.add(inode)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if "SKILL.md" in files:
            yield Path(current) / "SKILL.md"


def find_git_root(skill_dir: Path) -> Path | None:
    resolved = skill_dir.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def git_remote(git_root: Path) -> str | None:
    try:
        remote_result = subprocess.run(
            ["git", "-C", str(git_root), "remote", "get-url", "origin"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    remote = remote_result.stdout.strip() if remote_result.returncode == 0 else None
    return remote or None


def package_repository(skill_file: Path, boundary: Path) -> str | None:
    for parent in [skill_file.parent, *skill_file.parents]:
        if parent == boundary.parent:
            break
        package = parent / "package.json"
        if package.is_file():
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
                repo = data.get("repository")
                if isinstance(repo, dict):
                    repo = repo.get("url")
                if isinstance(repo, str):
                    return repo
            except (OSError, json.JSONDecodeError):
                pass
        if parent == boundary:
            break
    return None


def github_repo(url: str | None) -> str | None:
    if not url:
        return None
    for pattern in (r"github\.com[/:]([^/\s:]+/[^/#\s]+)", r"^github:([^/\s]+/[^/\s]+)$"):
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            repo = match.group(1).removesuffix(".git")
            return "/".join(repo.split("/")[:2])
    return None


def infer_category(name: str, description: str, declared: str | None) -> tuple[str, str]:
    if declared:
        return declared, "declared"
    haystack = f"{name} {description}".lower()
    for category, words in CATEGORY_RULES:
        if any(
            re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", haystack)
            if word.isascii()
            else word in haystack
            for word in words
        ):
            return category, "heuristic"
    return "其他", "heuristic"


def scope_for(path: Path, codex_skills: Path, agents_skills: Path, plugins: Path) -> str:
    absolute = path.absolute()
    try:
        relative = absolute.relative_to(codex_skills.absolute())
        return "system" if relative.parts and relative.parts[0] == ".system" else "user"
    except ValueError:
        pass
    try:
        absolute.relative_to(agents_skills.absolute())
        return "shared"
    except ValueError:
        pass
    try:
        absolute.relative_to(plugins.absolute())
        return "plugin-cache"
    except ValueError:
        return "other"


def load_star_cache(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def refresh_star(repo: str) -> tuple[int | None, str | None, str | None]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "codex-skill-manager/1",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
        return int(data["stargazers_count"]), dt.datetime.now(dt.timezone.utc).isoformat(), None
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429}:
            reset = exc.headers.get("x-ratelimit-reset") if exc.headers else None
            suffix = f"; reset={reset}" if reset else ""
            return None, None, f"GitHub API rate limit exceeded{suffix}"
        return None, None, f"GitHub API returned HTTP {exc.code}"
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        return None, None, str(exc)


def is_star_rate_limit(error: str | None) -> bool:
    if not error:
        return False
    normalized = error.lower()
    return "rate limit" in normalized or "http error 403" in normalized or "http error 429" in normalized


def scan_skills(args: argparse.Namespace) -> list[Skill]:
    codex_home = Path(args.codex_home).expanduser()
    agents_home = Path(args.agents_home).expanduser()
    codex_skills = codex_home / "skills"
    agents_skills = agents_home / "skills"
    plugins = codex_home / "plugins" / "cache"
    roots = [codex_skills, agents_skills]
    if not getattr(args, "no_plugins", False):
        roots.append(plugins)

    raw_cache_path = getattr(args, "star_cache", None)
    cache_path = Path(raw_cache_path).expanduser() if raw_cache_path else codex_home / "skill-manager" / "github-cache.json"
    cache = load_star_cache(cache_path)
    cache_changed = False
    skills: list[Skill] = []
    seen_paths: set[str] = set()
    remote_cache: dict[str, str | None] = {}
    refreshed_repos: dict[str, tuple[int | None, str | None, str | None]] = {}
    warned_repos: set[str] = set()
    star_refresh_blocked = False

    for root in roots:
        for skill_file in walk_skill_files(root):
            display_path = str(skill_file.parent.absolute())
            if display_path in seen_paths:
                continue
            seen_paths.add(display_path)
            meta = parse_frontmatter(skill_file)
            name = meta.get("name") or skill_file.parent.name
            description = meta.get("description", "")
            category, category_source = infer_category(name, description, meta.get("category"))
            scope = scope_for(skill_file, codex_skills, agents_skills, plugins)
            git_root = find_git_root(skill_file.parent)
            if git_root:
                root_key = str(git_root)
                if root_key not in remote_cache:
                    remote_cache[root_key] = git_remote(git_root)
                remote = remote_cache[root_key]
            else:
                remote = None
            source = meta.get("source") or remote or package_repository(skill_file, root)
            repo = github_repo(source)
            cached = cache.get(repo, {}) if repo else {}
            stars = cached.get("stars") if isinstance(cached.get("stars"), int) else None
            stars_updated = cached.get("updated_at") if isinstance(cached.get("updated_at"), str) else None
            refresh_all_stars = getattr(args, "refresh_stars", False)
            refresh_missing_stars = getattr(args, "refresh_missing_stars", False)
            if repo and not star_refresh_blocked and (refresh_all_stars or (refresh_missing_stars and stars is None)):
                if repo not in refreshed_repos:
                    refreshed_repos[repo] = refresh_star(repo)
                fetched_stars, fetched_at, error = refreshed_repos[repo]
                if error:
                    if is_star_rate_limit(error):
                        star_refresh_blocked = True
                        eprint("warning: GitHub Stars refresh paused: rate limit exceeded; cached values kept")
                    elif repo not in warned_repos:
                        eprint(f"warning: could not refresh {repo}: {error}")
                        warned_repos.add(repo)
                else:
                    stars, stars_updated = fetched_stars, fetched_at
                    cache[repo] = {"stars": stars, "updated_at": stars_updated}
                    cache_changed = True

            if scope == "system":
                update, uninstall = "provider: update Codex", "protected"
            elif scope == "plugin-cache":
                update, uninstall = "provider: plugin manager", "protected"
            elif git_root and remote:
                update = "git pull --ff-only (whole repository)"
                uninstall = "trash symlink" if skill_file.parent.is_symlink() else "trash"
            else:
                update = "blocked: unknown provenance"
                uninstall = "trash symlink" if skill_file.parent.is_symlink() else "trash"

            skills.append(Skill(
                name=name,
                description=description,
                path=display_path,
                scope=scope,
                category=category,
                category_source=category_source,
                source_url=source,
                github_repo=repo,
                stars=stars,
                stars_updated_at=stars_updated,
                update=update,
                uninstall=uninstall,
                symlink=skill_file.parent.is_symlink(),
                git_root=str(git_root) if git_root else None,
            ))

    if cache_changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    apply_usage(skills, Path(args.history_db).expanduser())
    return sorted(skills, key=lambda item: (item.name.lower(), item.scope, item.path))


def iter_message_text(item_json: str) -> Iterable[str]:
    try:
        data = json.loads(item_json)
    except json.JSONDecodeError:
        return
    for content in data.get("content", []):
        if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
            yield content["text"]


def apply_usage(skills: list[Skill], history_db: Path) -> None:
    if not history_db.is_file() or not skills:
        return
    now = dt.datetime.now(dt.timezone.utc)
    skills_by_name: dict[str, list[Skill]] = defaultdict(list)
    for skill in skills:
        skills_by_name[skill.name.lower()].append(skill)
    invocation_pattern = re.compile(r"(?<![\w-])\$([a-z0-9][a-z0-9-]*)(?![\w-])", re.IGNORECASE)
    try:
        with sqlite3.connect(f"file:{history_db}?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT created_at_ms, item_json FROM thread_items WHERE item_type = 'userMessage'")
            for created_at_ms, item_json in rows:
                text = "\n".join(iter_message_text(item_json))
                if not text:
                    continue
                used_at = dt.datetime.fromtimestamp(created_at_ms / 1000, tz=dt.timezone.utc)
                age = now - used_at
                invoked_names = {match.lower() for match in invocation_pattern.findall(text)}
                for invoked_name in invoked_names:
                    for skill in skills_by_name.get(invoked_name, []):
                        skill.usage_all += 1
                        if age <= dt.timedelta(days=90):
                            skill.usage_90d += 1
                        if age <= dt.timedelta(days=30):
                            skill.usage_30d += 1
                        stamp = used_at.isoformat()
                        if not skill.last_used or stamp > skill.last_used:
                            skill.last_used = stamp
    except (sqlite3.Error, OSError) as exc:
        eprint(f"warning: could not read usage history: {exc}")


def select_skill(skills: list[Skill], name: str, exact_path: str | None) -> Skill:
    if exact_path:
        target = str(Path(exact_path).expanduser().absolute())
        matches = [skill for skill in skills if skill.path == target]
    else:
        matches = [skill for skill in skills if skill.name.lower() == name.lower()]
    if not matches:
        raise ValueError(f"skill not found: {exact_path or name}")
    if len(matches) > 1:
        paths = "\n".join(f"- {skill.path}" for skill in matches)
        raise ValueError(f"ambiguous skill name; rerun with --path:\n{paths}")
    return matches[0]


def format_inventory(skills: list[Skill]) -> str:
    headers = ("Skill", "分类", "范围", "Stars", "显式使用 30/90/总", "最近显式使用", "更新")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for skill in skills:
        values = (
            skill.name,
            f"{skill.category} ({skill.category_source})",
            skill.scope,
            str(skill.stars) if skill.stars is not None else "unknown",
            f"{skill.usage_30d}/{skill.usage_90d}/{skill.usage_all}",
            skill.last_used[:10] if skill.last_used else "never observed",
            skill.update,
        )
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    return "\n".join(lines)


def run_git(args: argparse.Namespace, skill: Skill) -> int:
    if skill.scope in {"system", "plugin-cache"} or not skill.git_root or not skill.source_url:
        eprint(f"blocked: {skill.update}")
        return 2
    affected = [s.path for s in scan_skills(args) if s.git_root == skill.git_root]
    command = ["git", "-C", skill.git_root, "pull", "--ff-only"]
    plan = {
        "action": "update", "skill": skill.name, "path": skill.path,
        "git_root": skill.git_root, "source": skill.source_url,
        "affected_skills": affected, "command": command, "applied": False,
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if not args.yes:
        eprint("blocked: --apply also requires --yes")
        return 2
    status = subprocess.run(["git", "-C", skill.git_root, "status", "--porcelain"], capture_output=True, text=True, check=False)
    if status.returncode != 0 or status.stdout.strip():
        eprint("blocked: source repository is dirty or unreadable")
        return 2
    before = subprocess.run(["git", "-C", skill.git_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    after = subprocess.run(["git", "-C", skill.git_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    plan.update({"applied": result.returncode == 0, "before": before, "after": after, "output": result.stdout.strip()})
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if result.stderr:
        eprint(result.stderr.strip())
    return result.returncode


def trash_root(args: argparse.Namespace) -> Path:
    return Path(args.codex_home).expanduser() / "skill-trash"


def uninstall(args: argparse.Namespace, skill: Skill) -> int:
    if skill.scope in {"system", "plugin-cache"}:
        eprint(f"blocked: {skill.scope} skills are provider-managed")
        return 2
    source = Path(skill.path)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    trash_id = f"{stamp}-{skill.name}"
    destination = trash_root(args) / trash_id
    plan = {
        "action": "uninstall-to-trash", "skill": skill.name, "source": str(source),
        "trash_id": trash_id, "destination": str(destination), "recoverable": True, "applied": False,
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if not args.yes:
        eprint("blocked: --apply also requires --yes")
        return 2
    if destination.exists():
        eprint(f"blocked: trash destination exists: {destination}")
        return 2
    destination.mkdir(parents=True)
    metadata = {**plan, "original_path": str(source), "trashed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    (destination / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        shutil.move(str(source), str(destination / "payload"))
    except Exception as exc:
        shutil.rmtree(destination, ignore_errors=True)
        eprint(f"uninstall failed: {exc}")
        return 1
    plan["applied"] = True
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def restore(args: argparse.Namespace) -> int:
    entry = trash_root(args) / args.trash_id
    metadata_path, payload = entry / "metadata.json", entry / "payload"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        original = Path(metadata["original_path"])
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        eprint(f"invalid trash entry: {exc}")
        return 2
    plan = {"action": "restore", "trash_id": args.trash_id, "source": str(payload), "destination": str(original), "applied": False}
    if original.exists() or original.is_symlink():
        eprint(f"blocked: restore destination exists: {original}")
        return 2
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if not args.yes:
        eprint("blocked: --apply also requires --yes")
        return 2
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(payload), str(original))
    metadata["restored_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan["applied"] = True
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def install_skill(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        eprint("blocked: invalid GitHub repository")
        return 2
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", args.ref) or ".." in args.ref or args.ref.startswith("-"):
        eprint("blocked: invalid Git ref")
        return 2
    skill_path = PurePosixPath(args.skill_path)
    if skill_path.is_absolute() or ".." in skill_path.parts or (not skill_path.parts and args.skill_path != "."):
        eprint("blocked: invalid skill path")
        return 2
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.name):
        eprint("blocked: invalid skill name")
        return 2

    codex_home = Path(args.codex_home).expanduser()
    destination = codex_home / "skills" / args.name
    installer = codex_home / "skills" / ".system" / "skill-installer" / "scripts" / "install-skill-from-github.py"
    plan = {
        "action": "install-from-github",
        "skill": args.name,
        "repository": args.repo,
        "ref": args.ref,
        "skill_path": skill_path.as_posix(),
        "destination": str(destination),
        "applied": False,
    }
    if destination.exists() or destination.is_symlink():
        eprint(f"blocked: destination already exists: {destination}")
        return 2
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if not args.yes:
        eprint("blocked: --apply also requires --yes")
        return 2
    if not installer.is_file():
        eprint("blocked: Codex system skill-installer is unavailable")
        return 2

    result = subprocess.run(
        [
            sys.executable,
            str(installer),
            "--repo",
            args.repo,
            "--path",
            skill_path.as_posix(),
            "--ref",
            args.ref,
            "--dest",
            str(codex_home / "skills"),
            "--name",
            args.name,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        eprint(result.stderr.strip() or result.stdout.strip() or "skill installer failed")
        return result.returncode
    if not (destination / "SKILL.md").is_file():
        eprint("blocked: installer finished without a valid SKILL.md")
        return 2
    plan["applied"] = True
    plan["installer_output"] = result.stdout.strip()
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", default=str(home / ".codex"))
    parser.add_argument("--agents-home", default=str(home / ".agents"))
    parser.add_argument("--history-db", default=str(home / ".codex" / "thread_history_1.sqlite"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser("inventory", aliases=["list"], help="List installed skills")
    inventory_parser.add_argument("--json", action="store_true")
    inventory_parser.add_argument("--no-plugins", action="store_true")
    inventory_parser.add_argument("--refresh-stars", action="store_true")
    inventory_parser.add_argument("--refresh-missing-stars", action="store_true")
    inventory_parser.add_argument("--star-cache")

    for command in ("update", "uninstall"):
        action = subparsers.add_parser(command)
        action.add_argument("name")
        action.add_argument("--path")
        action.add_argument("--no-plugins", action="store_true")
        action.add_argument("--apply", action="store_true")
        action.add_argument("--yes", action="store_true")

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("trash_id")
    restore_parser.add_argument("--apply", action="store_true")
    restore_parser.add_argument("--yes", action="store_true")

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("name")
    install_parser.add_argument("--repo", required=True)
    install_parser.add_argument("--skill-path", required=True)
    install_parser.add_argument("--ref", default="main")
    install_parser.add_argument("--apply", action="store_true")
    install_parser.add_argument("--yes", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command in {"inventory", "list"}:
        skills = scan_skills(args)
        print(json.dumps([asdict(skill) for skill in skills], ensure_ascii=False, indent=2) if args.json else format_inventory(skills))
        return 0
    if args.command == "restore":
        return restore(args)
    if args.command == "install":
        return install_skill(args)
    try:
        skill = select_skill(scan_skills(args), args.name, args.path)
    except ValueError as exc:
        eprint(str(exc))
        return 2
    return run_git(args, skill) if args.command == "update" else uninstall(args, skill)


if __name__ == "__main__":
    raise SystemExit(main())
