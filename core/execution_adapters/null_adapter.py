#!/usr/bin/env python3
"""Read-only null adapter for planned or passive plugins."""

from __future__ import annotations

from core.execution_adapter import ExecutionAdapter


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
