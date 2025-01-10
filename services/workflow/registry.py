"""Workflow discovery and registration."""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Set
from localflow.core.schema import Workflow

class WorkflowRegistry:
    """Registry for managing available workflows."""
    
    def __init__(self):
        """Initialize registry."""
        self.workflows: Dict[str, Workflow] = {}
        
    def discover_workflows(self, *directories: Path) -> None:
        """
        Discover workflows in specified directories.
        
        Args:
            *directories: Variable number of Path objects to search
        """
        for directory in directories:
            if not directory.exists():
                continue
                
            for ext in [".yml", ".yaml"]:
                for workflow_path in directory.glob(f"*{ext}"):
                    try:
                        workflow = Workflow.from_file(workflow_path)
                        self.workflows[workflow.id] = workflow
                    except Exception as e:
                        print(f"Error loading workflow {workflow_path}: {e}")
                        
    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow by ID."""
        return self.workflows.get(workflow_id)
        
    def find_workflows(self, *, tags: Optional[Set[str]] = None) -> List[Workflow]:
        """Find workflows matching criteria."""
        workflows = list(self.workflows.values())
        
        if tags:
            workflows = [w for w in workflows if tags.issubset(w.tags)]
            
        return sorted(workflows, key=lambda w: w.name)