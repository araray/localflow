# LocalFlow Usage Guide

This document provides comprehensive guidance on using LocalFlow, including workflow creation, execution, and advanced features.

## Table of Contents

- [Workflow Structure](#workflow-structure)
- [Creating Workflows](#creating-workflows)
- [Running Workflows](#running-workflows)
- [Output Handling](#output-handling)
- [Docker Integration](#docker-integration)
- [Advanced Features](#advanced-features)
- [Troubleshooting](#troubleshooting)

## Workflow Structure

LocalFlow workflows are defined in YAML and follow a structure similar to GitHub Actions:

```yaml
name: Workflow Name
description: "Workflow description"
version: "1.0.0"
author: "Your Name"

# Optional global environment variables
env:
  GLOBAL_VAR: "value"

# Optional output configuration
output:
  file: "~/outputs/workflow.log"
  mode: "both"  # stdout, file, or both
  stdout: true
  append: false

jobs:
  job_name:
    description: "Job description"
    # Optional job-level environment
    env:
      JOB_VAR: "value"
    
    # Optional dependencies
    needs:
      - other_job
    
    steps:
      - name: "Step Name"
        run: echo "Command to execute"
        working-directory: "/optional/path"
        env:
          STEP_VAR: "value"
```

## Creating Workflows

### Basic Workflow Example

Start with a simple workflow:

```yaml
name: Basic Example
description: "Simple workflow demonstration"
version: "1.0.0"
author: "Your Name"

jobs:
  hello:
    steps:
      - name: "Greeting"
        run: echo "Hello, LocalFlow!"
      
      - name: "Current Time"
        run: date
```

### Multi-Job Workflow

Create workflows with multiple jobs and dependencies:

```yaml
name: Build and Test
description: "Build and test a Python project"
version: "1.0.0"

jobs:
  setup:
    steps:
      - name: "Install Dependencies"
        run: pip install -r requirements.txt
  
  test:
    needs: [setup]
    steps:
      - name: "Run Tests"
        run: python -m pytest tests/
        env:
          PYTHONPATH: .
  
  build:
    needs: [test]
    steps:
      - name: "Build Package"
        run: python setup.py build
```

### Docker-Based Workflow

Run steps in Docker containers:

```yaml
name: Docker Example
description: "Docker-based workflow"
version: "1.0.0"

jobs:
  docker_job:
    steps:
      - name: "Container Task"
        run: |
          echo "Running in container"
          python --version
        working-directory: /app
```

## Running Workflows

LocalFlow offers several ways to run workflows:

### Basic Execution

```bash
# Run entire workflow
localflow run workflow.yml

# Run specific job
localflow run workflow.yml --job job_name
```

### Output Control

```bash
# Save output to file
localflow run workflow.yml --output results.log

# Output to both file and console
localflow run workflow.yml --output results.log --output-mode both

# Append to existing log
localflow run workflow.yml --output results.log --append
```

### Docker Execution

```bash
# Enable Docker for all steps
localflow run workflow.yml --docker

# Use Docker selectively in workflow file
jobs:
  mixed:
    steps:
      - name: "Docker Step"
        run: echo "In Docker"
      
      - name: "Local Step"
        run: echo "Local execution"
        local: true
```

## Output Handling

LocalFlow provides flexible output handling options:

### Configuration Levels

1. Global (in config.yaml):
```yaml
output:
  file: "~/.localflow/default-output.log"
  mode: "stdout"
  stdout: true
```

2. Workflow-level:
```yaml
output:
  file: "~/outputs/workflow.log"
  mode: "both"
  stdout: true
```

3. Command-line:
```bash
localflow run workflow.yml \
  --output ~/outputs/result.log \
  --output-mode both
```

### Output Modes

- `stdout`: Display output only in console
- `file`: Write output only to file
- `both`: Output to both console and file

## Advanced Features

### Environment Variables

Variables can be defined at multiple levels:

```yaml
# Workflow-level
env:
  GLOBAL_VAR: "value"

jobs:
  example:
    # Job-level
    env:
      JOB_VAR: "value"
    steps:
      - name: "Step"
        # Step-level
        env:
          STEP_VAR: "value"
```

### Job Dependencies

Control job execution order:

```yaml
jobs:
  first:
    steps:
      - run: echo "First job"
  
  second:
    needs: [first]
    steps:
      - run: echo "Second job"
```

### Complex Commands

Use multi-line commands:

```yaml
steps:
  - name: "Complex Task"
    run: |
      cd /tmp
      for i in {1..3}; do
        echo "Step $i"
        date
        sleep 1
      done
```

## Troubleshooting

### Common Issues

1. Workflow Not Found
```bash
# Ensure correct workflow directory
localflow config

# List available workflows
localflow list

# Check full path resolution
localflow --debug run workflow.yml
```

2. Docker Issues
```bash
# Verify Docker is running
docker ps

# Enable debug logging
localflow --debug run workflow.yml --docker
```

3. Output Problems
```bash
# Check log directory
ls -l ~/.localflow/logs/

# Enable debug mode
localflow --debug run workflow.yml

# Verify output configuration
localflow config
```

### Debug Mode

Enable detailed logging:

```bash
localflow --debug run workflow.yml
```

### Checking Logs

Access detailed execution logs:

```bash
# List log files
ls -l ~/.localflow/logs/

# View specific log
cat ~/.localflow/logs/workflow_20240422_123456.log
```

### Configuration Issues

If you suspect configuration problems:

1. Check configuration source:
```bash
echo $LOCALFLOW_CONFIG
localflow config
```

2. Verify directory permissions:
```bash
ls -la ~/.localflow/
```

3. Validate workflow syntax:
```bash
localflow --debug run workflow.yml
```

Remember that LocalFlow creates detailed logs for each workflow execution. These logs can be invaluable for troubleshooting and understanding workflow behavior.
