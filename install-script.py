#!/usr/bin/env python3
"""
LocalFlow Installation Script

This script guides users through the installation process of LocalFlow,
setting up directories, configuration, and environment variables.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
import yaml
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

console = Console()

class Installer:
    def __init__(self):
        self.console = Console()
        self.home_dir = Path.home()
        self.default_install_dir = self.home_dir / '.localflow'
        self.default_bin_dir = self.home_dir / '.local' / 'bin'
        self.config: Dict[str, Any] = {}

    def print_welcome(self) -> None:
        """Display welcome message and brief explanation."""
        welcome_text = """
Welcome to LocalFlow Installation!

This script will help you set up LocalFlow on your system. We'll:
1. Create necessary directories for workflows and logs
2. Set up configuration files
3. Install required Python dependencies
4. Configure your shell environment

You can accept the defaults or customize the installation to your needs.
"""
        self.console.print(Panel(welcome_text, title="LocalFlow Installer", border_style="blue"))

    def check_prerequisites(self) -> bool:
        """Check if system meets all prerequisites."""
        self.console.print("\n[bold]Checking prerequisites...[/bold]")
        
        # Check Python version
        python_version = sys.version_info
        if python_version < (3, 8):
            self.console.print("[red]Error: Python 3.8 or higher is required[/red]")
            return False

        # Check pip installation
        try:
            subprocess.run([sys.executable, "-m", "pip", "--version"], 
                         capture_output=True, check=True)
        except subprocess.CalledProcessError:
            self.console.print("[red]Error: pip is not installed[/red]")
            return False

        # Check git installation (optional)
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.console.print("[yellow]Warning: git is not installed. " 
                             "It's recommended but not required.[/yellow]")

        self.console.print("[green]✓ All core prerequisites met[/green]")
        return True

    def get_installation_paths(self) -> bool:
        """Get user input for installation paths."""
        self.console.print("\n[bold]Setting up installation paths...[/bold]")

        # Get main installation directory
        default_install = str(self.default_install_dir)
        install_dir = Prompt.ask(
            "Main installation directory",
            default=default_install
        )
        self.install_dir = Path(install_dir).expanduser()

        # Get binary installation directory
        default_bin = str(self.default_bin_dir)
        bin_dir = Prompt.ask(
            "Binary installation directory",
            default=default_bin
        )
        self.bin_dir = Path(bin_dir).expanduser()

        # Set up subdirectories
        self.workflows_dir = self.install_dir / 'workflows'
        self.logs_dir = self.install_dir / 'logs'
        self.config_dir = self.install_dir

        # Show summary
        self.console.print("\nInstallation paths summary:")
        self.console.print(f"Main directory: {self.install_dir}")
        self.console.print(f"Binary directory: {self.bin_dir}")
        self.console.print(f"Workflows directory: {self.workflows_dir}")
        self.console.print(f"Logs directory: {self.logs_dir}")

        return Confirm.ask("Proceed with these paths?")

    def create_directories(self) -> None:
        """Create necessary directories."""
        self.console.print("\n[bold]Creating directories...[/bold]")
        
        directories = [
            self.install_dir,
            self.workflows_dir,
            self.logs_dir,
            self.bin_dir
        ]

        for directory in directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self.console.print(f"[green]✓ Created {directory}[/green]")
            except Exception as e:
                self.console.print(f"[red]Error creating {directory}: {e}[/red]")
                raise

    def install_dependencies(self) -> None:
        """Install required Python packages."""
        self.console.print("\n[bold]Installing dependencies...[/bold]")
        
        requirements = [
            'click>=8.0.0',
            'rich>=10.0.0',
            'pyyaml>=5.4.0',
            'docker>=5.0.0',
            'tabulate>=0.8.9'
        ]

        try:
            subprocess.run([
                sys.executable, "-m", "pip", "install", "--user"
            ] + requirements, check=True)
            self.console.print("[green]✓ Successfully installed dependencies[/green]")
        except subprocess.CalledProcessError as e:
            self.console.print(f"[red]Error installing dependencies: {e}[/red]")
            raise

    def create_config(self) -> None:
        """Create configuration file."""
        self.console.print("\n[bold]Creating configuration file...[/bold]")

        # Get Docker preferences
        docker_enabled = Confirm.ask(
            "Enable Docker support?",
            default=False
        )

        config = {
            'workflows_dir': str(self.workflows_dir),
            'log_dir': str(self.logs_dir),
            'log_level': "INFO",
            'show_output': True,
            'docker_enabled': docker_enabled,
            'docker_default_image': "ubuntu:latest",
            'default_shell': "/bin/bash"
        }

        config_file = self.config_dir / 'config.yml'
        try:
            with open(config_file, 'w') as f:
                yaml.safe_dump(config, f, default_flow_style=False)
            self.console.print(f"[green]✓ Created configuration at {config_file}[/green]")
        except Exception as e:
            self.console.print(f"[red]Error creating config file: {e}[/red]")
            raise

    def setup_shell(self) -> None:
        """Set up shell configuration."""
        self.console.print("\n[bold]Setting up shell environment...[/bold]")

        # Determine shell
        shell = os.environ.get('SHELL', '').split('/')[-1]
        if not shell:
            self.console.print("[yellow]Could not determine shell type[/yellow]")
            return

        # Create shell configuration
        env_setup = f"""
