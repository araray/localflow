"""
Daemon management functionality for LocalFlow.
Handles daemon lifecycle (start, stop, status) and process management.
"""

import os
import signal
import time
import sys
import fcntl
from pathlib import Path
from typing import Optional, Tuple
import daemon
import daemon.pidfile
import psutil
import logging


class ProcessRunningError(Exception):
    """Raised when trying to start a process that's already running."""
    pass


class ProcessNotRunningError(Exception):
    """Raised when trying to stop a process that's not running."""
    pass


class DaemonManager:
    """Manages LocalFlow daemon processes."""

    def __init__(self, pid_file: Path, log_file: Path):
        """
        Initialize daemon manager.
        
        Args:
            pid_file: Path to PID file
            log_file: Path to log file
        """
        self.pid_file = Path(pid_file).resolve()
        self.log_file = Path(log_file).resolve()
        self.logger = logging.getLogger("LocalFlow.DaemonManager")

    def _create_pid_file(self) -> None:
        """Create and lock PID file."""
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        
        pid = os.getpid()
        
        # Attempt to create and lock PID file
        try:
            with open(self.pid_file, 'w') as f:
                # Try to get exclusive lock
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except IOError:
                    raise ProcessRunningError("Another instance is already running")
                
                # Write PID
                f.write(str(pid))
                f.flush()
                os.fsync(f.fileno())
                
                self.logger.info(f"Created PID file: {self.pid_file} with PID: {pid}")
                
        except Exception as e:
            self.logger.error(f"Failed to create PID file: {e}")
            raise

    def _remove_pid_file(self) -> None:
        """Remove PID file."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
                self.logger.info(f"Removed PID file: {self.pid_file}")
        except Exception as e:
            self.logger.error(f"Failed to remove PID file: {e}")

    def ensure_single_instance(self) -> None:
        """
        Ensure only one instance of the daemon is running.
        
        Raises:
            ProcessRunningError: If daemon is already running
        """
        if self.is_running()[0]:
            raise ProcessRunningError("LocalFlow daemon is already running")

    def is_running(self) -> Tuple[bool, Optional[int]]:
        """
        Check if daemon is running.
        
        Returns:
            Tuple of (is_running: bool, pid: Optional[int])
        """
        try:
            if self.pid_file.exists():
                pid = int(self.pid_file.read_text().strip())
                if psutil.pid_exists(pid):
                    # Verify it's our process
                    process = psutil.Process(pid)
                    if "localflow" in process.cmdline()[0].lower():
                        return True, pid
                # Clean up stale PID file
                self._remove_pid_file()
            return False, None
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
            self._remove_pid_file()
            return False, None

    def start(self, service, foreground: bool = False) -> None:
        """
        Start daemon.
        
        Args:
            service: Service instance to run
            foreground: If True, run in foreground

        Raises:
            ProcessRunningError: If daemon is already running
            OSError: If failed to start daemon
        """
        self.ensure_single_instance()
        
        # Create necessary directories
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        if foreground:
            # Run in foreground
            self._create_pid_file()
            try:
                service.run()
            finally:
                self._remove_pid_file()
        else:
            # Prepare daemon context
            preserve_fds = []
            log_handle = open(self.log_file, 'a')
            preserve_fds.append(log_handle.fileno())
            
            context = daemon.DaemonContext(
                working_directory=str(Path.home()),
                umask=0o022,
                detach_process=True,
                files_preserve=preserve_fds,
                signal_map={
                    signal.SIGTERM: lambda signo, frame: service._handle_signal(signo, frame),
                    signal.SIGINT: lambda signo, frame: service._handle_signal(signo, frame),
                }
            )
            
            # Daemonize and run service
            with context:
                try:
                    self._create_pid_file()
                    service.run()
                except Exception as e:
                    self.logger.error(f"Daemon failed: {e}")
                    self._remove_pid_file()
                    raise
                finally:
                    self._remove_pid_file()

    def stop(self) -> None:
        """
        Stop daemon if running.
        
        Raises:
            ProcessNotRunningError: If daemon is not running
            OSError: If failed to stop daemon
        """
        running, pid = self.is_running()
        if not running:
            raise ProcessNotRunningError("LocalFlow daemon is not running")

        try:
            # Try graceful shutdown first
            os.kill(pid, signal.SIGTERM)
            
            # Wait for process to terminate
            for _ in range(10):  # 10 second timeout
                if not psutil.pid_exists(pid):
                    break
                time.sleep(1)
            else:
                # Force kill if still running
                if psutil.pid_exists(pid):
                    os.kill(pid, signal.SIGKILL)
            
            self.logger.info(f"Stopped daemon process {pid}")
            
        finally:
            self._remove_pid_file()

    def status(self) -> Tuple[bool, Optional[int]]:
        """
        Get daemon status.
        
        Returns:
            Tuple of (is_running: bool, pid: Optional[int])
        """
        return self.is_running()