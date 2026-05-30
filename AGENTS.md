# Agent Instructions

This file provides instructions for agents working in this repository.

## Code Formatting

Format Python files using `ruff`:

```bash
ruff format <file_or_directory>
```

Before committing changes, ensure all modified files are formatted with ruff.

## Testing

When running tests, use:

```bash
uv run pytest
```

After making changes, verify tests pass by running the above command. Use `-v` for verbose output or `-k <pattern>` to run specific tests.

## Documentation

### Sphinx-Style Docstrings

Use Sphinx-style docstrings for all functions. Include:
- A brief one-line summary
- A more detailed description (if needed)
- `:param` declarations for each parameter with type and description
- `:return` declaration with type and description
- `:raises` declarations for any exceptions (if applicable)

**Example:**

```python
def process_data(input_file, output_format):
    """
    Process input data and convert to the specified format.
    
    Reads data from the input file, validates it, and writes the result
    to stdout in the specified format.
    
    :param input_file: Path to the input file to process
    :type input_file: str
    :param output_format: Desired output format ('json', 'csv', or 'xml')
    :type output_format: str
    :return: Number of records processed
    :rtype: int
    :raises FileNotFoundError: If the input file does not exist
    :raises ValueError: If output_format is not recognized
    """
```

### Code Comments

Add short comments describing the purpose of code blocks that are logically separated from other code blocks. Use comments to clarify intent for distinct operations within a function.

**Example:**

```python
def analyze_data(data):
    # Looping over data
    results = []
    for item in data:
        results.append(process(item))
    
    # Post-processing and filtering
    filtered = [r for r in results if r.is_valid()]
    
    # Sorting by timestamp
    sorted_results = sorted(filtered, key=lambda x: x.timestamp)
    
    return sorted_results
```

Do not over-comment obvious operations. Comments should explain *why* a block exists and what it accomplishes, not restate the code.
