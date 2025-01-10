"""
Event monitoring and handling for LocalFlow.
Provides file system event monitoring and workflow triggering functionality.
"""

from dataclasses import dataclass, field
from datetime import datetime
import grp
import logging
import os
import pickle
import pwd
import re
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Set, Union

from watchdog.events import (FileCreatedEvent, FileDeletedEvent,
                           FileModifiedEvent, FileSystemEventHandler)
from watchdog.observers import Observer

from config import Config
from executor import WorkflowExecutor
from schema import Event, generate_id, Workflow


@dataclass
class EventTrigger:
    """Represents a file system event trigger configuration."""
    paths: List[str]  # Directories to watch
    patterns: List[str] = field(default_factory=list)  # File patterns (glob/regex)
    recursive: bool = False  # Whether to watch subdirectories
    max_depth: Optional[int] = None  # Maximum directory depth to watch
    include_patterns: List[str] = field(default_factory=list)  # Files to include
    exclude_patterns: List[str] = field(default_factory=list)  # Files to exclude
    owner: Optional[str] = None  # File owner to match
    group: Optional[str] = None  # File group to match
    min_size: Optional[int] = None  # Minimum file size in bytes
    max_size: Optional[int] = None  # Maximum file size in bytes
    _compiled_patterns: List[Pattern] = field(default_factory=list, init=False)

    def __post_init__(self):
        """Compile regex patterns after initialization."""
        self._compiled_patterns = []
        for pattern in self.patterns:
            try:
                self._compiled_patterns.append(re.compile(pattern))
            except re.error:
                # If it's not a valid regex, treat it as a glob pattern
                glob_pattern = pattern.replace("*", ".*").replace("?", ".")
                self._compiled_patterns.append(re.compile(glob_pattern))

    def matches(self, event_info: dict) -> bool:
        """
        Check if an event matches this trigger's criteria.

        Args:
            event_info: Dictionary containing event details (path, size, owner, etc.)

        Returns:
            bool: True if event matches all criteria, False otherwise
        """
        path = Path(event_info["path"])

        # Check patterns
        if self.patterns:
            filename = path.name
            if not any(p.match(filename) for p in self._compiled_patterns):
                return False

        # Check include/exclude patterns
        if self.include_patterns:
            if not any(path.match(pattern) for pattern in self.include_patterns):
                return False
        if self.exclude_patterns:
            if any(path.match(pattern) for pattern in self.exclude_patterns):
                return False

        # Check owner
        if self.owner and event_info.get("owner") != self.owner:
            return False

        # Check group
        if self.group and event_info.get("group") != self.group:
            return False

        # Check size
        size = event_info.get("size", 0)
        if self.min_size is not None and size < self.min_size:
            return False
        if self.max_size is not None and size > self.max_size:
            return False

        return True

@dataclass
class EventRegistration:
    """Represents a registered event configuration."""
    id: str  # Unique event registration ID
    workflow_id: str
    event_type: str
    trigger: EventTrigger
    source: str  # 'local' or 'global'
    job_ids: Optional[List[str]] = None
    enabled: bool = True
    registered_at: datetime = field(default_factory=datetime.now)
    last_triggered: Optional[datetime] = None
    
    @classmethod
    def from_event(cls, event: Event, source: str) -> 'EventRegistration':
        """Create registration from event definition."""
        return cls(
            id=generate_id('evt', f"{event.workflow_id}_{event.type}"),
            workflow_id=event.workflow_id,
            event_type=event.type,
            trigger=event.trigger,
            source=source,
            job_ids=event.job_ids
        )

