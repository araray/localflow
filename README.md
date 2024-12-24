# LocalFlow

LocalFlow is a powerful local workflow executor inspired by GitHub Actions. It allows you to define and run workflows locally or in Docker containers, with support for complex job dependencies, conditions, and environment management.

## Features

LocalFlow provides a robust set of features for workflow management:

- YAML-based workflow definitions similar to GitHub Actions
- Support for both local project-specific and global workflows
- Unique, persistent IDs for workflows and jobs
- Complex job dependencies and conditional execution
- Local and Docker-based execution environments
- Rich console output with progress tracking
- Flexible output handling (console, file, or both)
- Job and workflow tagging system
- Environment variable management at multiple levels

## Installation

Install LocalFlow using pip:

```bash
pip install -r requirements.txt
python install-script.py
```

This will install LocalFlow and its dependencies. The installation script will also create necessary configuration directories.

## Quick Start

1. Create a workflow file in your project's `.localflow` directory:

```yaml
id: wf_example
name: Example Workflow
description: A simple example workflow
version: 1.0.0
author: Your Name
tags: [example]

jobs:
  setup:
    id: job_setup
    description: Setup environment
    tags: [setup]
    steps:
      - name: Setup
        run: echo "Setting up environment"

  test:
    id: job_test
    description: Run tests
    tags: [test]
    condition:
      if: job_setup
    steps:
      - name: Test
        run: echo "Running tests"
```

2. Run your workflow:

```bash
# List available workflows
localflow list

# View workflow jobs
localflow jobs wf_example

# Run entire workflow
localflow run wf_example

# Run specific job
localflow run wf_example --job job_test
```

## Project Structure

```
localflow/
├── install-script.py      # Installation script
├── LICENSE               # MIT License
├── localflow            # Command-line entry point
├── localflow.py         # Main implementation
├── schema.py            # Schema definitions
├── README.md            # This file
├── requirements.txt     # Dependencies
└── USAGE.md            # Detailed usage guide
```

## Configuration

LocalFlow can be configured through:

1. Global configuration file (~/.localflow/config.yaml)
2. Environment variables
3. Command-line options

The configuration supports:

- Workflow directory locations
- Docker settings
- Output handling preferences
- Logging settings

## Workflow Organization

LocalFlow supports two locations for workflows:

1. Project-specific: `.localflow` directory in your project
2. Global: `~/.localflow/workflows` directory

Project-specific workflows take precedence over global ones with the same name.

## Contributing

Contributions are welcome! Just submit a pull request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

LocalFlow is inspired by GitHub Actions and aims to provide similar functionality for local development environments.