# LocalFlow Configuration
export LOCALFLOW_CONFIG="{self.config_dir / 'config.yml'}"
export PATH="{self.bin_dir}:$PATH"
"""

        # Determine rc file
        rc_file = None
        if shell == 'bash':
            rc_file = self.home_dir / '.bashrc'
        elif shell == 'zsh':
            rc_file = self.home_dir / '.zshrc'

        if rc_file:
            if Confirm.ask(f"Add LocalFlow configuration to {rc_file}?"):
                try:
                    with open(rc_file, 'a') as f:
                        f.write(env_setup)
                    self.console.print(f"[green]✓ Added configuration to {rc_file}[/green]")
                except Exception as e:
                    self.console.print(f"[red]Error updating shell configuration: {e}[/red]")
                    return

        self.console.print(f"\nTo manually configure your shell, add these lines:")
        self.console.print(env_setup)

    def create_example_workflow(self) -> None:
        """Create an example workflow file."""
        self.console.print("\n[bold]Creating example workflow...[/bold]")

        example_workflow = """
name: Example Workflow

jobs:
  hello:
    steps:
      - name: Say Hello
        run: echo "Hello from LocalFlow!"
        
      - name: Show System Info
        run: |
          echo "Current directory: $(pwd)"
          echo "Date: $(date)"
          echo "User: $(whoami)"
"""

        workflow_file = self.workflows_dir / 'example.yml'
        try:
            with open(workflow_file, 'w') as f:
                f.write(example_workflow.lstrip())
            self.console.print(f"[green]✓ Created example workflow at {workflow_file}[/green]")
        except Exception as e:
            self.console.print(f"[red]Error creating example workflow: {e}[/red]")
            raise

    def install_localflow(self) -> None:
        """Install LocalFlow script."""
        self.console.print("\n[bold]Installing LocalFlow...[/bold]")

        # Copy main script
        script_source = Path(__file__).parent / 'localflow.py'
        script_dest = self.bin_dir / 'localflow'

        try:
            shutil.copy2(script_source, script_dest)
            script_dest.chmod(0o755)  # Make executable
            self.console.print(f"[green]✓ Installed LocalFlow to {script_dest}[/green]")
        except Exception as e:
            self.console.print(f"[red]Error installing LocalFlow: {e}[/red]")
            raise

    def run(self) -> None:
        """Run the complete installation process."""
        try:
            self.print_welcome()
            
            if not self.check_prerequisites():
                return

            if not self.get_installation_paths():
                return

            self.create_directories()
            self.install_dependencies()
            self.create_config()
            self.setup_shell()
            self.create_example_workflow()
            self.install_localflow()

            self.console.print(Panel("""
[green]LocalFlow has been successfully installed![/green]

To get started:
1. Restart your shell or run: source ~/.bashrc (or ~/.zshrc)
2. Try the example workflow: localflow run ~/.localflow/workflows/example.yml
3. Run 'localflow --help' to see all available commands

Refer to the documentation for more information on creating workflows.
""", title="Installation Complete", border_style="green"))

        except Exception as e:
            self.console.print(f"\n[red]Installation failed: {e}[/red]")
            self.console.print("\nPlease fix the error and try again.")
            sys.exit(1)

if __name__ == '__main__':
    installer = Installer()
    installer.run()
