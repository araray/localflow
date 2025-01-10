"""Unit tests for LocalFlow daemon management."""

import os
import signal
import tempfile
from pathlib import Path
import pytest
import psutil
from daemon_manager import DaemonManager, ProcessRunningError, ProcessNotRunningError

@pytest.fixture
def temp_pid_file():
    """Provide temporary PID file."""
    with tempfile.NamedTemporaryFile() as f:
        yield Path(f.name)

@pytest.fixture
def manager(temp_pid_file):
    """Provide configured daemon manager."""
    return DaemonManager(temp_pid_file)

def test_daemon_start_stop(manager):
    """Test basic daemon lifecycle."""
    # Start daemon
    manager.start()
    assert manager.pid_file.exists()
    running, pid = manager.status()
    assert running
    assert pid == os.getpid()
    
    # Try starting again
    with pytest.raises(ProcessRunningError):
        manager.start()
    
    # Stop daemon
    manager.stop()
    assert not manager.pid_file.exists()
    running, pid = manager.status()
    assert not running
    assert pid is None
    
    # Try stopping again
    with pytest.raises(ProcessNotRunningError):
        manager.stop()

def test_stale_pid_handling(manager):
    """Test handling of stale PID files."""
    # Create stale PID file
    manager.pid_file.write_text("99999")
    
    # Should not report as running
    running, pid = manager.status()
    assert not running
    assert pid is None
    assert not manager.pid_file.exists()

def test_cleanup_on_termination(manager):
    """Test PID file cleanup on process termination."""
    manager.start()
    assert manager.pid_file.exists()
    
    # Simulate process termination
    os.kill(os.getpid(), signal.SIGTERM)
    
    # PID file should be cleaned up
    assert not manager.pid_file.exists()