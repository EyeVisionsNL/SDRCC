# SDRCC Plugin Foundation Architecture

Version: v0.40.0

## Status

The Plugin Foundation is complete and stabilized.

## Authorities and responsibilities

### Plugin Registry

Metadata authority.

The Registry owns static plugin metadata, including:

- plugin identity and display metadata;
- declared roles;
- declared services;
- declared capabilities;
- enabled and configuration metadata.

Consumers may query Registry metadata directly when they need metadata.

### Plugin Capability Layer

Read-only capability query layer.

Capability questions must go through `core.plugin_capabilities`, including:

- whether a plugin has a capability;
- which plugins provide a capability;
- capability snapshots and indexes.

Consumers must not call Registry capability helpers directly.

### Receiver Manager

Lifecycle authority for receivers.

It owns receiver inventory, assignment, reservation, locking and lifecycle state.
Read-only runtime modules must not duplicate this authority.

### Receiver Runtime

Read-only normalized receiver observation.

It combines existing metadata and Receiver Manager state without introducing
new receiver lifecycle decisions.

### Plugin Runtime

Read-only plugin runtime observation.

It reports runtime state without starting, stopping or controlling plugins.

### Plugin Health

Read-only validation and health reporting.

It observes and validates existing state. It is not a lifecycle controller.

### Plugin Manager

Read-only aggregation.

It combines Registry, Runtime and Health information for consumers and APIs.
It does not dynamically execute plugins.

## Architectural rules

1. No dynamic plugin execution is part of the Plugin Foundation.
2. No duplicate lifecycle authority may be introduced.
3. Registry remains the metadata authority.
4. Capability questions go through Plugin Capability Layer.
5. Runtime, Health and Manager layers remain read-only.
6. Receiver Manager remains receiver lifecycle authority.
7. Migrations are performed one consumer at a time.
8. Public API behavior must remain backwards compatible unless explicitly
   versioned and approved.

## Stabilization result

The capability consumer inventory completed before v0.40.0 found:

- `core/rf_diagnostics.py` as the only application capability consumer;
- that consumer uses `plugin_capabilities.has_capability(...)`;
- all remaining direct Registry usage is metadata-oriented;
- no remaining direct Registry capability consumers.

The Plugin Capability migration is therefore complete.
