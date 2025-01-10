# LocalFlow Usage Guide

This document provides comprehensive guidance on using LocalFlow, including workflow creation, execution, and advanced features.

## Table of Contents

- [Workflow Structure](#workflow-structure)
- [Creating Workflows](#creating-workflows)
- [Running Workflows](#running-workflows)
- [Job Management](#job-management)
- [Conditions and Dependencies](#conditions-and-dependencies)
- [Output Handling](#output-handling)
- [Docker Integration](#docker-integration)
- [Advanced Features](#advanced-features)
- [Troubleshooting](#troubleshooting)

## Workflow Structure

LocalFlow workflows are defined in YAML with unique identifiers for both workflows and jobs:

```yaml
id: wf_example         # Unique workflow ID
name: Example Workflow
description: "Workflow description"
version: "1.0.0"
author: "Your Name"
tags: [tag1, tag2]    # Optional workflow tags

# Optional global environment variables
env:
  GLOBAL_VAR: "value"

jobs:
  setup:
    id: job_setup     # Unique job ID
    description: "Setup job"
    tags: [setup]     # Optional job tags
    steps:
      - name: "Setup"
        run: echo "Setting up"

  build:
    id: job_build
    description: "Build job"
    tags: [build]
    condition:        # Optional condition
      if: "job_setup"
    needs: [job_setup]  # Dependencies using job IDs
    steps:
      - name: "Build"
        run: echo "Building"
```

## Creating Workflows

### Workflow Locations

LocalFlow supports two locations for workflows:

1. Project-specific: `.localflow` directory in your project
2. Global: `~/.localflow/workflows` directory

Project workflows take precedence over global ones.

### Basic Workflow Example

```yaml
id: wf_basic
name: Basic Example
description: "Simple workflow demonstration"
version: "1.0.0"
author: "Your Name"

jobs:
  hello:
    id: job_hello
    steps:
      - name: "Greeting"
        run: echo "Hello, LocalFlow!"
```

### Multi-Job Workflow with Dependencies

```yaml
id: wf_build
name: Build and Test
description: "Build and test a Python project"
version: "1.0.0"
tags: [python, build]

jobs:
  setup:
    id: job_setup
    steps:
      - name: "Install Dependencies"
        run: pip install -r requirements.txt

  test:
    id: job_test
    condition:
      if: "job_setup"
    needs: [job_setup]
    steps:
      - name: "Run Tests"
        run: python -m pytest tests/
```

## Running Workflows

### Command Overview

```bash
# List workflows
localflow list

# Show workflow details
localflow jobs <workflow_id>

# Run entire workflow
localflow run <workflow_id>

# Run specific job
localflow run <workflow_id> --job <job_id>
```

### Output Control

```bash
# Save output to file
localflow run <workflow_id> --output results.log

# Output to both file and console
localflow run <workflow_id> --output results.log --output-mode both

# Append to existing log
localflow run <workflow_id> --output results.log --append
```

## Job Management

### Job Structure

Each job in a workflow requires:
1. Unique ID (auto-generated if not provided)
2. One or more steps to execute
3. Optional conditions and dependencies

### Job Dependencies

Dependencies are specified using job IDs:

```yaml
jobs:
  first:
    id: job_first
    steps:
      - run: echo "First job"

  second:
    id: job_second
    needs: [job_first]
    condition:
      if: "job_first"
    steps:
      - run: echo "Second job"
```

## Conditions and Dependencies

### Condition Types

1. Simple conditions:
```yaml
condition: "job_id"  # Job must complete successfully
```

2. Complex conditions:
```yaml
condition:
  if: "job_id1 and job_id2"
  needs: [job_id1, job_id2]
```

3. Boolean operators:
```yaml
condition:
  if: "job_id1 and not job_id2 or job_id3"
```

### Dependency Resolution

LocalFlow automatically:
1. Identifies required jobs
2. Executes dependencies first
3. Evaluates conditions
4. Skips jobs if conditions aren't met

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

### Tags and Filtering

Tags help organize and filter workflows and jobs:

```yaml
tags: [development, testing]  # Workflow tags

jobs:
  test:
    tags: [unit-test, automated]  # Job tags
```

# Event-Based Workflow Triggering

LocalFlow now supports automatic workflow triggering based on file system events.

## Event Configuration

Add events to your workflow YAML file:

```yaml
id: example_workflow
name: File Processing Workflow
events:
  - type: file_change  # Event type (file_change, file_create, file_delete)
    workflow_id: example_workflow  # Workflow to trigger
    job_ids:  # Optional specific jobs to run
      - job_process
    trigger:
      paths:  # Directories to watch
        - ~/data
        - /var/log
      patterns:  # File patterns (glob/regex)
        - "*.log"
        - "data\d+\.csv"
      recursive: true  # Watch subdirectories
      max_depth: 3  # Maximum directory depth
      include_patterns:  # Additional file patterns to include
        - "*.txt"
      exclude_patterns:  # Patterns to exclude
        - "*.tmp"
      owner: username  # Match file owner
      group: groupname  # Match file group
      min_size: 1024  # Minimum file size (bytes)
      max_size: 1048576  # Maximum file size (bytes)

jobs:
  process:
    id: job_process
    steps:
      - name: Process File
        run: echo "Processing changed file"

## Troubleshooting

### Common Issues

1. ID Resolution:
```bash
# List all workflows with IDs
localflow list

# Show detailed job information
localflow jobs <workflow_id>
```

2. Condition Evaluation:
```bash
# Enable debug logging
localflow --debug run <workflow_id>
```

3. Dependency Problems:
```bash
# Check job dependencies
localflow jobs <workflow_id>
```

### Debug Mode

Enable detailed logging:

```bash
localflow --debug run <workflow_id>
```

### Log Files

Access execution logs:

```bash
# List log files
ls -l ~/.localflow/logs/

# View specific log
cat ~/.localflow/logs/workflow_20241224_123456.log
```
