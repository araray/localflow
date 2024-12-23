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
import sys
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

import click
import docker
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.panel import Panel
from rich.markup import escape

# Initialize Rich console for beautiful output
console = Console()

@dataclass
class Config:
    """Configuration settings for LocalFlow."""
    workflows_dir: Path
    log_dir: Path
    log_level: str
    docker_enabled: bool
    docker_default_image: str
    show_output: bool
    default_shell: str

    @classmethod
    def load_from_file(cls, config_path: Optional[Path]) -> 'Config':
        """Load configuration from a YAML file with proper error handling."""
        try:
            config_data = {}

            if config_path and config_path.exists():
                with open(config_path) as f:
                    loaded_data = yaml.safe_load(f)
                    if loaded_data:
                        config_data = loaded_data

            # Create configuration with proper path expansion
            return cls(
                workflows_dir=Path(os.path.expanduser(config_data.get('workflows_dir', '~/.localflow/workflows'))),
                log_dir=Path(os.path.expanduser(config_data.get('log_dir', '~/.localflow/logs'))),
                log_level=config_data.get('log_level', 'INFO'),
                docker_enabled=config_data.get('docker_enabled', False),
                docker_default_image=config_data.get('docker_default_image', 'ubuntu:latest'),
                show_output=config_data.get('show_output', True),
                default_shell=config_data.get('default_shell', '/bin/bash')
            )
        except Exception as e:
            console.print(f"[red]Error loading configuration: {e}[/red]")
            return cls.get_defaults()

    @classmethod
    def get_defaults(cls) -> 'Config':
        """Get default configuration."""
        return cls(
            workflows_dir=Path('~/.localflow/workflows').expanduser(),
            log_dir=Path('~/.localflow/logs').expanduser(),
            log_level='INFO',
            docker_enabled=False,
            docker_default_image='ubuntu:latest',
            show_output=True,
            default_shell='/bin/bash'
        )

    def ensure_directories(self) -> None:
        """Ensure required directories exist."""
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

