#!/usr/bin/env python3
import os
import sys
import yaml
import json
import logging
import docker
from pathlib import Path
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, asdict
from datetime import datetime
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from tabulate import tabulate
import click

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
    def load_from_file(cls, config_path: Path) -> 'Config':
        """Load configuration from a YAML file."""
        if not config_path.exists():
            return cls.get_defaults()

        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        return cls(
            workflows_dir=Path(config_data.get('workflows_dir', '~/.localflow/workflows')).expanduser(),
            log_dir=Path(config_data.get('log_dir', '~/.localflow/logs')).expanduser(),
            log_level=config_data.get('log_level', 'INFO'),
            docker_enabled=config_data.get('docker_enabled', False),
            docker_default_image=config_data.get('docker_default_image', 'ubuntu:latest'),
            show_output=config_data.get('show_output', True),
            default_shell=config_data.get('default_shell', '/bin/bash')
        )

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

class LocalFlowLogger:
    """Custom logger for LocalFlow."""
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
        """Run a command in a Docker container."""
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
                'output': str(e)
            }

class WorkflowExecutor:
    """Execute workflow files with enhanced logging and Docker support."""
    def __init__(self, workflow_path: Path, config: Config):
        self.workflow_path = workflow_path
        self.config = config
        self.logger = LocalFlowLogger(config, workflow_path.stem).logger
        self.docker_executor = DockerExecutor(config) if config.docker_enabled else None

    def execute_step(self, step: dict, env: Dict[str, str] = None) -> bool:
        """Execute a single workflow step with enhanced logging and Docker support."""
        step_name = step.get('name', 'Unnamed step')
        command = step.get('run')
        working_dir = step.get('working-directory', os.path.dirname(self.workflow_path))
        
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
                import subprocess
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

            # Log the results
            self.logger.debug(f"Exit code: {result['exit_code']}")
            if result['output']:
                if self.config.show_output:
                    console.print(result['output'])
                self.logger.debug(f"Output: {result['output']}")

            return result['exit_code'] == 0

        except Exception as e:
            self.logger.error(f"Failed to execute step '{step_name}': {e}")
            return False

@click.group()
@click.option('--config', '-c', type=click.Path(exists=True),
              help='Path to configuration file',
              default=lambda: os.environ.get('LOCALFLOW_CONFIG'))
@click.option('--debug/--no-debug', default=False, help='Enable debug mode')
@click.option('--quiet/--no-quiet', default=False, help='Suppress console output')
@click.pass_context
def cli(ctx, config, debug, quiet):
    """LocalFlow - A local workflow executor"""
    # Load configuration
    config_path = Path(config) if config else None
    cfg = Config.load_from_file(config_path) if config_path else Config.get_defaults()
    
    # Override configuration based on CLI options
    if debug:
        cfg.log_level = 'DEBUG'
    if quiet:
        cfg.show_output = False

    ctx.obj = cfg

@cli.command()
@click.argument('workflow', type=click.Path(exists=True))
@click.option('--docker/--no-docker', help='Override Docker setting')
@click.pass_obj
def run(config: Config, workflow: str, docker: bool):
    """Run a workflow file"""
    if docker is not None:
        config.docker_enabled = docker

    workflow_path = Path(workflow)
    executor = WorkflowExecutor(workflow_path, config)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Running workflow: {workflow_path.name}")
            executor.run()
            progress.update(task, completed=True)
    except Exception as e:
        console.print(f"[red]Error running workflow:[/red] {e}")
        sys.exit(1)

@cli.command()
@click.pass_obj
def list(config: Config):
    """List available workflows"""
    workflows = list(config.workflows_dir.glob('*.yml'))
    
    table = Table(title="Available Workflows")
    table.add_column("Name")
    table.add_column("Last Modified")
    table.add_column("Size")

    for workflow in workflows:
        stats = workflow.stat()
        table.add_row(
            workflow.name,
            datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            f"{stats.st_size / 1024:.1f} KB"
        )

    console.print(table)

@cli.command()
@click.pass_obj
def config(config: Config):
    """Show current configuration"""
    table = Table(title="Current Configuration")
    table.add_column("Setting")
    table.add_column("Value")

    for key, value in asdict(config).items():
        table.add_row(str(key), str(value))

    console.print(table)

if __name__ == '__main__':
    cli()
