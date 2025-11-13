"""Tests for Orchestrator implementation."""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestrator import Orchestrator
from core.models import TaskStatus


class MockConnector:
    """Mock connector for testing."""
    
    def __init__(self, return_value=None, should_fail=False):
        self.return_value = return_value or {"status": "success"}
        self.should_fail = should_fail
        self.call_count = 0
        self.last_payload = None
    
    async def call(self, payload):
        self.call_count += 1
        self.last_payload = payload
        if self.should_fail:
            raise Exception("Connector failed")
        return self.return_value


class MockConnectorRegistry:
    """Mock connector registry for testing."""
    
    def __init__(self):
        self.connectors = {}
    
    def register(self, name, connector):
        self.connectors[name] = connector
    
    def get(self, name):
        if name not in self.connectors:
            raise KeyError(f"Connector {name} not registered")
        return self.connectors[name]


@pytest.mark.asyncio
async def test_orchestrator_simple_playbook():
    """Test executing a simple playbook."""
    registry = MockConnectorRegistry()
    mock_connector = MockConnector({"result": "success"})
    registry.register("gmail:list_filters", mock_connector)
    
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_playbook",
        "tasks": {
            "task1": {
                "type": "ListFilters",
                "inputs": {"user_email": "test@example.com"},
                "needs": [],
                "approval_required": False,
            }
        }
    }
    
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_1",
        context={},
        auto_approve=False,
    )
    
    assert result["case_id"] == "test_case_1"
    assert result["playbook_id"] == "test_playbook"
    assert "task1" in result["tasks"]
    assert result["tasks"]["task1"]["status"] == TaskStatus.COMPLETED
    assert mock_connector.call_count == 1


@pytest.mark.asyncio
async def test_orchestrator_task_dependencies():
    """Test that tasks execute in correct order based on dependencies."""
    registry = MockConnectorRegistry()
    
    connector1 = MockConnector({"output": {"value": "from_task1"}})
    connector2 = MockConnector({"output": {"value": "from_task2"}})
    
    registry.register("gmail:list_filters", connector1)
    registry.register("gmail:delete_filter", connector2)
    
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_deps",
        "tasks": {
            "task1": {
                "type": "ListFilters",
                "inputs": {},
                "needs": [],
                "approval_required": False,
            },
            "task2": {
                "type": "DeleteFilter",
                "inputs": {},
                "needs": ["task1"],
                "approval_required": False,
            }
        }
    }
    
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_2",
        context={},
    )
    
    # Both tasks should complete
    assert result["tasks"]["task1"]["status"] == TaskStatus.COMPLETED
    assert result["tasks"]["task2"]["status"] == TaskStatus.COMPLETED
    
    # Task1 should execute before task2
    assert connector1.call_count == 1
    assert connector2.call_count == 1


@pytest.mark.asyncio
async def test_orchestrator_parallel_tasks():
    """Test that independent tasks can execute in parallel."""
    registry = MockConnectorRegistry()
    
    connector1 = MockConnector()
    connector2 = MockConnector()
    
    registry.register("gmail:list_filters", connector1)
    registry.register("evidence:take_snapshot", connector2)
    
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_parallel",
        "tasks": {
            "task1": {
                "type": "ListFilters",
                "inputs": {},
                "needs": [],
                "approval_required": False,
            },
            "task2": {
                "type": "EvidenceSnapshot",
                "inputs": {},
                "needs": [],
                "approval_required": False,
            }
        }
    }
    
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_3",
        context={},
    )
    
    # Both tasks should complete
    assert result["tasks"]["task1"]["status"] == TaskStatus.COMPLETED
    assert result["tasks"]["task2"]["status"] == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_orchestrator_idempotency():
    """Test idempotency checking."""
    registry = MockConnectorRegistry()
    mock_connector = MockConnector({"result": "success"})
    registry.register("gmail:list_filters", mock_connector)
    
    idempotency_store = {}
    orchestrator = Orchestrator(
        connector_registry=registry,
        idempotency_store=idempotency_store,
    )
    
    playbook = {
        "playbook_id": "test_idempotent",
        "tasks": {
            "task1": {
                "type": "ListFilters",
                "inputs": {},
                "needs": [],
                "approval_required": False,
                "idempotency_key": "unique_key_123",
            }
        }
    }
    
    # First execution
    result1 = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_4a",
        context={},
    )
    
    assert result1["tasks"]["task1"]["status"] == TaskStatus.COMPLETED
    assert mock_connector.call_count == 1
    
    # Second execution should skip due to idempotency
    orchestrator2 = Orchestrator(
        connector_registry=registry,
        idempotency_store=idempotency_store,  # Same store
    )
    
    # Reset connector count to track second run
    initial_count = mock_connector.call_count
    
    result2 = await orchestrator2.run_playbook(
        playbook=playbook,
        case_id="test_case_4b",
        context={},
    )
    
    # Task should be skipped in the result
    assert result2["tasks"]["task1"]["status"] == "skipped"
    # Connector should not be called again
    assert mock_connector.call_count == initial_count


@pytest.mark.asyncio
async def test_orchestrator_approval_required():
    """Test that tasks requiring approval wait."""
    registry = MockConnectorRegistry()
    mock_connector = MockConnector()
    registry.register("gmail:change_password", mock_connector)
    
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_approval",
        "tasks": {
            "task1": {
                "type": "RotatePassword",
                "inputs": {},
                "needs": [],
                "approval_required": True,
            }
        }
    }
    
    # Without auto-approve
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_5",
        context={},
        auto_approve=False,
    )
    
    assert result["tasks"]["task1"]["status"] == TaskStatus.WAITING_APPROVAL
    assert mock_connector.call_count == 0  # Not executed
    
    # With auto-approve
    orchestrator2 = Orchestrator(connector_registry=registry)
    result2 = await orchestrator2.run_playbook(
        playbook=playbook,
        case_id="test_case_5b",
        context={},
        auto_approve=True,
    )
    
    assert result2["tasks"]["task1"]["status"] == TaskStatus.COMPLETED
    assert mock_connector.call_count == 1


