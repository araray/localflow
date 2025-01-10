"""WorkflowExecutor for LocalFlow."""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set

from config import Config, OutputConfig
from schema import Job, Workflow
from utils import OutputHandler


@dataclass
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
    _output_handler: Optional[OutputHandler] = None

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
        """Initialize the executor after dataclass initialization."""
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

        # Initialize output handler if needed
        if self.output_config and self.output_config.mode in (OutputMode.FILE, OutputMode.BOTH):
            logging.debug(f"Initializing OutputHandler for file: {self.output_config.file}")
            self._output_handler = OutputHandler(self.output_config)

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
        """Execute a single workflow step with proper output handling."""
        step_name = step.get('name', 'Unnamed step')
        command = step.get('run')
        working_dir = step.get('working_dir', str(self.workflow_path.parent))

        if not command:
            self.logger.error(f"Step '{step_name}' is missing required 'run' field")
            return False

        self.logger.info(f"Executing step: {step_name}")

        output_handler = self._output_handler or OutputHandler(self.output_config)

        try:
            with output_handler:
                # Execute command and handle output
                if self.docker_executor and not step.get('local', False):
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
                output_text = result.get('output', '')
                if output_text:
                    output_handler.write(output_text)
                    if not output_text.endswith('\n'):
                        output_handler.write('\n')
                else:
                    # Write empty line to maintain file existence
                    output_handler.write('\n')

                success = result['exit_code'] == 0
                if not success:
                    error_msg = (f"Step '{step_name}' failed with exit code "
                               f"{result['exit_code']}\n")
                    output_handler.write(error_msg)
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

    def _execute_job_steps(self, job: Job) -> bool:
        """
        Execute all steps in a job sequentially.

        This method:
        1. Sets up the execution environment with workflow and job variables
        2. Executes each step in order
        3. Tracks job completion status

        Args:
            job: Job instance containing steps to execute

        Returns:
            bool: True if all steps executed successfully, False otherwise
        """
        try:
            self.logger.info(f"Starting job: {job.name} (ID: {job.id})")

            # Build execution environment by combining workflow and job variables
            env = os.environ.copy()
            env.update(self._workflow.env)  # Add workflow-level variables
            env.update(job.env)            # Add job-level variables

            # Execute each step in sequence
            for step in job.steps:
                if not self.execute_step(step, env):
                    return False

            # Record successful completion using job ID
            self._completed_jobs[job.id] = True
            return True

        except Exception as e:
            self._completed_jobs[job.id] = False
            raise

    def _execute_job_with_deps(self, job: Job, visited: Set[str] = None, execution_path: Set[str] = None) -> bool:
        """
        Execute a job ensuring all dependencies run first, with proper cycle detection
        and dependency resolution.

        This implementation uses two tracking sets:
        - visited: Tracks all jobs we've seen to detect cycles
        - execution_path: Tracks the current execution chain to allow parallel paths

        Args:
            job: Job to execute
            visited: Set of all job IDs seen during traversal
            execution_path: Set of job IDs in current execution chain

        Returns:
            bool: True if job and all dependencies executed successfully

        Example dependency graph:
            A -> B -> C
            A -> D -> C

        In this case, C should run only after both B and D complete, but B and D
        can run in parallel after A. The execution_path helps track the current
        chain (e.g. A->B->C vs A->D->C) while visited tracks all jobs seen.
        """
        if visited is None:
            visited = set()
        if execution_path is None:
            execution_path = set()

        # Check if we're in a cycle
        if job.id in execution_path:
            self.logger.error(
                f"Circular dependency detected in path: "
                f"{' -> '.join(execution_path)} -> {job.id}"
            )
            return False

        # Add job to current execution path
        execution_path.add(job.id)

        try:
            # First, process all dependencies if not already completed
            for dep_id in job.needs:
                # Skip if dependency already completed successfully
                if dep_id in self._completed_jobs and self._completed_jobs[dep_id]:
                    continue

                # Find the dependency job
                try:
                    dep_job = next(j for j in self._workflow.jobs.values() if j.id == dep_id)
                except StopIteration:
                    self.logger.error(f"Dependency job '{dep_id}' not found")
                    return False

                # Execute dependency if not visited or not completed
                if dep_id not in visited or not self._completed_jobs.get(dep_id, False):
                    if not self._execute_job_with_deps(dep_job, visited, execution_path.copy()):
                        return False

            # Mark this job as visited
            visited.add(job.id)

            # Check if job already completed successfully
            if job.id in self._completed_jobs and self._completed_jobs[job.id]:
                return True

            # Check conditions now that dependencies are handled
            if job.condition:
                try:
                    context = {
                        j.id: j.id in self._completed_jobs and self._completed_jobs[j.id]
                        for j in self._workflow.jobs.values()
                    }
                    if not job.condition.evaluate(context):
                        self.logger.info(
                            f"Skipping job '{job.name}' (ID: {job.id}) - conditions not met"
                        )
                        # Mark as completed but not necessarily successful
                        self._completed_jobs[job.id] = True
                        return True
                except Exception as e:
                    self.logger.error(
                        f"Failed to evaluate conditions for job '{job.name}': {e}"
                    )
                    return False

            # Execute the job itself
            success = self._execute_job_steps(job)
            self._completed_jobs[job.id] = success
            return success

        finally:
            # Always remove job from execution path when done
            execution_path.remove(job.id)

    def run(self) -> bool:
        """Execute the entire workflow respecting job dependencies."""
        if not self._workflow:
            raise ValueError("No workflow loaded")

        try:
            # Enter output handler context for entire workflow execution
            with self._output_handler or OutputHandler(self.output_config):
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
