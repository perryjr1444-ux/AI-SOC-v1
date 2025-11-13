# Orchestrator and DAG Task Execution Framework

## Overview

The orchestration framework provides a robust, DAG-based system for executing playbook tasks with built-in support for:
- Task dependency management and topological ordering
- Policy enforcement before task execution
- Approval gates for sensitive operations
- Idempotency checking to prevent duplicate execution
- Comprehensive audit logging
- Error handling and resilience

## Architecture

### Components

1. **DAG (Directed Acyclic Graph)** - `core/dag.py`
   - Validates task dependencies
   - Computes execution layers for parallel processing
   - Detects cycles and invalid references

2. **Orchestrator** - `core/orchestrator.py`
   - Manages playbook execution lifecycle
   - Enforces policies and approval gates
   - Handles idempotency and error recovery
   - Integrates with audit logging

3. **Task Model** - `core/models.py`
   - Represents individual task state
   - Tracks status, inputs, outputs, and metadata

4. **AuditLog** - `core/audit.py`
   - Records all significant events
   - Maintains cryptographic hash chain for integrity

## Execution Flow

### 1. Playbook Loading

```python
from agents.commander import Commander
from pathlib import Path

commander = Commander(playbook_dir=Path("./playbooks"))
playbook = commander.load("email_takeover_v1", context={
    "target_email": "user@example.com",
    "case_id": "case_123"
})
```

The Commander loads and validates the playbook YAML, rendering Jinja2 templates with the provided context.

### 2. Orchestrator Initialization

```python
from core.orchestrator import Orchestrator
from core.connectors import ConnectorRegistry

# Initialize connector registry
registry = ConnectorRegistry(token_provider=get_oauth_token)

# Optional: provide policy checker and idempotency store
async def policy_checker(task_type, task_name, inputs):
    # Custom policy logic
    return True  # Allow execution

orchestrator = Orchestrator(
    connector_registry=registry,
    policy_checker=policy_checker,
    idempotency_store=redis_store  # Or any dict-like object
)
```

### 3. Playbook Execution

```python
result = await orchestrator.run_playbook(
    playbook=playbook,
    case_id="case_123",
    context={"target_email": "user@example.com"},
    auto_approve=False  # Require manual approval for sensitive tasks
)
```

### 4. Execution Phases

For each layer in the DAG (tasks with no mutual dependencies):

#### a. Task Initialization
- Create Task record with status `PENDING`
- Record task creation in audit log

#### b. Idempotency Check
- If task has `idempotency_key`, check if already executed
- If found, set status to `SKIPPED` and continue to next task
- Record skip event in audit log

#### c. Input Resolution
- Resolve template variables from context
- Resolve references to previous task outputs
  - Format: `{{task_name.output.field}}`
  - Example: `{{list_filters.output.suspicious_ids}}`

#### d. Approval Gate
- If `approval_required=true` and `auto_approve=false`:
  - Set status to `WAITING_APPROVAL`
  - Record approval request in audit log
  - Skip task execution (can be approved later)

#### e. Policy Check
- If policy_checker is configured:
  - Call `policy_checker(task_type, task_name, inputs)`
  - If denied, set status to `FAILED` with error
  - Record policy decision in audit log

#### f. Task Execution
- Set status to `RUNNING`
- Map task type to connector
- Call connector with resolved inputs
- Record connector invocation in audit log

#### g. Completion Handling
- On success:
  - Set status to `COMPLETED`
  - Store output for dependent tasks
  - Record idempotency if key provided
  - Record completion in audit log
  
- On error:
  - Set status to `FAILED`
  - Store error message
  - Record failure in audit log
  - Continue with other tasks (fail gracefully)

### 5. Result Processing

```python
{
    "case_id": "case_123",
    "playbook_id": "email_takeover_v1",
    "tasks": {
        "task1": {
            "task_id": "uuid",
            "status": "completed",
            "output": {...},
            "executed_at": "2024-01-01T12:00:00Z"
        },
        "task2": {
            "task_id": "uuid",
            "status": "waiting_approval",
            ...
        }
    },
    "results": {
        "task1": {...}  # Task outputs for resolved references
    }
}
```

## Task Dependencies

Tasks define dependencies using the `needs` field:

