"""
Schema definitions for LocalFlow workflows and jobs.
Handles ID generation, validation, and condition evaluation.
"""

import hashlib
import re

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

import yaml


def generate_id(prefix: str, content: str) -> str:
    """
    Generate a deterministic ID based on content with a readable prefix.

    Args:
        prefix: String prefix for the ID (e.g., 'wf' for workflow, 'job' for job)
        content: Content to hash for ID generation

    Returns:
        A string ID in format: prefix_hash[:8] (e.g., wf_a1b2c3d4)
    """
    hash_obj = hashlib.sha256(content.encode())
    return f"{prefix}_{hash_obj.hexdigest()[:8]}"


@dataclass
class Condition:
    """Represents a job execution condition."""
    expression: str
    references: Set[str] = field(default_factory=set)

    @classmethod
    def parse(cls, condition_data: Union[str, dict]) -> 'Condition':
        """Parse condition from various formats."""
        if isinstance(condition_data, str):
            # Handle simple string conditions
            if condition_data.lower() == 'true':
                return cls('True')  # Convert string 'true' to Python True
            return cls(condition_data)
        elif isinstance(condition_data, dict):
            return cls(
                expression=condition_data.get('if', 'True'),
                references=set(condition_data.get('needs', []))
            )
        else:
            raise ValueError(f"Invalid condition format: {condition_data}")

    def evaluate(self, context: Dict[str, bool]) -> bool:
        """
        Evaluate condition with job completion context.

        Args:
            context: Maps job IDs to completion status (True/False)
        """
        try:
            # Create safe evaluation environment
            eval_env = {
                'True': True,
                'False': False,
                'true': True,
                'false': False,
                'and': lambda x, y: x and y,
                'or': lambda x, y: x or y,
                'not': lambda x: not x
            }

            # Add job statuses to environment
            eval_env.update(context)

            # Handle both quoted and unquoted job IDs
            expr = self.expression
            for job_id in context:
                # Replace quoted versions with direct references
                expr = expr.replace(f"'{job_id}'", job_id)
                expr = expr.replace(f'"{job_id}"', job_id)

            return bool(eval(expr, {"__builtins__": None}, eval_env))

        except Exception as e:
            raise ValueError(f"Failed to evaluate condition '{self.expression}': {e}")

@dataclass
class Job:
    """Represents a workflow job with metadata and execution details."""
    name: str
    id: str
    description: Optional[str] = None
    tags: Set[str] = field(default_factory=set)
    condition: Optional[Condition] = None
    steps: List[dict] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    needs: Set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, name: str, data: dict, workflow_id: str) -> 'Job':
        """
        Create a Job instance from dictionary data.

        Args:
            name: Job name
            data: Dictionary containing job data
            workflow_id: Parent workflow ID for scoping

        Returns:
            Job instance
        """
        # Generate deterministic job ID scoped to workflow
        job_id = generate_id('job', f"{workflow_id}_{name}_{yaml.dump(data)}")

        return cls(
            name=name,
            id=job_id,
            description=data.get('description'),
            tags=set(data.get('tags', [])),
            condition=Condition.parse(data.get('condition', 'true')),
            steps=data.get('steps', []),
            env=data.get('env', {}),
            needs=set(data.get('needs', []))
        )


