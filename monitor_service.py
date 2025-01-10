"""
LocalFlow monitoring service for event-based workflow triggering.
"""

import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from config import Config
from events import EventMonitor, EventRegistry
from schema import WorkflowRegistry


class LocalFlowMonitorService:
    """Monitor service for LocalFlow event monitoring."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize service.

        Args:
            config_path: Optional path to configuration file
        """
        self.config_path = config_path
        self.config = None
        self.registry = None
        self.event_registry = None
        self.monitor = None
        self.logger = None
        self.running = False

    def setup(self):
        """Setup service components."""
        try:
            # Load configuration
            from localflow import resolve_config_path
            config_path = resolve_config_path(self.config_path)
            self.config = Config.load_from_file(config_path)

            # Setup logging
            self.config.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.config.log_dir / self.config.monitor_log_file

            # Configure root logger for comprehensive logging
            logging.basicConfig(
                level=self.config.log_level,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                handlers=[
                    logging.FileHandler(log_file),
                    logging.StreamHandler(sys.stdout)
                ]
            )
            self.logger = logging.getLogger("LocalFlow.Monitor")
            self.logger.info("Starting LocalFlow Monitor Service")
            self.logger.info(f"Using config file: {config_path}")
            self.logger.info(f"Log file: {log_file}")

            # Create pid file directory if needed
            self.config.monitor_pid_file.parent.mkdir(parents=True, exist_ok=True)

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

            def handle_signal(signum, frame):
                sig_name = signal.Signals(signum).name
                self.logger.info(f"Received signal {signum} ({sig_name})")
                self.running = False

            signal.signal(signal.SIGTERM, handle_signal)
            signal.signal(signal.SIGINT, handle_signal)

            self.logger.info("Starting event monitor")
            self.monitor.start()
            self.logger.info("LocalFlow monitor started and running")

            while self.running:
                try:
                    # Periodically rediscover workflows and update watches
                    self.logger.debug("Rediscovering workflows")
                    self.registry.discover_workflows(
                        self.config.workflows_dir,
                        self.config.local_workflows_dir
                    )
                    self.monitor.setup_watches()
                    time.sleep(self.config.monitor_check_interval)
                except Exception as e:
                    self.logger.error(
                        f"Error during workflow rediscovery: {e}",
                        exc_info=True
                    )

        except Exception as e:
            self.logger.error(f"Monitor error: {e}", exc_info=True)
            raise
        finally:
            self.logger.info("Stopping event monitor")
            if self.monitor:
                self.monitor.stop()
            self.logger.info("LocalFlow monitor stopped")
