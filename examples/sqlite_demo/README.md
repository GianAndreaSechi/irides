# Irides Local SQLite Demo

This directory contains a zero-infrastructure demo of **Irides** (no Docker, Redis, or external database required).

## 1. Create the synthetic SQLite database

```bash
python examples/sqlite_demo/setup_demo.py
```

## 2. Introspect and generate Markdown + OKF v0.2 documentation

```bash
irides -c examples/sqlite_demo/irides.yaml describe --target demo_sqlite
```

This writes:
- Canonical JSON metadata under `storage/metadata/demo_sqlite/...`
- Markdown documentation under `storage/exports/markdown/demo_sqlite/...`
- An Open Knowledge Format (`OKF v0.2`) bundle under `storage/exports/okf/catalog/` with an `index.md` catalog index.

## 3. Add human annotations (`owner`, `notes`, `tags`, `classification`)

```bash
irides metadata update "<instance>" main orders \
  '{"owner":"checkout-team","classification":"confidential","tags":["orders","core"],"notes":"Primary order ledger table."}' \
  --target demo_sqlite
```

Re-running `irides -c examples/sqlite_demo/irides.yaml describe --target demo_sqlite --only-if-changed` preserves all human annotations and refreshes the exported Markdown and OKF files.

## 4. Validate the project manifest (`database.md`)

```bash
irides manifest validate examples/sqlite_demo/database.md
irides manifest links examples/sqlite_demo/database.md
```
