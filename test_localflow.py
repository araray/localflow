"""Unit tests for LocalFlow implementation."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
import yaml
from click.testing import CliRunner

from localflow import (
    Config,
    OutputConfig,
    OutputHandler,
    OutputMode,
    WorkflowExecutor,
    cli,
    resolve_workflow_path,
)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def example_workflow_file(temp_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary workflow file for testing."""
    content = {
        "id": "wf_test123",
        "name": "Test Workflow",
        "description": "A test workflow",
        "version": "1.0.0",
        "author": "Test Author",
        "tags": ["test", "example"],
        "jobs": {
            "setup": {
                "id": "job_setup123",
                "description": "Setup job",
                "tags": ["setup"],
                "steps": [{"name": "Setup", "run": 'echo "Setting up"'}],
            },
            "test": {
                "id": "job_test123",
                "description": "Test job",
                "tags": ["test"],
                "condition": {"if": "job_setup123", "needs": ["job_setup123"]},
                "steps": [{"name": "Test", "run": 'echo "Testing"'}],
            },
        },
    }

    workflow_file = temp_dir / "test_workflow.yml"
    with open(workflow_file, "w") as f:
        yaml.dump(content, f)

    yield workflow_file


@pytest.fixture
def config(temp_dir: Path) -> Config:
    """Create a test configuration."""
    return Config(
        workflows_dir=temp_dir / "workflows",
        local_workflows_dir=temp_dir / ".localflow",
        log_dir=temp_dir / "logs",
        log_level="DEBUG",
        docker_enabled=False,
        docker_default_image="ubuntu:latest",
        show_output=True,
        default_shell="/bin/bash",
        output_config=OutputConfig(),
    )


def test_workflow_path_resolution(config: Config, example_workflow_file: Path):
    """Test workflow path resolution from ID."""
    # Setup local workflow directory
    config.local_workflows_dir.mkdir(parents=True)
    local_workflow = config.local_workflows_dir / "local.yml"

    with open(local_workflow, "w") as f:
        yaml.dump(
            {
                "id": "wf_local123",
                "name": "Local Workflow",
                "jobs": {"test": {"steps": [{"run": 'echo "test"'}]}},
            },
            f,
        )

    # Test finding local workflow
    path = resolve_workflow_path(
        config.workflows_dir, "wf_local123", local_dir=config.local_workflows_dir
    )
    assert path == local_workflow.resolve()

    # Test workflow not found
    with pytest.raises(FileNotFoundError):
        resolve_workflow_path(config.workflows_dir, "nonexistent")


def test_workflow_executor(config: Config, example_workflow_file: Path):
    """Test workflow execution."""
    executor = WorkflowExecutor(example_workflow_file, config)

    # Test running specific job
    assert executor.execute_job("job_setup123")

    # Test running job with unmet condition
    assert executor.execute_job("job_test123")  # Should skip due to condition

    # Test running entire workflow
    assert executor.run()


def test_cli_commands(config: Config, example_workflow_file: Path):
    """Test CLI commands with proper workflow setup."""
    runner = CliRunner()

    with runner.isolated_filesystem() as fs:
        # Create required directories
        config.local_workflows_dir.mkdir(parents=True, exist_ok=True)
        config.workflows_dir.mkdir(parents=True, exist_ok=True)
        config.log_dir.mkdir(parents=True, exist_ok=True)

        # Copy workflow to local directory
        workflow_path = config.local_workflows_dir / example_workflow_file.name
        workflow_path.write_text(example_workflow_file.read_text())

        # Create a temporary config file
        config_file = Path(fs) / "config.yml"
        with open(config_file, "w") as f:
            yaml.dump(
                {
                    "workflows_dir": str(config.workflows_dir),
                    "local_workflows_dir": str(config.local_workflows_dir),
                    "log_dir": str(config.log_dir),
                    "log_level": config.log_level,
                    "docker_enabled": config.docker_enabled,
                    "docker_default_image": config.docker_default_image,
                    "show_output": config.show_output,
                    "default_shell": config.default_shell,
                },
                f,
            )

        env = {"LOCALFLOW_CONFIG": str(config_file)}

        # Test commands with environment
        result = runner.invoke(cli, ["list"], env=env)
        assert result.exit_code == 0, f"List command failed: {result.output}"

        result = runner.invoke(cli, ["jobs", "wf_test123"], env=env)
        assert result.exit_code == 0, f"Jobs command failed: {result.output}"

        result = runner.invoke(cli, ["run", "wf_test123"], env=env)
        assert result.exit_code == 0, f"Run command failed: {result.output}"


