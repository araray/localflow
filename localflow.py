#!/usr/bin/env python3
"""
LocalFlow - A local workflow executor inspired by GitHub Actions.
This tool allows running workflows defined in YAML locally or in Docker containers.

Key features:
- YAML-based workflow definitions
- Local and Docker execution support
- Job-level granular execution
- Rich console output and logging
- Flexible configuration management
"""

import logging
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import click
import psutil
import yaml
from daemon import DaemonContext
from daemon.pidfile import PIDLockFile
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from config import Config, OutputConfig
from events import EventRegistry
from executor import DockerExecutor, WorkflowExecutor
from monitor_service import LocalFlowMonitorService
from schema import WorkflowRegistry

# Initialize Rich console for beautiful output
console = Console()

class OutputMode(str, Enum):
    """Output modes for workflow execution"""

    STDOUT = "stdout"  # Output only to stdout
    FILE = "file"  # Output only to file
    BOTH = "both"  # Output to both stdout and file


@dataclass
class OutputConfig:
    """Configuration for workflow output handling"""

    file: Optional[Path] = None
    mode: OutputMode = OutputMode.STDOUT
    stdout: bool = True
    append: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "OutputConfig":
        """Create OutputConfig from dictionary (usually from YAML)"""
        if not data:
            return cls()

        return cls(
            file=(
                Path(os.path.expanduser(data.get("file", ""))).resolve()
                if data.get("file")
                else None
            ),
            mode=OutputMode(data.get("mode", "stdout")),
            stdout=data.get("stdout", True),
            append=data.get("append", False),
        )

    def merge_with_cli(
        self, output_file: Optional[str], output_mode: str, append: bool
    ) -> "OutputConfig":
        """Merge this config with CLI options, giving precedence to CLI"""
        return OutputConfig(
            file=Path(output_file).resolve() if output_file else self.file,
            mode=OutputMode(output_mode) if output_mode else self.mode,
            stdout=self.stdout,
            append=append if append is not None else self.append,
        )


class LocalFlowLogger:
    """Custom logger for LocalFlow with rich output support."""

    def __init__(self, config: Config, workflow_name: str):
        self.config = config
        self.workflow_name = workflow_name
        self.log_file = self._setup_log_file()
        self.logger = self._setup_logger()

    def _setup_log_file(self) -> Path:
        """Setup log file with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.config.log_dir / f"{self.workflow_name}_{timestamp}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        return log_file

    def _setup_logger(self) -> logging.Logger:
        """Setup logger with both file and console handlers."""
        logger = logging.getLogger(f"LocalFlow.{self.workflow_name}")
        logger.setLevel(self.config.log_level)
        logger.handlers = []  # Clear any existing handlers

        # File handler
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)

        # Console handler (using Rich)
        if self.config.show_output:
            console_handler = RichHandler(console=console, show_path=False)
            logger.addHandler(console_handler)

        return logger


def resolve_workflow_path(
    workflows_dir: Path, workflow_id: str, local_dir: Optional[Path] = None
) -> Path:
    """
    Resolve workflow path from ID, checking both local and global directories.

    Args:
        workflows_dir: Global workflows directory from config
        workflow_id: ID of the workflow to find
        local_dir: Optional local workflows directory

    Returns:
        Path: Resolved path to the workflow file

    Raises:
        FileNotFoundError: If workflow cannot be found
    """

    def find_workflow_in_dir(directory: Path) -> Optional[Path]:
        """Helper to find workflow in a directory."""
        if directory.exists():
            for ext in [".yml", ".yaml"]:
                for path in directory.glob(f"*{ext}"):
                    try:
                        with open(path) as f:
                            data = yaml.safe_load(f)
                            if data and data.get("id") == workflow_id:
                                return path.resolve()
                    except Exception:
                        continue
        return None

    # First check local directory (prioritize local_dir parameter if provided)
    search_local_dir = local_dir if local_dir else Path(".localflow")
    if local_path := find_workflow_in_dir(search_local_dir):
        return local_path

    # Then check global directory
    if global_path := find_workflow_in_dir(workflows_dir):
        return global_path

    raise FileNotFoundError(
        f"Workflow '{workflow_id}' not found in either local directory at {search_local_dir} "
        f"or global workflows directory at {workflows_dir}. "
        f"Available workflows can be listed using 'localflow list'"
    )


def resolve_config_path(config_path: Optional[str] = None) -> Path:
    """
    Resolve configuration file path.
    
    Args:
        config_path: Optional explicit path to config file
        
    Returns:
        Path to configuration file
    """
    # Try environment variable first
    if not config_path:
        config_path = os.environ.get("LOCALFLOW_CONFIG")
    
    # Then try default locations
    if not config_path:
        candidates = [
            Path("config.yml"),  # Current directory
            Path("~/.localflow/config.yml"),  # User home
            Path("/etc/localflow/config.yml"),  # System-wide
        ]
        
        for path in candidates:
            path = path.expanduser().resolve()
            if path.exists():
                return path
    else:
        path = Path(config_path).expanduser().resolve()
        if path.exists():
            return path
            
    # If no config found, use default in current directory
    return Path("config.yml").resolve()

def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from file.
    
    Args:
        config_path: Optional explicit path to config file
        
    Returns:
        Loaded configuration
    """
    path = resolve_config_path(config_path)
    return Config.load_from_file(path)