```yaml
tasks:
  proof_of_control:
    type: ProofOfControl
    needs: []  # No dependencies, runs in layer 0
    
  list_filters:
    type: ListFilters
    needs: [proof_of_control]  # Runs after proof_of_control
    
  delete_filters:
    type: DeleteFilter
    needs: [list_filters]  # Runs after list_filters
```

### Parallel Execution

Tasks with no mutual dependencies execute in the same layer:

```yaml
tasks:
  snapshot:
    needs: [proof_of_control]
    
  list_filters:
    needs: [proof_of_control]
    
  rotate_password:
    needs: [proof_of_control]
```

All three tasks run in parallel (layer 1) after `proof_of_control` (layer 0).

### Diamond Pattern

Common pattern where multiple tasks converge:

```yaml
tasks:
  start:
    needs: []
    
  path_a:
    needs: [start]
    
  path_b:
    needs: [start]
    
  end:
    needs: [path_a, path_b]
```

Execution layers:
- Layer 0: `start`
- Layer 1: `path_a`, `path_b` (parallel)
- Layer 2: `end`

## Idempotency

Prevent duplicate execution of tasks:

```yaml
tasks:
  rotate_password:
    type: RotatePassword
    idempotency_key: "pwd-{{target_email}}"
    inputs:
      user_email: "{{target_email}}"
```

The orchestrator:
1. Checks if `idempotency_key` exists in store
2. If found, skips task execution
3. If not found, executes task and records key

### Idempotency Store

Any dict-like object can serve as the store:

```python
# In-memory (development)
store = {}

# Redis (production)
import redis
store = redis.Redis().hgetall("idempotency")

# Custom implementation
class CustomStore:
    def __contains__(self, key):
        ...
    def __setitem__(self, key, value):
        ...
```

## Approval Workflow

Tasks requiring approval:

```yaml
tasks:
  delete_suspicious_filters:
    type: DeleteFilter
    approval_required: true
    inputs:
      filter_ids: "{{list_filters.output.suspicious_ids}}"
```

### Manual Approval

```python
# Task starts in WAITING_APPROVAL status
result = await orchestrator.run_playbook(
    playbook=playbook,
    case_id="case_123",
    context={},
    auto_approve=False
)

# Later, approve the task
approved = await orchestrator.approve_task(
    task_name="delete_suspicious_filters",
    approver="admin@example.com"
)

# Re-run playbook or continue execution
# (Implementation detail: would need to resume execution)
```

### Auto-Approval

For automated scenarios:

```python
result = await orchestrator.run_playbook(
    playbook=playbook,
    case_id="case_123",
    context={},
    auto_approve=True  # Skip approval gates
)
```

## Policy Enforcement

Implement custom policy logic:

```python
async def opa_policy_checker(task_type, task_name, inputs):
    """Check OPA (Open Policy Agent) for authorization."""
    import aiohttp
    
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            "http://opa:8181/v1/data/playbooks/allow",
            json={
                "input": {
                    "task_type": task_type,
                    "task_name": task_name,
                    "inputs": inputs
                }
            }
        )
        data = await response.json()
        return data.get("result", False)

orchestrator = Orchestrator(
    connector_registry=registry,
    policy_checker=opa_policy_checker
)
```

Tasks denied by policy are marked as `FAILED` with error "Policy check failed".

## Error Handling

### Task-Level Errors