class LocalFlowLogger:
    """Custom logger for LocalFlow with rich output support."""
    def __init__(self, config: Config, workflow_name: str):
        self.config = config
        self.workflow_name = workflow_name
        self.log_file = self._setup_log_file()
        self.logger = self._setup_logger()

    def _setup_log_file(self) -> Path:
        """Setup log file with timestamp."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = self.config.log_dir / f"{self.workflow_name}_{timestamp}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        return log_file

    def _setup_logger(self) -> logging.Logger:
        """Setup logger with both file and console handlers."""
        logger = logging.getLogger(f'LocalFlow.{self.workflow_name}')
        logger.setLevel(self.config.log_level)
        logger.handlers = []  # Clear any existing handlers

        # File handler
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(file_handler)

        # Console handler (using Rich)
        if self.config.show_output:
            console_handler = RichHandler(console=console, show_path=False)
            logger.addHandler(console_handler)

        return logger

class DockerExecutor:
    """Handle Docker-based execution of workflow steps."""
    def __init__(self, config: Config):
        self.config = config
        self.client = docker.from_env() if config.docker_enabled else None

    def run_in_container(self, command: str, env: Dict[str, str], working_dir: str) -> dict:
        """Run a command in a Docker container with proper error handling."""
        if not self.client:
            return {'exit_code': 1, 'output': 'Docker is not enabled'}

        try:
            container = self.client.containers.run(
                self.config.docker_default_image,
                command=command,
                environment=env,
                working_dir=working_dir,
                volumes={working_dir: {'bind': working_dir, 'mode': 'rw'}},
                detach=True
            )

            output = container.wait()
            logs = container.logs().decode()
            container.remove()

            return {
                'exit_code': output['StatusCode'],
                'output': logs
            }
        except Exception as e:
            return {
                'exit_code': 1,
                'output': f"Docker execution failed: {str(e)}"
            }

class WorkflowExecutor:
    """Execute workflow files with enhanced logging and Docker support."""
    def __init__(self, workflow_path: Path, config: Config):
        self.workflow_path = workflow_path
        self.config = config
        self.logger = LocalFlowLogger(config, workflow_path.stem).logger
        self.docker_executor = DockerExecutor(config) if config.docker_enabled else None

    def load_workflow(self) -> Dict[str, Any]:
        """Load and validate workflow file."""
        try:
            with open(self.workflow_path) as f:
                workflow_data = yaml.safe_load(f)

                # Basic validation
                if not isinstance(workflow_data, dict):
                    raise ValueError("Workflow must be a YAML dictionary")
                if 'jobs' not in workflow_data:
                    raise ValueError("Workflow must contain a 'jobs' section")

                return workflow_data
        except Exception as e:
            raise ValueError(f"Failed to load workflow file: {e}")

    def execute_step(self, step: dict, env: Dict[str, str] = None) -> bool:
        """Execute a single workflow step with enhanced logging and Docker support."""
        step_name = step.get('name', 'Unnamed step')
        command = step.get('run')
        working_dir = step.get('working-directory', str(self.workflow_path.parent))

        if not command:
            self.logger.error(f"Step '{step_name}' is missing required 'run' field")
            return False

        self.logger.info(f"Executing step: {step_name}")
        self.logger.debug(f"Command: {command}")
        self.logger.debug(f"Working directory: {working_dir}")

        # Prepare environment
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        if step.get('env'):
            full_env.update(step['env'])

        try:
            if self.config.docker_enabled and not step.get('local', False):
                result = self.docker_executor.run_in_container(command, full_env, working_dir)
            else:
                # Local execution
                process = subprocess.run(
                    command,
                    shell=True,
                    cwd=working_dir,
                    env=full_env,
                    text=True,
                    capture_output=True
                )
                result = {
                    'exit_code': process.returncode,
                    'output': process.stdout + process.stderr
                }

            if result['output']:
                if self.config.show_output:
                    console.print(result['output'])
                self.logger.debug(f"Output: {result['output']}")

            success = result['exit_code'] == 0
            if not success:
                self.logger.error(f"Step '{step_name}' failed with exit code {result['exit_code']}")
            return success

        except Exception as e:
            self.logger.error(f"Failed to execute step '{step_name}': {e}")
            return False

    def execute_job(self, job_name: str, job_data: dict, workflow_env: Dict[str, str]) -> bool:
        """Execute all steps in a job."""
        self.logger.info(f"Starting job: {job_name}")

        # Prepare job environment
        job_env = workflow_env.copy()
        if job_data.get('env'):
            job_env.update(job_data['env'])

        for step in job_data.get('steps', []):
            if not self.execute_step(step, job_env):
                return False

        return True

    def run_job(self, job_name: str) -> bool:
        """Execute a specific job from the workflow."""
        try:
            workflow = self.load_workflow()
            workflow_env = workflow.get('env', {})

            # Check if job exists
            if job_name not in workflow.get('jobs', {}):
                raise ValueError(
                    f"Job '{job_name}' not found in workflow. "
                    f"Use 'localflow jobs {self.workflow_path.name}' to list available jobs."
                )

            # Get job data
            job_data = workflow['jobs'][job_name]

            # Check job dependencies
            needs = job_data.get('needs', [])
            if needs:
                self.logger.warning(
                    f"Running job '{job_name}' without its dependencies: {', '.join(needs)}"
                )

            # Execute the job
            return self.execute_job(job_name, job_data, workflow_env)

        except Exception as e:
            self.logger.error(f"Job execution failed: {e}")
            return False

    def run(self) -> bool:
        """Execute the entire workflow."""
        try:
            workflow = self.load_workflow()
            workflow_env = workflow.get('env', {})

            for job_name, job_data in workflow.get('jobs', {}).items():
                if not self.execute_job(job_name, job_data, workflow_env):
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Workflow execution failed: {e}")
            return False

def resolve_workflow_path(workflows_dir: Path, workflow_name: str) -> Path:
    """
    Resolve workflow path from name, supporting both direct paths and names from workflows directory.
    Also handles both .yml and .yaml extensions.
    """
    # First, check if it's a direct path
    direct_path = Path(workflow_name)
    if direct_path.exists():
        return direct_path.resolve()

    # Remove any extension from the workflow name
    base_name = Path(workflow_name).stem

    # Check both extensions in the workflows directory
    for ext in ['.yml', '.yaml']:
        workflow_path = workflows_dir / f"{base_name}{ext}"
        if workflow_path.exists():
            return workflow_path.resolve()

    # If we get here, the workflow wasn't found
    raise FileNotFoundError(
        f"Workflow '{workflow_name}' not found in {workflows_dir}. "
        f"Available workflows can be listed using 'localflow list'"
    )

def resolve_config_path(config_path: Optional[str]) -> Optional[Path]:
    """Resolve configuration file path with environment variable support."""
    if not config_path:
        config_path = os.environ.get('LOCALFLOW_CONFIG')

    if config_path:
        return Path(os.path.expanduser(config_path)).resolve()
    return None

@click.group()
@click.option('--config', '-c', type=click.Path(exists=True),
              help='Path to configuration file',
              default=lambda: os.environ.get('LOCALFLOW_CONFIG'))
@click.option('--debug/--no-debug', default=False, help='Enable debug mode')
@click.option('--quiet/--no-quiet', default=False, help='Suppress console output')
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
            cfg.log_level = 'DEBUG'
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
@click.argument('workflow')
@click.option('--job', '-j', help='Specific job to run')
@click.option('--docker/--no-docker', help='Override Docker setting')
@click.pass_obj
def run(config: Config, workflow: str, job: str, docker: bool):
    """Run a workflow file or a specific job within it"""
    try:
        # Resolve the workflow path
        workflow_path = resolve_workflow_path(config.workflows_dir, workflow)

        if docker is not None:
            config.docker_enabled = docker

        executor = WorkflowExecutor(workflow_path, config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task_desc = f"Running job '{job}' from" if job else "Running"
            task = progress.add_task(
                f"{task_desc} workflow: {workflow_path.name}"
            )

            if job:
                # Run specific job
                success = executor.run_job(job)
            else:
                # Run entire workflow
                success = executor.run()

            progress.update(task, completed=True)

        if not success:
            sys.exit(1)

    except FileNotFoundError as e:
        console.print(f"[red]{str(e)}[/red]")
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
        # Ensure workflows directory exists
        config.workflows_dir.mkdir(parents=True, exist_ok=True)

        # First, collect all workflow files with both extensions
        yml_files = config.workflows_dir.glob('*.yml')
        yaml_files = config.workflows_dir.glob('*.yaml')

        # Convert paths to strings for sorting and combine them
        workflow_paths = sorted(
            [path for path in (*yml_files, *yaml_files)],
            key=lambda p: str(p)  # Use string representation for sorting
        )

        if not workflow_paths:
            console.print(Panel("""
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
""", title="No Workflows Found", border_style="yellow"))
            return

        # Create and populate the table
        table = Table(
            title="Available Workflows",
            show_header=True,
            header_style="bold blue",
            border_style="blue"
        )

        table.add_column("Name", justify="left", no_wrap=True)
        table.add_column("Description", justify="left", no_wrap=False)
        table.add_column("Version", justify="left", no_wrap=True)
        table.add_column("Author", justify="left", no_wrap=True)
        table.add_column("Last Modified", justify="left")
        table.add_column("Size", justify="right")

        for workflow_path in workflow_paths:
            try:
                with open(workflow_path, 'r') as file:
                    workflow_data = yaml.safe_load(file) or {}

                stats = workflow_path.stat()
                table.add_row(
                    workflow_path.name,
                    workflow_data.get('description', 'No description'),
                    workflow_data.get('version', 'N/A'),
                    workflow_data.get('author', 'Unknown'),
                    datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    f"{stats.st_size / 1024:.1f} KB"
                )
            except Exception as e:
                # If there's an error reading a workflow, show it as invalid but don't crash
                table.add_row(
                    workflow_path.name,
                    f"[red]Error: {str(e)}[/red]",
                    "Invalid",
                    "Invalid",
                    datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    f"{stats.st_size / 1024:.1f} KB"
                )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error listing workflows: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()

@cli.command()
@click.argument('workflow')
@click.pass_obj
def jobs(config: Config, workflow: str):
    """List available jobs in a workflow"""
    try:
        # Resolve the workflow path
        workflow_path = resolve_workflow_path(config.workflows_dir, workflow)

        # Load and parse the workflow
        with open(workflow_path) as f:
            workflow_data = yaml.safe_load(f)

        if not workflow_data or 'jobs' not in workflow_data:
            console.print(f"[red]No jobs found in workflow: {workflow_path.name}[/red]")
            return

        # Create the jobs table
        table = Table(
            title=f"Jobs in {workflow_path.name}",
            show_header=True,
            header_style="bold blue",
            border_style="blue"
        )

        table.add_column("Job Name", justify="left", no_wrap=True)
        table.add_column("Description", justify="left")
        table.add_column("Steps", justify="center")
        table.add_column("Dependencies", justify="left")
        table.add_column("Environment", justify="left")

        # Add job information to the table
        for job_name, job_data in workflow_data['jobs'].items():
            # Count steps
            steps = job_data.get('steps', [])
            steps_count = len(steps)

            # Get dependencies
            needs = job_data.get('needs', [])
            needs_str = ', '.join(needs) if needs else 'None'

            # Get environment variables
            env = job_data.get('env', {})
            env_str = ', '.join(f'{k}={v}' for k, v in env.items()) if env else 'None'

            # Get job description (support both direct description and name fields)
            description = job_data.get('description', job_data.get('name', 'No description'))

            table.add_row(
                job_name,
                description,
                str(steps_count),
                needs_str,
                env_str
            )

        console.print("\n")  # Add some spacing

        # Print workflow metadata
        metadata_panel = Panel(
            f"""
