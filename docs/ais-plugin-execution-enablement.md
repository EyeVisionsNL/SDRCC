# v0.44.0a — AIS Plugin Execution Enablement

This release enables the AIS plugin as the first end-to-end executable SDRCC plugin.

Flow:

`Plugin Manager API -> Execution Plan consumer -> existing dashboard service action -> run_systemctl -> ais-catcher.service`

Architectural boundaries:

- AIS is the only enabled plugin in this release.
- The Service Adapter remains descriptive and fail-closed.
- No systemctl implementation is added to Plugin Manager or the adapter.
- Existing dashboard service control remains the operational authority.
- ADS-B and Weather are unchanged.
- Receiver Manager remains receiver authority.

API:

`POST /api/plugin-manager/ais/action`

Body:

```json
{"action": "start"}
```

Supported actions: `start`, `stop`, `restart`.
