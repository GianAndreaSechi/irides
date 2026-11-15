from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional
from loguru import logger

from core.db_connector.configurations import ensure_dotenv_loaded
from core.db_connector.exporting import ExportFormat, ExportOptions, FileArtifactStore
from core.db_connector.exporting.artifact_store import desanitize_segment, sanitize_segment


class MetadataStorageError(RuntimeError):
    """Raised when metadata persistence or reading fails unexpectedly."""


class CorruptedMetadataError(MetadataStorageError):
    """Raised when a metadata file exists on disk but contains invalid JSON."""


class AmbiguousMetadataError(ValueError):
    """Raised when multiple configurations match a table lookup without config_name."""


def build_metadata_key(
    config_name: str, instance_name: str, schema_name: str, table_name: str
) -> str:
    """Build a composite unique metadata key."""
    return f"{config_name}::{instance_name}::{schema_name}::{table_name}"


class BaseMetadataStore(ABC):
    """Abstract Base Class for Metadata Storage (File System, MongoDB, Postgres, etc.)."""

    @abstractmethod
    def save_table_metadata(
        self,
        config_name: str,
        instance_name: str,
        schema_name: str,
        table_name: str,
        schema_description: Dict[str, Any],
        ai_documentation: Optional[Dict[str, Any]] = None,
        only_if_changed: bool = False,
        export_options: Optional[ExportOptions] = None,
        save_metadata: bool = True,
        save_markdown: Optional[bool] = None,
        rebuild_index: bool = True,
    ) -> Dict[str, Any]:
        """Save or update table metadata.

        Must preserve existing ai_documentation if ai_documentation is None.
        Must keep schema_description and ai_documentation in separate top-level fields.
        Derived exports are controlled independently through ``export_options``.
        """
        raise NotImplementedError

    @abstractmethod
    def get_table_metadata(
        self,
        config_name: str,
        instance_name: str,
        schema_name: str,
        table_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve stored table metadata."""
        raise NotImplementedError

    def list_configs(self) -> List[str]:
        """List all configuration target names that have stored metadata."""
        return []

    @abstractmethod
    def list_instances(
        self, page: int = 1, page_size: int = 20, config_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """List all unique instance names across configs, paginated."""
        raise NotImplementedError

    @abstractmethod
    def list_databases(
        self,
        instance_name: str,
        page: int = 1,
        page_size: int = 20,
        config_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List all database/schema names for a given instance, paginated."""
        raise NotImplementedError

    @abstractmethod
    def list_tables_metadata(
        self,
        instance_name: str,
        database_name: str,
        page: int = 1,
        page_size: int = 20,
        config_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List all table names for a given instance+database, paginated."""
        raise NotImplementedError

    @abstractmethod
    def find_table_metadata(
        self,
        instance_name: str,
        database_name: str,
        table_name: str,
        config_name: Optional[str] = None,
        *,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Find table metadata by instance, database and table name (optionally scoped by config_name)."""
        raise NotImplementedError

    @abstractmethod
    def update_table_metadata(
        self,
        instance_name: str,
        database_name: str,
        table_name: str,
        payload: Dict[str, Any],
        config_name: Optional[str] = None,
        *,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Merge payload into an existing metadata document.

        System identity fields are protected and cannot be overwritten.
        Returns the updated document, or None if the document does not exist.
        """
        raise NotImplementedError


class FileMetadataStore(BaseMetadataStore):
    """File System implementation storing metadata as JSON files."""

    def __init__(self, base_dir: Optional[str] = None, export_dir: Optional[str] = None):
        ensure_dotenv_loaded()
        explicit_base_dir = base_dir is not None
        if base_dir is None:
            base_dir = os.getenv("STORAGE_METADATA_DIR", "storage/metadata")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if export_dir is None:
            if explicit_base_dir:
                export_dir = str(self.base_dir / "exports")
            else:
                export_dir = os.getenv("STORAGE_EXPORT_DIR", "storage/exports")
        self.artifact_store = FileArtifactStore(export_dir)

    @staticmethod
    def _sanitize(name: str) -> str:
        """Encode a logical name into a safe, reversible, collision-free path segment."""
        return sanitize_segment(name)

    @staticmethod
    def _legacy_sanitize(name: str) -> str:
        """Legacy lossy sanitizer retained for backward-compatible file lookups."""
        return re.sub(r"[^\w.\-]", "_", name)

    def _ensure_confined(self, path: Path) -> Path:
        base_resolved = self.base_dir.resolve()
        target_resolved = path.resolve()
        if not target_resolved.is_relative_to(base_resolved):
            raise ValueError(f"Refusing to access path '{path}' outside metadata root '{self.base_dir}'.")
        return path

    def _get_file_path(
        self, config_name: str, instance_name: str, schema_name: str, table_name: str
    ) -> Path:
        safe_config = self._sanitize(config_name)
        safe_instance = self._sanitize(instance_name)
        safe_schema = self._sanitize(schema_name)
        safe_table = self._sanitize(table_name)
        candidate = self.base_dir / safe_config / safe_instance / safe_schema / f"{safe_table}.json"
        return self._ensure_confined(candidate)

    def _get_legacy_file_path(
        self, config_name: str, instance_name: str, schema_name: str, table_name: str
    ) -> Optional[Path]:
        if any(seg in {"", ".", ".."} for seg in (config_name, instance_name, schema_name, table_name)):
            return None
        safe_config = self._legacy_sanitize(config_name)
        safe_instance = self._legacy_sanitize(instance_name)
        safe_schema = self._legacy_sanitize(schema_name)
        safe_table = self._legacy_sanitize(table_name)
        candidate = self.base_dir / safe_config / safe_instance / safe_schema / f"{safe_table}.json"
        try:
            return self._ensure_confined(candidate)
        except ValueError:
            return None

    def _resolve_existing_file_path(
        self, config_name: str, instance_name: str, schema_name: str, table_name: str
    ) -> Optional[Path]:
        primary = self._get_file_path(config_name, instance_name, schema_name, table_name)
        if primary.exists():
            return primary
        legacy = self._get_legacy_file_path(config_name, instance_name, schema_name, table_name)
        if legacy is not None and legacy.exists():
            return legacy
        return None

    def _cleanup_legacy_file(self, legacy_path: Optional[Path], canonical_path: Path) -> None:
        """Remove a legacy metadata file after migrating to its canonical path, pruning empty dirs."""
        if legacy_path is None or legacy_path == canonical_path or not legacy_path.exists():
            return
        try:
            legacy_path.unlink()
            base_resolved = self.base_dir.resolve()
            parent = legacy_path.parent
            while (
                parent.exists()
                and parent.resolve() != base_resolved
                and parent.resolve().is_relative_to(base_resolved)
            ):
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        except OSError as e:
            logger.debug(f"FileMetadataStore: Could not remove legacy path {legacy_path}: {e}")

    @staticmethod
    def _read_json_file(file_path: Path, *, raise_on_corrupt: bool = False) -> Optional[Dict[str, Any]]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise CorruptedMetadataError(f"Metadata file '{file_path}' does not contain a JSON object.")
            return data
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as e:
            logger.error(f"FileMetadataStore: Corrupted JSON in {file_path}: {e}")
            if raise_on_corrupt:
                raise CorruptedMetadataError(f"Corrupted metadata JSON in '{file_path}': {e}") from e
            return None
        except OSError as e:
            logger.error(f"FileMetadataStore: Error reading {file_path}: {e}")
            if raise_on_corrupt:
                raise MetadataStorageError(f"Failed to read metadata file '{file_path}': {e}") from e
            return None

    @staticmethod
    def _atomic_write_json(file_path: Path, payload: Dict[str, Any]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=file_path.parent, delete=False
            ) as tmp:
                json.dump(payload, tmp, indent=2, ensure_ascii=False)
                tmp.flush()
                os.fsync(tmp.fileno())
                temp_path = Path(tmp.name)
            temp_path.chmod(0o644)
            os.replace(temp_path, file_path)
        except Exception as e:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            logger.error(f"FileMetadataStore: Failed to write {file_path}: {e}")
            raise MetadataStorageError(f"Failed to write metadata file '{file_path}': {e}") from e

    def get_table_metadata(
        self,
        config_name: str,
        instance_name: str,
        schema_name: str,
        table_name: str,
    ) -> Optional[Dict[str, Any]]:
        file_path = self._resolve_existing_file_path(
            config_name, instance_name, schema_name, table_name
        )
        if file_path is None:
            return None
        return self._read_json_file(file_path)

    # Keys managed entirely by the system — never carried forward from existing data
    _SYSTEM_KEYS = frozenset({
        "metadata_key", "config_name", "instance_name", "schema_name",
        "table_name", "updated_at", "schema_description", "ai_documentation",
    })

    def save_table_metadata(
        self,
        config_name: str,
        instance_name: str,
        schema_name: str,
        table_name: str,
        schema_description: Dict[str, Any],
        ai_documentation: Optional[Dict[str, Any]] = None,
        only_if_changed: bool = False,
        export_options: Optional[ExportOptions] = None,
        save_metadata: bool = True,
        save_markdown: Optional[bool] = None,
        rebuild_index: bool = True,
    ) -> Dict[str, Any]:
        options = export_options or ExportOptions()
        if export_options is None and save_markdown is not None:
            formats = list(options.formats)
            if save_markdown and ExportFormat.MARKDOWN not in formats:
                formats.append(ExportFormat.MARKDOWN)
            if not save_markdown:
                formats = [item for item in formats if item != ExportFormat.MARKDOWN]
            options = options.model_copy(update={"formats": formats})

        file_path = self._get_file_path(config_name, instance_name, schema_name, table_name)
        legacy_path = self._get_legacy_file_path(config_name, instance_name, schema_name, table_name)
        existing_data = self.get_table_metadata(config_name, instance_name, schema_name, table_name) or {}

        # Preserve existing ai_documentation if not passed in this call
        final_ai_doc = (
            ai_documentation
            if ai_documentation is not None
            else existing_data.get("ai_documentation")
        )

        # Skip write if both schema and AI documentation are unchanged
        if only_if_changed and existing_data:
            schema_unchanged = existing_data.get("schema_description") == schema_description
            ai_unchanged = existing_data.get("ai_documentation") == final_ai_doc
            if schema_unchanged and ai_unchanged:
                if save_metadata and not file_path.exists() and legacy_path and legacy_path.exists():
                    self._atomic_write_json(file_path, existing_data)
                    self._cleanup_legacy_file(legacy_path, file_path)
                self.artifact_store.export(existing_data, options, rebuild_index=rebuild_index)
                logger.info(f"FileMetadataStore: No schema or AI change for {table_name}, skipping write.")
                return {**existing_data, "_unchanged": True}

        # Carry forward any custom fields added by humans (owner, tags, notes, etc.)
        custom_fields = {k: v for k, v in existing_data.items() if k not in self._SYSTEM_KEYS}

        metadata_record = {
            **custom_fields,
            "metadata_key": build_metadata_key(config_name, instance_name, schema_name, table_name),
            "config_name": config_name,
            "instance_name": instance_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "schema_description": schema_description,
            "ai_documentation": final_ai_doc,
        }

        if save_metadata:
            self._atomic_write_json(file_path, metadata_record)
            self._cleanup_legacy_file(legacy_path, file_path)
            logger.info(f"FileMetadataStore: Saved table metadata for {table_name} -> {file_path}")

        self.artifact_store.export(metadata_record, options, rebuild_index=rebuild_index)
        return metadata_record

    def _paginate(self, items: List[str], page: int, page_size: int) -> Dict[str, Any]:
        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": math.ceil(total / page_size) if total > 0 else 0,
        }

    @classmethod
    def _dedup_logical_names(cls, raw_names: List[str]) -> List[str]:
        decoded = {desanitize_segment(name) for name in raw_names}
        shadows = {
            cls._legacy_sanitize(d)
            for d in decoded
            if cls._sanitize(d) != cls._legacy_sanitize(d)
        }
        return sorted(d for d in decoded if d not in shadows)

    def _iter_config_dirs(self, config_name: Optional[str] = None) -> List[Path]:
        if not self.base_dir.exists():
            return []
        if config_name is not None:
            candidates = []
            # Order canonical path before legacy path
            for candidate_name in (self._sanitize(config_name), self._legacy_sanitize(config_name)):
                candidate = self._ensure_confined(self.base_dir / candidate_name)
                if candidate.is_dir() and candidate not in candidates:
                    candidates.append(candidate)
            return candidates
        return sorted(
            [
                d
                for d in self.base_dir.iterdir()
                if d.is_dir() and d.name != "exports"
            ],
            key=lambda p: p.name,
        )

    def _matching_subdirs(self, parent_dir: Path, logical_name: str) -> List[Path]:
        if not parent_dir.is_dir():
            return []
        matches = []
        # Order canonical segment before legacy segment
        for seg in (self._sanitize(logical_name), self._legacy_sanitize(logical_name)):
            candidate = self._ensure_confined(parent_dir / seg)
            if candidate.is_dir() and candidate not in matches:
                matches.append(candidate)
        return matches

    def list_configs(self) -> List[str]:
        raw_names = [d.name for d in self._iter_config_dirs(None)]
        return self._dedup_logical_names(raw_names)

    def list_instances(
        self, page: int = 1, page_size: int = 20, config_name: Optional[str] = None
    ) -> Dict[str, Any]:
        raw_names: List[str] = []
        for config_dir in self._iter_config_dirs(config_name):
            for instance_dir in config_dir.iterdir():
                if instance_dir.is_dir():
                    raw_names.append(instance_dir.name)
        return self._paginate(self._dedup_logical_names(raw_names), page, page_size)

    def list_databases(
        self,
        instance_name: str,
        page: int = 1,
        page_size: int = 20,
        config_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        raw_names: List[str] = []
        for config_dir in self._iter_config_dirs(config_name):
            for instance_dir in self._matching_subdirs(config_dir, instance_name):
                for db_dir in instance_dir.iterdir():
                    if db_dir.is_dir():
                        raw_names.append(db_dir.name)
        return self._paginate(self._dedup_logical_names(raw_names), page, page_size)

    def list_tables_metadata(
        self,
        instance_name: str,
        database_name: str,
        page: int = 1,
        page_size: int = 20,
        config_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        raw_names: List[str] = []
        for config_dir in self._iter_config_dirs(config_name):
            for instance_dir in self._matching_subdirs(config_dir, instance_name):
                for db_dir in self._matching_subdirs(instance_dir, database_name):
                    for f in db_dir.iterdir():
                        if f.is_file() and f.suffix == ".json":
                            raw_names.append(f.stem)
        return self._paginate(self._dedup_logical_names(raw_names), page, page_size)

    def _find_matching_file_paths(
        self,
        instance_name: str,
        database_name: str,
        table_name: str,
        config_name: Optional[str] = None,
    ) -> List[Path]:
        matches: List[Path] = []
        # Check canonical stem first, then legacy stem
        table_stems = []
        for s in (self._sanitize(table_name), self._legacy_sanitize(table_name)):
            if s not in table_stems:
                table_stems.append(s)
        for config_dir in self._iter_config_dirs(config_name):
            for instance_dir in self._matching_subdirs(config_dir, instance_name):
                for db_dir in self._matching_subdirs(instance_dir, database_name):
                    for stem in table_stems:
                        candidate = self._ensure_confined(db_dir / f"{stem}.json")
                        if candidate.exists() and candidate not in matches:
                            matches.append(candidate)
        return matches

    def _config_name_for_path(self, path: Path) -> str:
        data = self._read_json_file(path)
        if isinstance(data, dict) and data.get("config_name"):
            return str(data["config_name"])
        return desanitize_segment(path.parent.parent.parent.name)

    def _resolve_single_match(
        self,
        instance_name: str,
        database_name: str,
        table_name: str,
        config_name: Optional[str] = None,
        *,
        strict: bool = False,
    ) -> Optional[Path]:
        matches = self._find_matching_file_paths(
            instance_name, database_name, table_name, config_name=config_name
        )
        if not matches:
            return None
        # Group by logical config_name so a legacy + canonical file in the same config is never treated as ambiguous
        by_config: Dict[str, List[Path]] = {}
        for p in matches:
            cfg = self._config_name_for_path(p)
            by_config.setdefault(cfg, []).append(p)

        if len(by_config) > 1:
            configs = sorted(by_config.keys())
            msg = (
                f"Ambiguous metadata reference for '{instance_name}/{database_name}/{table_name}': "
                f"found in multiple configurations {configs}. Specify config_name to disambiguate."
            )
            if strict:
                raise AmbiguousMetadataError(msg)
            logger.warning(f"FileMetadataStore: {msg}")

        first_cfg = next(iter(by_config))
        cfg_matches = by_config[first_cfg]
        try:
            canonical = self._get_file_path(first_cfg, instance_name, database_name, table_name)
            if canonical in cfg_matches:
                return canonical
        except ValueError:
            pass
        return cfg_matches[0]

    def find_table_metadata(
        self,
        instance_name: str,
        database_name: str,
        table_name: str,
        config_name: Optional[str] = None,
        *,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        file_path = self._resolve_single_match(
            instance_name, database_name, table_name, config_name=config_name, strict=strict
        )
        if file_path is None:
            return None
        return self._read_json_file(file_path)

    _PROTECTED_FIELDS = frozenset({
        "metadata_key", "config_name", "instance_name", "schema_name", "table_name", "updated_at"
    })

    def update_table_metadata(
        self,
        instance_name: str,
        database_name: str,
        table_name: str,
        payload: Dict[str, Any],
        config_name: Optional[str] = None,
        *,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        file_path = self._resolve_single_match(
            instance_name, database_name, table_name, config_name=config_name, strict=strict
        )
        if file_path is None:
            return None
        existing = self._read_json_file(file_path, raise_on_corrupt=True)
        if existing is None:
            return None

        for key, value in payload.items():
            if key not in self._PROTECTED_FIELDS:
                existing[key] = value
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()

        cfg = str(existing.get("config_name") or config_name or desanitize_segment(file_path.parent.parent.parent.name))
        inst = str(existing.get("instance_name") or instance_name)
        sch = str(existing.get("schema_name") or database_name)
        tbl = str(existing.get("table_name") or table_name)
        canonical_path = self._get_file_path(cfg, inst, sch, tbl)

        self._atomic_write_json(canonical_path, existing)
        self._cleanup_legacy_file(file_path, canonical_path)
        logger.info(f"FileMetadataStore: Updated metadata for {table_name} -> {canonical_path}")

        self.artifact_store.export(existing, ExportOptions())
        return existing

    def iter_all_metadata(self, config_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all stored metadata records (optionally filtered by config_name)."""
        by_key: Dict[str, Dict[str, Any]] = {}
        for config_dir in self._iter_config_dirs(config_name):
            for json_file in sorted(config_dir.rglob("*.json")):
                record = self._read_json_file(json_file)
                if record is None:
                    continue
                m_key = record.get("metadata_key") or str(json_file)
                if m_key not in by_key:
                    by_key[m_key] = record
                else:
                    # Prefer canonical path record if both legacy and canonical exist on disk
                    cfg = str(record.get("config_name") or "")
                    inst = str(record.get("instance_name") or "")
                    sch = str(record.get("schema_name") or "")
                    tbl = str(record.get("table_name") or "")
                    if cfg and inst and sch and tbl:
                        try:
                            if json_file == self._get_file_path(cfg, inst, sch, tbl):
                                by_key[m_key] = record
                        except ValueError:
                            pass
        return list(by_key.values())

    def export_all(
        self,
        export_options: Optional[ExportOptions] = None,
        config_name: Optional[str] = None,
    ) -> int:
        """Regenerate Markdown/OKF exports from stored JSON metadata without querying databases."""
        options = export_options or ExportOptions()
        records = self.iter_all_metadata(config_name=config_name)
        return self.artifact_store.export_batch(records, options)


def get_metadata_store(store_type: Optional[str] = None) -> BaseMetadataStore:
    """Factory to get configured metadata store implementation."""
    ensure_dotenv_loaded()
    store_type = store_type or os.getenv("METADATA_STORE_TYPE", "file")
    if store_type == "file":
        return FileMetadataStore()
    else:
        logger.warning(f"Unknown METADATA_STORE_TYPE '{store_type}', falling back to FileMetadataStore")
        return FileMetadataStore()