[bold]Workflow:[/bold] {workflow_data.get('name', workflow_path.name)}
[bold]Description:[/bold] {workflow_data.get('description', 'No description')}
[bold]Version:[/bold] {workflow_data.get('version', 'N/A')}
[bold]Author:[/bold] {workflow_data.get('author', 'Unknown')}
            """.strip(),
            title="Workflow Information",
            border_style="blue"
        )
        console.print(metadata_panel)
        console.print("\n")  # Add some spacing

        # Print the jobs table
        console.print(table)

        # Print usage hint
        console.print("\n[dim]To run a specific job, use:[/dim]")
        console.print(f"[dim]  localflow run {workflow_path.name} --job <job_name>[/dim]")

    except FileNotFoundError as e:
        console.print(f"[red]{str(e)}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error listing jobs: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()
        sys.exit(1)

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
            border_style="blue"
        )

        table.add_column("Setting", style="bold")
        table.add_column("Value")
        table.add_column("Description")

        # Configuration descriptions for better understanding
        descriptions = {
            'workflows_dir': 'Directory containing workflow files',
            'log_dir': 'Directory for log files',
            'log_level': 'Logging verbosity level',
            'docker_enabled': 'Whether Docker execution is enabled',
            'docker_default_image': 'Default Docker image for containerized steps',
            'show_output': 'Whether to show command output in console',
            'default_shell': 'Default shell for executing commands'
        }

        for key, value in asdict(config).items():
            table.add_row(
                str(key),
                str(value),
                descriptions.get(key, 'No description available')
            )

        # Print configuration source
        config_source = os.environ.get('LOCALFLOW_CONFIG', 'Using default configuration')
        console.print(f"\n[dim]Configuration source: {config_source}[/dim]\n")

        # Print the configuration table
        console.print(table)

        # Print help text for modifying configuration
        console.print("\n[dim]To use a different configuration file:[/dim]")
        console.print("[dim]  1. Set LOCALFLOW_CONFIG environment variable[/dim]")
        console.print("[dim]  2. Use --config option: localflow --config path/to/config.yaml <command>[/dim]")

    except Exception as e:
        console.print(f"[red]Error displaying configuration: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()

if __name__ == '__main__':
    cli()