@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="Path to configuration file",
    default=lambda: os.environ.get("LOCALFLOW_CONFIG"),
)
@click.option("--debug/--no-debug", default=False, help="Enable debug mode")
@click.option("--quiet/--no-quiet", default=False, help="Suppress console output")
@click.pass_context
def cli(ctx, config, debug, quiet):
    """LocalFlow - A local workflow executor"""
    # Ensure we have a context object
    ctx.ensure_object(dict)

    try:
        # Resolve and load configuration
        config_path = resolve_config_path(config)
        cfg = Config.load_from_file(config_path)

        # Override configuration based on CLI options
        if debug:
            cfg.log_level = "DEBUG"
        if quiet:
            cfg.show_output = False

        # Ensure required directories exist
        cfg.ensure_directories()

        # Store configuration in context
        ctx.obj = cfg

    except Exception as e:
        console.print(f"[red]Error initializing LocalFlow: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.pass_obj
@click.argument("workflow")
@click.option("--job", "-j", help="Specific job to run")
@click.option("--docker/--no-docker", help="Override Docker setting")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option(
    "--output-mode",
    type=click.Choice(["stdout", "file", "both"]),
    help="Output destination mode",
)
@click.option(
    "--append/--no-append", help="Append to output file instead of overwriting"
)
def run(
    config: Config,
    workflow: str,
    job: str,
    docker: bool,
    output: Optional[str],
    output_mode: str,
    append: bool,
):
    """Run a workflow file or specific job with output handling"""
    try:
        # Pass local_workflows_dir from config
        workflow_path = resolve_workflow_path(
            config.workflows_dir, workflow, local_dir=config.local_workflows_dir
        )
        if docker is not None:
            config.docker_enabled = docker

        executor = WorkflowExecutor(workflow_path, config)

        # Merge CLI output options with workflow config
        if output or output_mode or append:
            executor.output_config = executor.output_config.merge_with_cli(
                output, output_mode, append
            )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task_desc = f"Running job '{job}' from" if job else "Running"
            task = progress.add_task(f"{task_desc} workflow: {workflow_path.name}")

            if job:
                success = executor.execute_job(job)
            else:
                success = executor.run()

            progress.update(task, completed=True)

        if not success:
            sys.exit(1)

    except Exception as e:
        console.print(f"[red]Error running workflow: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()
        sys.exit(1)


@cli.command()
@click.pass_obj
def list(config: Config):
    """List available workflows"""
    try:
        # Initialize workflow registry
        registry = WorkflowRegistry()

        # Discover workflows from both global and local directories
        registry.discover_workflows(config.workflows_dir, config.local_workflows_dir)

        workflows = registry.find_workflows()

        if not workflows:
            console.print(
                Panel(
                    """
No workflows found. To get started, create a workflow file like this:

[blue]example-workflow.yml:[/blue]
name: Example Workflow
description: A simple example workflow
version: 1.0.0
author: Your Name

jobs:
  hello:
    name: Hello World
    description: A simple greeting job
    steps:
      - name: Say Hello
        run: echo "Hello, LocalFlow!"
""",
                    title="No Workflows Found",
                    border_style="yellow",
                )
            )
            return

        # Create and populate the table
        table = Table(
            title="Available Workflows",
            show_header=True,
            header_style="bold blue",
            border_style="blue",
        )

        table.add_column("ID", justify="left", no_wrap=True)
        table.add_column("Name", justify="left", no_wrap=True)
        table.add_column("Description", justify="left", no_wrap=False)
        table.add_column("Tags", justify="left", no_wrap=True)
        table.add_column("Version", justify="left", no_wrap=True)
        table.add_column("Author", justify="left", no_wrap=True)
        table.add_column("Location", justify="left", no_wrap=True)

        for workflow in workflows:
            location = (
                "Local"
                if workflow.source.parent == config.local_workflows_dir
                else "Global"
            )
            table.add_row(
                workflow.id,
                workflow.name,
                workflow.description or "No description",
                ", ".join(sorted(workflow.tags)) or "None",
                workflow.version,
                workflow.author or "Unknown",
                location,
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error listing workflows: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()


@cli.command()
@click.argument("workflow_id")
@click.pass_obj
def jobs(config: Config, workflow_id: str):
    """List available jobs in a workflow"""
    try:
        # Initialize registry and discover workflows
        registry = WorkflowRegistry()
        registry.discover_workflows(config.workflows_dir, config.local_workflows_dir)

        # Get workflow
        workflow = registry.get_workflow(workflow_id)
        if not workflow:
            console.print(f"[red]No workflow found with ID: {workflow_id}[/red]")
            return

        # Create the jobs table
        table = Table(
            title=f"Jobs in {workflow.name}",
            show_header=True,
            header_style="bold blue",
            border_style="blue",
        )

        table.add_column("ID", justify="left", no_wrap=True)
        table.add_column("Name", justify="left", no_wrap=True)
        table.add_column("Description", justify="left")
        table.add_column("Tags", justify="left")
        table.add_column("Dependencies", justify="left")
        table.add_column("Condition", justify="left")

        # Add job information
        for job in workflow.jobs.values():
            table.add_row(
                job.id,
                job.name,
                job.description or "No description",
                ", ".join(sorted(job.tags)) or "None",
                ", ".join(sorted(job.needs)) or "None",
                job.condition.expression if job.condition else "None",
            )

        console.print("\n")  # Add spacing
        console.print(table)

        # Print usage hint
        console.print("\n[dim]To run a specific job, use:[/dim]")
        console.print(f"[dim]  localflow run {workflow_id} --job <job_id>[/dim]")

    except Exception as e:
        console.print(f"[red]Error listing jobs: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()


@cli.command()
@click.pass_obj
def config(config: Config):
    """Show current configuration"""
    try:
        # Create the configuration table
        table = Table(
            title="Current Configuration",
            show_header=True,
            header_style="bold blue",
            border_style="blue",
        )

        table.add_column("Setting", style="bold")
        table.add_column("Value")
        table.add_column("Description")

        # Configuration descriptions for better understanding
        descriptions = {
            "workflows_dir": "Directory containing workflow files",
            "log_dir": "Directory for log files",
            "log_level": "Logging verbosity level",
            "docker_enabled": "Whether Docker execution is enabled",
            "docker_default_image": "Default Docker image for containerized steps",
            "show_output": "Whether to show command output in console",
            "default_shell": "Default shell for executing commands",
        }

        for key, value in asdict(config).items():
            table.add_row(
                str(key), str(value), descriptions.get(key, "No description available")
            )

        # Print configuration source
        config_source = os.environ.get(
            "LOCALFLOW_CONFIG", "Using default configuration"
        )
        console.print(f"\n[dim]Configuration source: {config_source}[/dim]\n")

        # Print the configuration table
        console.print(table)

        # Print help text for modifying configuration
        console.print("\n[dim]To use a different configuration file:[/dim]")
        console.print("[dim]  1. Set LOCALFLOW_CONFIG environment variable[/dim]")
        console.print(
            "[dim]  2. Use --config option: localflow --config path/to/config.yaml <command>[/dim]"
        )

    except Exception as e:
        console.print(f"[red]Error displaying configuration: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()


@cli.group()
def events():
    """Manage event monitoring and triggers"""
    pass


@events.command("list")
@click.pass_obj
def list_events(config: Config):
    """List configured event triggers"""
    try:
        # Initialize registry and discover workflows
        registry = WorkflowRegistry()
        registry.discover_workflows(config.workflows_dir, config.local_workflows_dir)

        # Create table for events
        table = Table(
            title="Configured Event Triggers",
            show_header=True,
            header_style="bold blue",
            border_style="blue",
        )

        table.add_column("Workflow", justify="left")
        table.add_column("Event Type", justify="left")
        table.add_column("Paths", justify="left")
        table.add_column("Patterns", justify="left")
        table.add_column("Recursive", justify="center")
        table.add_column("Conditions", justify="left")

        # Collect events from all workflows
        for workflow in registry.find_workflows():
            for event in workflow.events:
                conditions = []
                if event.trigger.min_size:
                    conditions.append(f"min_size: {event.trigger.min_size}")
                if event.trigger.max_size:
                    conditions.append(f"max_size: {event.trigger.max_size}")
                if event.trigger.owner:
                    conditions.append(f"owner: {event.trigger.owner}")
                if event.trigger.group:
                    conditions.append(f"group: {event.trigger.group}")

                table.add_row(
                    workflow.name,
                    event.type,
                    "\n".join(event.trigger.paths),
                    "\n".join(event.trigger.patterns),
                    "✓" if event.trigger.recursive else "✗",
                    "\n".join(conditions) or "None",
                )

        console.print("\n")
        console.print(table)
        console.print("\n[dim]To start monitoring, run: localflow events start[/dim]")

    except Exception as e:
        console.print(f"[red]Error listing events: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()

@events.command()
@click.option("--config", help="Path to config file")
def status(config: Optional[str] = None):
    """Show status of registered events."""
    config = load_config(config)
    event_registry = EventRegistry(config)
    
    registrations = event_registry.list_registrations()
    
    if not registrations:
        click.echo("No events registered")
        return
        
    table = Table(title="Event Registrations")
    table.add_column("ID")
    table.add_column("Workflow")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Source")
    table.add_column("Last Triggered")
    
    for reg in registrations:
        table.add_row(
            reg.id,
            reg.workflow_id,
            reg.event_type,
            "Enabled" if reg.enabled else "Disabled",
            reg.source,
            reg.last_triggered.strftime("%Y-%m-%d %H:%M:%S")
            if reg.last_triggered else "Never"
        )
    
    console = Console()
    console.print(table)

@events.command()
@click.argument("event_id")
@click.option("--config", help="Path to config file")
def enable(event_id: str, config: Optional[str] = None):
    """Enable an event."""
    config = load_config(config)
    event_registry = EventRegistry(config)
    
    if event_registry.enable_event(event_id):
        click.echo(f"Enabled event {event_id}")
    else:
        click.echo(f"Event {event_id} not found", err=True)

@events.command()
@click.argument("event_id")
@click.option("--config", help="Path to config file")
def disable(event_id: str, config: Optional[str] = None):
    """Disable an event."""
    config = load_config(config)
    event_registry = EventRegistry(config)
    
    if event_registry.disable_event(event_id):
        click.echo(f"Disabled event {event_id}")
    else:
        click.echo(f"Event {event_id} not found", err=True)


@events.command()
@click.argument("workflow_id")
@click.option("--config", help="Path to config file")
def unregister(workflow_id: str, config: Optional[str] = None):
    """Unregister all events for a workflow."""
    config = load_config(config)
    event_registry = EventRegistry(config)
    
    unregistered = event_registry.unregister_events(workflow_id)
    if unregistered:
        click.echo(f"Unregistered {len(unregistered)} events for workflow {workflow_id}")
    else:
        click.echo(f"No events found for workflow {workflow_id}")

@events.command("start")
@click.pass_obj
@click.option("--foreground", "-f", is_flag=True, help="Run in foreground (no daemon)")
def start_monitor(config: Config, foreground: bool):
    """Start event monitoring"""
    try:
        # Check if already running
        if config.monitor_pid_file.exists():
            try:
                with open(config.monitor_pid_file) as f:
                    pid = int(f.read().strip())
                process = psutil.Process(pid)
                if process.is_running():
                    console.print("[yellow]Event monitor is already running[/yellow]")
                    return
                config.monitor_pid_file.unlink()
            except (ProcessLookupError, ValueError, FileNotFoundError):
                config.monitor_pid_file.unlink()

        if foreground:
            # Run directly (no daemon)
            registry = WorkflowRegistry()
            registry.discover_workflows(
                config.workflows_dir, config.local_workflows_dir
            )

            monitor = EventMonitor(config, registry)

            console.print("[green]Starting event monitor in foreground...[/green]")
            try:
                monitor.start()
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopping event monitor...[/yellow]")
                monitor.stop()
        else:
            # Import and run daemon
            from daemon import DaemonContext
            from daemon.pidfile import PIDLockFile

            # Ensure directories exist
            config.monitor_pid_file.parent.mkdir(parents=True, exist_ok=True)
            config.log_dir.mkdir(parents=True, exist_ok=True)

            # Setup log file
            log_file = config.log_dir / config.monitor_log_file
            console_log = open(log_file, 'a+')

            context = DaemonContext(
                pidfile=PIDLockFile(str(config.monitor_pid_file)),
                working_directory="/",
                stdout=console_log,
                stderr=console_log,
                umask=0o002,
                detach_process=True,
                signal_map={
                    signal.SIGTERM: lambda signo, frame: daemon_cleanup(config),
                    signal.SIGINT: lambda signo, frame: daemon_cleanup(config),
                }
            )

            try:
                with context:
                    service = LocalFlowMonitorService(
                        config_path=str(config.config_file) if config.config_file else None
                    )
                    service.run()

                # Wait a bit to check if daemon started successfully
                time.sleep(1)
                if config.monitor_pid_file.exists():
                    console.print("[green]Event monitor daemon started[/green]")
                else:
                    console.print("[red]Failed to start event monitor daemon[/red]")
            except Exception as e:
                console.print(f"[red]Failed to start monitor: {e}[/red]")
                if config.monitor_pid_file.exists():
                    config.monitor_pid_file.unlink()

    except Exception as e:
        console.print(f"[red]Error starting monitor: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()

@events.command("stop")
@click.pass_obj
def stop_monitor(config: Config):
    """Stop event monitoring daemon"""
    try:
        if not config.monitor_pid_file.exists():
            console.print("[yellow]Event monitor is not running[/yellow]")
            return

        try:
            with open(config.monitor_pid_file) as f:
                pid = int(f.read().strip())

            process = psutil.Process(pid)
            process.terminate()
            
            # Wait for process to stop
            try:
                process.wait(timeout=10)
            except psutil.TimeoutExpired:
                process.kill()  # Force kill if not responding
                process.wait()
                
            if config.monitor_pid_file.exists():
                config.monitor_pid_file.unlink()
            console.print("[green]Event monitor stopped[/green]")
                
        except (ProcessLookupError, FileNotFoundError, ValueError):
            console.print("[yellow]Event monitor process not found[/yellow]")
            if config.monitor_pid_file.exists():
                config.monitor_pid_file.unlink()
        except Exception as e:
            console.print(f"[red]Error stopping monitor: {e}[/red]")

    except Exception as e:
        console.print(f"[red]Error stopping monitor: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()

@events.command("logs")
@click.pass_obj
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=100, help="Number of lines to show")
def show_logs(config: Config, follow: bool, lines: int):
    """Show event monitor logs"""
    try:
        log_file = config.log_dir / config.monitor_log_file

        if not log_file.exists():
            console.print("[yellow]No log file found[/yellow]")
            return

        def display_logs():
            with open(log_file) as f:
                if follow:
                    # Start from end for follow mode
                    f.seek(0, 2)
                else:
                    # Show last N lines
                    for line in tail(f, lines):
                        console.print(line.strip())
                    return

                while follow:
                    line = f.readline()
                    if line:
                        console.print(line.strip())
                    else:
                        time.sleep(0.1)

        if follow:
            try:
                display_logs()
            except KeyboardInterrupt:
                pass
        else:
            display_logs()

    except Exception as e:
        console.print(f"[red]Error showing logs: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()

@events.command("register")
@click.option("--local", is_flag=True, help="Register events from local workflows only")
@click.option("--global", "global_", is_flag=True, help="Register events from global workflows only")
@click.option("--config", help="Path to config file")
def register_events(local: bool, global_: bool, config: Optional[str] = None):
    """Register events from workflows."""
    config = load_config(config)
    registry = WorkflowRegistry()
    event_registry = EventRegistry(config)
    
    if not local and not global_:
        local = global_ = True
    
    registered = []
    
    if local:
        registry.discover_workflows(config.local_workflows_dir)
        for workflow in registry.workflows.values():
            if workflow.events:
                reg_ids = event_registry.register_events(workflow, "local")
                registered.extend(reg_ids)
    
    if global_:
        registry.discover_workflows(config.workflows_dir)
        for workflow in registry.workflows.values():
            if workflow.events:
                reg_ids = event_registry.register_events(workflow, "global")
                registered.extend(reg_ids)
                
    if registered:
        click.echo(f"Registered {len(registered)} events")
    else:
        click.echo("No new events registered")

def daemon_cleanup(config: Config):
    """Clean up daemon resources before exit"""
    try:
        if config.monitor_pid_file.exists():
            config.monitor_pid_file.unlink()
    except Exception:
        pass
    sys.exit(0)

@cli.group()
def daemon():
    """Manage LocalFlow daemon process"""
    pass

@daemon.command()
def start():
    """Start LocalFlow daemon"""
    try:
        service = LocalFlowMonitorService()
        service.run()
        click.echo("LocalFlow daemon started successfully")
    except Exception as e:
        click.echo(f"Failed to start daemon: {e}", err=True)
        sys.exit(1)

@daemon.command()
def stop():
    """Stop LocalFlow daemon"""
    try:
        # Read PID and send SIGTERM
        with open(Config.get_defaults().monitor_pid_file) as f:
            pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
        click.echo("LocalFlow daemon stopped")
    except Exception as e:
        click.echo(f"Failed to stop daemon: {e}", err=True)
        sys.exit(1)

@daemon.command()
def status():
    """Check LocalFlow daemon status"""
    try:
        pid_file = Config.get_defaults().monitor_pid_file
        if not pid_file.exists():
            click.echo("LocalFlow daemon is not running")
            return
        
        with open(pid_file) as f:
            pid = int(f.read().strip())
            try:
                os.kill(pid, 0)  # Check if process exists
                click.echo(f"LocalFlow daemon is running (PID: {pid})")
            except OSError:
                click.echo("LocalFlow daemon is not running (stale PID file)")
    except Exception as e:
        click.echo(f"Failed to check daemon status: {e}", err=True)

def tail(f, lines=1):
    """Read last N lines from file"""
    total_lines_wanted = lines

    BLOCK_SIZE = 1024
    f.seek(0, 2)
    block_end_byte = f.tell()
    lines_to_go = total_lines_wanted
    block_number = -1
    blocks = []

    while lines_to_go > 0 and block_end_byte > 0:
        if block_end_byte - BLOCK_SIZE > 0:
            f.seek(block_number * BLOCK_SIZE, 2)
            blocks.append(f.read(BLOCK_SIZE))
        else:
            f.seek(0, 0)
            blocks.append(f.read(block_end_byte))

        lines_found = blocks[-1].count(b"\n")
        lines_to_go -= lines_found
        block_end_byte -= BLOCK_SIZE
        block_number -= 1

    all_read = b"".join(reversed(blocks))
    return all_read.splitlines()[-total_lines_wanted:]


if __name__ == "__main__":
    cli()
