"""Configuration management for LocalFlow."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class OutputConfig:
    """Configuration for workflow output handling"""

    file: Optional[Path] = None
    mode: str = "stdout"
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
            mode=data.get("mode", "stdout"),
            stdout=data.get("stdout", True),
            append=data.get("append", False),
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
    local_workflows_dir: Path = field(default_factory=lambda: Path(".localflow"))
    config_file: Optional[Path] = None
    monitor_pid_file: Path = field(
        default_factory=lambda: Path("/tmp/localflow-monitor.pid")
    )
    monitor_log_file: Path = field(
        default_factory=lambda: Path("localflow-monitor.log")
    )
    monitor_check_interval: int = 60  # seconds

    @classmethod
    def load_from_file(cls, config_path: Optional[Path]) -> "Config":
        """Load configuration from a YAML file with proper error handling."""
        try:
            config_data = {}

            if config_path and config_path.exists():
                with open(config_path) as f:
                    loaded_data = yaml.safe_load(f)
                    if loaded_data:
                        config_data = loaded_data

            # Get monitor settings from config
            for conf in config_data: #AV_DEBUG
                print(conf)
            monitor_config = config_data.get("monitor", {})
            monitor_pid_file = Path(
                os.path.expanduser(
                    monitor_config.get("pid_file", "/tmp/localflow-monitor.pid")
                )
            )
            monitor_log_file = Path(
                monitor_config.get("log_file", "localflow-monitor.log")
            )
            monitor_check_interval = monitor_config.get("check_interval", 60)

            # Create configuration with proper path expansion
            return cls(
                workflows_dir=Path(
                    os.path.expanduser(
                        config_data.get("workflows_dir", "~/.localflow/workflows")
                    )
                ),
                local_workflows_dir=Path(
                    config_data.get("local_workflows_dir", ".localflow")
                ),
                log_dir=Path(
                    os.path.expanduser(config_data.get("log_dir", "~/.localflow/logs"))
                ),
                log_level=config_data.get("log_level", "INFO"),
                docker_enabled=config_data.get("docker_enabled", False),
                docker_default_image=config_data.get(
                    "docker_default_image", "ubuntu:latest"
                ),
                show_output=config_data.get("show_output", True),
                default_shell=config_data.get("default_shell", "/bin/bash"),
                output_config=OutputConfig.from_dict(config_data.get("output", {})),
                config_file=config_path,
                monitor_pid_file=monitor_pid_file,
                monitor_log_file=monitor_log_file,
                monitor_check_interval=monitor_check_interval,
            )
        except Exception as e:
            # Return defaults if config loading fails
            return cls.get_defaults()

    @classmethod
    def get_defaults(cls) -> "Config":
        """Get default configuration."""
        return cls(
            workflows_dir=Path("~/.localflow/workflows").expanduser(),
            local_workflows_dir=Path(".localflow"),
            log_dir=Path("~/.localflow/logs").expanduser(),
            log_level="INFO",
            docker_enabled=False,
            docker_default_image="ubuntu:latest",
            show_output=True,
            default_shell="/bin/bash",
        )

    def ensure_directories(self) -> None:
        """Ensure required directories exist."""
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
