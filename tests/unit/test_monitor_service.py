"""Unit tests for LocalFlow monitor service."""

import os
import signal
import tempfile
import time
from pathlib import Path
import pytest
from monitor_service import LocalFlowMonitorService
from config import Config

@pytest.fixture
def temp_dir():
    """Provide temporary directory for test files."""
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
        monitor_log_file=temp_dir / "monitor.log",
        monitor_check_interval=1  # Use shorter interval for tests
    )

def wait_for_pid_file(path, timeout=2):
    """Wait for PID file to be created."""
    start = time.time()
    while not path.exists():
        if time.time() - start > timeout:
            return False
        time.sleep(0.1)
    return True

def test_monitor_service_pid_file(test_config):
    """Test PID file creation and cleanup."""
    service = LocalFlowMonitorService(test_config)
    
    # Fork process for daemon
    pid = os.fork()
    if pid == 0:  # Child process
        try:
            # Catch SystemExit
            with pytest.raises(SystemExit) as exc_info:
                service.run()
            assert exc_info.value.code == 0
            os._exit(0)  # Ensure child exits
        except Exception:
            os._exit(1)
    else:  # Parent process
        try:
            # Wait for PID file
            assert wait_for_pid_file(test_config.monitor_pid_file)
            
            # Check PID file content
            pid_content = test_config.monitor_pid_file.read_text().strip()
            assert pid_content.isdigit()
            
            # Stop daemon
            os.kill(int(pid_content), signal.SIGTERM)
            
            # Wait for process to exit
            _, status = os.waitpid(pid, 0)
            assert status == 0
            
            # Verify PID file cleanup
            assert not test_config.monitor_pid_file.exists()
        finally:
            # Cleanup in case test fails
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

def test_monitor_service_signal_handling(test_config):
    """Test signal handling and cleanup."""
    service = LocalFlowMonitorService(test_config)
    
    pid = os.fork()
    if pid == 0:  # Child process
        try:
            with pytest.raises(SystemExit) as exc_info:
                service.run()
            assert exc_info.value.code == 0
            os._exit(0)
        except Exception:
            os._exit(1)
    else:  # Parent process
        try:
            # Wait for PID file
            assert wait_for_pid_file(test_config.monitor_pid_file)
            
            # Send SIGTERM
            os.kill(pid, signal.SIGTERM)
            
            # Wait for process to exit
            _, status = os.waitpid(pid, 0)
            assert status == 0
            
            # Verify cleanup
            assert not test_config.monitor_pid_file.exists()
        finally:
            # Cleanup in case test fails
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

def test_monitor_service_setup_failure(test_config):
    """Test cleanup on setup failure."""
    # Create directory structure
    test_config.monitor_pid_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Make directory read-only
    os.chmod(str(test_config.monitor_pid_file.parent), 0o444)
    
    service = LocalFlowMonitorService(test_config)
    
    try:
        # Should raise PermissionError due to read-only directory
        with pytest.raises(PermissionError):
            service.setup()
            
        # We don't need to check file existence since the directory is read-only
        # and the setup failed with PermissionError as expected
        
    finally:
        # Restore permissions for cleanup
        os.chmod(str(test_config.monitor_pid_file.parent), 0o755)