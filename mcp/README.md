# MCP — Irides Control Plane

Model Context Protocol (MCP) server built with `fastmcp` that exposes API introspection, async scan capabilities, and stored metadata read/write as tools for LLM agents (Claude, Gemini, Cursor, IDE assistants, etc.).

---

## Available Tools

### Introspection Tools (Synchronous, Live DB)

These tools query the live database through the API. Results are TOON-compressed to minimise token consumption.

| Tool | Parameters | Description |
|---|---|---|
| `get_available_connectors` | `no_cache?` | List all active database configurations |
| `list_instances` | `config_name?`, `no_cache?` | List database instances. Omit `config_name` to list all active configurations |
| `list_schemas` | `config_name?`, `instance_name?`, `no_cache?` | List schemas/databases. Omitted fields expand the scope |
| `list_tables` | `config_name?`, `instance_name?`, `schema_name?`, `limit?`, `offset?`, `no_cache?` | List tables. Omitted scope fields expand the query |
| `describe_table` | `config_name?`, `instance_name?`, `schema_name?`, `table_name?`, `generate_ai_docs?`, `save_metadata?`, `only_if_changed?`, `export_options?`, `no_cache?` | Describe tables with optional AI documentation and derived exports |

> **LLM Optimization**: All introspection tools automatically request data in **TOON** format (`Accept: application/toon`), drastically reducing token consumption compared to verbose JSON.
> **Export Artifacts**: `describe_table` and `enqueue_scan` generate both **Markdown** and **OKF v0.2** bundle artifacts by default. Pass `export_options: {"formats": []}` or `preformat: false` to customize or opt out.

### Async Table Scan Tools

| Tool | Parameters | Description |
|---|---|---|
| `enqueue_scan` | `config_name?`, `instance_name?`, `schema_name?`, `generate_ai_docs?`, `save_metadata?`, `only_if_changed?`, `export_options?`, `no_cache?` | Launch an async background scan job — returns `job_id` |
| `get_scan_job` | `job_id`, `include_results?` | Check job status; set `include_results=True` to fetch full `TableDescription` list |
| `list_scan_jobs` | `limit?` | List recent scan jobs (newest first) |

Typical LLM agent workflow:
1. Call `enqueue_scan(config_name="sales_mysql")` → receive `job_id`
2. Poll `get_scan_job(job_id)` until `status` is `completed`, `partial`, or `failed`
3. Call `get_scan_job(job_id, include_results=True)` to read scanned schemas

### Metadata Store Tools (Stored Snapshots)

These tools read from and write to the **stored metadata snapshots** — JSON documents saved to disk by `/describe` and scan jobs. Unlike the live introspection tools, the data here may be **stale** and may include **human-added annotations** (owner, tags, notes, etc.) that are not present in the live database.

Use these tools to inspect what has been indexed and stored so far, or to read/update human-enriched metadata.

| Tool | Parameters | Description |
|---|---|---|
| `list_stored_instances` | `page?`, `page_size?` | List all instances with stored metadata snapshots |
| `list_stored_databases` | `instance_name`, `page?`, `page_size?` | List all databases stored for an instance |
| `list_stored_tables` | `instance_name`, `database_name`, `page?`, `page_size?` | List all tables stored for an instance+database |
| `get_stored_table_metadata` | `instance_name`, `database_name`, `table_name` | Get full stored metadata for a table (TOON-compressed) |
| `update_stored_table_metadata` | `instance_name`, `database_name`, `table_name`, `fields` | Merge custom fields into a stored metadata document |

`update_stored_table_metadata` accepts any `fields` dict. Protected system fields (`metadata_key`, `config_name`, `instance_name`, `schema_name`, `table_name`, `updated_at`) are ignored; everything else is merged in.

---

## Environment Variables

Copy `.env.example` to `.env`.

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `http` | Transport protocol (`http` or `stdio`) |
| `MCP_HOST` | `0.0.0.0` | Listen address for HTTP transport |
| `MCP_PORT` | `8000` | Listen port for HTTP transport |
| `API_BASE_URL` | `http://localhost:8000` | Address of the running `irides-api` service |
| `API_PREFIX` | `/api/v1` | API version prefix — must match the API service setting |

---

## Running

### Docker Compose

Starting MCP via Docker Compose provisions the **API**, the **MCP Server**, and the **Worker**, sharing a common `storage` volume for canonical metadata and derived Markdown/OKF exports (`STORAGE_EXPORT_DIR`). Start the shared Redis infrastructure first:

```bash
# 1. Start shared Redis infrastructure
docker compose -f ../infra/docker-compose.infra.yml up -d

# 2. Start API + MCP Server + Background Worker
docker compose up -d
```

### Local Development

```bash
pip install -r requirements.txt
python -m irides_mcp.server
```

---

## LLM Client Configuration

### Claude Desktop / Gemini CLI (via `mcp-remote`)

Add to your client configuration (e.g. `~/.gemini/settings.json` or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "irides": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "http://<mcp-host>:<port>/mcp"]
    }
  }
}
```

Replace `<mcp-host>:<port>` with your MCP server address (e.g. `http://localhost:8000/mcp`).
