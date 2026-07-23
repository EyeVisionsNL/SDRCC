#!/usr/bin/env python3
"""Fail-closed execution adapter contract for SDRCC.

This foundation is intentionally non-operational. Adapters may inspect and
validate plugin execution metadata, but they cannot start services, reserve
receivers, create missions, or launch external processes.
"""

from __future__ import annotations

from abc import ABC
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


class ExecutionAdapterError(RuntimeError):
    """Base exception for execution adapter contract failures."""


class ExecutionNotEnabledError(ExecutionAdapterError):
    """Raised when execution is requested from the read-only foundation."""


class InvalidExecutionMetadataError(ExecutionAdapterError):
    """Raised when plugin execution metadata violates an adapter contract."""


@dataclass(frozen=True)
class ExecutionAdapterDescriptor:
    """Immutable, API-safe description of one resolved adapter."""

    plugin_id: str
    adapter_type: str
    executor_type: str | None
    executable: bool
    foundation_only: bool
    metadata_valid: bool
    validation_errors: tuple[str, ...]
    delegates_to: tuple[str, ...]
    services: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a defensive dictionary representation."""
        return {
            "plugin_id": self.plugin_id,
            "adapter_type": self.adapter_type,
            "executor_type": self.executor_type,
            "executable": self.executable,
            "foundation_only": self.foundation_only,
            "metadata_valid": self.metadata_valid,
            "validation_errors": list(self.validation_errors),
            "delegates_to": list(self.delegates_to),
            "services": list(self.services),
        }


class ExecutionAdapter(ABC):
    """Read-only base contract for future execution delegation.

    Current release scope:
    - metadata validation;
    - adapter resolution;
    - architecture introspection.

    Explicitly out of scope:
    - receiver lifecycle;
    - mission lifecycle;
    - service/process control;
    - runtime or health state mutation.
    """

    adapter_type = "base"
    supported_executor: str | None = None
    delegates_to: tuple[str, ...] = ()
    foundation_only = True

    def __init__(self, plugin: Mapping[str, Any]) -> None:
        self._plugin = deepcopy(dict(plugin))

    @property
    def plugin_id(self) -> str:
        """Return the normalized plugin identifier."""
        return str(self._plugin.get("id") or "").strip().lower()

    @property
    def metadata(self) -> dict[str, Any]:
        """Return a defensive copy of plugin metadata."""
        return deepcopy(self._plugin)

    def validate(self) -> tuple[str, ...]:
        """Return adapter-specific metadata errors without side effects."""
        errors: list[str] = []

        if not self.plugin_id:
            errors.append("plugin id ontbreekt")

        executor = self._plugin.get("executor")
        if executor != self.supported_executor:
            errors.append(
                f"executor {executor!r} past niet bij adapter "
                f"{self.adapter_type!r}"
            )

        return tuple(errors)

    def can_execute(self) -> bool:
        """Return False while this foundation remains non-operational."""
        return False

    def describe(self) -> ExecutionAdapterDescriptor:
        """Return an immutable description of this adapter resolution."""
        errors = self.validate()
        services = self._plugin.get("services")
        if not isinstance(services, list):
            services = []

        return ExecutionAdapterDescriptor(
            plugin_id=self.plugin_id,
            adapter_type=self.adapter_type,
            executor_type=self._plugin.get("executor"),
            executable=self.can_execute(),
            foundation_only=self.foundation_only,
            metadata_valid=not errors,
            validation_errors=errors,
            delegates_to=self.delegates_to,
            services=tuple(str(item) for item in services),
        )

    def prepare(self, request: Mapping[str, Any] | None = None) -> None:
        """Fail closed until a later release explicitly enables delegation."""
        del request
        self._raise_not_enabled("prepare")

    def execute(self, request: Mapping[str, Any] | None = None) -> None:
        """Fail closed until a later release explicitly enables delegation."""
        del request
        self._raise_not_enabled("execute")

    def cancel(self, execution_id: str | None = None) -> None:
        """Fail closed until a later release explicitly enables delegation."""
        del execution_id
        self._raise_not_enabled("cancel")

    def cleanup(self, execution_id: str | None = None) -> None:
        """Fail closed until a later release explicitly enables delegation."""
        del execution_id
        self._raise_not_enabled("cleanup")

    def get_status(self, execution_id: str | None = None) -> dict[str, Any]:
        """Return foundation status without claiming lifecycle authority."""
        del execution_id
        descriptor = self.describe().as_dict()
        return {
            "ok": descriptor["metadata_valid"],
            "state": "FOUNDATION_ONLY",
            "read_only": True,
            "adapter": descriptor,
        }

    def _raise_not_enabled(self, operation: str) -> None:
        raise ExecutionNotEnabledError(
            f"{self.adapter_type}.{operation} is niet actief in "
            "v0.42.0a Execution Adapter Foundation"
        )
