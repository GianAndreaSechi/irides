"""Project database manifest (`database.md` / YAML / JSON) parser, validator, and reverse-link builder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import yaml
from pydantic import BaseModel, Field

from .exporting.artifact_store import extract_frontmatter
from .storage import BaseMetadataStore, FileMetadataStore, get_metadata_store


class ManifestEvidence(BaseModel):
    path: str
    symbol: Optional[str] = None
    notes: Optional[str] = None


class ManifestResource(BaseModel):
    resource_id: str
    environment: Optional[str] = None
    usage: List[str] = Field(default_factory=list)
    evidence: List[ManifestEvidence] = Field(default_factory=list)
    provenance: str = "declared"
    verification: Optional[str] = None
    observed_at: Optional[str] = None


class ProjectManifest(BaseModel):
    manifest_version: str = "1"
    project_id: str
    repository: Optional[str] = None
    revision: Optional[str] = None
    resources: List[ManifestResource] = Field(default_factory=list)


class ManifestValidationResult(BaseModel):
    valid: bool
    project_id: str
    resolved_resources: List[Dict[str, Any]] = Field(default_factory=list)
    unresolved_resources: List[str] = Field(default_factory=list)
    missing_owners: List[str] = Field(default_factory=list)
    missing_documentation: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


def load_project_manifest(path: Union[str, Path]) -> ProjectManifest:
    """Load a ProjectManifest from a Markdown file with YAML frontmatter, YAML file, or JSON file."""
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    raw_text = manifest_path.read_text(encoding="utf-8")
    suffix = manifest_path.suffix.lower()

    if suffix in (".md", ".markdown"):
        frontmatter = extract_frontmatter(raw_text)
        if not frontmatter:
            raise ValueError(
                f"Manifest Markdown file '{manifest_path}' does not contain a valid YAML frontmatter block."
            )
        data = frontmatter
    elif suffix == ".json":
        try:
            data = json.loads(raw_text)
        except Exception as exc:
            raise ValueError(f"Invalid JSON in manifest file '{manifest_path}': {exc}") from exc
    else:
        try:
            data = yaml.safe_load(raw_text)
        except Exception as exc:
            raise ValueError(f"Invalid YAML in manifest file '{manifest_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Manifest file '{manifest_path}' must define a mapping at top level.")

    return ProjectManifest.model_validate(data)


def _match_resource_in_store(
    resource_id: str,
    all_docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Resolve a `resource_id` against stored metadata documents.
    Supports:
      - `config::instance::schema::table` (exact 4-part table key)
      - `config::instance::schema` (3-part database/schema key matching all tables in that schema)
      - `instance::schema::table` (3-part table key when unambiguous)
    """
    parts = [p.strip() for p in resource_id.split("::")]
    if len(parts) == 4:
        cfg, inst, sch, tbl = parts
        return [
            doc
            for doc in all_docs
            if doc.get("config_name") == cfg
            and doc.get("instance_name") == inst
            and doc.get("schema_name") == sch
            and doc.get("table_name") == tbl
        ]
    if len(parts) == 3:
        p0, p1, p2 = parts
        # First check config::instance::schema (database-level reference)
        schema_matches = [
            doc
            for doc in all_docs
            if doc.get("config_name") == p0
            and doc.get("instance_name") == p1
            and doc.get("schema_name") == p2
        ]
        if schema_matches:
            return schema_matches
        # Otherwise check config::schema::table
        config_table_matches = [
            doc
            for doc in all_docs
            if doc.get("config_name") == p0
            and doc.get("schema_name") == p1
            and doc.get("table_name") == p2
        ]
        if config_table_matches:
            return config_table_matches
        # Otherwise check instance::schema::table
        return [
            doc
            for doc in all_docs
            if doc.get("instance_name") == p0
            and doc.get("schema_name") == p1
            and doc.get("table_name") == p2
        ]
    return []


