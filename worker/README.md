# Worker

Async background worker that reads table scan jobs from the Redis Stream and executes them using the **core** library. Depends only on **core** — no direct dependency on the API service.

---

## How It Works

```
API  ──xadd──►  Redis Stream (scan:queue)
                       │
                  Worker polls (xreadgroup: scan-workers)
                       │
                ScanExecutorService
                       │
           resolves hosts & flat connector instances
                       │
           for each config / instance / schema / table:
                connector.describe_table()
                       │
                Redis List (scan:results:{job_id})
                       │
                job status → completed / partial / failed
```

1. The API enqueues a job to the Redis Stream (`{prefix}:scan:queue`) and returns a `job_id` (HTTP 202 Accepted).
2. The Worker reads the job message via `xreadgroup`, deserializes `export_formats` and `export_preformat` (defaulting to Markdown+OKF, with legacy `save_markdown` fallback), calls `mark_running`, and defensively matches configurations using `configuration_matches_instance` and `resolve_instance_names`.
3. Each scanned `TableDescription` is appended to the Redis results list (`{prefix}:scan:results:{job_id}`). If `generate_ai_docs=true`, results include `ai_documentation`, `ai_generation_status`, and `ai_generation_error`. If `save_metadata=true` or exports are active, metadata and derived artifacts (Markdown and OKF catalog bundle) are persisted under `STORAGE_METADATA_DIR` and `STORAGE_EXPORT_DIR`.
4. On finish, the Worker updates job status via `mark_completed(count)`, `mark_partial(count, error)`, or `mark_failed(error)`.
5. The API's `GET /scan/{job_id}?include_results=true` reads results directly from Redis.

### Crash Recovery (`reclaim_abandoned`)
On startup, the Worker automatically reclaims and re-executes pending stream messages delivered to dead/crashed worker instances using Redis Stream `XPENDING` / `XCLAIM` semantics.

---

## Environment Variables

Copy `.env.example` to `.env`.

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `localhost` | Redis host (must match API) |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_DB` | `0` | Redis database index |
| `REDIS_TTL_SECONDS` | `86400` | Introspection cache TTL |
| `CACHE_KEY_PREFIX` | `irides` | Redis key prefix (must match API) |
| `SCAN_RESULTS_TTL_SECONDS` | `604800` | Scan result retention in Redis (7 days) |
| `WORKER_STREAM_BLOCK_MS` | `5000` | Stream read timeout per poll cycle |
| `DB_CONFIG_FILE` | *(none)* | Explicit path to `.env` file for Docker container |
| `DB_TARGETS` | *(none)* | Comma-separated list of named DB targets |
| `LITELLM_MODEL` | `gpt-4o-mini` | LLM model for AI doc generation (via LiteLLM) |
| `LITELLM_API_KEY` | *(none)* | Optional LiteLLM API key override |
| `LITELLM_API_BASE` | *(none)* | Optional LiteLLM API base URL |
| `STORAGE_METADATA_DIR` | `storage/metadata` | Directory for JSON metadata files |
| `STORAGE_EXPORT_DIR` | `storage/exports` | Directory for generated Markdown and OKF exports |
| `METADATA_STORE_TYPE` | `file` | Metadata store backend (`file`; `s3`/`athena` planned) |


DB target variables — see [root README](../README.md#db-configuration--activation).

---

## Running

### Docker Compose

```bash
# Start shared Redis first
docker compose -f ../infra/docker-compose.infra.yml up -d

# Start Worker
docker compose up -d
```

### Local Development

```bash
pip install -r requirements.txt
python -m worker.irides_worker.main
```

---

## Horizontal Scaling

Multiple worker instances can run concurrently. Each worker registers with a unique hostname in the shared `scan-workers` consumer group. Redis Streams guarantees that each scan job message is delivered to exactly one consumer worker.

Jobs that complete with at least one failed table/config are marked `partial`; jobs with no successful table descriptions are marked `failed`.
