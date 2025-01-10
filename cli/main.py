"""Workflow-related CLI commands."""

import click
import logging
from pathlib import Path

from localflow.core import WorkflowExecutor, WorkflowRegistry
from localflow.core.config import Config

logger = logging.getLogger(__name__)

@click.group()
def workflows():
    """Workflow management commands."""
    pass

@workflows.command()
@click.argument('workflow_id')
@click.option('--job', help='Specific job to run')
@click.option('--output', help='Output file path')
@click.option('--output-mode', type=click.Choice(['stdout', 'file', 'both']), 
             default='stdout', help='Output mode')
@click.option('--append/--no-append', default=False, help='Append to output file')
@click.pass_context
def run(ctx, workflow_id: str, job: str, output: str, output_mode: str, append: bool):
    """Run a workflow or specific job."""
    config = ctx.obj['config']
    try:
        # Update output config if specified
        if output:
            config.output_config.file = Path(output)
            config.output_config.mode = output_mode
            config.output_config.append = append

        # Find workflow file
        registry = WorkflowRegistry()
        registry.discover_workflows(config.workflows_dir, config.local_workflows_dir)
        workflow = registry.get_workflow(workflow_id)
        
        if not workflow:
            raise click.ClickException(f"Workflow {workflow_id} not found")
            
        executor = WorkflowExecutor(workflow.source, config)
        
        if job:
            success = executor.execute_job(job)
        else:
            success = executor.run()
            
        if not success:
            raise click.ClickException("Workflow execution failed")
            
    except Exception as e:
        logger.error(f"Error running workflow: {e}")
        raise click.ClickException(str(e))

@workflows.command()
@click.option('--tag', multiple=True, help='Filter by tags')
@click.pass_context
def list(ctx, tag):
    """List available workflows."""
    config = ctx.obj['config']
    try:
        registry = WorkflowRegistry()
        registry.discover_workflows(config.workflows_dir, config.local_workflows_dir)
        
        workflows = registry.find_workflows(tags=set(tag) if tag else None)
        
        if not workflows:
            click.echo("No workflows found")
            return
            
        for wf in workflows:
            click.echo(f"\nWorkflow: {wf.name} (ID: {wf.id})")
            if wf.description:
                click.echo(f"Description: {wf.description}")
            if wf.tags:
                click.echo(f"Tags: {', '.join(wf.tags)}")
            click.echo(f"Source: {wf.source}")
            
    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        raise click.ClickException(str(e))

@workflows.command()
@click.argument('workflow_id')
@click.pass_context
def jobs(ctx, workflow_id):
    """List jobs in a workflow."""
    config = ctx.obj['config']
    try:
        registry = WorkflowRegistry()
        registry.discover_workflows(config.workflows_dir, config.local_workflows_dir)
        
        workflow = registry.get_workflow(workflow_id)
        if not workflow:
            raise click.ClickException(f"Workflow {workflow_id} not found")
            
        click.echo(f"\nWorkflow: {workflow.name} (ID: {workflow.id})")
        
        for name, job in workflow.jobs.items():
            click.echo(f"\nJob: {name} (ID: {job.id})")
            if job.description:
                click.echo(f"Description: {job.description}")
            if job.tags:
                click.echo(f"Tags: {', '.join(job.tags)}")
            if job.needs:
                click.echo(f"Depends on: {', '.join(job.needs)}")
                
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise click.ClickException(str(e))

# File: localflow/cli/commands/daemon.py

"""Daemon-related CLI commands."""

import click
import logging
from localflow.services.daemon.service import LocalFlowMonitorService

logger = logging.getLogger(__name__)

@click.group()
def daemon():
    """Daemon management commands."""
    pass

@daemon.command()
@click.option('--foreground', is_flag=True, help='Run in foreground')
@click.pass_context
def start(ctx, foreground):
    """Start the LocalFlow daemon."""
    config = ctx.obj['config']
    try:
        service = LocalFlowMonitorService(config)
        service.start(foreground=foreground)
        click.echo("Daemon started successfully")
    except Exception as e:
        logger.error(f"Failed to start daemon: {e}")
        raise click.ClickException(str(e))

@daemon.command()
@click.pass_context
def stop(ctx):
    """Stop the LocalFlow daemon."""
    config = ctx.obj['config']
    try:
        service = LocalFlowMonitorService(config)
        service.stop()
        click.echo("Daemon stopped successfully")
    except Exception as e:
        logger.error(f"Failed to stop daemon: {e}")
        raise click.ClickException(str(e))

