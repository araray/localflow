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
from typing import Dict, Optional, TextIO, Set

import click
import docker
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.panel import Panel

from schema import WorkflowRegistry, Workflow, Job

# Initialize Rich console for beautiful output
console = Console()

def list_files_in_folder(folder_name, extensions):
    """
    Checks if a folder exists in the current directory and lists files with specific extensions.

    Parameters:
    - folder_name (str): The name of the folder to check for.
    - extensions (tuple): A tuple of file extensions (e.g., ('.txt', '.jpg')) to filter files by.

    Returns:
    - list: A list of file names with the specified extensions if the folder exists.
    - None: If the folder does not exist.
    """
    try:
        # Check if the folder exists in the current directory
        if os.path.isdir(folder_name):
            # Get all files in the folder with the specified extensions
            files = [
                file for file in os.listdir(folder_name)
                if file.endswith(extensions) and os.path.isfile(os.path.join(folder_name, file))
            ]
            return files
        else:
            return None  # Return None if the folder does not exist
    except Exception as e:
        # Log the error or handle it appropriately without interrupting the program flow
        print(f"An error occurred: {e}")
        return None


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
    local_workflows_dir: Path = field(default_factory=lambda: Path('.localflow'))

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
                local_workflows_dir=Path(config_data.get('local_workflows_dir', '.localflow')),
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
            local_workflows_dir=Path('.localflow'),
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

