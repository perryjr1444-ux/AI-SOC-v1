"""Core Pydantic models for data contracts across the AI SOC system.

These models define the schema for Case, Task, and Artifact entities that are
used throughout the orchestrator, API, and audit log. Models are designed with
immutability constraints and comprehensive validation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TaskStatus(str, Enum):
    """Status values for Task execution lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CaseStatus(str, Enum):
    """Status values for Case lifecycle."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class CustodyEntry(BaseModel):
    """Represents a single entry in an artifact's custody chain."""

    actor: str = Field(..., description="Identity of the actor performing the action")
    action: str = Field(..., description="Action performed (e.g., create, update, transfer)")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the action occurred",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context about the action",
    )

    model_config = {"frozen": True}


class TaskStatus(str, Enum):
    """Status of a task in the execution workflow."""
    PENDING = "pending"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Task(BaseModel):
    """Represents a single task in a playbook execution."""
    task_id: str
    case_id: str
    playbook_id: str
    task_name: str
    task_type: str
    inputs: Dict[str, Any]
    needs: List[str]  # Task dependencies
    approval_required: bool
    idempotency_key: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    approved_by: Optional[str] = None
    executed_at: Optional[str] = None


class Artifact(BaseModel):
    """Immutable artifact metadata for evidence and data captured during investigations.

    Artifacts represent files, logs, or other evidence collected and stored in S3.
    Once created, core fields are immutable except for redaction_map and custody_chain
    which track ongoing lifecycle events.
    """

    artifact_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique identifier for this artifact",
    )
    case_id: str = Field(..., description="Case this artifact belongs to")
    kind: str = Field(
        ...,
        description="Type of artifact (e.g., log, screenshot, memory_dump)",
    )
    sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 hash of the artifact content",
    )
    s3_path: str = Field(..., description="S3 URI where artifact is stored")
    redaction_map: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of original to redacted values for PII/sensitive data",
    )
    custody_chain: List[CustodyEntry] = Field(
        default_factory=list,
        description="Chronological chain of custody entries",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the artifact was created",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata about the artifact",
    )

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        """Ensure SHA-256 hash is valid hex string."""
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("SHA-256 hash must be a valid hexadecimal string")
        return v.lower()

    @field_validator("s3_path")
    @classmethod
    def validate_s3_path(cls, v: str) -> str:
        """Ensure S3 path has correct format."""
        if not v.startswith("s3://"):
            raise ValueError("S3 path must start with 's3://'")
        return v

    def add_custody_entry(
        self,
        actor: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Artifact:
        """Add a new custody entry to the chain.

        Returns a new Artifact instance with the updated custody chain.
        """
        entry = CustodyEntry(
            actor=actor,
            action=action,
            details=details or {},
        )
        new_chain = self.custody_chain.copy()
        new_chain.append(entry)
        return self.model_copy(update={"custody_chain": new_chain})


class Task(BaseModel):
    """Represents a unit of work in the orchestration system.

    Tasks are executed by connectors and track their lifecycle from creation
    through completion. Core fields are immutable after creation; only status,
    output, and error_message can be updated.
    """

    task_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this task",
    )
    case_id: str = Field(..., description="Case this task belongs to")
    task_type: str = Field(
        ...,
        description="Type of task (e.g., take_snapshot, enrich_alert)",
    )
    connector: str = Field(..., description="Connector responsible for execution")
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Input parameters for task execution",
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Current execution status",
    )
    output: Optional[Dict[str, Any]] = Field(
        None,
        description="Result data from task execution",
    )
    error_message: Optional[str] = Field(
        None,
        description="Error message if task failed",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the task was created",
    )
    started_at: Optional[datetime] = Field(
        None,
        description="When task execution began",
    )
    completed_at: Optional[datetime] = Field(
        None,
        description="When task execution finished",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional task metadata",
    )

    @model_validator(mode="after")
    def validate_timestamps(self) -> Task:
        """Ensure timestamp ordering is logical."""
        if self.started_at and self.started_at < self.created_at:
            raise ValueError("started_at cannot be before created_at")
        if self.completed_at:
            if self.completed_at < self.created_at:
                raise ValueError("completed_at cannot be before created_at")
            if self.started_at and self.completed_at < self.started_at:
                raise ValueError("completed_at cannot be before started_at")
        return self

    def mark_running(self) -> Task:
        """Transition task to running state.

        Returns a new Task instance with updated status and timestamp.
        """
        if self.status != TaskStatus.PENDING:
            raise ValueError(f"Cannot mark task as running from status: {self.status}")
        return self.model_copy(
            update={
                "status": TaskStatus.RUNNING,
                "started_at": datetime.now(UTC),
            }
        )

    def mark_completed(self, output: Dict[str, Any]) -> Task:
        """Transition task to completed state with output.

        Returns a new Task instance with updated status, output, and timestamp.
        """
        if self.status != TaskStatus.RUNNING:
            raise ValueError(f"Cannot mark task as completed from status: {self.status}")
        return self.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "output": output,
                "completed_at": datetime.now(UTC),
            }
        )

    def mark_failed(self, error_message: str) -> Task:
        """Transition task to failed state with error message.

        Returns a new Task instance with updated status, error, and timestamp.
        """
        if self.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            raise ValueError(f"Cannot mark task as failed from status: {self.status}")
        return self.model_copy(
            update={
                "status": TaskStatus.FAILED,
                "error_message": error_message,
                "completed_at": datetime.now(UTC),
            }
        )


