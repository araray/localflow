"""
Event monitoring and handling for LocalFlow.
Provides file system event monitoring and workflow triggering functionality.
"""

import grp
import logging
import os
import pwd

from typing import Dict, Set

from watchdog.events import (FileCreatedEvent, FileDeletedEvent,
                             FileModifiedEvent, FileSystemEventHandler)
from watchdog.observers import Observer

from config import Config
from executor import WorkflowExecutor



class LocalFlowEventHandler(FileSystemEventHandler):
    """Handle file system events and trigger workflows."""

    def __init__(self, workflow_registry, config: Config):
        """
        Initialize event handler.

        Args:
            workflow_registry: Registry containing available workflows
            config: LocalFlow configuration
        """
        self.workflow_registry = workflow_registry
        self.config = config
        self.logger = logging.getLogger('LocalFlow.EventHandler')

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
                'path': path,
                'size': stat.st_size,
                'owner': pwd.getpwuid(stat.st_uid).pw_name,
                'group': grp.getgrgid(stat.st_gid).gr_name,
                'mode': stat.st_mode,
                'created': stat.st_ctime,
                'modified': stat.st_mtime
            }
        except (OSError, KeyError) as e:
            self.logger.error(f"Error getting file info for {path}: {e}")
            return {'path': path}

    def trigger_workflows(self, event_type: str, file_info: dict):
        """
        Check and trigger matching workflows.

        Args:
            event_type: Type of event (create, modify, delete)
            file_info: Information about the affected file
        """
        for workflow in self.workflow_registry.find_workflows():
            for event in workflow.events:
                if event.type == event_type:
                    if event.trigger.matches(file_info):
                        self.logger.info(
                            f"Triggering workflow {workflow.id} "
                            f"for {event_type} event on {file_info['path']}"
                        )
                        try:
                            executor = WorkflowExecutor(
                                workflow.source,
                                self.config
                            )
                            if event.job_ids:
                                for job_id in event.job_ids:
                                    executor.execute_job(job_id)
                            else:
                                executor.run()
                        except Exception as e:
                            self.logger.error(
                                f"Error executing workflow {workflow.id}: {e}"
                            )

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory:
            file_info = self.get_file_info(event.src_path)
            self.trigger_workflows('file_change', file_info)

    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            file_info = self.get_file_info(event.src_path)
            self.trigger_workflows('file_create', file_info)

    def on_deleted(self, event):
        """Handle file deletion events."""
        if not event.is_directory:
            file_info = {'path': event.src_path}
            self.trigger_workflows('file_delete', file_info)

class EventMonitor:
    """File system event monitor for LocalFlow."""

    def __init__(self, config: Config, workflow_registry):
        """
        Initialize event monitor.

        Args:
            config: LocalFlow configuration
            workflow_registry: Registry of available workflows
        """
        self.config = config
        self.workflow_registry = workflow_registry
        self.logger = logging.getLogger('LocalFlow.EventMonitor')
        self.observer = Observer()
        self.watch_paths: Dict[str, Set[str]] = {}

    def setup_watches(self):
        """Setup directory watches based on workflow event triggers."""
        # Clear existing watches
        self.watch_paths.clear()

        # Collect unique paths and their watch requirements
        for workflow in self.workflow_registry.find_workflows():
            for event in workflow.events:
                for path in event.trigger.paths:
                    path = os.path.expanduser(path)
                    if os.path.exists(path):
                        self.watch_paths.setdefault(path, set()).add(
                            event.trigger.recursive
                        )

        # Setup watches
        handler = LocalFlowEventHandler(
            self.workflow_registry,
            self.config
        )
        for path, recursive_set in self.watch_paths.items():
            recursive = any(recursive_set)  # If any trigger wants recursive
            self.observer.schedule(
                handler,
                path,
                recursive=recursive
            )
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