When a task fails:
- Status set to `FAILED`
- Error message stored
- Execution continues with other tasks
- Dependent tasks are not affected (they'll fail if they need the output)

### DAG-Level Errors

Validation errors caught before execution:
- Cycle detection: `DAGCycleError`
- Unknown dependencies: `ValueError`
- Duplicate task names: `ValueError` (from Commander)

### Connector Errors

When a connector fails:
- Exception caught and logged
- Task status set to `FAILED`
- Error details stored for debugging

## Audit Trail

Every significant event is logged:

```json
{
  "case_id": "case_123",
  "task_id": "task_uuid",
  "event": "task_started",
  "details": "Task: rotate_password",
  "ts": "2024-01-01T12:00:00Z"
}
```

### Event Types

- `playbook_started` / `playbook_completed`
- `dag_validated` / `dag_validation_failed`
- `layer_started` / `layer_completed`
- `task_created` / `task_started` / `task_completed` / `task_failed`
- `task_waiting_approval` / `task_approved`
- `task_skipped_idempotent`
- `policy_checked` / `policy_check_error` / `task_policy_failed`
- `connector_called` / `connector_error`

### Cryptographic Integrity

Each log entry includes a hash chain:
```
entry_json previous_hash -> SHA256 -> chain_hash
```

This prevents tampering with historical records.

## Testing

### Unit Tests

```bash
# Test DAG implementation
pytest tests/test_dag.py -v

# Test orchestrator
pytest tests/test_orchestrator.py -v
```

### Integration Testing

Mock connectors for testing:

```python
class MockConnector:
    async def call(self, payload):
        return {"status": "success"}

registry = MockConnectorRegistry()
registry.register("gmail:list_filters", MockConnector())

orchestrator = Orchestrator(connector_registry=registry)
```

### Test Scenarios

1. **Linear dependencies** - Sequential task execution
2. **Parallel tasks** - Independent tasks in same layer
3. **Diamond pattern** - Converging dependencies
4. **Idempotency** - Duplicate execution prevention
5. **Approval gates** - Manual approval workflow
6. **Policy denial** - Task blocked by policy
7. **Error handling** - Connector failures
8. **Input resolution** - Template variable substitution
9. **Output references** - Cross-task data flow

## Edge Cases

### Cycle Detection

```yaml
tasks:
  task1:
    needs: [task2]
  task2:
    needs: [task1]
```

**Result**: `DAGCycleError` raised during initialization

### Missing Dependencies

```yaml
tasks:
  task1:
    needs: [nonexistent_task]
```

**Result**: `ValueError` raised during DAG validation

### Failed Dependency

If a task fails, dependent tasks may fail when they try to resolve output references. Consider implementing explicit dependency status checking in future versions.

### Empty Playbook

```yaml
tasks: {}
```

**Result**: Valid playbook with 0 layers, no tasks executed

### Self-Reference

```yaml
tasks:
  task1:
    needs: [task1]
```

**Result**: `DAGCycleError` raised during cycle detection

## Best Practices

### 1. Design Playbooks for Idempotency

Always include idempotency keys for non-idempotent operations:

```yaml
tasks:
  create_resource:
    idempotency_key: "create-{{resource_id}}"
```

### 2. Minimize Layer Depth

Keep dependency chains shallow for faster execution:
- ❌ Bad: 10 sequential tasks
- ✅ Good: 3 layers with parallel tasks

### 3. Use Approval Gates Wisely

Only require approval for destructive operations:
- Delete operations
- Password rotations
- Token revocations
- Factory resets

### 4. Implement Comprehensive Policies

Check all aspects of task execution:
- User permissions
- Resource quotas
- Time-based restrictions
- Compliance requirements

### 5. Monitor Audit Logs

Regularly review audit logs for:
- Unusual approval patterns
- Policy violations
- Execution failures
- Performance bottlenecks

### 6. Test Edge Cases

Ensure your playbooks handle:
- Empty outputs
- Null values
- Missing fields
- Connector timeouts

### 7. Use Meaningful Task Names

Task names should be descriptive and unique:
- ❌ Bad: `task1`, `task2`, `task3`
- ✅ Good: `proof_of_control`, `list_filters`, `delete_suspicious_filters`

## Future Enhancements

Potential improvements to the framework:

1. **Resumable Execution**
   - Save orchestrator state
   - Resume from last checkpoint
   - Handle approval workflows asynchronously

2. **Task Retries**
   - Automatic retry on transient failures
   - Exponential backoff
   - Max retry limits

3. **Conditional Execution**
   - Skip tasks based on runtime conditions
   - Dynamic dependency resolution

4. **Parallel Execution**
   - Actual async/await parallelism within layers
   - Configurable concurrency limits

5. **Real-time Monitoring**
   - WebSocket updates for task status
   - Progress indicators
   - Live audit log streaming

6. **Rollback Support**
   - Undo operations on failure
   - Compensating transactions
   - State snapshots

## References

- **Playbook Example**: `playbooks/email_takeover_v1.yaml`
- **DAG Implementation**: `core/dag.py`
- **Orchestrator**: `core/orchestrator.py`
- **Task Model**: `core/models.py`
- **Audit Log**: `core/audit.py`
- **Tests**: `tests/test_dag.py`, `tests/test_orchestrator.py`