class Case(BaseModel):
    """Represents an investigation case coordinating multiple tasks and artifacts.

    Cases aggregate related tasks and artifacts under a single investigative context.
    Core fields are immutable after creation; only status, tasks, artifacts, and
    metadata can be updated to track case progression.
    """

    case_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this case",
    )
    title: str = Field(..., description="Human-readable case title")
    description: str = Field(
        default="",
        description="Detailed description of the case",
    )
    status: CaseStatus = Field(
        default=CaseStatus.OPEN,
        description="Current case status",
    )
    priority: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Priority level (1=highest, 5=lowest)",
    )
    assignee: Optional[str] = Field(
        None,
        description="User or team assigned to this case",
    )
    tasks: List[str] = Field(
        default_factory=list,
        description="List of task IDs associated with this case",
    )
    artifacts: List[str] = Field(
        default_factory=list,
        description="List of artifact IDs collected for this case",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the case was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the case was last updated",
    )
    closed_at: Optional[datetime] = Field(
        None,
        description="When the case was closed",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional case metadata and context",
    )

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        """Ensure priority is in valid range."""
        if not 1 <= v <= 5:
            raise ValueError("Priority must be between 1 (highest) and 5 (lowest)")
        return v

    @model_validator(mode="after")
    def validate_timestamps(self) -> Case:
        """Ensure timestamp ordering is logical."""
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        if self.closed_at and self.closed_at < self.created_at:
            raise ValueError("closed_at cannot be before created_at")
        return self

    def add_task(self, task_id: str) -> Case:
        """Add a task ID to this case.

        Returns a new Case instance with the updated task list.
        """
        if task_id in self.tasks:
            raise ValueError(f"Task {task_id} already associated with case")
        new_tasks = self.tasks.copy()
        new_tasks.append(task_id)
        return self.model_copy(
            update={
                "tasks": new_tasks,
                "updated_at": datetime.now(UTC),
            }
        )

    def add_artifact(self, artifact_id: str) -> Case:
        """Add an artifact ID to this case.

        Returns a new Case instance with the updated artifact list.
        """
        if artifact_id in self.artifacts:
            raise ValueError(f"Artifact {artifact_id} already associated with case")
        new_artifacts = self.artifacts.copy()
        new_artifacts.append(artifact_id)
        return self.model_copy(
            update={
                "artifacts": new_artifacts,
                "updated_at": datetime.now(UTC),
            }
        )

    def update_status(self, new_status: CaseStatus) -> Case:
        """Update the case status.

        Returns a new Case instance with the updated status.
        """
        updates = {
            "status": new_status,
            "updated_at": datetime.now(UTC),
        }
        if new_status == CaseStatus.CLOSED and not self.closed_at:
            updates["closed_at"] = datetime.now(UTC)
        return self.model_copy(update=updates)


__all__ = [
    "Artifact",
    "Case",
    "CaseStatus",
    "CustodyEntry",
    "Task",
    "TaskStatus",
]
