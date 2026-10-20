# v0.17.0 validation

257 offline tests passed on 2026-10-20. Includes 22 new original-Outreach
adapter/approval/history/connection tests. Tests used fake external APIs/Gmail.

An isolated upgrade of a snapshot of the installed Mac agent preserved
preferences.json, sending.json, profile.json and SQLite byte-for-byte.
29 leads, 2 outbox items and 1 campaign remained. No credential files copied.

Notion verification: 22 original rows, 12 Sent rows; zero differences in
original row property values. Existing field types and select-option IDs
preserved. Five views and grouped record layout verified by fetch.

Live Mac Notion token: access enabled by the owner and verified. Original
database and source GETs passed. Live adapter create/read passed with a
recipient-free Do Not Contact verification record, then archived.
Installing this release, first real research sync and an original-database
self-inbox send remain to be verified. Destination on the installed Mac has
not changed. No migration production email sent; no paid AI run performed.
The preconfigured installer passed zsh syntax validation.
