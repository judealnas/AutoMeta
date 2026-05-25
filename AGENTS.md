# Agent Instructions

This file provides instructions for agents working in this repository.

## Code Formatting

Format Python files using `ruff`:

```bash
ruff format <file_or_directory>
```

Before committing changes, ensure all modified files are formatted with ruff.

## Testing

Run the test suite using:

```bash
uv run pytest
```

After making changes, verify tests pass by running the above command. Use `-v` for verbose output or `-k <pattern>` to run specific tests.
