# AutoMeta design specification

## Watch rule file application

### Context

`autometa watch` uses one YAML `RuleStore`, changed atomically under an advisory lock. The watch service checks for a changed store signature and reloads and rescans without restart. The existing `Config` rulefile is used only by one-off metadata commands.

### Design

- A separate version-1 user YAML format contains `rules`, optionally a shared `root`; every entry has a unique, nonempty string `name`, an effective root, optional include/exclude lists and integer priority, and nonempty known-tag `metadata`. Reject unknown fields and invalid types instead of silently ignoring typos. Resolve relative roots against the source file's parent; preserve absolute and `~` paths.
- Parse one YAML document only. Top-level keys are exactly `version` (integer 1), `root` (optional directory path), and `rules` (required list, possibly empty). Rule keys are exactly `name`, `root`, `include`, `exclude`, `priority`, and `metadata`: a nonempty unpadded string name, a root required only if no shared root exists, optional lists of root-relative forward-slash patterns, an optional integer priority, and a required nonempty mapping of known tags to string/integer/nonempty-string-list values. Defaults are `["*"]`, `[]`, and `0`; empty includes disable matching. Reject duplicate YAML keys and duplicate rule names. WatchRule validates existing roots and patterns that cannot escape them.
- File-level `root` is a fallback, **not a prefix**. A rule-level root overrides it entirely; both are interpreted from the source file's parent independently. Include and exclude patterns are interpreted relative to that rule's effective root. Priority takes precedence over root depth for individual tags, with equal precedence and incompatible values resulting in a per-file reconciliation conflict.
- Parse and validate the *complete* source before changing the store. Each applied rule has a deterministic UUID derived from the canonical source path and rule name. Store the canonical source path as an optional provenance field on `WatchRule`; CLI-created and legacy rules have no provenance. Store version 4 adds optional provenance and continues reading v2 and v3 stores.
- Apply under the existing store RMW lock in one atomic write. Preserve rules with other provenance (including CLI rules), reject any ID collision with them, replace all rules owned by this file in source order, and skip the write if nothing changed. Changes made concurrently by other CLI commands must not be lost.
- `watch update` retains provenance on edited rules; a later apply resets such edits to the source definition. `watch remove` can remove any rule; a later apply recreates a removed file-owned rule with the same ID. Source path identity is canonical: moving a source file makes it a distinct owner; the old source must be applied as an empty document or its rules removed by CLI before moving it.
- On a successful write the existing service signature check reloads and rescans. There is no live source-file watcher or service lifecycle change.

### Decisions and tradeoffs

- Explicit apply instead of live file reload: errors never affect the running service until the user intentionally applies a validated source.
- File-scoped replacement instead of whole-store replacement: manually added rules and other source files are safe.
- Stable names instead of content-based IDs: edits retain rule IDs (important for logs and `watch update`).

### Verification and rollback

Test end-to-end CLI apply/reapply with overlapping priorities, independent owners and CLI rules; validate malformed inputs leave byte-identical stores; exercise concurrent CLI changes; check the service's existing store reload tests. Run `uv run pytest`. Rollback by removing file-owned rules with `watch remove` or by applying an empty `rules` list for that file; v4 stores are not readable by older versions without a backup or conversion, so retain a store backup before downgrading.
