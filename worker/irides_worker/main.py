"""
Async scan worker.

Listens on the Redis Stream for scan jobs enqueued by the API,
executes them using the core library, and stores results back in Redis.

Dependencies: core only (no api imports).

Run:
    python -m worker.irides_worker.main
"""
import os
import json
import signal
import socket
from dataclasses import dataclass
from loguru import logger

from core.db_connector.cache_manager import CacheManager
from core.db_connector.config_service import ConfigService
from core.db_connector.job_store import JobStore
from core.db_connector.manager import ConnectorManager
from core.db_connector.exporting import ExportOptions
from worker.irides_worker.services.scan_executor_service import ScanExecutorService


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass
class WorkerSettings:
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", 6379))
    redis_db: int = int(os.getenv("REDIS_DB", 0))
    redis_ttl: int = int(os.getenv("REDIS_TTL_SECONDS", 86400))
    cache_prefix: str = os.getenv("CACHE_KEY_PREFIX", "multi-db-connector")
    redis_socket_connect_timeout: float = float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", 2))
    redis_cache_socket_timeout: float = float(os.getenv("REDIS_CACHE_SOCKET_TIMEOUT_SECONDS", 2))
    # How long to block waiting for new stream messages (ms)
    stream_block_ms: int = int(os.getenv("WORKER_STREAM_BLOCK_MS", 5000))
    consumer_name: str = f"{socket.gethostname()}-{os.getpid()}"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class ScanWorker:
    def __init__(self, settings: WorkerSettings):
        self.settings = settings
        self._running = False

        cache_manager = CacheManager(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            ttl_seconds=settings.redis_ttl,
            project_prefix=settings.cache_prefix,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_timeout=settings.redis_cache_socket_timeout,
        )
        connector_manager = ConnectorManager(cache_manager)
        config_service = ConfigService(connector_manager)

        self.job_store = JobStore(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            prefix=settings.cache_prefix,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
        )
        self.executor = ScanExecutorService(self.job_store, config_service)

    def start(self):
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info(
            f"ScanWorker started | consumer={self.settings.consumer_name} "
            f"| redis={self.settings.redis_host}:{self.settings.redis_port}"
        )

        while self._running:
            self._poll()

        logger.info("ScanWorker stopped.")

    def _handle_signal(self, sig, _frame):
        logger.info(f"ScanWorker: received signal {sig}, shutting down…")
        self._running = False

    def _poll(self):
        # 1. Reclaim messages stuck on dead consumers (crash recovery)
        for message_id, data in self.job_store.reclaim_abandoned(self.settings.consumer_name):
            self._process(message_id, data)

        # 2. Read fresh undelivered messages
        messages = self.job_store.read_pending(
            self.settings.consumer_name,
            count=1,
            block_ms=self.settings.stream_block_ms,
        )
        if not messages:
            return

        for _stream, entries in messages:
            for message_id, data in entries:
                self._process(message_id, data)

    def _process(self, message_id: str, data: dict):
        job_id = data.get("job_id")
        if not job_id:
            logger.warning(f"ScanWorker: message {message_id} missing job_id — skipping")
            self.job_store.ack(message_id)
            return

        config_name = data.get("config_name") or None
        instance_name = data.get("instance_name") or None
        schema_name = data.get("schema_name") or None
        no_cache = data.get("no_cache") == "true"
        generate_ai_docs = data.get("generate_ai_docs") == "true"
        save_metadata = data.get("save_metadata", "true") == "true"
        only_if_changed = data.get("only_if_changed") == "true"
        if "export_formats" in data:
            export_options = ExportOptions(
                formats=json.loads(data["export_formats"]),
                preformat=data.get("export_preformat", "true") == "true",
            )
        elif "save_markdown" in data:
            export_options = ExportOptions(
                formats=["markdown"] if data["save_markdown"] == "true" else []
            )
        else:
            export_options = ExportOptions()

        logger.info(
            f"ScanWorker: processing job {job_id} "
            f"[config={config_name}, instance={instance_name}, schema={schema_name}, "
            f"no_cache={no_cache}, generate_ai_docs={generate_ai_docs}, save_metadata={save_metadata}, "
            f"only_if_changed={only_if_changed}, export_options={export_options.model_dump(mode='json')}]"
        )
        self.job_store.mark_running(job_id)

        try:
            result = self.executor.execute(
                job_id,
                config_name,
                instance_name,
                schema_name,
                no_cache=no_cache,
                generate_ai_docs=generate_ai_docs,
                save_metadata=save_metadata,
                only_if_changed=only_if_changed,
                export_options=export_options,
            )
            if result.errors:
                error_text = "; ".join(result.errors)
                if result.count > 0:
                    self.job_store.mark_partial(job_id, result.count, error_text)
                    logger.warning(
                        f"ScanWorker: job {job_id} partially completed — "
                        f"{result.count} tables described, {len(result.errors)} error(s)"
                    )
                else:
                    self.job_store.mark_failed(job_id, error_text)
                    logger.warning(f"ScanWorker: job {job_id} failed — no tables described")
            else:
                self.job_store.mark_completed(job_id, result.count)
                logger.info(f"ScanWorker: job {job_id} completed — {result.count} tables described")
        except Exception as e:
            logger.exception(f"ScanWorker: job {job_id} failed: {e}")
            self.job_store.mark_failed(job_id, str(e))


        self.job_store.ack(message_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    settings = WorkerSettings()
    ScanWorker(settings).start()


if __name__ == "__main__":
    main()
