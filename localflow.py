"""
LocalFlow - A local workflow executor inspired by GitHub Actions.
This tool allows running workflows defined in YAML locally or in Docker containers.
"""

import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

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
                return yaml.safe_load(f)
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
@click.argument('workflow', type=click.Path(exists=True))
@click.option('--docker/--no-docker', help='Override Docker setting')
@click.pass_obj
def run(config: Config, workflow: str, docker: bool):
    """Run a workflow file"""
    if docker is not None:
        config.docker_enabled = docker

    try:
        workflow_path = config.workflows_dir.glob(f'{workflow}')
        executor = WorkflowExecutor(workflow_path, config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Running workflow: {workflow_path.name}")
            success = executor.run()
            progress.update(task, completed=True)

        if not success:
            sys.exit(1)

    except Exception as e:
        console.print(f"[red]Error running workflow: {e}[/red]")
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

[blue]example-workflow.yaml:[/blue]
name: Example Workflow
jobs:
  hello:
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

        for workflow in workflow_paths:
            with open(workflow, 'r') as file:
                wf = yaml.safe_load(file)

            stats = workflow.stat()
            table.add_row(
                workflow.name,
                wf['description'],
                wf['version'],
                wf['author'],
                datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                f"{stats.st_size / 1024:.1f} KB"
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error listing workflows: {e}[/red]")
        if config.log_level == "DEBUG":
            console.print_exception()

@cli.command()
@click.pass_obj
def config(config: Config):
    """Show current configuration"""
    try:
        table = Table(
            title="Current Configuration",
            show_header=True,
            header_style="bold blue",
            border_style="blue"
        )

        table.add_column("Setting", style="bold")
        table.add_column("Value")

        for key, value in asdict(config).items():
            table.add_row(str(key), str(value))

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error displaying configuration: {e}[/red]")

if __name__ == '__main__':
    cli()
