"""
LocalFlow monitoring service for event-based workflow triggering.
"""


import logging
import signal
import time
from typing import Optional

from config import Config
from events import EventMonitor
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
        self.monitor = None
        self.logger = None
        self.running = False
        
    def setup(self):
        """Setup service components."""
        # Load configuration
        from localflow import resolve_config_path
        config_path = resolve_config_path(self.config_path)
        self.config = Config.load_from_file(config_path)
        
        # Setup logging
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.config.log_dir / self.config.monitor_log_file
        
        logging.basicConfig(
            level=self.config.log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('LocalFlow.Monitor')
        
        # Create pid file directory if needed
        self.config.monitor_pid_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize workflow registry
        self.registry = WorkflowRegistry()
        self.registry.discover_workflows(
            self.config.workflows_dir,
            self.config.local_workflows_dir
        )
        
        # Setup event monitor
        self.monitor = EventMonitor(self.config, self.registry)
        
    def run(self):
        """Main service loop."""
        self.setup()
        self.running = True
        
        def handle_signal(signum, frame):
            self.logger.info(f"Received signal {signum}")
            self.running = False
            
        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)
        
        try:
            self.monitor.start()
            self.logger.info("LocalFlow monitor started")
            
            while self.running:
                # Periodically rediscover workflows
                self.registry.discover_workflows(
                    self.config.workflows_dir,
                    self.config.local_workflows_dir
                )
                self.monitor.setup_watches()
                time.sleep(self.config.monitor_check_interval)
                
        except Exception as e:
            self.logger.error(f"Monitor error: {e}")
            raise
        finally:
            self.monitor.stop()
            self.logger.info("LocalFlow monitor stopped")