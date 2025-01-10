#!/usr/bin/env python3

"""
events_db_util.py - Utility script for managing LocalFlow's events database.
"""

import argparse
import pickle
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm

from localflow.core import Config
from localflow.core.schema import Event, Workflow, generate_id

# Import LocalFlow classes
try:
    from events import EventRegistration
except ImportError:
    print("Error: LocalFlow package not found in PYTHONPATH.")
    print("Make sure LocalFlow is installed or add its path to PYTHONPATH.")
    sys.exit(1)

console = Console()

class EventsDBManager:
    """Manage LocalFlow's events database."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.registrations = {}
        self.load()

    def load(self) -> None:
        """Load event registrations from database."""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'rb') as f:
                    self.registrations = pickle.load(f)
                console.print(f"Loaded {len(self.registrations)} event registrations.")
            except Exception as e:
                console.print(f"[red]Error loading database: {e}")
                sys.exit(1)
        else:
            console.print("[yellow]No existing database found.")

    def save(self) -> None:
        """Save event registrations to database."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.db_path, 'wb') as f:
                pickle.dump(self.registrations, f)
            console.print(f"[green]Successfully saved {len(self.registrations)} registrations.")
        except Exception as e:
            console.print(f"[red]Error saving database: {e}")
            sys.exit(1)

    def list_events(self) -> None:
        """Display all event registrations."""
        if not self.registrations:
            console.print("[yellow]No event registrations found.")
            return

        table = Table(title="Event Registrations")
        table.add_column("ID")
        table.add_column("Workflow")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Source")
        table.add_column("Last Triggered")

        for reg_id, reg in self.registrations.items():
            last_triggered = reg.last_triggered.strftime("%Y-%m-%d %H:%M:%S") if reg.last_triggered else "Never"
            status = "[green]Enabled" if reg.enabled else "[red]Disabled"
            table.add_row(
                reg_id,
                reg.workflow_id,
                reg.event_type,
                status,
                reg.source,
                last_triggered
            )

        console.print(table)

    def delete_event(self, event_id: str) -> None:
        """Delete an event registration."""
        if event_id in self.registrations:
            reg = self.registrations[event_id]
            if Confirm.ask(f"Delete event {event_id} for workflow {reg.workflow_id}?"):
                del self.registrations[event_id]
                self.save()
                console.print(f"[green]Deleted event {event_id}")
        else:
            console.print(f"[yellow]Event {event_id} not found.")

    def enable_event(self, event_id: str) -> None:
        """Enable an event registration."""
        if event_id in self.registrations:
            self.registrations[event_id].enabled = True
            self.save()
            console.print(f"[green]Enabled event {event_id}")
        else:
            console.print(f"[yellow]Event {event_id} not found.")

    def disable_event(self, event_id: str) -> None:
        """Disable an event registration."""
        if event_id in self.registrations:
            self.registrations[event_id].enabled = False
            self.save()
            console.print(f"[green]Disabled event {event_id}")
        else:
            console.print(f"[yellow]Event {event_id} not found.")

def main():
    parser = argparse.ArgumentParser(description="LocalFlow Events Database Utility")
    parser.add_argument(
        '--db', 
        default='~/.localflow/logs/events.db',
        help='Path to events database (default: ~/.localflow/logs/events.db)'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # List command
    subparsers.add_parser('list', help='List all event registrations')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete event registration')
    delete_parser.add_argument('event_id', help='Event ID to delete')
    
    # Enable command
    enable_parser = subparsers.add_parser('enable', help='Enable event registration')
    enable_parser.add_argument('event_id', help='Event ID to enable')
    
    # Disable command
    disable_parser = subparsers.add_parser('disable', help='Disable event registration')
    disable_parser.add_argument('event_id', help='Event ID to disable')

    args = parser.parse_args()

    # Initialize manager
    manager = EventsDBManager(Path(args.db).expanduser())

    # Execute command
    if args.command == 'list':
        manager.list_events()
    elif args.command == 'delete':
        manager.delete_event(args.event_id)
    elif args.command == 'enable':
        manager.enable_event(args.event_id)
    elif args.command == 'disable':
        manager.disable_event(args.event_id)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
