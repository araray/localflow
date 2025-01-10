"""Unit tests for LocalFlow daemon functionality."""

import os
import tempfile
from pathlib import Path
import time
import pytest
import psutil
from localflow import Config, LocalFlowMonitorService

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

def test_daemon_start_stop(test_config):
    """Test starting and stopping the daemon."""
    
    # Start daemon
    service = LocalFlowMonitorService(config_path=None)
    service.config = test_config
    
    # Fork process
    pid = os.fork()
    if pid == 0:  # Child process
        try:
            service.run()
        except Exception:
            os._exit(1)
        os._exit(0)
    else:  # Parent process
        time.sleep(1)  # Wait for daemon to start
        
        # Check if running
        assert test_config.monitor_pid_file.exists()
        daemon_pid = int(test_config.monitor_pid_file.read_text().strip())
        assert psutil.Process(daemon_pid).is_running()
        
        # Stop daemon
        process = psutil.Process(daemon_pid)
        process.terminate()
        process.wait(timeout=10)
        
        # Verify stopped
        assert not process.is_running()
        
def test_daemon_file_watching(test_config, temp_dir):
    """Test that daemon properly watches files."""
    
    # Create test workflow with file watch
    workflow_dir = test_config.workflows_dir
    workflow_dir.mkdir(parents=True)
    
    workflow_content = {
        "id": "test_watch",
        "name": "Test Watch",
        "events": [{
            "type": "file_change",
            "workflow_id": "test_watch",
            "trigger": {
                "paths": [str(temp_dir)],
                "patterns": ["*.txt"],
                "recursive": True
            }
        }],
        "jobs": {
            "echo": {
                "id": "job_echo",
                "steps": [{
                    "run": "echo 'File changed!'"
                }]
            }
        }
    }
    
    import yaml
    workflow_file = workflow_dir / "watch.yml"
    with open(workflow_file, "w") as f:
        yaml.dump(workflow_content, f)
    
    # Start daemon
    service = LocalFlowMonitorService(config_path=None)
    service.config = test_config
    
    pid = os.fork()
    if pid == 0:  # Child
        try:
            service.run()
        except Exception:
            os._exit(1)
        os._exit(0)
    else:  # Parent
        time.sleep(1)
        
        # Create file that should trigger workflow
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")
        
        time.sleep(2)
        
        # Check logs for workflow execution
        log_file = test_config.log_dir / test_config.monitor_log_file
        assert log_file.exists()
        log_content = log_file.read_text()
        assert "Triggering workflow test_watch" in log_content
        
        # Cleanup
        daemon_pid = int(test_config.monitor_pid_file.read_text().strip())
        process = psutil.Process(daemon_pid)
        process.terminate()
        process.wait(timeout=10)