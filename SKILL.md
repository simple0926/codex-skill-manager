---
name: codex-skill-manager
description: Inventory and manage locally installed Codex skills. Use when the user wants to list or classify skills, inspect GitHub stars or local usage frequency, check updateability, update a skill, or safely uninstall and restore one. Do not use for creating or editing a skill's contents.
---

# Codex Skill Manager

Use `scripts/skill_manager.py` as the deterministic source of inventory and usage data. Keep inspection read-only unless the user explicitly asks to update, uninstall, or restore.

## Local management panel

For a visual dashboard, launch the loopback-only panel:

```bash
python3 panel/server.py --open
```

The panel reuses `scripts/skill_manager.py` and shows only skills that support at least one panel action: update or recoverable uninstall. Provider-managed system and plugin-cache skills stay out of the action list. The panel provides search, category filters, Stars refresh, explicit-usage metrics, update previews, recoverable uninstall, and trash restore. Keep the server bound to `127.0.0.1`; non-loopback binding exposes local management operations and requires the explicit `--allow-non-loopback` flag.

Every mutation in the panel requires a fresh server-issued preview, a short-lived preview ID, and the displayed confirmation phrase. Do not remove or bypass these controls.

Discovery and third-party installation are intentionally outside the local panel. Use a public discovery site or the protected system `skill-installer` for GitHub installation. The local panel must not fetch or execute third-party `SKILL.md` content.

## Inventory and audit

Run:

```bash
python3 scripts/skill_manager.py inventory
```

The scanner covers user, system, shared, and plugin-cache skill locations. Report these dimensions separately:

- `category` is declared metadata when present, otherwise a heuristic inference.
- `stars` is the GitHub repository star count. Show `unknown` when provenance cannot be resolved or the value has not been refreshed; never infer popularity from local usage.
- `usage_30d`, `usage_90d`, and `usage_all` count observed explicit `$skill-name` tokens in the local Codex thread-history database. They are a usage-frequency proxy, do not measure implicit invocation, and must be labeled accordingly.
- `scope` distinguishes user-managed skills from protected system and plugin-managed skills.
- `update` describes the available update strategy; `blocked` is a real result, not an error to work around.

Use `--refresh-stars` only when current GitHub data is requested and network access is authorized. The script caches successful lookups. Use `--json` when subsequent filtering or analysis is needed.

When identifying cleanup candidates, treat low explicit usage only as a review signal. Consider recency, duplicated capability, scope, source, and whether the skill may be invoked implicitly before recommending action.

## Update

First preview the exact target:

```bash
python3 scripts/skill_manager.py update <name>
```

Proceed only after the user confirms the resolved path and affected repository:

```bash
python3 scripts/skill_manager.py update <name> --apply --yes
```

Git-linked skills update their whole source repository with a fast-forward-only pull. The script blocks dirty repositories, ambiguous names, system skills, plugin-cache skills, and skills with unknown provenance. Do not bypass these blocks. For plugin-managed skills, use the plugin manager; for system skills, update Codex itself.

## Uninstall and restore

Preview before changing anything:

```bash
python3 scripts/skill_manager.py uninstall <name>
```

After explicit confirmation, use `--apply --yes`. Uninstall moves the skill or symlink into the Codex skill trash; it does not permanently delete it. System and plugin-cache skills are protected. If multiple installed skills share a name, pass the exact path with `--path`.

Restore a trashed entry by previewing and then applying:

```bash
python3 scripts/skill_manager.py restore <trash-id>
python3 scripts/skill_manager.py restore <trash-id> --apply --yes
```

After any mutation, rerun `inventory` and verify the target state. Report what changed, what repository or path was affected, and how to restore when applicable.

## Paths and portability

The script defaults to `~/.codex`, `~/.agents`, and the current Codex thread-history database. For tests or nonstandard installations, pass `--codex-home`, `--agents-home`, and `--history-db` before the subcommand.
