# v0.43.0c4 – Execution Journal Visibility

This release exposes the observer-only Execution Journal in Mission Operations.

## API

`GET /api/execution-journal` supports:

- `limit`
- `offset`
- `plugin`
- `status`
- `execution_id`

The response includes filtered summary counts and pagination metadata.

## Dashboard

Mission Operations shows a read-only Execution Journal panel beneath the Live Event Timeline. It refreshes through the existing five-second dashboard cycle and contains no controls or write calls.

## Authority

Mission Engine remains lifecycle authority. The Journal remains memory-only, read-only and observer-only.
