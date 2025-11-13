"""Tests for DAG implementation."""

import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.dag import DAG, DAGCycleError


def test_dag_simple_linear():
    """Test a simple linear task dependency."""
    tasks = {
        "task1": {"needs": []},
        "task2": {"needs": ["task1"]},
        "task3": {"needs": ["task2"]},
    }
    
    dag = DAG(tasks)
    layers = dag.get_execution_layers()
    
    assert len(layers) == 3
    assert layers[0] == ["task1"]
    assert layers[1] == ["task2"]
    assert layers[2] == ["task3"]


def test_dag_parallel_tasks():
    """Test tasks that can run in parallel."""
    tasks = {
        "task1": {"needs": []},
        "task2": {"needs": []},
        "task3": {"needs": ["task1", "task2"]},
    }
    
    dag = DAG(tasks)
    layers = dag.get_execution_layers()
    
    assert len(layers) == 2
    assert set(layers[0]) == {"task1", "task2"}
    assert layers[1] == ["task3"]


def test_dag_complex_dependencies():
    """Test a more complex DAG structure."""
    tasks = {
        "proof": {"needs": []},
        "snapshot": {"needs": ["proof"]},
        "list": {"needs": ["proof"]},
        "delete": {"needs": ["list"]},
        "rotate": {"needs": ["proof"]},
        "enroll": {"needs": ["rotate"]},
        "revoke": {"needs": ["rotate"]},
        "coach": {"needs": ["enroll", "revoke"]},
    }
    
    dag = DAG(tasks)
    layers = dag.get_execution_layers()
    
    # Verify layer structure
    assert "proof" in layers[0]
    assert set(layers[1]) == {"snapshot", "list", "rotate"}
    assert "delete" in layers[2] and "enroll" in layers[2] and "revoke" in layers[2]
    assert "coach" in layers[3]


def test_dag_cycle_detection():
    """Test that cycles are detected."""
    tasks = {
        "task1": {"needs": ["task2"]},
        "task2": {"needs": ["task3"]},
        "task3": {"needs": ["task1"]},
    }
    
    with pytest.raises(DAGCycleError):
        dag = DAG(tasks)


def test_dag_self_cycle():
    """Test that self-referencing tasks are detected."""
    tasks = {
        "task1": {"needs": ["task1"]},
    }
    
    with pytest.raises(DAGCycleError):
        dag = DAG(tasks)


def test_dag_unknown_dependency():
    """Test that unknown dependencies are detected."""
    tasks = {
        "task1": {"needs": ["nonexistent"]},
    }
    
    with pytest.raises(ValueError, match="depends on unknown task"):
        dag = DAG(tasks)


def test_dag_get_dependencies():
    """Test getting direct dependencies."""
    tasks = {
        "task1": {"needs": []},
        "task2": {"needs": ["task1"]},
    }
    
    dag = DAG(tasks)
    assert dag.get_dependencies("task1") == []
    assert dag.get_dependencies("task2") == ["task1"]


def test_dag_get_dependents():
    """Test getting tasks that depend on a given task."""
    tasks = {
        "task1": {"needs": []},
        "task2": {"needs": ["task1"]},
        "task3": {"needs": ["task1"]},
    }
    
    dag = DAG(tasks)
    dependents = dag.get_dependents("task1")
    assert set(dependents) == {"task2", "task3"}


def test_dag_no_tasks():
    """Test empty DAG."""
    tasks = {}
    dag = DAG(tasks)
    layers = dag.get_execution_layers()
    assert layers == []


def test_dag_single_task():
    """Test DAG with single task."""
    tasks = {
        "only_task": {"needs": []},
    }
    
    dag = DAG(tasks)
    layers = dag.get_execution_layers()
    assert len(layers) == 1
    assert layers[0] == ["only_task"]


def test_dag_diamond_pattern():
    """Test diamond dependency pattern."""
    tasks = {
        "start": {"needs": []},
        "left": {"needs": ["start"]},
        "right": {"needs": ["start"]},
        "end": {"needs": ["left", "right"]},
    }
    
    dag = DAG(tasks)
    layers = dag.get_execution_layers()
    
    assert len(layers) == 3
    assert layers[0] == ["start"]
    assert set(layers[1]) == {"left", "right"}
    assert layers[2] == ["end"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
