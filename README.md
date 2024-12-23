# LocalFlow: Local Workflow Executor

LocalFlow brings the power of GitHub Actions-like workflow automation to your local environment. It allows you to define workflows in YAML and execute them either locally or in Docker containers, making it perfect for development, testing, and local automation tasks.

## Key Features

LocalFlow combines the familiarity of GitHub Actions with the convenience of local execution:

- Write workflows in simple, GitHub Actions-inspired YAML syntax
- Run workflows locally or in isolated Docker containers
- Execute entire workflows or specific jobs
- Flexible output handling with file and console options
- Rich, colorful command-line interface with progress tracking
- Comprehensive logging system with debug capabilities
- Environment variable management at multiple levels
- Docker integration for isolated execution

## Quick Start

Getting started with LocalFlow is straightforward:

```bash
# Install LocalFlow
git clone https://github.com/yourusername/localflow.git
cd localflow
./install.py

# Create your first workflow
cat > ~/.localflow/workflows/hello.yml << EOL
name: Hello World
description: A simple example workflow
version: 1.0.0
author: Your Name

jobs:
  greet:
    steps:
      - name: Say Hello
        run: echo "Hello from LocalFlow!"
EOL

# Run the workflow
localflow run hello.yml
```

## Installation

LocalFlow requires Python 3.8 or higher and optionally Docker for container-based execution.

### Using the Installation Script

The recommended way to install LocalFlow is using the provided installation script:

```bash
./install.py
```

The script will:
1. Check prerequisites
2. Create necessary directories
3. Install Python dependencies
4. Configure your shell environment
5. Create an example workflow
6. Set up initial configuration

### Manual Installation

If you prefer manual installation:

```bash
# Create required directories
mkdir -p ~/.localflow/{workflows,logs}

# Install dependencies
pip install -r requirements.txt

# Create symbolic link
ln -s $(pwd)/localflow.py ~/.local/bin/localflow

# Copy and edit configuration
cp config.example.yml ~/.localflow/config.yml
```

## Configuration

LocalFlow can be configured through:
- Configuration file (`~/.localflow/config.yaml`)
- Environment variables
- Command-line options

Example configuration:
```yaml
workflows_dir: "~/.localflow/workflows"
log_dir: "~/.localflow/logs"
log_level: "INFO"
docker_enabled: false
docker_default_image: "ubuntu:latest"
show_output: true
default_shell: "/bin/bash"
```

## Basic Usage

LocalFlow provides several commands for managing and executing workflows:

```bash
# List available workflows
localflow list

# Show jobs in a workflow
localflow jobs workflow.yml

# Run entire workflow
localflow run workflow.yml

# Run specific job
localflow run workflow.yml --job job_name

# Run with Docker
localflow run workflow.yml --docker

# Show configuration
localflow config
```

See [USAGE.md](USAGE.md) for detailed usage instructions and advanced features.

## Directory Structure

After installation, LocalFlow creates the following structure:

```
~/.localflow/
├── config.yaml       # Configuration file
├── workflows/        # Workflow definitions
└── logs/            # Execution logs
```

## Contributing

We welcome contributions! Please see our contributing guidelines for details on:
- Code style and standards
- Testing requirements
- Pull request process
- Development setup

## Troubleshooting

If you encounter issues:

1. Enable debug mode: `localflow --debug ...`
2. Check logs in `~/.localflow/logs/`
3. Verify configuration: `localflow config`
4. See [USAGE.md](USAGE.md) for troubleshooting guide

## License

LocalFlow is released under the MIT License. See LICENSE file for details.
