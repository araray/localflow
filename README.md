# LocalFlow

A local workflow execution engine with event-based triggers and daemon support.

## Project Structure

```
localflow/
├── cli/                 # Command Line Interface
│   ├── commands/       # CLI command modules
│   └── main.py        # CLI entry point
├── core/               # Core functionality
│   ├── config.py      # Configuration management
│   ├── executor.py    # Workflow execution
│   ├── schema.py      # Data models
│   └── utils.py       # Utility functions
├── services/           # Service modules
│   ├── daemon/        # Daemon management
│   ├── events/        # Event handling
│   └── workflow/      # Workflow management
└── tests/             # Test suite
    ├── unit/          # Unit tests
    └── functional/    # Functional tests
```

## Installation

```bash
# From source
git clone https://github.com/araray/localflow.git
cd localflow
pip install -e .

# Or via pip
pip install localflow
```

## Usage

1. Basic workflow execution:
```bash
localflow run <workflow-id>
```

2. Running specific jobs:
```bash
localflow run <workflow-id> --job <job-id>
```

3. List available workflows:
```bash
localflow list
```

4. Manage daemon:
```bash
localflow daemon start
localflow daemon status
localflow daemon stop
```

5. Manage events:
```bash
localflow events list
localflow events enable <event-id>
localflow events disable <event-id>
```

See [USAGE.md](USAGE.md) for detailed documentation.

## Development

1. Setup development environment:
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install development dependencies
pip install -e ".[dev]"
```

2. Run tests:
```bash
pytest
```

3. Run linting:
```bash
flake8 localflow
```

## License

MIT - see [LICENSE](LICENSE) for details.