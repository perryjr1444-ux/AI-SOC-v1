"""
Orchestrator for executing playbook tasks in a DAG-based workflow.
"""

import uuid
import datetime
from typing import Dict, Any, Optional, Callable, List
from pathlib import Path

from .dag import DAG
from .models import Task, TaskStatus
from .audit import AuditLog


class PolicyCheckError(Exception):
    """Raised when a policy check fails."""
    pass


class IdempotencyError(Exception):
    """Raised when idempotency check fails."""
    pass


class Orchestrator:
    """
    Manages playbook task execution with DAG-based ordering, policy checks,
    approval gates, and audit logging.
    """

    def __init__(
        self,
        connector_registry,
        policy_checker: Optional[Callable] = None,
        idempotency_store: Optional[Dict] = None,
    ):
        """
        Initialize orchestrator.
        
        Args:
            connector_registry: Registry of connector implementations
            policy_checker: Optional callable to check policies before execution
            idempotency_store: Optional dict-like store for idempotency tracking
        """
        self.connector_registry = connector_registry
        self.policy_checker = policy_checker
        self.idempotency_store = idempotency_store if idempotency_store is not None else {}
        self.task_store: Dict[str, Task] = {}

    async def run_playbook(
        self,
        playbook: Dict[str, Any],
        case_id: str,
        context: Dict[str, Any],
        auto_approve: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a playbook by processing its tasks layer-by-layer.
        
        Args:
            playbook: Playbook definition with 'playbook_id' and 'tasks'
            case_id: Unique identifier for this execution case
            context: Context variables for task execution
            auto_approve: If True, automatically approve tasks requiring approval
            
        Returns:
            Dict with execution results including task outputs and errors
        """
        playbook_id = playbook["playbook_id"]
        tasks_def = playbook["tasks"]
        
        # Initialize audit log
        audit = AuditLog(case_id)
        audit.record(
            case_id=case_id,
            task_id="__orchestrator__",
            event="playbook_started",
            details=f"Playbook: {playbook_id}",
        )
        
        # Build DAG
        try:
            dag = DAG(tasks_def)
            layers = dag.get_execution_layers()
        except Exception as e:
            audit.record(
                case_id=case_id,
                task_id="__orchestrator__",
                event="dag_validation_failed",
                details=str(e),
            )
            raise
        
        audit.record(
            case_id=case_id,
            task_id="__orchestrator__",
            event="dag_validated",
            details=f"Layers: {len(layers)}, Tasks: {len(tasks_def)}",
        )
        
        # Create task records
        for task_name, task_def in tasks_def.items():
            task = Task(
                task_id=str(uuid.uuid4()),
                case_id=case_id,
                playbook_id=playbook_id,
                task_name=task_name,
                task_type=task_def.get("type", "Unknown"),
                inputs=task_def.get("inputs", {}),
                needs=task_def.get("needs", []),
                approval_required=task_def.get("approval_required", False),
                idempotency_key=task_def.get("idempotency_key"),
            )
            self.task_store[task_name] = task
            
            audit.record(
                case_id=case_id,
                task_id=task.task_id,
                event="task_created",
                details=f"Task: {task_name}, Type: {task.task_type}",
            )
        
        # Execute layer by layer
        results = {}
        for layer_idx, layer_tasks in enumerate(layers):
            audit.record(
                case_id=case_id,
                task_id="__orchestrator__",
                event="layer_started",
                details=f"Layer {layer_idx}: {layer_tasks}",
            )
            
            for task_name in layer_tasks:
                task = self.task_store[task_name]
                
                try:
                    # Check idempotency
                    if task.idempotency_key:
                        if await self._check_idempotency(task, audit):
                            task.status = TaskStatus.SKIPPED
                            audit.record(
                                case_id=case_id,
                                task_id=task.task_id,
                                event="task_skipped_idempotent",
                                details=f"Key: {task.idempotency_key}",
                            )
                            continue
                    
                    # Resolve inputs from previous task outputs
                    resolved_inputs = self._resolve_inputs(task, context, results)
                    
                    # Check approval requirements
                    if task.approval_required and not auto_approve:
                        task.status = TaskStatus.WAITING_APPROVAL
                        audit.record(
                            case_id=case_id,
                            task_id=task.task_id,
                            event="task_waiting_approval",
                            details=f"Task: {task_name}",
                        )
                        # In a real system, this would wait for external approval
                        # For now, we skip tasks requiring approval
                        continue
                    
                    # Policy check
                    if self.policy_checker:
                        if not await self._check_policy(task, resolved_inputs, audit):
                            task.status = TaskStatus.FAILED
                            task.error = "Policy check failed"
                            audit.record(
                                case_id=case_id,
                                task_id=task.task_id,
                                event="task_policy_failed",
                                details=f"Task: {task_name}",
                            )
                            continue
                    
                    # Execute task
                    task.status = TaskStatus.RUNNING
                    audit.record(
                        case_id=case_id,
                        task_id=task.task_id,
                        event="task_started",
                        details=f"Task: {task_name}",
                    )
                    
                    output = await self._execute_task(task, resolved_inputs, audit)
                    
                    task.status = TaskStatus.COMPLETED
                    task.output = output
                    task.executed_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
                    results[task_name] = output
                    
                    # Store idempotency record
                    if task.idempotency_key:
                        await self._record_idempotency(task, output)
                    
                    audit.record(
                        case_id=case_id,
                        task_id=task.task_id,
                        event="task_completed",
                        details=f"Task: {task_name}",
                    )
                    
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    audit.record(
                        case_id=case_id,
                        task_id=task.task_id,
                        event="task_failed",
                        details=f"Error: {str(e)}",
                    )
                    # Continue with other tasks in the layer
                    # Dependent tasks will be skipped automatically
            
            audit.record(
                case_id=case_id,
                task_id="__orchestrator__",
                event="layer_completed",
                details=f"Layer {layer_idx}",
            )
        
        audit.record(
            case_id=case_id,
            task_id="__orchestrator__",
            event="playbook_completed",
            details=f"Playbook: {playbook_id}",
        )
        
        return {
            "case_id": case_id,
            "playbook_id": playbook_id,
            "tasks": {name: task.model_dump() for name, task in self.task_store.items()},
            "results": results,
        }

    async def _check_idempotency(self, task: Task, audit: AuditLog) -> bool:
        """
        Check if task has already been executed with the same idempotency key.
        
        Returns:
            True if task should be skipped (already executed), False otherwise
        """
        key = task.idempotency_key
        if key in self.idempotency_store:
            # Task already executed
            return True
        return False

    async def _record_idempotency(self, task: Task, output: Dict[str, Any]):
        """Record successful task execution for idempotency."""
        if task.idempotency_key:
            self.idempotency_store[task.idempotency_key] = {
                "task_id": task.task_id,
                "task_name": task.task_name,
                "output": output,
                "executed_at": task.executed_at,
            }

    def _resolve_inputs(
        self,
        task: Task,
        context: Dict[str, Any],
        results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Resolve task inputs by replacing template variables with actual values.
        Supports references to context variables and previous task outputs.
        
        Args:
            task: Task to resolve inputs for
            context: Context variables
            results: Dictionary of task_name -> output from previous tasks
            
        Returns:
            Resolved inputs dictionary
        """
        resolved = {}
        for key, value in task.inputs.items():
            if isinstance(value, str) and "{{" in value:
                # Simple template resolution
                resolved_value = value
                # Replace context variables
                for ctx_key, ctx_value in context.items():
                    resolved_value = resolved_value.replace(
                        f"{{{{{ctx_key}}}}}", str(ctx_value)
                    )
                # Replace task output references (e.g., {{task_name.output.field}})
                for task_name, task_output in results.items():
                    if f"{{{{{task_name}.output" in resolved_value:
                        # Handle nested output references
                        import re
                        pattern = rf"\{{\{{{task_name}\.output\.([^}}]+)\}}\}}"
                        matches = re.findall(pattern, resolved_value)
                        for field in matches:
                            if task_output and field in task_output:
                                resolved_value = resolved_value.replace(
                                    f"{{{{{task_name}.output.{field}}}}}",
                                    str(task_output[field]),
                                )
                resolved[key] = resolved_value
            else:
                resolved[key] = value
        return resolved

    async def _check_policy(
        self,
        task: Task,
        resolved_inputs: Dict[str, Any],
        audit: AuditLog,
    ) -> bool:
        """
        Check if task execution is allowed by policy.
        
        Args:
            task: Task to check
            resolved_inputs: Resolved input parameters
            audit: Audit log for recording checks
            
        Returns:
            True if policy allows execution, False otherwise
        """
        if not self.policy_checker:
            return True
        
        try:
            result = await self.policy_checker(
                task_type=task.task_type,
                task_name=task.task_name,
                inputs=resolved_inputs,
            )
            
            audit.record(
                case_id=task.case_id,
                task_id=task.task_id,
                event="policy_checked",
                details=f"Result: {result}",
            )
            
            return result
        except Exception as e:
            audit.record(
                case_id=task.case_id,
                task_id=task.task_id,
                event="policy_check_error",
                details=str(e),
            )
            return False

    async def _execute_task(
        self,
        task: Task,
        resolved_inputs: Dict[str, Any],
        audit: AuditLog,
    ) -> Dict[str, Any]:
        """
        Execute a task by calling its connector.
        
        Args:
            task: Task to execute
            resolved_inputs: Resolved input parameters
            audit: Audit log
            
        Returns:
            Task output dictionary
        """
        # Map task type to connector
        connector_map = {
            "ProofOfControl": "gmail:list_filters",  # Example mapping
            "EvidenceSnapshot": "evidence:take_snapshot",
            "ListFilters": "gmail:list_filters",
            "DeleteFilter": "gmail:delete_filter",
            "RotatePassword": "gmail:change_password",
            "Enroll2FA": "gmail:setup_2fa",
            "RevokeOAuthTokens": "msgraph:revoke_tokens",
            "HardeningCoach": None,  # No connector, returns advice
        }
        
        connector_name = connector_map.get(task.task_type)
        
        if connector_name is None:
            # Task doesn't require a connector (e.g., HardeningCoach)
            return {"status": "success", "message": f"{task.task_type} completed"}
        
        try:
            connector = self.connector_registry.get(connector_name)
            
            # Add operation hint for connectors that need it
            payload = {**resolved_inputs, "__operation": task.task_type.lower()}
            
            result = await connector.call(payload)
            
            audit.record(
                case_id=task.case_id,
                task_id=task.task_id,
                event="connector_called",
                details=f"Connector: {connector_name}",
            )
            
            return result
        except Exception as e:
            audit.record(
                case_id=task.case_id,
                task_id=task.task_id,
                event="connector_error",
                details=str(e),
            )
            raise

    async def approve_task(self, task_name: str, approver: str) -> bool:
        """
        Approve a task that is waiting for approval.
        
        Args:
            task_name: Name of the task to approve
            approver: Identifier of the approver
            
        Returns:
            True if task was approved, False if not found or not waiting
        """
        task = self.task_store.get(task_name)
        if not task or task.status != TaskStatus.WAITING_APPROVAL:
            return False
        
        task.status = TaskStatus.APPROVED
        task.approved_by = approver
        
        # Record approval in audit log
        audit = AuditLog(task.case_id)
        audit.record(
            case_id=task.case_id,
            task_id=task.task_id,
            event="task_approved",
            details=f"Approved by: {approver}",
        )
        
        return True

    def get_task_status(self, task_name: str) -> Optional[TaskStatus]:
        """Get the current status of a task."""
        task = self.task_store.get(task_name)
        return task.status if task else None

    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        """Get all tasks with a specific status."""
        return [task for task in self.task_store.values() if task.status == status]
