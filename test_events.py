"""Unit tests for LocalFlow event monitoring."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from config import Config
from events import EventMonitor, EventRegistry, EventTrigger, LocalFlowEventHandler
from schema import Workflow


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def event_workflow(temp_dir):
    """Create a test workflow with event triggers."""
    content = {
        "id": "wf_event_test",
        "name": "Event Test Workflow",
        "version": "1.0.0",
        "events": [
            {
                "type": "file_change",
                "workflow_id": "wf_event_test",
                "trigger": {
                    "paths": [str(temp_dir)],
                    "patterns": ["*.txt"],
                    "recursive": True,
                    "max_depth": 3,
                    "min_size": 100,
                    "max_size": 1000000,
                },
            }
        ],
        "jobs": {
            "process": {
                "id": "job_process",
                "steps": [{"run": 'echo "Processing file"'}],
            }
        },
    }

    workflow_file = temp_dir / "event_workflow.yml"
    with open(workflow_file, "w") as f:
        yaml.dump(content, f)

    return Workflow.from_file(workflow_file)


@pytest.fixture
def config(temp_dir):
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
    )


def test_event_trigger_matching():
    """Test event trigger pattern matching."""
    trigger = EventTrigger(
        paths=["/test"],
        patterns=["*.txt", r"data\d+\.csv"],
        recursive=True,
        min_size=100,
        max_size=1000,
    )

    # Test file pattern matching
    assert trigger.matches({"path": "/test/file.txt", "size": 500})
    assert trigger.matches({"path": "/test/data123.csv", "size": 500})
    assert not trigger.matches({"path": "/test/file.pdf", "size": 500})

    # Test size constraints
    assert not trigger.matches({"path": "/test/file.txt", "size": 50})
    assert not trigger.matches({"path": "/test/file.txt", "size": 1500})


def test_event_handler(config, event_workflow, temp_dir):
    """Test event handler workflow triggering."""
    registry = MagicMock()
    registry.find_workflows.return_value = [event_workflow]

    handler = LocalFlowEventHandler(registry, config)

    # Create a test file
    test_file = temp_dir / "test.txt"
    with open(test_file, "w") as f:
        f.write("test" * 100)  # Create file with size 400 bytes

    # Mock workflow execution
    with patch("events.WorkflowExecutor") as mock_executor:
        handler.on_modified(MagicMock(is_directory=False, src_path=str(test_file)))

        mock_executor.assert_called_once()
        mock_executor.return_value.run.assert_called_once()


def test_event_monitor(config, event_workflow, temp_dir):
    """Test event monitor setup and watch management."""
    registry = MagicMock()
    registry.find_workflows.return_value = [event_workflow]

    monitor = EventMonitor(config, registry)

    # Test watch setup
    with patch("watchdog.observers.Observer.schedule") as mock_schedule:
        monitor.setup_watches()
        mock_schedule.assert_called_once()

        # Verify recursive watching is enabled
        args = mock_schedule.call_args[1]
        assert args["recursive"] is True


def test_workflow_event_loading(temp_dir):
    """Test loading workflow with event configuration."""
    content = {
        "id": "wf_test",
        "name": "Test Workflow",
        "events": [
            {
                "type": "file_change",
                "workflow_id": "wf_test",
                "trigger": {"paths": ["/test"], "patterns": ["*.txt"]},
            }
        ],
    }

    workflow_file = temp_dir / "workflow.yml"
    with open(workflow_file, "w") as f:
        yaml.dump(content, f)

    workflow = Workflow.from_file(workflow_file)
    assert len(workflow.events) == 1
    assert workflow.events[0].type == "file_change"
    assert "*.txt" in workflow.events[0].trigger.patterns


@pytest.mark.integration
def test_event_triggered_workflow(config, event_workflow, temp_dir):
    """Integration test for event-triggered workflow execution."""
    registry = WorkflowRegistry()
    registry.workflows[event_workflow.id] = event_workflow

    monitor = EventMonitor(config, registry)
    monitor.start()

    try:
        # Create a file that should trigger the workflow
        test_file = temp_dir / "test.txt"
        with open(test_file, "w") as f:
            f.write("test" * 100)

        # Wait for event processing
        time.sleep(2)

        # Verify log file for workflow execution
        log_file = config.log_dir / "localflow-daemon.log"
        assert log_file.exists()
        log_content = log_file.read_text()
        assert "Triggering workflow wf_event_test" in log_content

    finally:
        monitor.stop()


def test_daemon_pidfile_handling():
    """Test daemon PID file management."""
    with tempfile.NamedTemporaryFile() as pid_file:
        # Test PID file creation
        daemon = LocalFlowDaemon()
        with patch("daemon.DaemonContext"):
            with patch.object(daemon, "run"):
                context = DaemonContext(pidfile=PIDLockFile(pid_file.name))
                with context:
                    assert os.path.exists(pid_file.name)

        # Test PID file cleanup
        assert not os.path.exists(pid_file.name)

def test_event_registration(config, event_workflow):
    """Test event registration functionality."""
    event_registry = EventRegistry(config)
    
    # Test registration
    reg_ids = event_registry.register_events(event_workflow, "local")
    assert len(reg_ids) == 1
    
    # Test listing
    regs = event_registry.list_registrations()
    assert len(regs) == 1
    assert regs[0].workflow_id == event_workflow.id
    
    # Test enable/disable
    reg_id = reg_ids[0]
    assert event_registry.disable_event(reg_id)
    reg = event_registry.get_registration(reg_id)
    assert not reg.enabled
    
    assert event_registry.enable_event(reg_id)
    reg = event_registry.get_registration(reg_id)
    assert reg.enabled
    
    # Test unregistration
    unreg_ids = event_registry.unregister_events(event_workflow.id)
    assert len(unreg_ids) == 1
    assert not event_registry.list_registrations()

def test_event_persistence(config, event_workflow):
    """Test event registration persistence."""
    event_registry = EventRegistry(config)
    
    # Register events
    reg_ids = event_registry.register_events(event_workflow, "local")
    assert len(reg_ids) == 1
    
    # Create new registry instance
    new_registry = EventRegistry(config)
    
    # Verify registrations loaded
    regs = new_registry.list_registrations()
    assert len(regs) == 1
    assert regs[0].workflow_id == event_workflow.id

def test_event_trigger_recording(config, event_workflow):
    """Test recording of event triggers."""
    event_registry = EventRegistry(config)
    reg_ids = event_registry.register_events(event_workflow, "local")
    
    reg_id = reg_ids[0]
    reg = event_registry.get_registration(reg_id)
    assert reg.last_triggered is None
    
    event_registry.record_trigger(reg_id)
    reg = event_registry.get_registration(reg_id)
    assert reg.last_triggered is not None


if __name__ == "__main__":
    pytest.main([__file__])