@pytest.mark.asyncio
async def test_orchestrator_policy_check():
    """Test policy checking before task execution."""
    registry = MockConnectorRegistry()
    mock_connector = MockConnector()
    registry.register("gmail:list_filters", mock_connector)
    
    # Policy that denies execution
    async def deny_policy(**kwargs):
        return False
    
    orchestrator = Orchestrator(
        connector_registry=registry,
        policy_checker=deny_policy,
    )
    
    playbook = {
        "playbook_id": "test_policy",
        "tasks": {
            "task1": {
                "type": "ListFilters",
                "inputs": {},
                "needs": [],
                "approval_required": False,
            }
        }
    }
    
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_6",
        context={},
    )
    
    assert result["tasks"]["task1"]["status"] == TaskStatus.FAILED
    assert "Policy check failed" in result["tasks"]["task1"]["error"]
    assert mock_connector.call_count == 0  # Not executed


@pytest.mark.asyncio
async def test_orchestrator_error_handling():
    """Test error handling when connector fails."""
    registry = MockConnectorRegistry()
    mock_connector = MockConnector(should_fail=True)
    registry.register("gmail:list_filters", mock_connector)
    
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_error",
        "tasks": {
            "task1": {
                "type": "ListFilters",
                "inputs": {},
                "needs": [],
                "approval_required": False,
            }
        }
    }
    
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_7",
        context={},
    )
    
    assert result["tasks"]["task1"]["status"] == TaskStatus.FAILED
    assert result["tasks"]["task1"]["error"] is not None


@pytest.mark.asyncio
async def test_orchestrator_input_resolution():
    """Test that task inputs are resolved from context."""
    registry = MockConnectorRegistry()
    mock_connector = MockConnector()
    registry.register("gmail:list_filters", mock_connector)
    
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_resolve",
        "tasks": {
            "task1": {
                "type": "ListFilters",
                "inputs": {
                    "user_email": "{{target_email}}",
                    "case_id": "{{case_id}}",
                },
                "needs": [],
                "approval_required": False,
            }
        }
    }
    
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_8",
        context={"target_email": "user@example.com", "case_id": "case_123"},
    )
    
    assert result["tasks"]["task1"]["status"] == TaskStatus.COMPLETED
    assert mock_connector.call_count == 1
    
    # Check that inputs were resolved
    payload = mock_connector.last_payload
    assert payload["user_email"] == "user@example.com"
    assert payload["case_id"] == "case_123"


@pytest.mark.asyncio
async def test_orchestrator_task_output_resolution():
    """Test resolving inputs from previous task outputs."""
    registry = MockConnectorRegistry()
    
    connector1 = MockConnector({"suspicious_ids": ["id1", "id2"]})
    connector2 = MockConnector()
    
    registry.register("gmail:list_filters", connector1)
    registry.register("gmail:delete_filter", connector2)
    
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_output_resolve",
        "tasks": {
            "list": {
                "type": "ListFilters",
                "inputs": {},
                "needs": [],
                "approval_required": False,
            },
            "delete": {
                "type": "DeleteFilter",
                "inputs": {
                    "filter_ids": "{{list.output.suspicious_ids}}",
                },
                "needs": ["list"],
                "approval_required": False,
            }
        }
    }
    
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_9",
        context={},
    )
    
    assert result["tasks"]["list"]["status"] == TaskStatus.COMPLETED
    assert result["tasks"]["delete"]["status"] == TaskStatus.COMPLETED
    
    # Check that output was resolved
    payload = connector2.last_payload
    assert "filter_ids" in payload


@pytest.mark.asyncio
async def test_orchestrator_approve_task():
    """Test manual task approval."""
    registry = MockConnectorRegistry()
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_manual_approve",
        "tasks": {
            "task1": {
                "type": "RotatePassword",
                "inputs": {},
                "needs": [],
                "approval_required": True,
            }
        }
    }
    
    # Start playbook execution (task will wait for approval)
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_10",
        context={},
        auto_approve=False,
    )
    
    assert result["tasks"]["task1"]["status"] == TaskStatus.WAITING_APPROVAL
    
    # Approve the task
    approved = await orchestrator.approve_task("task1", "admin@example.com")
    assert approved is True
    
    # Check approval was recorded
    status = orchestrator.get_task_status("task1")
    assert status == TaskStatus.APPROVED


@pytest.mark.asyncio
async def test_orchestrator_get_tasks_by_status():
    """Test retrieving tasks by status."""
    registry = MockConnectorRegistry()
    mock_connector = MockConnector()
    registry.register("gmail:list_filters", mock_connector)
    
    orchestrator = Orchestrator(connector_registry=registry)
    
    playbook = {
        "playbook_id": "test_status",
        "tasks": {
            "task1": {
                "type": "ListFilters",
                "inputs": {},
                "needs": [],
                "approval_required": False,
            },
            "task2": {
                "type": "RotatePassword",
                "inputs": {},
                "needs": [],
                "approval_required": True,
            }
        }
    }
    
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="test_case_11",
        context={},
        auto_approve=False,
    )
    
    completed_tasks = orchestrator.get_tasks_by_status(TaskStatus.COMPLETED)
    waiting_tasks = orchestrator.get_tasks_by_status(TaskStatus.WAITING_APPROVAL)
    
    assert len(completed_tasks) == 1
    assert len(waiting_tasks) == 1
    assert completed_tasks[0].task_name == "task1"
    assert waiting_tasks[0].task_name == "task2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