def test_output_handler_file_creation(temp_dir: Path):
    """Test that OutputHandler creates the specified output file and writes content."""
    output_file = Path(os.path.join(temp_dir, "test_output.log"))
    config = OutputConfig(file=output_file, mode=OutputMode.FILE, stdout=False)

    content = "Test content"

    with OutputHandler(config) as handler:
        handler.write(content)

    assert output_file.exists(), "Output file was not created."
    assert output_file.read_text() == content, "Output content does not match."


def test_output_handling(config: Config, example_workflow_file: Path, temp_dir: Path):
    """Test output handling configurations."""
    output_dir = Path(os.path.join(temp_dir, "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = Path(os.path.join(output_dir, "output.log"))

    config.output_config = OutputConfig(
        file=output_file, mode=OutputMode.FILE, stdout=False, append=False
    )

    executor = WorkflowExecutor(example_workflow_file, config)

    try:
        # Log start
        logging.debug("Starting test_output_handling.")

        # Run workflow and verify execution
        assert executor.run(), "Workflow execution failed"

        # Verify file exists
        assert output_file.exists(), "Output file was not created"

        # Verify file content
        content = output_file.read_text().strip()
        assert content, "Output file is empty"
        assert "Setting up" in content, "Expected output missing from log file"
        assert "Testing" in content, "Expected output missing from log file"
    except Exception as e:
        raise AssertionError(f"Test failed: {e}")
    finally:
        # Cleanup
        if output_file.exists():
            output_file.unlink()
        if output_dir.exists():
            output_dir.rmdir()


def test_condition_evaluation(config: Config, example_workflow_file: Path):
    """Test job condition evaluation."""
    executor = WorkflowExecutor(example_workflow_file, config)

    # Run setup job
    assert executor.execute_job("job_setup123")

    # Test job should now run since setup completed
    assert executor.execute_job("job_test123")


def test_environment_variables(config: Config, temp_dir: Path):
    """Test environment variable handling."""
    workflow_content = {
        "id": "wf_env_test",
        "name": "Env Test",
        "env": {"GLOBAL": "value"},
        "jobs": {
            "test": {
                "id": "job_env_test",
                "env": {"JOB_VAR": "test"},
                "steps": [
                    {
                        "name": "Check Env",
                        "run": 'echo "${GLOBAL}-${JOB_VAR}"',
                        "env": {"STEP_VAR": "local"},
                    }
                ],
            }
        },
    }
    workflow_file = temp_dir / "env_test.yml"
    with open(workflow_file, "w") as f:
        yaml.dump(workflow_content, f)

    executor = WorkflowExecutor(workflow_file, config)
    assert executor.run()


def test_workflow_tags(config: Config, temp_dir: Path):
    """Test workflow and job tag functionality."""
    # Create workflows with different tags
    workflows = [
        {
            "id": "wf_tag1",
            "name": "Tag Test 1",
            "tags": ["deploy", "production"],
            "jobs": {"test": {"id": "job_1", "steps": [{"run": 'echo "test"'}]}},
        },
        {
            "id": "wf_tag2",
            "name": "Tag Test 2",
            "tags": ["test", "development"],
            "jobs": {"test": {"id": "job_2", "steps": [{"run": 'echo "test"'}]}},
        },
    ]

    config.workflows_dir.mkdir(parents=True)
    for i, wf in enumerate(workflows):
        with open(config.workflows_dir / f"wf_{i}.yml", "w") as f:
            yaml.dump(wf, f)

    # Test workflow filtering by tags
    from schema import WorkflowRegistry

    registry = WorkflowRegistry()
    registry.discover_workflows(config.workflows_dir)

    prod_flows = registry.find_workflows(tags={"production"})
    assert len(prod_flows) == 1
    assert prod_flows[0].id == "wf_tag1"


def test_job_dependencies(config: Config, temp_dir: Path):
    """Test job dependency resolution and execution order."""
    workflow_content = {
        "id": "wf_deps",
        "name": "Dependency Test",
        "jobs": {
            "first": {"id": "job_first", "steps": [{"run": 'echo "first"'}]},
            "second": {
                "id": "job_second",
                "condition": {"if": "job_first"},
                "needs": ["job_first"],
                "steps": [{"run": 'echo "second"'}],
            },
            "third": {
                "id": "job_third",
                "condition": {"if": "job_first and job_second"},
                "needs": ["job_first", "job_second"],
                "steps": [{"run": 'echo "third"'}],
            },
        },
    }

    workflow_file = temp_dir / "deps_test.yml"
    with open(workflow_file, "w") as f:
        yaml.dump(workflow_content, f)

    executor = WorkflowExecutor(workflow_file, config)

    # Test individual job execution with dependencies
    assert executor.execute_job("job_third")  # Should execute all dependencies


def test_local_workflow_override(config: Config, temp_dir: Path):
    """Test that local workflows override global ones with same ID."""
    workflow_content = {"id": "wf_override", "name": "Test Workflow"}

    # Create global workflow
    config.workflows_dir.mkdir(parents=True)
    global_file = config.workflows_dir / "test.yml"
    with open(global_file, "w") as f:
        yaml.dump(dict(workflow_content, name="Global Workflow"), f)

    # Create local workflow with same ID
    config.local_workflows_dir.mkdir(parents=True)
    local_file = config.local_workflows_dir / "test.yml"
    with open(local_file, "w") as f:
        yaml.dump(dict(workflow_content, name="Local Workflow"), f)

    # Test that local workflow is preferred when local_dir is provided
    path = resolve_workflow_path(
        config.workflows_dir, "wf_override", local_dir=config.local_workflows_dir
    )
    assert path == local_file.resolve()


def test_error_handling(config: Config, temp_dir: Path):
    """Test error handling in various scenarios."""
    # Test invalid workflow format
    invalid_file = temp_dir / "invalid.yml"
    with open(invalid_file, "w") as f:
        f.write("invalid: yaml: content")

    with pytest.raises(ValueError):
        WorkflowExecutor(invalid_file, config)

    # Test missing job reference
    workflow_content = {
        "id": "wf_error",
        "jobs": {
            "test": {
                "id": "job_error",
                "condition": {"if": "nonexistent_job"},
                "steps": [{"run": 'echo "test"'}],
            }
        },
    }

    error_file = temp_dir / "error_test.yml"
    with open(error_file, "w") as f:
        yaml.dump(workflow_content, f)

    executor = WorkflowExecutor(error_file, config)
    assert not executor.execute_job("job_error")  # Should fail gracefully


def test_workflow_validation(config: Config, temp_dir: Path):
    """Test workflow validation rules."""
    # Test circular dependencies
    workflow_content = {
        "id": "wf_circular",
        "jobs": {
            "job1": {
                "id": "job_1",
                "condition": {"if": "job_2"},
                "needs": ["job_2"],
                "steps": [{"run": 'echo "test"'}],
            },
            "job2": {
                "id": "job_2",
                "condition": {"if": "job_1"},
                "needs": ["job_1"],
                "steps": [{"run": 'echo "test"'}],
            },
        },
    }

    circular_file = temp_dir / "circular.yml"
    with open(circular_file, "w") as f:
        yaml.dump(workflow_content, f)

    executor = WorkflowExecutor(circular_file, config)
    assert not executor.run()  # Should detect circular dependency


if __name__ == "__main__":
    pytest.main([__file__])
