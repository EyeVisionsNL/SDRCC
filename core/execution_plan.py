#!/usr/bin/env python3
"""Immutable, read-only execution planning contract for SDRCC."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


class ExecutionPlanError(RuntimeError):
    """Base exception for execution plan construction failures."""


@dataclass(frozen=True)
class ExecutionPlan:
    """Immutable description of how a plugin would be delegated.

    An ExecutionPlan never performs work. It contains no live process handles,
    receiver locks, mission objects or mutable runtime state.
    """

    plugin_id: str
    adapter_type: str
    executor_type: str | None
    launch_type: str
    target_type: str
    targets: tuple[str, ...]
    receiver_role: str | None
    receiver_type: str | None
    requirements: tuple[str, ...]
    delegates_to: tuple[str, ...]
    executable: bool
    read_only: bool
    foundation_only: bool
    metadata_valid: bool
    validation_errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return an API-safe defensive representation."""
        return {
            "plugin_id": self.plugin_id,
            "adapter_type": self.adapter_type,
            "executor_type": self.executor_type,
            "launch_type": self.launch_type,
            "target_type": self.target_type,
            "targets": list(self.targets),
            "receiver_role": self.receiver_role,
            "receiver_type": self.receiver_type,
            "requirements": list(self.requirements),
            "delegates_to": list(self.delegates_to),
            "executable": self.executable,
            "read_only": self.read_only,
            "foundation_only": self.foundation_only,
            "metadata_valid": self.metadata_valid,
            "validation_errors": list(self.validation_errors),
        }


def normalize_request(
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a defensive request copy without interpreting lifecycle state."""
    if request is None:
        return {}
    return deepcopy(dict(request))
