"""Unit tests for LocalFlow schema module."""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Generator
import pytest
import yaml

from schema import (
    Condition, Job, Workflow, WorkflowRegistry,
    generate_id
)

@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def example_workflow_content() -> dict:
    """Provide example workflow content for testing."""
    return {
        'id': 'wf_test123',
        'name': 'Test Workflow',
        'description': 'A test workflow',
        'version': '1.0.0',
        'author': 'Test Author',
        'tags': ['test', 'example'],
        'env': {'GLOBAL_VAR': 'value'},
        'jobs': {
            'setup': {
                'id': 'job_setup123',
                'description': 'Setup job',
                'tags': ['setup'],
                'steps': [
                    {'name': 'Setup', 'run': 'echo "Setting up"'}
                ]
            },
            'test': {
                'id': 'job_test123',
                'description': 'Test job',
                'tags': ['test'],
                'condition': {
                    'if': 'job_setup123',
                    'needs': ['job_setup123']
                },
                'steps': [
                    {'name': 'Test', 'run': 'echo "Testing"'}
                ]
            }
        }
    }

@pytest.fixture
def example_workflow_file(temp_dir: Path, example_workflow_content: dict) -> Generator[Path, None, None]:
    """Create a temporary workflow file for testing."""
    workflow_file = temp_dir / 'test_workflow.yml'
    with open(workflow_file, 'w') as f:
        yaml.dump(example_workflow_content, f)
    yield workflow_file

def test_generate_id():
    """Test ID generation functionality."""
    # Test deterministic ID generation
    id1 = generate_id('test', 'content')
    id2 = generate_id('test', 'content')
    assert id1 == id2

    # Test different content produces different IDs
    id3 = generate_id('test', 'different')
    assert id1 != id3

    # Test ID format
    assert id1.startswith('test_')
    assert len(id1) == len('test') + 1 + 8  # prefix + underscore + 8 char hash

def test_condition_parse():
    """Test condition parsing from various formats."""
    # Test simple string condition
    cond = Condition.parse('true')
    assert cond.expression == 'True'
    assert not cond.references

    # Test job reference
    cond = Condition.parse('job_123')
    assert cond.expression == 'job_123'
    assert not cond.references

    # Test complex condition
    cond = Condition.parse({
        'if': 'job_1 and job_2',
        'needs': ['job_1', 'job_2']
    })
    assert cond.expression == 'job_1 and job_2'
    assert cond.references == {'job_1', 'job_2'}

def test_condition_evaluate():
    """Test condition evaluation with various contexts."""
    # Test simple conditions
    cond = Condition.parse('true')
    assert cond.evaluate({})

    # Test job reference
    cond = Condition.parse('job_123')
    assert not cond.evaluate({'job_123': False})
    assert cond.evaluate({'job_123': True})

    # Test complex conditions
    cond = Condition.parse({
        'if': 'job_1 and not job_2',
        'needs': ['job_1', 'job_2']
    })
    assert cond.evaluate({'job_1': True, 'job_2': False})
    assert not cond.evaluate({'job_1': True, 'job_2': True})

def test_job_from_dict():
    """Test job creation from dictionary data."""
    job_data = {
        'id': 'job_test',
        'description': 'Test job',
        'tags': ['test'],
        'condition': {
            'if': 'dep_job',
            'needs': ['dep_job']
        },
        'steps': [
            {'name': 'Step 1', 'run': 'echo "test"'}
        ],
        'env': {'TEST': 'value'},
        'needs': ['dep_job']
    }

    job = Job.from_dict('test_job', job_data, 'wf_parent')

    assert job.id == 'job_test'
    assert job.name == 'test_job'
    assert job.description == 'Test job'
    assert job.tags == {'test'}
    assert job.condition.expression == 'dep_job'
    assert len(job.steps) == 1
    assert job.env == {'TEST': 'value'}
    assert job.needs == {'dep_job'}

def test_workflow_from_file(example_workflow_file: Path):
    """Test workflow loading from file."""
    workflow = Workflow.from_file(example_workflow_file)

    assert workflow.id == 'wf_test123'
    assert workflow.name == 'Test Workflow'
    assert workflow.description == 'A test workflow'
    assert workflow.version == '1.0.0'
    assert workflow.author == 'Test Author'
    assert workflow.tags == {'test', 'example'}
    assert workflow.env == {'GLOBAL_VAR': 'value'}
    assert len(workflow.jobs) == 2
    assert workflow.source == example_workflow_file.resolve()
    assert isinstance(workflow.created_at, datetime)
    assert isinstance(workflow.modified_at, datetime)

def test_workflow_validation(example_workflow_file: Path):
    """Test workflow validation rules."""
    workflow = Workflow.from_file(example_workflow_file)

    # Test valid workflow
    assert not workflow.validate()

    # Test with invalid job reference
    workflow.jobs['test'].needs.add('nonexistent')
    errors = workflow.validate()
    assert len(errors) == 1
    assert 'unknown job ID' in errors[0]

def test_workflow_registry(temp_dir: Path, example_workflow_content: dict):
    """Test workflow registry functionality."""
    # Create test workflows
    workflows_dir = temp_dir / 'workflows'
    workflows_dir.mkdir()

    # Create multiple workflow files
    for i in range(2):
        content = dict(example_workflow_content)
        content['id'] = f'wf_test_{i}'
        content['tags'] = ['tag1'] if i == 0 else ['tag2']

        with open(workflows_dir / f'workflow_{i}.yml', 'w') as f:
            yaml.dump(content, f)

    # Test workflow discovery
    registry = WorkflowRegistry()
    registry.discover_workflows(workflows_dir)

    assert len(registry.workflows) == 2

    # Test workflow lookup
    workflow = registry.get_workflow('wf_test_0')
    assert workflow is not None
    assert workflow.id == 'wf_test_0'

    # Test workflow filtering by tags
    workflows = registry.find_workflows(tags={'tag1'})
    assert len(workflows) == 1
    assert workflows[0].id == 'wf_test_0'

def test_workflow_persistence(temp_dir: Path):
    """Test workflow ID persistence and file updates."""
    # Create workflow without IDs
    content = {
        'name': 'Test Workflow',
        'jobs': {
            'test': {
                'steps': [{'run': 'echo "test"'}]
            }
        }
    }

    workflow_file = temp_dir / 'workflow.yml'
    with open(workflow_file, 'w') as f:
        yaml.dump(content, f)
