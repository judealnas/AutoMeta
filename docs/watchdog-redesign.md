# Watchdog Feature Redesign

I would redesign the watchdog feature as an idempotent reconciliation service,
not as a collection of detached per-watch processes.

## User-facing model

The root directory and matching rules should be separate:

```bash
autometa watch add /music \
  --include "*.mp3" \
  --include "*.flac" \
  --recursive \
  --artist "Alice,Bob" \
  --year 2024

autometa watch list
autometa watch update <id> --year 2025
# A scoped override wins per tag over a broad default.
autometa watch update <id> --priority 100
autometa watch remove <id>
autometa watch run
```

`autometa watch run` would run in the foreground. For persistent background
operation, systemd, launchd, or Windows Service Manager should supervise it.
That avoids reimplementing daemonization, PID management, logging, restart
policies, and platform-specific termination.

A later convenience command could install the appropriate service definition,
but service management would remain outside the watcher core.

## Architecture

```text
Filesystem observer
        |
        v
Tiny event adapter ----> keyed debounce queue
                              |
                              v
                       stability check
                              |
                              v
                       bounded worker pool
                              |
                              v
                    read -> compare -> update
                              |
                              v
                    success / retry / error
```

### 1. One supervised process

A single process would manage every configured rule.

Advantages:

- No per-rule PID or lock files.
- No duplicate-start takeover race.
- One lifecycle and shutdown path.
- Configuration can be reconciled centrally.
- Observer health represents actual service health.

A singleton lock would prevent two service instances. It would be acquired
non-blockingly; a second invocation would immediately exit with a useful error.

### 2. Event handlers only enqueue

Watchdog callbacks should never parse or modify media. They should normalize
the event and enqueue a path in milliseconds.

The pipeline would recognize:

- Created files
- Modified files
- Files moved into the tree, using `dest_path`
- Closed-write events where supported
- Files found during the initial reconciliation scan

Queue entries would be keyed by canonical path, so a burst of 30 events for one
file becomes one job.

### 3. Wait for file stability

Before opening a file, wait until its size and modification time remain
unchanged for a configurable settling period, such as 500 ms.

Transient failures--a file still being copied, temporarily locked, or having
incomplete headers--would be retried with bounded exponential backoff.
Permanent failures would be logged without killing the observer.

Each path would be processed serially, while unrelated paths could use a small
worker pool.

### 4. Treat watching as reconciliation

Every operation would be idempotent:

1. Read current tags.
2. Normalize both current and desired values.
3. Compute the changes.
4. Save only when something differs.

On startup, the service would scan matching existing files by default. This
repairs events missed while the service was stopped and means the filesystem,
rather than an event stream, is the source of truth.

The event stream merely prompts reconciliation sooner.

### 5. Explicit pattern semantics

The watch root should not be inferred from a glob. Configuration would store
these separately:

```yaml
id: 8b5e...
root: /music
recursive: true
priority: 0
include:
  - "*.mp3"
  - "*.flac"
exclude:
  - ".*"
  - "*.part"
metadata:
  artist:
    - Alice
    - Bob
  year: "2024"
```

`*.mp3` would mean "matching filename at any watched depth when recursive is
enabled." Relative-path matching could be offered separately if needed. This
avoids exposing watchdog's surprising absolute-pattern behavior.

Configuration validation would reject:

- Missing or non-directory roots
- Empty metadata
- Unknown tags
- Unsupported pattern syntax
- Duplicate rule IDs

### 6. Rule overlap and precedence

Rules may overlap. For a matching file, the service first computes one effective
metadata mapping and then reconciles it once. Values for different tags merge.
For the same tag, the highest numeric `priority` wins (default `0`); at equal
priority, the rule with the deeper root wins.

Rules assigning the same value at equal precedence are compatible. Rules
assigning different values at equal priority and root depth are reported with
their rule IDs, and the file is skipped without a write. This prevents
self-generated filesystem events from making rules overwrite each other
indefinitely.

### 7. Declarative, atomic configuration

YAML can remain the configuration format, but writes should be safe:

- Write to a temporary file in the same directory.
- Flush and `fsync` it.
- Atomically replace the old file.
- Protect read-modify-write CLI operations with a configuration lock.
- Use UUIDs instead of incrementing integers.

Runtime status would remain outside the configuration. The running service
could reload configuration when the file changes, applying a diff to add,
remove, or replace schedules.

SQLite would be reasonable if editing, audit history, or many concurrent
clients became requirements, but it is unnecessary for the initial design.

### 8. Health and failure behavior

The service should exit nonzero if its observer dies. An external service
manager can then restart it.

"Healthy" would mean:

- Singleton ownership acquired
- Configuration loaded
- All roots scheduled
- Observer thread alive
- Worker queue operating

Per-file failures would not make the entire service unhealthy, but would be
logged with the path, rule ID, attempt count, and exception.

Logs would go to stderr in foreground mode so the service manager captures
them. Nothing important would be redirected to `/dev/null`.

### 9. Predictable shutdown

On SIGINT or SIGTERM:

1. Stop accepting filesystem events.
2. Stop and join the observer.
3. Drain already-running jobs within a timeout.
4. Cancel remaining queued work.
5. Exit with an accurate status.

Signal handlers would only set a shutdown event; cleanup would happen in
normal control flow.

## Suggested internal boundaries

The implementation should be divided into independently testable pieces:

- `WatchRule`: validated configuration model.
- `RuleStore`: atomic YAML persistence.
- `PathMatcher`: documented matching semantics.
- `EventNormalizer`: maps create, modify, and move events to candidate paths.
- `DebounceQueue`: coalesces repeated path events.
- `FileStabilityProbe`: detects completed writes.
- `MetadataReconciler`: pure read, compare, and update behavior.
- `WatchService`: observer and worker lifecycle.
- CLI: configuration and foreground service commands only.

The metadata reconciler should not know about watchdog, and the watchdog
handler should not know about Mutagen.

## Test strategy

The important tests should be behavioral rather than primarily lock-oriented:

- A partial file becomes valid after several retries.
- A permanently malformed file does not kill the service.
- An atomic rename into the directory is processed.
- Nested files match recursive `*.mp3`.
- Event storms produce one effective update.
- Self-generated modification events converge without looping.
- Missed files are repaired by the startup scan.
- One bad rule does not stop other rules.
- A second service instance exits immediately.
- Observer death makes the process exit nonzero.
- Configuration writes are atomic under concurrent CLI calls.
- SIGTERM cleanly stops observers and workers.

## Guiding principle

Filesystem events are unreliable hints, reconciliation is the actual feature,
and process existence is not equivalent to health.
