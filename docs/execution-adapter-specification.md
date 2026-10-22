# SDRCC Execution Adapter Specification

Version: **v0.42.0a foundation**

## Purpose

The Execution Adapter Layer translates Plugin Registry executor metadata into
a typed, read-only adapter description. It does not become a new execution,
receiver, mission, runtime, health, or process authority.

## Authority model

| Domain | Authority | Adapter responsibility |
|---|---|---|
| Plugin metadata | Plugin Registry | Read |
| Capabilities | Plugin Capability Layer | Read when needed |
| Receiver lifecycle | Receiver Manager | Future delegation only |
| Mission lifecycle | Mission Engine | Future delegation only |
| SatDump/process lifecycle | Existing SatDump/Process Manager | Future delegation only |
| Runtime | Plugin Runtime | Never write |
| Health | Plugin Health | Never write |
| Events | Event Bus | Reuse existing events only |

## Supported metadata mappings

| Registry executor | Adapter |
|---|---|
| `service` | `ServiceAdapter` |
| `satdump` | `SatDumpAdapter` |
| `null` / absent | `NullAdapter` |

Unknown executor values fail closed.

## Foundation contract

Each adapter exposes:

- immutable plugin metadata;
- `validate()`;
- `can_execute()`;
- `describe()`;
- fail-closed placeholders for `prepare()`, `execute()`, `cancel()` and
  `cleanup()`;
- `get_status()` returning `FOUNDATION_ONLY`.

In v0.42.0a, `can_execute()` always returns `False`. Lifecycle methods always
raise `ExecutionNotEnabledError`.

## Hard boundaries

Adapter modules must not:

- import or call subprocess/systemd control;
- reserve, release, activate or deactivate receivers;
- create or mutate mission jobs or mission state;
- write Plugin Runtime or Plugin Health;
- control RTL hardware;
- maintain an independent lifecycle state machine;
- replace any existing SDRCC execution route.

## ServiceAdapter

Validates that:

- Registry executor equals `service`;
- at least one unique non-empty service is declared.

Future service delegation must reuse existing service and receiver authority.
The adapter must not implement independent systemd control.

## SatDumpAdapter

Validates that:

- Registry executor equals `satdump`;
- `recording` and `decoding` capabilities exist;
- no systemd services are declared.

Future delegation must reuse Mission Engine, Receiver Manager, `core.satdump`
and Process Manager. It must not create a second mission state machine.

## NullAdapter

Represents planned or passive plugins with no execution backend. It is a valid
resolution, not an error, and remains non-executable.

## Factory behavior

`execution_factory`:

- resolves Registry metadata to an adapter;
- rejects unknown plugins;
- rejects unknown executor values;
- provides a read-only catalog;
- validates all active and planned mappings;
- performs no execution.

## Backwards compatibility

v0.42.0a adds isolated modules, documentation and a validator. It changes no
existing API, UI, service, receiver assignment, mission flow or SatDump path.