class EventRegistry:
    """Manages event registrations and their state."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("LocalFlow.EventRegistry")
        self._registrations: Dict[str, EventRegistration] = {}
        self._db_file = config.log_dir / "events.db"

        # Ensure PID file directory exists
        self.config.monitor_pid_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Initializing EventRegistry with database: {self._db_file}")
        self._load_registrations()
    
    def _load_registrations(self):
        """Load registrations from persistent storage."""
        if self._db_file.exists():
            try:
                with open(self._db_file, 'rb') as f:
                    self._registrations = pickle.load(f)
                self.logger.info(
                    f"Loaded {len(self._registrations)} event registrations from {self._db_file}"
                )
                # Log details of loaded registrations
                for reg in self._registrations.values():
                    self.logger.debug(
                        f"Loaded event registration: id={reg.id}, "
                        f"workflow={reg.workflow_id}, type={reg.event_type}, "
                        f"enabled={reg.enabled}"
                    )
            except Exception as e:
                self.logger.error(
                    f"Failed to load event registrations from {self._db_file}: {e}",
                    exc_info=True
                )
                self._registrations = {}
        else:
            self.logger.info("No existing event registrations database found")
            self._registrations = {}
    
    def _save_registrations(self):
        """Save registrations to persistent storage."""
        try:
            self._db_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._db_file, 'wb') as f:
                pickle.dump(self._registrations, f)
            self.logger.info(
                f"Saved {len(self._registrations)} event registrations to {self._db_file}"
            )
        except Exception as e:
            self.logger.error(
                f"Failed to save event registrations to {self._db_file}: {e}",
                exc_info=True
            )
    
    def register_events(self, workflow: Workflow, source: str) -> List[str]:
        """Register all events from a workflow."""
        self.logger.info(
            f"Registering events from workflow {workflow.id} (source: {source})"
        )
        registered_ids = []
        for event in workflow.events:
            reg = EventRegistration.from_event(event, source)
            if reg.id not in self._registrations:
                self._registrations[reg.id] = reg
                registered_ids.append(reg.id)
                self.logger.info(
                    f"Registered event {reg.id} for workflow {workflow.id} "
                    f"(type: {reg.event_type})"
                )
                self.logger.debug(
                    f"Event details: trigger_paths={reg.trigger.paths}, "
                    f"job_ids={reg.job_ids}, enabled={reg.enabled}"
                )
            else:
                self.logger.debug(
                    f"Event {reg.id} for workflow {workflow.id} already registered"
                )
        
        if registered_ids:
            self._save_registrations()
            self.logger.info(
                f"Successfully registered {len(registered_ids)} events "
                f"for workflow {workflow.id}"
            )
        else:
            self.logger.info(f"No new events registered for workflow {workflow.id}")
            
        return registered_ids
    
    def unregister_events(self, workflow_id: str) -> List[str]:
        """Unregister all events for a workflow."""
        unregistered = []
        for reg_id, reg in list(self._registrations.items()):
            if reg.workflow_id == workflow_id:
                del self._registrations[reg_id]
                unregistered.append(reg_id)
                self.logger.info(
                    f"Unregistered event {reg_id} for workflow {workflow_id}"
                )
        
        if unregistered:
            self._save_registrations()
        return unregistered
    
    def enable_event(self, event_id: str) -> bool:
        """Enable an event registration."""
        if event_id in self._registrations:
            self._registrations[event_id].enabled = True
            self._save_registrations()
            self.logger.info(f"Enabled event {event_id}")
            return True
        return False
    
    def disable_event(self, event_id: str) -> bool:
        """Disable an event registration."""
        if event_id in self._registrations:
            self._registrations[event_id].enabled = False
            self._save_registrations()
            self.logger.info(f"Disabled event {event_id}")
            return True
        return False
    
    def get_registration(self, event_id: str) -> Optional[EventRegistration]:
        """Get event registration by ID."""
        return self._registrations.get(event_id)
    
    def list_registrations(
        self, 
        source: Optional[str] = None, 
        workflow_id: Optional[str] = None,
        enabled_only: bool = False
    ) -> List[EventRegistration]:
        """List event registrations with optional filtering."""
        regs = list(self._registrations.values())
        
        if source:
            regs = [r for r in regs if r.source == source]
        if workflow_id:
            regs = [r for r in regs if r.workflow_id == workflow_id]
        if enabled_only:
            regs = [r for r in regs if r.enabled]
            
        return sorted(regs, key=lambda r: r.registered_at)

    def record_trigger(self, event_id: str):
        """Record when an event was last triggered."""
        if event_id in self._registrations:
            self._registrations[event_id].last_triggered = datetime.now()
            self._save_registrations()

class LocalFlowEventHandler(FileSystemEventHandler):
    """Handle file system events and trigger workflows."""

    def __init__(
        self, 
        workflow_registry, 
        event_registry: EventRegistry,
        config: Config
    ):
        """
        Initialize event handler.

        Args:
            workflow_registry: Registry containing available workflows
            config: LocalFlow configuration
        """
        self.workflow_registry = workflow_registry
        self.event_registry = event_registry
        self.config = config
        self.logger = logging.getLogger("LocalFlow.EventHandler")

    def get_file_info(self, path: str) -> dict:
        """
        Get detailed file information.

        Args:
            path: Path to the file

        Returns:
            dict: File information including size, owner, group, etc.
        """
        try:
            stat = os.stat(path)
            return {
                "path": path,
                "size": stat.st_size,
                "owner": pwd.getpwuid(stat.st_uid).pw_name,
                "group": grp.getgrgid(stat.st_gid).gr_name,
                "mode": stat.st_mode,
                "created": stat.st_ctime,
                "modified": stat.st_mtime,
            }
        except (OSError, KeyError) as e:
            self.logger.error(f"Error getting file info for {path}: {e}")
            return {"path": path}

    def trigger_workflows(self, event_type: str, file_info: dict):
        """Check and trigger matching workflows."""
        registrations = self.event_registry.list_registrations(enabled_only=True)
        
        for reg in registrations:
            if reg.event_type == event_type:
                if reg.trigger.matches(file_info):
                    self.logger.info(
                        f"Event {reg.id} triggered for {event_type} "
                        f"on {file_info['path']}"
                    )
                    
                    # Use workflow registry to find workflow
                    workflows = self.workflow_registry.find_workflows()
                    matching_workflow = None
                    
                    # Check both ID and name
                    for wf in workflows:
                        if (wf.id == reg.workflow_id or
                            wf.name.lower().replace(" ", "_") == reg.workflow_id):
                            matching_workflow = wf
                            break
                    
                    if matching_workflow:
                        try:
                            executor = WorkflowExecutor(
                                matching_workflow.source, 
                                self.config
                            )
                            if reg.job_ids:
                                for job_id in reg.job_ids:
                                    executor.execute_job(job_id)
                            else:
                                executor.run()
                            
                            self.event_registry.record_trigger(reg.id)
                            
                        except Exception as e:
                            self.logger.error(
                                f"Error executing workflow {matching_workflow.id}: {e}"
                            )
                    else:
                        self.logger.error(
                            f"Workflow {reg.workflow_id} not found for event {reg.id}"
                        )

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory:
            file_info = self.get_file_info(event.src_path)
            self.trigger_workflows("file_change", file_info)

    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            file_info = self.get_file_info(event.src_path)
            self.trigger_workflows("file_create", file_info)

    def on_deleted(self, event):
        """Handle file deletion events."""
        if not event.is_directory:
            file_info = {"path": event.src_path}
            self.trigger_workflows("file_delete", file_info)


class EventMonitor:
    """File system event monitor for LocalFlow."""

    def __init__(self, config: Config, workflow_registry, event_registry: EventRegistry):
        """
        Initialize event monitor.

        Args:
            config: LocalFlow configuration
            workflow_registry: Registry of available workflows
        """
        self.config = config
        self.workflow_registry = workflow_registry
        self.event_registry = event_registry
        self.logger = logging.getLogger("LocalFlow.EventMonitor")
        self.observer = Observer()
        self.watch_paths: Dict[str, Set[str]] = {}

    def setup_watches(self):
        """Setup directory watches based on registered events."""
        # Clear existing watches
        self.watch_paths.clear()
        
        # Only consider enabled events
        registrations = self.event_registry.list_registrations(enabled_only=True)
        
        # Collect unique paths and their watch requirements
        for reg in registrations:
            for path in reg.trigger.paths:
                path = os.path.expanduser(path)
                if os.path.exists(path):
                    self.watch_paths.setdefault(path, set()).add(
                        reg.trigger.recursive
                    )

        # Setup watches
        handler = LocalFlowEventHandler(
            self.workflow_registry, 
            self.event_registry,
            self.config
        )
        for path, recursive_set in self.watch_paths.items():
            recursive = any(recursive_set)
            self.observer.schedule(handler, path, recursive=recursive)
            self.logger.info(
                f"Watching {path} "
                f"({'recursively' if recursive else 'non-recursively'})"
            )

    def start(self):
        """Start event monitoring."""
        self.setup_watches()
        self.observer.start()
        self.logger.info("Event monitor started")

    def stop(self):
        """Stop event monitoring."""
        self.observer.stop()
        self.observer.join()
        self.logger.info("Event monitor stopped")

