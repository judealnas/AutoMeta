# AutoMeta product specification

## User-authored watcher rules

### Goal

A user can maintain a complex set of watch rules in an editable YAML file and apply it in one command, without editing the CLI-managed watch store.

### Scope

- `autometa watch apply <file>` applies a versioned YAML document containing named watch rules. Each rule supplies a root (or inherits a shared file-level root), include/exclude patterns, numeric priority, and desired metadata. Relative roots resolve against the file's directory.
- Reapplying the file replaces that file's prior rules as a set: matching names keep their identifiers, changed definitions update, and omitted names are removed. An empty rules list removes only this file's rules.
- Rules added by CLI or applied from another file remain unchanged. The existing `watch add`, `update`, `remove`, `list`, and service commands continue to work.
- A running watcher picks up successful applies through its existing store reload. Applying does not start or stop the service.
- The user-authored format is distinct from both the CLI-managed store and the one-off metadata `--rulefile` format.
- The authoring file is a single version-1 YAML mapping with a required `rules` list, an optional shared root, and entries named uniquely within that file. Each entry needs nonempty metadata and a rule-level root unless it inherits the shared root. Include/exclude lists and numeric priority are optional, with defaults `["*"]`, `[]`, and `0`.
- A rule-level root replaces, not extends, the file-level default. Either relative root is resolved independently from the authoring file's directory. Patterns match paths relative to each rule's effective root. Overlapping rules merge disjoint tags; for shared tags the higher priority wins, then the deeper root. Equal-priority, equal-depth conflicting values skip that audio file.

### Constraints and non-goals

- Invalid files (including duplicate names, unknown fields, malformed rules, or nonexistent roots) fail without changing stored rules. A nonexistent source file must not delete rules previously applied from it.
- The file is not continuously watched; edits take effect only after an explicit apply.
- No automatic import of existing CLI rules or direct manual editing of the internal store.

### Acceptance criteria

- [x] A file with multiple overlapping, prioritized rules can be applied, and the persisted rules match its definitions.
- [x] Reapplying changed content keeps stable IDs for retained names, deletes omitted file-owned rules, and leaves CLI/other-file rules intact.
- [x] A valid empty rules list removes only that file's rules.
- [x] Invalid or missing input exits nonzero with a useful error and leaves the store unchanged.
- [x] The watcher detects a successful change and reconciles against the new rules without a service restart.
