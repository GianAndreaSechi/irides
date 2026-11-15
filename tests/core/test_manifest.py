from pathlib import Path
import pytest

from core.db_connector.manifest import (
    build_reverse_links,
    load_project_manifest,
    validate_project_manifest,
)
from core.db_connector.storage import FileMetadataStore


SCHEMA_DESC = {
    "instance_name": "demo.sqlite",
    "schema_name": "main",
    "table_name": "orders",
    "columns": [{"name": "id", "data_type": "INTEGER"}],
}


def test_load_and_validate_markdown_manifest(tmp_path):
    store = FileMetadataStore(base_dir=str(tmp_path / "meta"))
    store.save_table_metadata("demo_sqlite", "demo.sqlite", "main", "orders", SCHEMA_DESC)
    store.update_table_metadata(
        "demo.sqlite",
        "main",
        "orders",
        {"owner": "checkout-team", "notes": "Orders table"},
        config_name="demo_sqlite",
    )

    manifest_file = tmp_path / "database.md"
    manifest_file.write_text(
        """---
manifest_version: "1"
project_id: "checkout-service"
repository: "https://example.org/acme/checkout-service"
revision: "abc1234"
resources:
  - resource_id: "demo_sqlite::demo.sqlite::main::orders"
    environment: "production"
    usage: [read, write]
    evidence:
      - path: "src/orders/repo.py"
        symbol: "OrderRepo"
    provenance: "repository-analysis"
    verification: "human-reviewed"
---
# Database Dependencies
""",
        encoding="utf-8",
    )

    manifest = load_project_manifest(manifest_file)
    assert manifest.project_id == "checkout-service"
    assert len(manifest.resources) == 1

    validation = validate_project_manifest(manifest_file, store=store, require_owner=True)
    assert validation.valid is True
    assert validation.unresolved_resources == []
    assert validation.missing_owners == []
    assert validation.missing_documentation == []

    links = build_reverse_links([manifest_file], store=store)
    key = "demo_sqlite::demo.sqlite::main::orders"
    assert key in links
    assert links[key][0]["project_id"] == "checkout-service"
    assert links[key][0]["usage"] == ["read", "write"]


def test_validate_manifest_detects_unresolved_and_missing_owner(tmp_path):
    store = FileMetadataStore(base_dir=str(tmp_path / "meta"))
    store.save_table_metadata("demo_sqlite", "demo.sqlite", "main", "orders", SCHEMA_DESC)

    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
manifest_version: "1"
project_id: "billing-service"
resources:
  - resource_id: "demo_sqlite::main::orders"
  - resource_id: "demo_sqlite::main::missing_table"
""",
        encoding="utf-8",
    )

    validation = validate_project_manifest(manifest_file, store=store, require_owner=True)
    assert validation.valid is False
    assert "demo_sqlite::main::missing_table" in validation.unresolved_resources
    assert "demo_sqlite::demo.sqlite::main::orders" in validation.missing_owners
