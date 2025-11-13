from typing import Dict, Any, List, Set
from collections import defaultdict, deque


class DAGCycleError(Exception):
    """Raised when a cycle is detected in the DAG."""
    pass


class DAG:
    """
    Directed Acyclic Graph for task execution ordering.
    Supports topological sorting and layer-by-layer execution.
    """

    def __init__(self, tasks: Dict[str, Any]):
        """
        Initialize DAG with tasks dictionary.
        
        Args:
            tasks: Dict mapping task_name -> task_definition
                   Each task_definition should have a 'needs' field listing dependencies
        """
        self.tasks = tasks
        self._validate_dag()

    def _validate_dag(self):
        """Validate that the task graph is acyclic."""
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()
        
        def has_cycle(task_name: str) -> bool:
            visited.add(task_name)
            rec_stack.add(task_name)
            
            task = self.tasks.get(task_name)
            if task and "needs" in task:
                for dep in task["needs"]:
                    if dep not in self.tasks:
                        raise ValueError(f"Task '{task_name}' depends on unknown task '{dep}'")
                    if dep not in visited:
                        if has_cycle(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            
            rec_stack.remove(task_name)
            return False
        
        for task_name in self.tasks:
            if task_name not in visited:
                if has_cycle(task_name):
                    raise DAGCycleError(f"Cycle detected in task graph involving '{task_name}'")

    def get_execution_layers(self) -> List[List[str]]:
        """
        Return tasks grouped into layers for execution.
        Tasks in the same layer have no dependencies on each other and can run in parallel.
        
        Returns:
            List of layers, where each layer is a list of task names
        """
        # Calculate in-degree for each task
        in_degree = defaultdict(int)
        adjacency = defaultdict(list)
        
        for task_name, task_def in self.tasks.items():
            if task_name not in in_degree:
                in_degree[task_name] = 0
            
            needs = task_def.get("needs", [])
            for dep in needs:
                adjacency[dep].append(task_name)
                in_degree[task_name] += 1
        
        # Find tasks with no dependencies (layer 0)
        queue = deque([name for name in self.tasks if in_degree[name] == 0])
        layers = []
        
        while queue:
            # All tasks in current queue form one layer
            current_layer = list(queue)
            layers.append(current_layer)
            
            # Process this layer and find next layer
            next_queue = []
            for task_name in current_layer:
                for dependent in adjacency[task_name]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_queue.append(dependent)
            
            queue = deque(next_queue)
        
        # Verify all tasks were processed (no cycles)
        if sum(len(layer) for layer in layers) != len(self.tasks):
            raise DAGCycleError("Not all tasks could be ordered - cycle detected")
        
        return layers

    def get_dependencies(self, task_name: str) -> List[str]:
        """Get direct dependencies for a task."""
        task = self.tasks.get(task_name, {})
        return task.get("needs", [])

    def get_dependents(self, task_name: str) -> List[str]:
        """Get tasks that depend on the given task."""
        dependents = []
        for name, task_def in self.tasks.items():
            if task_name in task_def.get("needs", []):
                dependents.append(name)
        return dependents