@dataclass
class WorkflowExecutor:
    """
    Execute workflow files with enhanced output handling.

    This class manages the execution of workflows, including:
    - Loading and validating workflow definitions
    - Managing job dependencies and conditions
    - Handling execution environment and output
    - Supporting both local and Docker-based execution
    """
    workflow_path: Path
    config: Config
    logger: Optional[logging.Logger] = None
    docker_executor: Optional[DockerExecutor] = None
    output_config: Optional[OutputConfig] = None

    # Track completed jobs for condition evaluation
    _completed_jobs: Dict[str, bool] = field(default_factory=dict)    # Store loaded workflow
    _workflow: Optional[Workflow] = None

    def _get_job_by_id_or_name(self, job_identifier: str) -> Job:
        """
        Find a job by either its ID or name.

        This method first tries to find a job by ID, and if not found,
        falls back to looking up by name. This maintains backward compatibility
        while supporting the new ID-based referencing.

        Args:
            job_identifier: Either a job ID or job name

        Returns:
            Job: The found job instance

        Raises:
            ValueError: If no job matches the given identifier
        """
        # First try to find by ID
        for job in self._workflow.jobs.values():
            if job.id == job_identifier:
                return job

        # If not found by ID, try to find by name
        if job_identifier in self._workflow.jobs:
            return self._workflow.jobs[job_identifier]

        # If we get here, the job wasn't found
        available_jobs = [
            f"{job.name} (ID: {job.id})"
            for job in self._workflow.jobs.values()
        ]
        raise ValueError(
            f"Job '{job_identifier}' not found. Available jobs: "
            f"{', '.join(available_jobs)}"
        )

    def __post_init__(self):
        """
        Initialize the executor after dataclass initialization.
        Sets up logging, Docker executor if enabled, and loads the workflow.
        """
        # Initialize logger
        self.logger = LocalFlowLogger(
            self.config,
            self.workflow_path.stem
        ).logger

        # Setup Docker executor if enabled
        if self.config.docker_enabled:
            self.docker_executor = DockerExecutor(self.config)

        # Load and validate workflow
        self._load_workflow()

        # Setup output configuration
        self._setup_output_config()

    def _load_workflow(self) -> None:
        """
        Load and validate the workflow from the specified path.
        Raises ValueError if the workflow is invalid.
        """
        try:
            # Load workflow using new schema
            self._workflow = Workflow.from_file(self.workflow_path)

            # Validate workflow
            errors = self._workflow.validate()
            if errors:
                raise ValueError(
                    "Workflow validation failed:\n" +
                    "\n".join(f"- {error}" for error in errors)
                )

        except Exception as e:
            raise ValueError(f"Failed to load workflow: {e}")

    def _setup_output_config(self) -> None:
        """
        Configure output handling by merging workflow-level settings
        with global configuration.
        """
        # Get workflow-level output config if it exists
        workflow_output = OutputConfig.from_dict(
            getattr(self._workflow, 'output', {})
        )

        # Use workflow config if present, otherwise use global config
        self.output_config = workflow_output or self.config.output_config

    def execute_step(self, step: dict, env: Dict[str, str] = None) -> bool:
        """
        Execute a single workflow step with proper output handling.

        Args:
            step: Dictionary containing step configuration
            env: Environment variables for step execution

        Returns:
            bool: True if step executed successfully, False otherwise
        """
        step_name = step.get('name', 'Unnamed step')
        command = step.get('run')
        working_dir = step.get('working-directory',
                             str(self.workflow_path.parent))

        if not command:
            self.logger.error(f"Step '{step_name}' is missing required 'run' field")
            return False

        self.logger.info(f"Executing step: {step_name}")

        try:
            with OutputHandler(self.output_config) as output:
                # Execute in Docker if enabled and step isn't marked local
                if (self.docker_executor and
                    not step.get('local', False)):
                    result = self.docker_executor.run_in_container(
                        command, env, working_dir
                    )
                else:
                    # Execute locally
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

                # Handle command output
                if result['output']:
                    output.write(result['output'])
                    if not result['output'].endswith('\n'):
                        output.write('\n')
                    self.logger.debug(f"Output: {result['output']}")

                success = result['exit_code'] == 0
                if not success:
                    error_msg = (f"Step '{step_name}' failed with exit code "
                               f"{result['exit_code']}\n")
                    output.write(error_msg)
                    self.logger.error(error_msg.strip())

                return success

        except Exception as e:
            error_msg = f"Failed to execute step '{step_name}': {e}\n"
            self.logger.error(error_msg.strip())
            with OutputHandler(self.output_config) as output:
                output.write(error_msg)
            return False

    def _execute_job_steps(self, job: Job) -> bool:
        """Execute all steps in a job"""
        try:
            self.logger.info(f"Starting job: {job.name} (ID: {job.id})")

            # Build execution environment
            env = os.environ.copy()
            env.update(self._workflow.env)
            env.update(job.env)

            # Execute each step
            for step in job.steps:
                if not self.execute_step(step, env):
                    return False

            # Record successful completion using job ID
            self._completed_jobs[job.id] = True
            return True
        except Exception as e:
            self._completed_jobs[job.id] = False
            raise

    def _check_job_conditions(self, job: Job) -> bool:
        """
        Check if a job's conditions are met.

        Args:
            job: Job instance to check

        Returns:
            bool: True if conditions are met or no conditions exist
        """
        if not job.condition:
            return True

        # Build context of completed jobs using IDs
        context = {
            j.id: j.id in self._completed_jobs
            for j in self._workflow.jobs.values()
        }

        try:
            return job.condition.evaluate(context)
        except Exception as e:
            self.logger.error(
                f"Failed to evaluate conditions for job '{job.name}': {e}"
            )
            return False

    def execute_job(self, job_identifier: str) -> bool:
        """Execute a job and its dependencies."""
        if not self._workflow:
            raise ValueError("No workflow loaded")

        try:
            job = self._get_job_by_id_or_name(job_identifier)
            return self._execute_job_with_deps(job)
        except Exception as e:
            self.logger.error(f"Failed to execute job: {e}")
            return False

    def _execute_job_with_deps(self, job: Job, visited: Set[str] = None) -> bool:
        """
        Execute a job ensuring all dependencies run first.

        Args:
            job: Job to execute
            visited: Set of job IDs already processed (for cycle detection)
        """
        if visited is None:
            visited = set()

        # Check for cycles
        if job.id in visited:
            self.logger.error(f"Circular dependency detected for job '{job.name}'")
            return False

        visited.add(job.id)

        # Execute dependencies first
        for dep_id in job.needs:
            dep_job = next(j for j in self._workflow.jobs.values() if j.id == dep_id)
            if not self._execute_job_with_deps(dep_job, visited):
                return False

        # Now check conditions
        context = {j.id: j.id in self._completed_jobs
                  for j in self._workflow.jobs.values()}

        if job.condition:
            try:
                if not job.condition.evaluate(context):
                    self.logger.info(f"Skipping job '{job.name}' - conditions not met")
                    return True
            except Exception as e:
                self.logger.error(str(e))
                return False

        # Execute the job itself
        if self._execute_job_steps(job):
            self._completed_jobs[job.id] = True
            return True
        return False

    def run(self) -> bool:
        """
        Execute the entire workflow respecting job dependencies.

        Returns:
            bool: True if workflow executed successfully, False otherwise
        """
        if not self._workflow:
            raise ValueError("No workflow loaded")

        try:
            # Clear completed jobs at start of workflow
            self._completed_jobs.clear()

            # Execute all jobs in workflow
            for job_name in self._workflow.jobs:
                if job_name not in self._completed_jobs:
                    if not self.execute_job(job_name):
                        return False

            return True

        except Exception as e:
            self.logger.error(f"Workflow execution failed: {e}")
            return False


