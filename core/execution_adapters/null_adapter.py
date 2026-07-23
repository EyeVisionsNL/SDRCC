#!/usr/bin/env python3
"""Read-only null adapter for planned or passive plugins."""

from __future__ import annotations

from typing import Any, Mapping

from core.execution_adapter import ExecutionAdapter
from core.execution_plan import ExecutionPlan, normalize_request


class NullAdapter(ExecutionAdapter):
    """Represent a plugin without an execution backend."""

    adapter_type = "null"
    supported_executor = None
    delegates_to = ()

    def validate(self) -> tuple[str, ...]:
        errors = list(super().validate())
        status = str(self.metadata.get("status") or "").strip().lower()
        if status not in {"planned", "active"}:
            errors.append("null-adapter vereist pluginstatus active of planned")
        return tuple(errors)


    def build_plan(
        self,
        request: Mapping[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Describe that no execution backend is currently available."""
        normalized_request = normalize_request(request)
        descriptor = self.describe()
        receiver_role = str(
            normalized_request.get("receiver_role")
            or self.metadata.get("assignment_role")
            or ""
        ).strip() or None
        receiver_type = str(
            self.metadata.get("receiver_type") or ""
        ).strip() or None

        return ExecutionPlan(
            plugin_id=self.plugin_id,
            adapter_type=self.adapter_type,
            executor_type=None,
            launch_type="none",
            target_type="none",
            targets=(),
            receiver_role=receiver_role,
            receiver_type=receiver_type,
            requirements=("execution_backend_required",),
            delegates_to=(),
            executable=False,
            read_only=True,
            foundation_only=True,
            metadata_valid=descriptor.metadata_valid,
            validation_errors=descriptor.validation_errors,
        )
