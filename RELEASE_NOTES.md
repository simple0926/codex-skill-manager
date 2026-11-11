# Codex Skill Manager v1.0.0

Initial public release of the local Codex Skills management dashboard and CLI.

## Highlights

- Inventory of user-managed Codex Skills with category, source, update strategy, GitHub Stars, and observed explicit usage.
- Focused dashboard that excludes protected system and plugin-managed Skills from destructive actions.
- Git-linked fast-forward updates with dirty-repository and ambiguous-target protection.
- Recoverable uninstall and restore workflow.
- Short-lived mutation previews and explicit confirmation phrases.
- Stars caching, repository-level request deduplication, authenticated token support, and graceful GitHub rate-limit handling.
- Loopback-only local service by default.

## Verification

- 16 automated tests covering the CLI, dashboard API, authorization token, mutation confirmation, system protection, Stars limiting, update, uninstall, and restore.
- JavaScript syntax validation for the dashboard client.
- Skill structure validated with the Codex `skill-creator` validator.

## Known limitations

- Explicit usage metrics do not include implicit Skill invocation.
- Stars and update availability depend on resolvable repository provenance.
- Plugin-managed Skills must be updated through their plugin manager; Codex system Skills must be updated with Codex itself.

## Upgrade

If installed from Git, update the repository with a fast-forward pull. Restart Codex after upgrading.

