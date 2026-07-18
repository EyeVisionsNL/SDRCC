# SDRCC Development Working Agreement

Status: **Active and mandatory**

## File workflow

- Files the user uploads for analysis are created in `/home/eyevisions`.
- Packages returned by ChatGPT are downloaded and installed from `/home/eyevisions/Downloads`.
- Do not change this workflow.

## Development method

1. Analyse the current code and runtime evidence before changing anything.
2. Agree the exact scope and acceptance criteria.
3. Make the smallest coherent implementation step.
4. Provide complete files or a complete installation package; avoid partial copy/paste patches.
5. Installer tests must use the complete project import context and must be validated before delivery.
6. Back up changed production files before installation.
7. Run syntax and focused isolated tests before restarting services.
8. Restart only services required by the change.
9. Run API and runtime smoke tests after installation.
10. Perform visual UI verification with screenshots where relevant.
11. Test regressions in Weather, Voice, AIS and ADS-B where the change can affect them.
12. Fix issues before committing.
13. Commit in a small, stable unit with a clear version message.
14. Push to `origin/develop` only after user approval.
15. Verify `git status` is clean before starting the next version.

## UI rules

- Do not change layout unless it is explicitly part of the agreed scope.
- Do not create mocks or substitute images for the actual application.
- Preserve accepted layouts until a deliberate redesign step.
- System-level components move only during the agreed System-tab phase.

## Architecture rules

- Never hard-code a mission type to a receiver.
- Never assume exactly two receivers in backend data models.
- Keep default role, current role, assignment, reservation and runtime separate.
- Use one generic runtime per physical receiver.
- Scope stop, failure, processes and restoration to one receiver runtime.
- Allow concurrent missions only on different compatible receivers.
- Add future functionality through capabilities and mission adapters.
- Maintain backward compatibility while migrating working flows.

## Quality rules

- Do not claim a feature works until it has been observed through the relevant API/runtime/UI test.
- Installer success is not the same as feature success.
- A failed installer test must be classified as installer, test-environment or production-code failure before making another package.
- Do not commit generated logs, caches, recordings or local state unless explicitly intended.
- Preserve user configuration such as `config/station.yaml` unless the agreed change requires a controlled migration.

## Current architectural objective

Implement the accepted receiver-oriented Runtime v2 design in `docs/architecture/runtime-v2.md`, incrementally, while keeping the working Weather, Voice, AIS and ADS-B paths operational.
