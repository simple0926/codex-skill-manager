# Codex Skill Manager

[简体中文](README.zh-CN.md) | English

A local, safety-first manager for installed Codex Skills. It provides a browser-based dashboard and a deterministic CLI for inventory, GitHub Stars, observed explicit usage, update checks, recoverable uninstall, and restore.

![Codex Skill Manager dashboard](design-reference-option-2.png)

## What it does

- Lists locally installed Skills that can be updated or safely uninstalled.
- Hides Codex system Skills and plugin-managed Skills from the actionable list.
- Shows inferred category, GitHub Stars, explicit `$skill-name` usage, source, and update strategy.
- Stops Stars refresh after GitHub rate limiting and preserves cached values.
- Previews every update, uninstall, and restore operation before applying it.
- Moves uninstalled Skills to a recoverable trash directory instead of permanently deleting them.

## Install

Ask Codex:

```text
Use $skill-installer to install this Skill:
https://github.com/simple0926/codex-skill-manager
```

Or clone it manually:

```bash
git clone https://github.com/simple0926/codex-skill-manager.git ~/.codex/skills/codex-skill-manager
```

Restart Codex after installation so the Skill is discovered.

## Open the local dashboard

```bash
python3 panel/server.py --open
```

The server binds to `127.0.0.1` by default. Keep it loopback-only: the dashboard can update and uninstall local Skills.

## Use the CLI

```bash
python3 scripts/skill_manager.py inventory
python3 scripts/skill_manager.py inventory --refresh-stars
python3 scripts/skill_manager.py update <skill-name>
python3 scripts/skill_manager.py uninstall <skill-name>
python3 scripts/skill_manager.py restore <trash-id>
```

Update, uninstall, and restore commands are previews unless both `--apply` and `--yes` are supplied. Run the preview first and verify the resolved path.

## GitHub API limits

Anonymous GitHub API requests have a small rate limit. Set `GITHUB_TOKEN` or `GH_TOKEN` in the environment that starts the dashboard to use your authenticated allowance. Never place a token in this repository or in browser-side code.

## Usage metric boundary

`usage_30d`, `usage_90d`, and `usage_all` count observed explicit `$skill-name` tokens in local Codex thread history. They do not measure implicit Skill invocation and should be treated as review signals, not proof that a Skill is unused.

## Development

```bash
python3 -m unittest discover -s tests -v
node --check panel/static/app.js
```

The project uses only the Python standard library at runtime.

## Security model

- The dashboard is loopback-only unless `--allow-non-loopback` is explicitly provided.
- Every mutation requires a fresh server-issued preview and the displayed confirmation phrase.
- System and plugin-managed Skills are protected.
- Dirty or ambiguous Git repositories are blocked instead of force-updated.
- Uninstall is recoverable.

## Release notes

See [Release Notes](RELEASE_NOTES.md). The first public release is `v1.0.0`.

