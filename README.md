# LocalFlow: Local Workflow Executor

LocalFlow is a powerful, Unix-philosophy inspired workflow executor that brings GitHub Actions-like functionality to your local environment. It allows you to define workflows in YAML, execute them locally or in Docker containers, and manage them with a beautiful command-line interface.

![LocalFlow Banner](docs/banner.png)

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Creating Workflows](#creating-workflows)
- [Command Line Interface](#command-line-interface)
- [Docker Integration](#docker-integration)
- [Advanced Usage](#advanced-usage)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## Features

LocalFlow brings the power of workflow automation to your local environment with:

- **YAML-Based Workflows**: Define complex workflows using simple, human-readable YAML syntax
- **Local or Docker Execution**: Run steps locally or in isolated Docker containers
- **Rich Command-Line Interface**: Beautiful, informative output with progress indicators and color-coding
- **Comprehensive Logging**: Detailed logs with configurable verbosity and output formats
- **Flexible Configuration**: Easy configuration through YAML files and environment variables
- **Unix Philosophy**: Each component does one thing well, making the tool composable and maintainable

## Installation

### Prerequisites

- Python 3.8 or higher
- Docker (optional, for container-based execution)

### Basic Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/localflow.git
cd localflow

# Install dependencies
pip install -r requirements.txt

# Make the script executable
chmod +x localflow.py

# Create required directories
mkdir -p ~/.localflow/{workflows,logs}

# Copy default configuration
cp config.example.yml ~/.localflow/config.yml

# Add to your PATH (optional)
ln -s $(pwd)/localflow.py ~/.local/bin/localflow
```

## Quick Start

Let's create and run a simple workflow:

```bash
# Create a workflow file
cat > ~/.localflow/workflows/hello.yml << EOL
name: Hello World Workflow

jobs:
  greet:
    steps:
      - name: Say Hello
        run: echo "Hello, LocalFlow!"
      
      - name: Show Date
        run: date
EOL

# Run the workflow
localflow run ~/.localflow/workflows/hello.yml
```

## Configuration

LocalFlow can be configured through a YAML configuration file. By default, it looks for `~/.localflow/config.yml`, but you can specify a different location using the `LOCALFLOW_CONFIG` environment variable.

### Sample Configuration

```yaml
# Directory Settings
workflows_dir: "~/.localflow/workflows"
log_dir: "~/.localflow/logs"

# Logging Configuration
log_level: "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
show_output: true  # Whether to show command output in console

# Docker Configuration
docker_enabled: false
docker_default_image: "ubuntu:latest"

# Shell Configuration
default_shell: "/bin/bash"
```

### Environment Variables

- `LOCALFLOW_CONFIG`: Path to configuration file
- `LOCALFLOW_DEBUG`: Enable debug mode when set to "1"
- `LOCALFLOW_QUIET`: Suppress console output when set to "1"

## Creating Workflows

Workflows in LocalFlow are defined using YAML syntax. Here's a comprehensive guide to creating workflows:

### Basic Structure

```yaml
name: My Workflow

env:
  GLOBAL_VAR: "value"

jobs:
  job_id:
    name: Job Name
    env:
      JOB_VAR: "value"
    steps:
      - name: Step Name
        run: command
        env:
          STEP_VAR: "value"
```

### Step Properties

Each step can have the following properties:

- `name`: Human-readable step name
- `run`: Command to execute
- `working-directory`: Directory where the command runs
- `env`: Environment variables for this step
- `if`: Condition for step execution
- `local`: Force local execution even when Docker is enabled

### Example: Complex Workflow

```yaml
name: Build and Test Python Project

env:
  PYTHONPATH: "src"

jobs:
  setup:
    name: Setup Environment
    steps:
      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
        working-directory: ./src
        
      - name: Create Configuration
        run: cp config.example.json config.json
        env:
          ENV: development

  test:
    name: Run Tests
    needs: [setup]
    steps:
      - name: Unit Tests
        run: python -m pytest tests/
        working-directory: ./src
        env:
          TEST_MODE: true

      - name: Integration Tests
        run: python -m pytest integration_tests/
        if: success()
        env:
          TEST_ENV: integration

  build:
    name: Build Package
    needs: [test]
    steps:
      - name: Build Distribution
        run: python setup.py sdist bdist_wheel
        local: true  # Force local execution
```

### Multi-line Commands

For complex commands, use YAML's block scalar syntax:

```yaml
steps:
  - name: Complex Script
    run: |
      echo "Starting script..."
      if [ -d "build" ]; then
        rm -rf build
      fi
      mkdir build
      cd build
      cmake ..
      make
```

### Environment Variables

Environment variables cascade from workflow to job to step level:

1. Global variables (workflow level)
2. Job variables (override global)
3. Step variables (override job and global)

### Conditional Execution

Use the `if` property for conditional execution:

```yaml
steps:
  - name: Build
    run: make build
    if: success()  # Only run if previous steps succeeded

  - name: Deploy
    run: make deploy
    if: env.DEPLOY == 'true'  # Check environment variable
```

## Command Line Interface

LocalFlow provides a rich command-line interface with several commands:

### Run Command

Run a workflow:

```bash
# Basic usage
localflow run workflow.yml

# Enable Docker execution
localflow run --docker workflow.yml

# Debug mode
localflow run --debug workflow.yml

# Quiet mode (logs only)
localflow run --quiet workflow.yml
```

### List Command

List available workflows:

```bash
localflow list
```

### Config Command

Show current configuration:

```bash
localflow config
```

### Global Options

All commands support these options:

- `--config, -c`: Specify configuration file
- `--debug/--no-debug`: Enable/disable debug mode
- `--quiet/--no-quiet`: Enable/disable quiet mode

## Docker Integration

LocalFlow can execute workflow steps in Docker containers for isolated, reproducible environments.

### Enabling Docker

Enable Docker execution in three ways:

1. Configuration file:
```yaml
docker_enabled: true
docker_default_image: "ubuntu:latest"
```

2. Command line:
```bash
localflow run --docker workflow.yml
```

3. Per step:
```yaml
steps:
  - name: Docker Step
    run: echo "Running in Docker"
    docker: true
```

### Docker Features

- **Volume Mounting**: Working directory is automatically mounted
- **Environment Variables**: All environment variables are passed to the container
- **Image Selection**: Use default image or specify per step
- **Network Access**: Containers have network access by default

## Advanced Usage

### Logging

LocalFlow provides comprehensive logging:

1. File Logging: All output is logged to `~/.localflow/logs/`
2. Console Output: Rich, formatted output (unless quiet mode is enabled)
3. Debug Information: Available with `--debug` flag

### Error Handling

LocalFlow handles errors gracefully:

1. Step Failures: Logged with error messages and exit codes
2. Workflow Failures: Complete error report with stack traces in debug mode
3. Recovery: Failed workflows can be rerun from specific steps

## Troubleshooting

Common issues and solutions:

### Permission Errors

```bash
# Fix directory permissions
chmod -R u+rw ~/.localflow

# Fix Docker permissions
sudo usermod -aG docker $USER
```

### Docker Issues

```bash
# Check Docker service
systemctl status docker

# Test Docker access
docker run hello-world
```

### Logging Issues

```bash
# Clear log directory
rm -rf ~/.localflow/logs/*

# Check log directory permissions
ls -la ~/.localflow/logs
```

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details on:

- Code Style
- Testing Requirements
- Pull Request Process
- Development Setup

## License

LocalFlow is released under the MIT License. See the [LICENSE](LICENSE) file for details.
