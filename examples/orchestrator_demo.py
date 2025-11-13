#!/usr/bin/env python3
"""
Demo script showing how to use the orchestrator to execute a playbook.

This example demonstrates:
- Loading a playbook from YAML
- Setting up connectors
- Running the orchestrator
- Handling approval gates
- Checking task status
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.commander import Commander
from core.orchestrator import Orchestrator
from core.models import TaskStatus


class DemoConnectorRegistry:
    """Simple mock connector registry for demonstration."""
    
    def __init__(self):
        self.connectors = {}
        self._setup_demo_connectors()
    
    def _setup_demo_connectors(self):
        """Setup mock connectors that simulate real operations."""
        
        class ListFiltersConnector:
            async def call(self, payload):
                print(f"  📧 Listing email filters for {payload.get('user_email', 'user')}")
                # Simulate finding suspicious filters
                return {
                    "filters": [
                        {"id": "filter_123", "name": "Forward to attacker"},
                        {"id": "filter_456", "name": "Delete security alerts"}
                    ],
                    "suspicious_ids": ["filter_123", "filter_456"]
                }
        
        class DeleteFilterConnector:
            async def call(self, payload):
                filter_ids = payload.get('filter_ids', [])
                print(f"  🗑️  Deleting {len(filter_ids)} suspicious filters")
                return {"deleted": filter_ids, "status": "success"}
        
        class ChangePasswordConnector:
            async def call(self, payload):
                print(f"  🔐 Rotating password for {payload.get('user_email', 'user')}")
                return {"status": "success", "changed_at": "2024-01-01T12:00:00Z"}
        
        class Setup2FAConnector:
            async def call(self, payload):
                print(f"  🔒 Enrolling 2FA for {payload.get('user_email', 'user')}")
                return {"status": "success", "method": "totp"}
        
        class RevokeTokensConnector:
            async def call(self, payload):
                print(f"  🚫 Revoking OAuth tokens for user {payload.get('user_id', 'user')}")
                return {"status": "success", "tokens_revoked": 5}
        
        class EvidenceConnector:
            async def call(self, payload):
                print(f"  📸 Taking evidence snapshot: {payload.get('local_path', 'unknown')}")
                return {"status": "success", "artifact_id": "artifact_12345"}
        
        self.connectors = {
            "gmail:list_filters": ListFiltersConnector(),
            "gmail:delete_filter": DeleteFilterConnector(),
            "gmail:change_password": ChangePasswordConnector(),
            "gmail:setup_2fa": Setup2FAConnector(),
            "msgraph:revoke_tokens": RevokeTokensConnector(),
            "evidence:take_snapshot": EvidenceConnector(),
        }
    
    def get(self, name):
        if name not in self.connectors:
            # Return a default connector for unknown types
            class DefaultConnector:
                async def call(self, payload):
                    print(f"  ✅ Executing {name}")
                    return {"status": "success"}
            return DefaultConnector()
        return self.connectors[name]


async def demo_basic_execution():
    """Demo 1: Basic playbook execution with auto-approve."""
    print("\n" + "="*60)
    print("DEMO 1: Basic Playbook Execution (Auto-Approve)")
    print("="*60)
    
    # Create a simple playbook
    playbook = {
        "playbook_id": "demo_simple",
        "tasks": {
            "proof": {
                "type": "ProofOfControl",
                "inputs": {"account_email": "victim@example.com"},
                "needs": [],
                "approval_required": False,
            },
            "list_filters": {
                "type": "ListFilters",
                "inputs": {"user_email": "victim@example.com"},
                "needs": ["proof"],
                "approval_required": False,
            },
            "delete_filters": {
                "type": "DeleteFilter",
                "inputs": {"filter_ids": "{{list_filters.output.suspicious_ids}}"},
                "needs": ["list_filters"],
                "approval_required": True,  # Requires approval
            }
        }
    }
    
    # Setup orchestrator
    registry = DemoConnectorRegistry()
    orchestrator = Orchestrator(connector_registry=registry)
    
    # Execute with auto-approve
    print("\n🚀 Starting playbook execution...")
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="demo_case_001",
        context={"target_email": "victim@example.com"},
        auto_approve=True
    )
    
    # Show results
    print("\n📊 Execution Results:")
    for task_name, task_info in result["tasks"].items():
        status = task_info["status"]
        emoji = "✅" if status == TaskStatus.COMPLETED else "⏸️"
        print(f"  {emoji} {task_name}: {status}")
    
    return result


async def demo_manual_approval():
    """Demo 2: Playbook execution with manual approval required."""
    print("\n" + "="*60)
    print("DEMO 2: Manual Approval Workflow")
    print("="*60)
    
    playbook = {
        "playbook_id": "demo_approval",
        "tasks": {
            "list_filters": {
                "type": "ListFilters",
                "inputs": {"user_email": "user@example.com"},
                "needs": [],
                "approval_required": False,
            },
            "delete_filters": {
                "type": "DeleteFilter",
                "inputs": {"filter_ids": "{{list_filters.output.suspicious_ids}}"},
                "needs": ["list_filters"],
                "approval_required": True,
            }
        }
    }
    
    registry = DemoConnectorRegistry()
    orchestrator = Orchestrator(connector_registry=registry)
    
    # Execute WITHOUT auto-approve
    print("\n🚀 Starting playbook execution (manual approval required)...")
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="demo_case_002",
        context={},
        auto_approve=False
    )
    
    # Show tasks waiting for approval
    print("\n⏸️  Tasks waiting for approval:")
    waiting_tasks = orchestrator.get_tasks_by_status(TaskStatus.WAITING_APPROVAL)
    for task in waiting_tasks:
        print(f"  - {task.task_name} ({task.task_type})")
    
    # Simulate manual approval
    if waiting_tasks:
        task_name = waiting_tasks[0].task_name
        print(f"\n👤 Approving task: {task_name}")
        approved = await orchestrator.approve_task(task_name, "admin@example.com")
        if approved:
            print(f"  ✅ Task approved by admin@example.com")


async def demo_idempotency():
    """Demo 3: Idempotency preventing duplicate execution."""
    print("\n" + "="*60)
    print("DEMO 3: Idempotency Check")
    print("="*60)
    
    playbook = {
        "playbook_id": "demo_idempotent",
        "tasks": {
            "rotate_password": {
                "type": "RotatePassword",
                "inputs": {"user_email": "user@example.com"},
                "needs": [],
                "approval_required": False,
                "idempotency_key": "pwd-user@example.com",
            }
        }
    }
    
    # Shared idempotency store
    idempotency_store = {}
    
    registry = DemoConnectorRegistry()
    orchestrator1 = Orchestrator(
        connector_registry=registry,
        idempotency_store=idempotency_store
    )
    
    # First execution
    print("\n🚀 First execution...")
    result1 = await orchestrator1.run_playbook(
        playbook=playbook,
        case_id="demo_case_003a",
        context={},
        auto_approve=True
    )
    
    status1 = result1["tasks"]["rotate_password"]["status"]
    print(f"  Result: {status1}")
    
    # Second execution with same idempotency key
    orchestrator2 = Orchestrator(
        connector_registry=registry,
        idempotency_store=idempotency_store  # Same store
    )
    
    print("\n🚀 Second execution (should be skipped)...")
    result2 = await orchestrator2.run_playbook(
        playbook=playbook,
        case_id="demo_case_003b",
        context={},
        auto_approve=True
    )
    
    status2 = result2["tasks"]["rotate_password"]["status"]
    print(f"  Result: {status2}")
    print(f"\n✨ Idempotency prevented duplicate execution!")


async def demo_policy_enforcement():
    """Demo 4: Policy enforcement blocking task execution."""
    print("\n" + "="*60)
    print("DEMO 4: Policy Enforcement")
    print("="*60)
    
    playbook = {
        "playbook_id": "demo_policy",
        "tasks": {
            "delete_filters": {
                "type": "DeleteFilter",
                "inputs": {"filter_ids": ["filter_1", "filter_2"]},
                "needs": [],
                "approval_required": False,
            }
        }
    }
    
    # Policy that denies certain operations
    async def strict_policy(task_type, task_name, inputs):
        print(f"  🛡️  Policy check: {task_type}")
        if task_type == "DeleteFilter":
            print(f"    ❌ Policy DENIED: DeleteFilter operations not allowed")
            return False
        return True
    
    registry = DemoConnectorRegistry()
    orchestrator = Orchestrator(
        connector_registry=registry,
        policy_checker=strict_policy
    )
    
    print("\n🚀 Starting playbook execution...")
    result = await orchestrator.run_playbook(
        playbook=playbook,
        case_id="demo_case_004",
        context={},
        auto_approve=True
    )
    
    status = result["tasks"]["delete_filters"]["status"]
    error = result["tasks"]["delete_filters"].get("error", "")
    print(f"\n📊 Result: {status}")
    print(f"  Error: {error}")


async def demo_dag_layers():
    """Demo 5: Show how DAG organizes tasks into layers."""
    print("\n" + "="*60)
    print("DEMO 5: DAG Layer Execution")
    print("="*60)
    
    from core.dag import DAG
    
    # Complex playbook with multiple dependency paths
    tasks = {
        "proof": {"needs": []},
        "snapshot": {"needs": ["proof"]},
        "list_filters": {"needs": ["proof"]},
        "rotate_password": {"needs": ["proof"]},
        "delete_filters": {"needs": ["list_filters"]},
        "enroll_2fa": {"needs": ["rotate_password"]},
        "revoke_tokens": {"needs": ["rotate_password"]},
        "coach": {"needs": ["enroll_2fa", "revoke_tokens"]},
    }
    
    dag = DAG(tasks)
    layers = dag.get_execution_layers()
    
    print("\n📊 Execution Layers:")
    for i, layer in enumerate(layers):
        print(f"\n  Layer {i}:")
        for task_name in layer:
            deps = dag.get_dependencies(task_name)
            if deps:
                print(f"    - {task_name} (depends on: {', '.join(deps)})")
            else:
                print(f"    - {task_name} (no dependencies)")
    
    print(f"\n✨ Total layers: {len(layers)}")
    print(f"   Tasks can be executed in {len(layers)} sequential steps")
    print(f"   Tasks within each layer can run in parallel")


async def main():
    """Run all demos."""
    print("\n" + "█"*60)
    print("  ORCHESTRATOR & DAG TASK EXECUTION FRAMEWORK DEMO")
    print("█"*60)
    
    try:
        # Run demos
        await demo_basic_execution()
        await demo_manual_approval()
        await demo_idempotency()
        await demo_policy_enforcement()
        await demo_dag_layers()
        
        print("\n" + "="*60)
        print("✅ All demos completed successfully!")
        print("="*60)
        print("\nFor more details, see: docs/ORCHESTRATION.md")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
