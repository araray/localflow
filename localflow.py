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
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, TextIO, Any

import click
import docker
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.panel import Panel


# Initialize Rich console for beautiful output
console = Console()

class OutputMode(str, Enum):
    """Output modes for workflow execution"""
    STDOUT = "stdout"    # Output only to stdout
    FILE = "file"       # Output only to file
    BOTH = "both"       # Output to both stdout and file

@dataclass
class OutputConfig:
    """Configuration for workflow output handling"""
    file: Optional[Path] = None
    mode: OutputMode = OutputMode.STDOUT
    stdout: bool = True
    append: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> 'OutputConfig':
        """Create OutputConfig from dictionary (usually from YAML)"""
        if not data:
            return cls()

        return cls(
            file=Path(os.path.expanduser(data.get('file', ''))).resolve() if data.get('file') else None,
            mode=OutputMode(data.get('mode', 'stdout')),
            stdout=data.get('stdout', True),
            append=data.get('append', False)
        )

    def merge_with_cli(self, output_file: Optional[str], output_mode: str, append: bool) -> 'OutputConfig':
        """Merge this config with CLI options, giving precedence to CLI"""
        return OutputConfig(
            file=Path(output_file).resolve() if output_file else self.file,
            mode=OutputMode(output_mode) if output_mode else self.mode,
            stdout=self.stdout,
            append=append if append is not None else self.append
        )

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
    output_config: OutputConfig = field(default_factory=OutputConfig)

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
                default_shell=config_data.get('default_shell', '/bin/bash'),
                output_config=OutputConfig.from_dict(config_data.get('output', {}))
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

class OutputHandler:
    """Handles workflow output routing"""
    def __init__(self, config: OutputConfig):
        self.config = config
        self._file_handle: Optional[TextIO] = None

    def __enter__(self):
        """Set up output handling on context enter"""
        if self.config.file and self.config.mode in (OutputMode.FILE, OutputMode.BOTH):
            # Ensure parent directory exists
            self.config.file.parent.mkdir(parents=True, exist_ok=True)
            mode = 'a' if self.config.append else 'w'
            self._file_handle = open(self.config.file, mode)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up on context exit"""
        if self._file_handle:
            self._file_handle.close()

    def write(self, content: str):
        """Write content according to configuration"""
        # Write to stdout if configured
        if self.config.stdout and self.config.mode in (OutputMode.STDOUT, OutputMode.BOTH):
            sys.stdout.write(content)
            sys.stdout.flush()

        # Write to file if configured
        if self._file_handle and self.config.mode in (OutputMode.FILE, OutputMode.BOTH):
            self._file_handle.write(content)
            self._file_handle.flush()

class WorkflowExecutor:
    """Execute workflow files with enhanced output handling"""
    def __init__(self, workflow_path: Path, config: Config):
        self.workflow_path = workflow_path
        self.config = config
        self.logger = LocalFlowLogger(config, workflow_path.stem).logger
        self.docker_executor = DockerExecutor(config) if config.docker_enabled else None
        self.workflow_data = self.load_workflow()

        # Merge workflow-level output config with global config
        workflow_output = OutputConfig.from_dict(self.workflow_data.get('output', {}))
        self.output_config = workflow_output or config.output_config

    def load_workflow(self) -> Dict[str, Any]:
        """Load and validate workflow file"""
        try:
            with open(self.workflow_path) as f:
                workflow_data = yaml.safe_load(f)

                if not isinstance(workflow_data, dict):
                    raise ValueError("Workflow must be a YAML dictionary")
                if 'jobs' not in workflow_data:
                    raise ValueError("Workflow must contain a 'jobs' section")

                return workflow_data
        except Exception as e:
            raise ValueError(f"Failed to load workflow file: {e}")

    def execute_step(self, step: dict, env: Dict[str, str] = None) -> bool:
        """Execute a single workflow step with output handling"""
        step_name = step.get('name', 'Unnamed step')
        command = step.get('run')
        working_dir = step.get('working-directory', str(self.workflow_path.parent))

        if not command:
            self.logger.error(f"Step '{step_name}' is missing required 'run' field")
            return False

        self.logger.info(f"Executing step: {step_name}")

        try:
            with OutputHandler(self.output_config) as output:
                if self.config.docker_enabled and not step.get('local', False):
                    result = self.docker_executor.run_in_container(command, env, working_dir)
                else:
                    process = subprocess.run(
                        command,
                        shell=True,
                        cwd=working_dir,
                        env=env or os.environ.copy(),
                        text=True,
                        capture_output=True
                    )
                    result = {
                        'exit_code': process.returncode,
                        'output': process.stdout + process.stderr
                    }

                if result['output']:
                    output.write(result['output'])
                    if not result['output'].endswith('\n'):
                        output.write('\n')  # Ensure output ends with newline
                    self.logger.debug(f"Output: {result['output']}")

                success = result['exit_code'] == 0
                if not success:
                    error_msg = f"Step '{step_name}' failed with exit code {result['exit_code']}\n"
                    output.write(error_msg)
                    self.logger.error(error_msg.strip())
                return success

        except Exception as e:
            error_msg = f"Failed to execute step '{step_name}': {e}\n"
            self.logger.error(error_msg.strip())
            with OutputHandler(self.output_config) as output:
                output.write(error_msg)
            return False

    def execute_job(self, job_name: str, job_data: dict) -> bool:
        """Execute all steps in a job"""
        self.logger.info(f"Starting job: {job_name}")

        # Get job-level environment variables
        env = os.environ.copy()
        if 'env' in self.workflow_data:
            env.update(self.workflow_data['env'])
        if 'env' in job_data:
            env.update(job_data['env'])

        for step in job_data.get('steps', []):
            if not self.execute_step(step, env):
                return False

        return True

    def run_job(self, job_name: str) -> bool:
        """Execute a specific job from the workflow"""
        try:
            # Check if job exists
            if job_name not in self.workflow_data.get('jobs', {}):
                raise ValueError(
                    f"Job '{job_name}' not found in workflow. "
                    f"Available jobs: {', '.join(self.workflow_data['jobs'].keys())}"
                )

            # Get job data and execute
            job_data = self.workflow_data['jobs'][job_name]
            return self.execute_job(job_name, job_data)

        except Exception as e:
            self.logger.error(f"Job execution failed: {e}")
            return False

    def run(self) -> bool:
        """Execute the entire workflow"""
        try:
            for job_name, job_data in self.workflow_data.get('jobs', {}).items():
                if not self.execute_job(job_name, job_data):
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
@click.pass_obj
@click.argument('workflow')
@click.option('--job', '-j', help='Specific job to run')
@click.option('--docker/--no-docker', help='Override Docker setting')
@click.option('--output', '-o', type=click.Path(), help='Output file path')
@click.option('--output-mode',
              type=click.Choice(['stdout', 'file', 'both']),
              help='Output destination mode')
@click.option('--append/--no-append', help='Append to output file instead of overwriting')
def run(config: Config, workflow: str, job: str, docker: bool,
        output: Optional[str], output_mode: str, append: bool):
    """Run a workflow file or specific job with output handling"""
    try:
        workflow_path = resolve_workflow_path(config.workflows_dir, workflow)

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
            console=console
        ) as progress:
            task_desc = f"Running job '{job}' from" if job else "Running"
            task = progress.add_task(
                f"{task_desc} workflow: {workflow_path.name}"
            )

            if job:
                success = executor.run_job(job)
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