@dataclass
class Workflow:
    """Represents a complete workflow with metadata and jobs."""
    name: str
    id: str  # Now required
    description: Optional[str] = None
    version: str = "1.0.0"
    author: Optional[str] = None
    tags: Set[str] = field(default_factory=set)
    env: Dict[str, str] = field(default_factory=dict)
    jobs: Dict[str, Job] = field(default_factory=dict)
    source: Path = field(default_factory=Path)
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_file(cls, path: Path) -> 'Workflow':
        """Load workflow from file, using stored IDs."""
        with open(path) as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Invalid workflow format in {path}")

            # Use existing workflow ID
            workflow_id = data.get('id')
            if not workflow_id:
                raise ValueError(f"Workflow in {path} is missing required ID")

            workflow = cls(
                name=data.get('name', path.stem),
                id=workflow_id,
                description=data.get('description'),
                version=data.get('version', '1.0.0'),
                author=data.get('author'),
                tags=set(data.get('tags', [])),
                env=data.get('env', {}),
                source=path,
                created_at=datetime.fromtimestamp(path.stat().st_ctime),
                modified_at=datetime.fromtimestamp(path.stat().st_mtime)
            )

            # Parse jobs using their stored IDs
            jobs_data = data.get('jobs', {})
            for job_name, job_data in jobs_data.items():
                if not isinstance(job_data, dict):
                    job_data = {}

                if 'id' not in job_data:
                    raise ValueError(
                        f"Job '{job_name}' in {path} is missing required ID"
                    )

                workflow.jobs[job_name] = Job(
                    name=job_name,
                    id=job_data['id'],
                    description=job_data.get('description'),
                    tags=set(job_data.get('tags', [])),
                    condition=Condition.parse(job_data.get('condition', 'true')),
                    steps=job_data.get('steps', []),
                    env=job_data.get('env', {}),
                    needs=set(job_data.get('needs', []))
                )

            return workflow

    def validate(self) -> List[str]:
        """
        Validate workflow configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check for required jobs
        if not self.jobs:
            errors.append("Workflow must contain at least one job")

        # Validate job references
        job_ids = {job.id for job in self.jobs.values()}
        for job in self.jobs.values():
            # Check needs references
            for needed_id in job.needs:
                if needed_id not in job_ids:
                    errors.append(
                        f"Job '{job.name}' references unknown job ID '{needed_id}'"
                    )

            # Check condition references
            if job.condition:
                for ref in job.condition.references:
                    if ref not in job_ids:
                        errors.append(
                            f"Job '{job.name}' condition references unknown job ID '{ref}'"
                        )

        return errors


class WorkflowRegistry:
    """Registry for managing available workflows with persistent IDs."""

    def __init__(self):
        self.workflows: Dict[str, Workflow] = {}

    def discover_workflows(self, *directories: Path) -> None:
        """
        Discover workflows and ensure they have persistent IDs.
        Updates workflow files if IDs are missing.
        """
        for directory in directories:
            if not directory.exists():
                continue

            for ext in ['.yml', '.yaml']:
                for workflow_path in directory.glob(f'*{ext}'):
                    try:
                        # Load raw YAML first to check/add IDs
                        with open(workflow_path) as f:
                            data = yaml.safe_load(f) or {}

                        # Check if we need to add IDs
                        modified = False

                        # Add workflow ID if missing
                        if 'id' not in data:
                            data['id'] = generate_id('wf', str(workflow_path))
                            modified = True

                        # Add job IDs if missing
                        for job_name, job_data in data.get('jobs', {}).items():
                            if not isinstance(job_data, dict):
                                job_data = {}
                                data['jobs'][job_name] = job_data

                            if 'id' not in job_data:
                                job_data['id'] = generate_id(
                                    'job',
                                    f"{data['id']}_{job_name}"
                                )
                                modified = True

                        # Save updates if needed
                        if modified:
                            with open(workflow_path, 'w') as f:
                                yaml.dump(data, f, sort_keys=False)

                        # Now load as Workflow object
                        workflow = Workflow.from_file(workflow_path)
                        self.workflows[workflow.id] = workflow

                    except Exception as e:
                        print(f"Error loading workflow {workflow_path}: {e}")

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """
        Get workflow by ID.

        Args:
            workflow_id: Workflow ID

        Returns:
            Workflow instance if found, None otherwise
        """
        return self.workflows.get(workflow_id)

    def find_workflows(self, *, tags: Optional[Set[str]] = None) -> List[Workflow]:
        """
        Find workflows matching specified criteria.

        Args:
            tags: Set of tags to filter by (if provided)

        Returns:
            List of matching Workflow instances
        """
        workflows = list(self.workflows.values())

        if tags:
            workflows = [w for w in workflows if tags.issubset(w.tags)]

        return sorted(workflows, key=lambda w: w.name)
