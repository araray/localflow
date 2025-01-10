"""
LocalFlow monitoring service for event-based workflow triggering.
Handles daemon lifecycle, event monitoring, and workflow discovery.
"""

import logging
import signal
import os
import sys
import time
from pathlib import Path
from typing import Optional

from localflow.core import Config 
from localflow.services.events import EventMonitor, EventRegistry
from localflow.core.schema import WorkflowRegistry
from .manager import DaemonManager


class LocalFlowMonitorService:
    """Monitor service for LocalFlow event monitoring."""

    def __init__(self, config: Optional[Config] = None):
        """Initialize service."""
        self.config = config
        self.registry = None
        self.event_registry = None
        self.monitor = None
        self.logger = logging.getLogger("LocalFlow.Monitor")
        self.running = False
        self.daemon_manager = None

        # Configure basic logging until proper setup
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)]
        )

    def start(self, foreground: bool = False):
        """Start the monitor service using DaemonManager."""
        if not self.config:
            from localflow import resolve_config_path
            config_path = resolve_config_path(None)
            self.config = Config.load_from_file(config_path)

        # Initialize daemon manager
        self.daemon_manager = DaemonManager(
            pid_file=self.config.monitor_pid_file,
            log_file=self.config.log_dir / self.config.monitor_log_file
        )

        try:
            self.daemon_manager.start(self, foreground)
        except Exception as e:
            self.logger.error(f"Failed to start daemon: {e}")
            raise

    def stop(self):
        """Stop the monitor service using DaemonManager."""
        if not self.daemon_manager:
            if not self.config:
                from localflow import resolve_config_path
                config_path = resolve_config_path(None)
                self.config = Config.load_from_file(config_path)
            
            self.daemon_manager = DaemonManager(
                pid_file=self.config.monitor_pid_file,
                log_file=self.config.log_dir / self.config.monitor_log_file
            )

        try:
            self.daemon_manager.stop()
        except Exception as e:
            self.logger.error(f"Failed to stop daemon: {e}")
            raise

    def status(self) -> tuple[bool, Optional[int]]:
        """Get daemon status using DaemonManager."""
        if not self.daemon_manager:
            if not self.config:
                from localflow import resolve_config_path
                config_path = resolve_config_path(None)
                self.config = Config.load_from_file(config_path)
            
            self.daemon_manager = DaemonManager(
                pid_file=self.config.monitor_pid_file,
                log_file=self.config.log_dir / self.config.monitor_log_file
            )

        return self.daemon_manager.status()

    def _handle_signal(self, signum, frame):
        """Handle termination signals."""
        sig_name = signal.Signals(signum).name
        self.logger.info(f"Received signal {signum} ({sig_name})")
        
        try:
            # Stop event monitoring
            if self.monitor:
                self.monitor.stop()
                
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
            
        finally:
            self.running = False
            sys.exit(0)

    def setup(self):
        """Setup service components."""
        try:
            # Setup logging
            self.config.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.config.log_dir / self.config.monitor_log_file

            # Configure logging
            handlers = [
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
            
            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)
                
            logging.basicConfig(
                level=self.config.log_level,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                handlers=handlers
            )

            self.logger.info("Starting LocalFlow Monitor Service")
            self.logger.info(f"Using config file: {self.config.config_file}")
            self.logger.info(f"Log file: {log_file}")

            # Setup signal handlers
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)

            # Initialize registries
            self.logger.info("Initializing workflow and event registries")
            self.registry = WorkflowRegistry()
            self.event_registry = EventRegistry(self.config)

            # Discover workflows
            self.logger.info("Discovering workflows")
            self.registry.discover_workflows(
                self.config.workflows_dir,
                self.config.local_workflows_dir
            )
            self.logger.info(
                f"Found {len(self.registry.workflows)} workflows"
            )

            # Setup event monitor
            self.logger.info("Setting up event monitor")
            self.monitor = EventMonitor(
                self.config,
                self.registry,
                self.event_registry
            )

            self.logger.info("Service setup completed successfully")

        except Exception as e:
            self.logger.error(f"Failed to setup service: {e}", exc_info=True)
            raise

    def run(self):
        """Main service loop."""
        try:
            self.setup()
            self.running = True

            self.logger.info("Starting event monitor")
            self.monitor.start()
            self.logger.info("LocalFlow monitor started and running")

            # Main loop
            while self.running:
                try:
                    self.logger.debug("Rediscovering workflows")
                    self.registry.discover_workflows(
                        self.config.workflows_dir,
                        self.config.local_workflows_dir
                    )
                    self.monitor.setup_watches()
                    time.sleep(self.config.monitor_check_interval)
                except Exception as e:
                    self.logger.error(f"Error during workflow rediscovery: {e}", exc_info=True)
                    
        except Exception as e:
            self.logger.error(f"Monitor error: {e}", exc_info=True)
            raise
        finally:
            self.logger.info("Stopping event monitor")
            if self.monitor:
                self.monitor.stop()
            self.logger.info("LocalFlow monitor stopped")