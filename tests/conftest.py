"""Common test fixtures and configuration."""

import pytest
import tempfile
from pathlib import Path
from localflow.core.config import Config

@pytest.fixture
def temp_dir():
    """Provide a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def test_config(temp_dir):
    """Create test configuration."""
    return Config(
        workflows_dir=temp_dir / "workflows",
        local_workflows_dir=temp_dir / ".localflow",
        log_dir=temp_dir / "logs",
        log_level="DEBUG",
        docker_enabled=False,
        docker_default_image="ubuntu:latest",
        show_output=True,
        default_shell="/bin/bash",
        monitor_pid_file=temp_dir / "monitor.pid",
        monitor_log_file=temp_dir / "monitor.log"
    )