@daemon.command()
@click.pass_context
def status(ctx):
    """Check daemon status."""
    config = ctx.obj['config']
    try:
        service = LocalFlowMonitorService(config)
        running, pid = service.status()
        
        if running:
            click.echo(f"Daemon is running (PID: {pid})")
        else:
            click.echo("Daemon is not running")
            
    except Exception as e:
        logger.error(f"Failed to get daemon status: {e}")
        raise click.ClickException(str(e))

# File: localflow/cli/commands/events.py

"""Event management CLI commands."""

import click
import logging
from localflow.services.events.registry import EventRegistry

logger = logging.getLogger(__name__)

@click.group()
def events():
    """Event management commands."""
    pass

@events.command(name='list')
@click.option('--source', help='Filter by source (local/global)')
@click.option('--workflow', help='Filter by workflow ID')
@click.option('--enabled-only', is_flag=True, help='Show only enabled events')
@click.pass_context
def list_events(ctx, source, workflow, enabled_only):
    """List registered events."""
    config = ctx.obj['config']
    try:
        registry = EventRegistry(config)
        events = registry.list_registrations(
            source=source,
            workflow_id=workflow,
            enabled_only=enabled_only
        )
        
        if not events:
            click.echo("No events registered")
            return
            
        for event in events:
            click.echo(f"\nEvent: {event.id}")
            click.echo(f"Workflow: {event.workflow_id}")
            click.echo(f"Type: {event.event_type}")
            click.echo(f"Source: {event.source}")
            click.echo(f"Enabled: {event.enabled}")
            if event.job_ids:
                click.echo(f"Jobs: {', '.join(event.job_ids)}")
            click.echo(f"Registered: {event.registered_at}")
            if event.last_triggered:
                click.echo(f"Last triggered: {event.last_triggered}")
                
    except Exception as e:
        logger.error(f"Error listing events: {e}")
        raise click.ClickException(str(e))

@events.command()
@click.argument('event_id')
@click.pass_context
def enable(ctx, event_id):
    """Enable an event."""
    config = ctx.obj['config']
    try:
        registry = EventRegistry(config)
        if registry.enable_event(event_id):
            click.echo(f"Event {event_id} enabled")
        else:
            raise click.ClickException(f"Event {event_id} not found")
    except Exception as e:
        logger.error(f"Error enabling event: {e}")
        raise click.ClickException(str(e))

@events.command()
@click.argument('event_id')
@click.pass_context
def disable(ctx, event_id):
    """Disable an event."""
    config = ctx.obj['config']
    try:
        registry = EventRegistry(config)
        if registry.disable_event(event_id):
            click.echo(f"Event {event_id} disabled")
        else:
            raise click.ClickException(f"Event {event_id} not found")
    except Exception as e:
        logger.error(f"Error disabling event: {e}")
        raise click.ClickException(str(e))

# File: localflow/cli/main.py

"""LocalFlow CLI main entry point."""

import click
import logging
import os
from pathlib import Path

from localflow.core.config import Config
from .commands.workflows import workflows
from .commands.daemon import daemon
from .commands.events import events

def resolve_config_path(config_path: str = None) -> Path:
    """Resolve configuration file path."""
    if config_path:
        return Path(config_path)
        
    # Check environment variable
    if 'LOCALFLOW_CONFIG' in os.environ:
        return Path(os.environ['LOCALFLOW_CONFIG'])
        
    # Default location
    return Path('~/.localflow/config.yml').expanduser()

def setup_logging(config: Config):
    """Configure logging based on configuration."""
    log_level = getattr(logging, config.log_level.upper())
    
    # Ensure log directory exists
    config.log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure file and console logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(config.log_dir / 'localflow.log'),
            logging.StreamHandler()
        ]
    )

@click.group()
@click.option('--config', help='Path to config file')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.pass_context
def cli(ctx, config, debug):
    """LocalFlow CLI interface."""
    try:
        # Initialize context
        ctx.ensure_object(dict)
        
        # Load config
        config_path = resolve_config_path(config)
        config_obj = Config.load_from_file(config_path)
        
        # Override log level if debug enabled
        if debug:
            config_obj.log_level = 'DEBUG'
            
        # Setup logging
        setup_logging(config_obj)
        
        # Store in context
        ctx.obj['config'] = config_obj
        
    except Exception as e:
        raise click.ClickException(f"Failed to initialize CLI: {e}")

# Register command groups
cli.add_command(workflows)
cli.add_command(daemon)
cli.add_command(events)

if __name__ == '__main__':
    cli()