def resolve_workflow_path(workflows_dir: Path, workflow_id: str) -> Path:
    """
    Resolve workflow path from ID, checking both local and global directories.

    Args:
        workflows_dir: Global workflows directory from config
        workflow_id: ID of the workflow to find

    Returns:
        Path: Resolved path to the workflow file

    Raises:
        FileNotFoundError: If workflow cannot be found
    """
    # First check local directory
    local_dir = Path('.localflow')
    if local_dir.exists():
        for ext in ['.yml', '.yaml']:
            for workflow_path in local_dir.glob(f'*{ext}'):
                try:
                    with open(workflow_path) as f:
                        data = yaml.safe_load(f)
                        if data and data.get('id') == workflow_id:
                            return workflow_path.resolve()
                except Exception:
                    continue

    # Then check global directory
    if workflows_dir.exists():
        for ext in ['.yml', '.yaml']:
            for workflow_path in workflows_dir.glob(f'*{ext}'):
                try:
                    with open(workflow_path) as f:
                        data = yaml.safe_load(f)
                        if data and data.get('id') == workflow_id:
                            return workflow_path.resolve()
                except Exception:
                    continue

    # If we get here, the workflow wasn't found
    raise FileNotFoundError(
        f"Workflow '{workflow_id}' not found in either local '.localflow' "
        f"directory or global workflows directory at {workflows_dir}. "
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
        registry.discover_workflows(
            config.workflows_dir,
            config.local_workflows_dir
        )

        workflows = registry.find_workflows()

        if not workflows:
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

        table.add_column("ID", justify="left", no_wrap=True)
        table.add_column("Name", justify="left", no_wrap=True)
        table.add_column("Description", justify="left", no_wrap=False)
        table.add_column("Tags", justify="left", no_wrap=True)
        table.add_column("Version", justify="left", no_wrap=True)
        table.add_column("Author", justify="left", no_wrap=True)
        table.add_column("Location", justify="left", no_wrap=True)

        for workflow in workflows:
            location = (
                "Local" if workflow.source.parent == config.local_workflows_dir
                else "Global"
            )
            table.add_row(
                workflow.id,
                workflow.name,
                workflow.description or "No description",
                ", ".join(sorted(workflow.tags)) or "None",
                workflow.version,
                workflow.author or "Unknown",
                location
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error listing workflows: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()

@cli.command()
@click.argument('workflow_id')
@click.pass_obj
def jobs(config: Config, workflow_id: str):
    """List available jobs in a workflow"""
    try:
        # Initialize registry and discover workflows
        registry = WorkflowRegistry()
        registry.discover_workflows(
            config.workflows_dir,
            config.local_workflows_dir
        )

        # Get workflow
        workflow = registry.get_workflow(workflow_id)
        if not workflow:
            console.print(
                f"[red]No workflow found with ID: {workflow_id}[/red]"
            )
            return

        # Create the jobs table
        table = Table(
            title=f"Jobs in {workflow.name}",
            show_header=True,
            header_style="bold blue",
            border_style="blue"
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
                job.condition.expression if job.condition else "None"
            )

        console.print("\n")  # Add spacing
        console.print(table)

        # Print usage hint
        console.print("\n[dim]To run a specific job, use:[/dim]")
        console.print(
            f"[dim]  localflow run {workflow_id} --job <job_id>[/dim]"
        )

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
