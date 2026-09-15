# Iride CLI

Command-line interface for database introspection, built only on the `core` package and Python's standard library. It does not require FastAPI, MCP, or the Redis worker.

## Structure

The CLI is organized by responsibility:

- `irides_cli/presentation/`: command definitions and `argparse` parsing;
- `irides_cli/controllers/`: maps command-line arguments to use cases;
- `irides_cli/dto/`: immutable, typed request DTOs;
- `irides_cli/services/`: live introspection and metadata operations using only `core`;
- `irides_cli/main.py`: composition root, JSON serialization, and process-level error handling.

## Local installation

```bash
pip install -e ./core -e ./cli
```

Target configuration is shared with the rest of the project: use `DB_TARGETS` and the corresponding `DB_TARGET_<NAME>_*` variables.

Create a local configuration before running the CLI:

```bash
cp cli/.env.example cli/.env
```

## Commands

```bash
irides configurations
irides connect sales_mysql
irides instances --config sales_mysql
irides schemas --config sales_mysql --instance db1.company.com
irides tables --config sales_mysql --instance db1.company.com --schema production --limit 50
irides describe --config sales_mysql --instance db1.company.com --schema production --table orders
irides describe --config sales_mysql --instance db1.company.com --schema production --table orders --generate-ai-docs
irides describe --config sales_mysql --instance db1.company.com --schema production --table orders --no-export-okf
```

Omitting `--config`, `--instance`, `--schema`, or `--table` expands the scope, just like the corresponding API endpoints. Results are always written as JSON to stdout; errors are written to stderr. Add `--no-cache` to introspection commands to bypass Redis.

`describe` saves canonical JSON metadata and generates both **Markdown** and **Open Knowledge Format (OKF v0.2)** exports by default.

Available options for `describe`:
- `--generate-ai-docs`: generate domain summary and column descriptions via LiteLLM.
- `--no-save-metadata`: skip saving the canonical JSON metadata file (exports are still generated if enabled).
- `--only-if-changed`: skip writing if the schema is identical to the stored version.
- `--no-export-markdown`: disable the default Markdown export.
- `--no-export-okf`: disable the default OKF catalog bundle generation.
- `--no-preformat`: export full metadata instead of the essential deterministic record.
- `--save-markdown`: legacy compatibility flag for Markdown export.

Artifacts are persisted under `STORAGE_EXPORT_DIR` (default `storage/exports`):
- `storage/exports/markdown/{config}/{instance}/{schema}/{table}.md`
- `storage/exports/okf/catalog/{config}/{instance}/{schema}/{table}.md` (along with `storage/exports/okf/catalog/index.md`)

## Metadata

```bash
irides metadata instances
irides metadata databases db1.company.com
irides metadata tables db1.company.com production
irides metadata get db1.company.com production orders
irides metadata update db1.company.com production orders '{"owner":"data-team","tags":["billing"]}'
```

The CLI does not include `scan` commands. They are asynchronous and explicitly require Redis Streams and the `worker` service.

## Docker

The CLI reads its configuration from `cli/.env` and uses the shared Redis network. Start by copying `.env.example` as shown above and configure at least one `DB_TARGETS` entry.

```bash
docker compose -f infra/docker-compose.infra.yml up -d
docker compose -f cli/docker-compose.yml run --rm irides-cli configurations
docker compose -f cli/docker-compose.yml run --rm irides-cli tables --config sales_mysql --schema public
docker compose -f cli/docker-compose.yml run --rm irides-cli describe --config sales_mysql --schema public --table orders
```