def _collect_all_docs(store: BaseMetadataStore) -> List[Dict[str, Any]]:
    if isinstance(store, FileMetadataStore):
        return list(store.iter_all_metadata())
    docs: List[Dict[str, Any]] = []
    for inst in store.list_instances().get("items", []):
        for db in store.list_databases(inst).get("items", []):
            for tbl in store.list_tables_metadata(inst, db).get("items", []):
                doc = store.find_table_metadata(inst, db, tbl)
                if doc:
                    docs.append(doc)
    return docs


def validate_project_manifest(
    manifest_or_path: Union[ProjectManifest, str, Path],
    store: Optional[BaseMetadataStore] = None,
    require_owner: bool = False,
) -> ManifestValidationResult:
    """Validate a project manifest against the stored metadata catalog."""
    manifest = (
        manifest_or_path
        if isinstance(manifest_or_path, ProjectManifest)
        else load_project_manifest(manifest_or_path)
    )
    metadata_store = store or get_metadata_store()
    all_docs = _collect_all_docs(metadata_store)

    resolved: List[Dict[str, Any]] = []
    unresolved: List[str] = []
    missing_owners: List[str] = []
    missing_docs: List[str] = []
    errors: List[str] = []

    for res in manifest.resources:
        matches = _match_resource_in_store(res.resource_id, all_docs)
        if not matches:
            unresolved.append(res.resource_id)
            errors.append(f"Unresolved resource_id: '{res.resource_id}'")
            continue

        matched_keys = [
            m.get("metadata_key")
            or f"{m.get('config_name')}::{m.get('instance_name')}::{m.get('schema_name')}::{m.get('table_name')}"
            for m in matches
        ]
        resolved.append(
            {
                "resource_id": res.resource_id,
                "matched_metadata_keys": matched_keys,
                "environment": res.environment,
                "usage": res.usage,
                "provenance": res.provenance,
                "verification": res.verification,
            }
        )
        for m in matches:
            m_key = (
                m.get("metadata_key")
                or f"{m.get('config_name')}::{m.get('instance_name')}::{m.get('schema_name')}::{m.get('table_name')}"
            )
            if not m.get("owner"):
                if m_key not in missing_owners:
                    missing_owners.append(m_key)
                if require_owner:
                    errors.append(f"Resource '{m_key}' is missing a required 'owner'.")
            ai_doc = m.get("ai_documentation")
            has_summary = isinstance(ai_doc, dict) and bool(ai_doc.get("summary"))
            if not has_summary and not m.get("notes"):
                if m_key not in missing_docs:
                    missing_docs.append(m_key)

    return ManifestValidationResult(
        valid=len(errors) == 0,
        project_id=manifest.project_id,
        resolved_resources=resolved,
        unresolved_resources=unresolved,
        missing_owners=missing_owners,
        missing_documentation=missing_docs,
        errors=errors,
    )


def build_reverse_links(
    manifests: Sequence[Union[ProjectManifest, str, Path]],
    store: Optional[BaseMetadataStore] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build a reverse index mapping catalog `metadata_key` (or `resource_id` if unresolved)
    to the list of projects that declare or show usage of that resource.
    """
    metadata_store = store or get_metadata_store()
    all_docs = _collect_all_docs(metadata_store)
    reverse_map: Dict[str, List[Dict[str, Any]]] = {}

    for item in manifests:
        manifest = item if isinstance(item, ProjectManifest) else load_project_manifest(item)
        for res in manifest.resources:
            matches = _match_resource_in_store(res.resource_id, all_docs)
            target_keys = (
                [
                    m.get("metadata_key")
                    or f"{m.get('config_name')}::{m.get('instance_name')}::{m.get('schema_name')}::{m.get('table_name')}"
                    for m in matches
                ]
                if matches
                else [res.resource_id]
            )
            for key in target_keys:
                reverse_map.setdefault(key, []).append(
                    {
                        "project_id": manifest.project_id,
                        "repository": manifest.repository,
                        "revision": manifest.revision,
                        "resource_id": res.resource_id,
                        "resolved": bool(matches),
                        "environment": res.environment,
                        "usage": res.usage,
                        "provenance": res.provenance,
                        "verification": res.verification,
                        "observed_at": res.observed_at,
                        "evidence": [ev.model_dump(exclude_none=True) for ev in res.evidence],
                    }
                )
    return reverse_map
