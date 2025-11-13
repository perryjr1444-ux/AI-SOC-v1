# Orchestrator Examples

This directory contains example scripts demonstrating how to use the orchestrator and DAG task execution framework.

## Running the Demo

```bash
python3 examples/orchestrator_demo.py
```

## What the Demo Shows

The demo script (`orchestrator_demo.py`) demonstrates the following features:

### 1. Basic Playbook Execution
- Creating a playbook with task dependencies
- Auto-approving tasks that require approval
- Sequential execution based on dependencies

### 2. Manual Approval Workflow
- Tasks that wait for manual approval
- Retrieving tasks by status
- Approving tasks programmatically

### 3. Idempotency
- Preventing duplicate execution using idempotency keys
- Sharing idempotency state across orchestrator instances
- Skipping already-executed tasks

### 4. Policy Enforcement
- Implementing custom policy checkers
- Blocking tasks based on policy rules
- Recording policy decisions in audit logs

### 5. DAG Layer Execution
- Visualizing task dependencies
- Understanding execution layers
- Identifying tasks that can run in parallel

## Expected Output

When you run the demo, you should see output similar to:

```
████████████████████████████████████████████████████████████
  ORCHESTRATOR & DAG TASK EXECUTION FRAMEWORK DEMO
████████████████████████████████████████████████████████████

