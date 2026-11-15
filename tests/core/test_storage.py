import time
import stat
import pytest
import yaml
from core.db_connector.exporting import ExportFormat, ExportOptions
from core.db_connector.storage import (
    AmbiguousMetadataError,
    FileMetadataStore,
    build_metadata_key,
)


@pytest.fixture
def store(tmp_path):
    return FileMetadataStore(base_dir=str(tmp_path))


SCHEMA_DESC = {
    "instance_name": "db.host.local",
    "schema_name": "mydb",
    "table_name": "users",
    "columns": [{"name": "id", "data_type": "int"}],
}


class TestBuildMetadataKey:
    def test_composite_key(self):
        key = build_metadata_key("cfg", "inst", "sch", "tbl")
        assert key == "cfg::inst::sch::tbl"


class TestFileMetadataStoreSanitize:
    def test_replaces_slash(self, store):
        result = store._sanitize("a/b")
        assert "/" not in result

    def test_replaces_colon(self, store):
        result = store._sanitize("host:3306")
        assert ":" not in result

    def test_replaces_star_and_question(self, store):
        result = store._sanitize("tab*le?name")
        assert "*" not in result
        assert "?" not in result

    def test_preserves_dot(self, store):
        result = store._sanitize("db.host.local")
        assert result == "db.host.local"

    def test_preserves_hyphen_and_underscore(self, store):
        result = store._sanitize("my-config_name")
        assert result == "my-config_name"

    def test_rejects_dot_and_dotdot_segments(self, store):
        with pytest.raises(ValueError, match="relative traversal segments are not allowed"):
            store._sanitize(".")
        with pytest.raises(ValueError, match="relative traversal segments are not allowed"):
            store._sanitize("..")

    def test_reversible_sanitization_prevents_collision(self, store):
        assert store._sanitize("a/b") != store._sanitize("a:b")
        assert store._sanitize("a/b") != store._sanitize("a_b")


class TestFileMetadataStoreGetSave:
    def test_get_returns_none_for_missing(self, store):
        assert store.get_table_metadata("cfg", "inst", "sch", "tbl") is None

    def test_save_and_get_roundtrip(self, store):
        saved = store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)
        loaded = store.get_table_metadata("cfg", "inst", "sch", "users")

        assert loaded is not None
        assert loaded["table_name"] == "users"
        assert loaded["schema_description"] == SCHEMA_DESC
        assert loaded["ai_documentation"] is None
        assert "updated_at" in loaded
        assert loaded["metadata_key"] == "cfg::inst::sch::users"

    def test_save_with_ai_doc(self, store):
        ai_doc = {"summary": "User table", "column_descriptions": {"id": "Primary key"}}
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC, ai_documentation=ai_doc)
        loaded = store.get_table_metadata("cfg", "inst", "sch", "users")
        assert loaded["ai_documentation"] == ai_doc

    def test_schema_update_preserves_existing_ai_doc(self, store):
        ai_doc = {"summary": "Preserved", "column_descriptions": {}}
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC, ai_documentation=ai_doc)

        new_schema = {**SCHEMA_DESC, "columns": [{"name": "id", "data_type": "bigint"}]}
        store.save_table_metadata("cfg", "inst", "sch", "users", new_schema, ai_documentation=None)

        loaded = store.get_table_metadata("cfg", "inst", "sch", "users")
        assert loaded["ai_documentation"] == ai_doc
        assert loaded["schema_description"]["columns"][0]["data_type"] == "bigint"

    def test_ai_doc_can_be_overwritten(self, store):
        first = {"summary": "First"}
        second = {"summary": "Second"}
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC, ai_documentation=first)
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC, ai_documentation=second)
        loaded = store.get_table_metadata("cfg", "inst", "sch", "users")
        assert loaded["ai_documentation"]["summary"] == "Second"

    def test_special_chars_in_names_do_not_raise(self, store):
        store.save_table_metadata("cfg:1", "host:3306", "db/schema", "tab*le", SCHEMA_DESC)
        loaded = store.get_table_metadata("cfg:1", "host:3306", "db/schema", "tab*le")
        assert loaded is not None

    def test_creates_nested_directories(self, store, tmp_path):
        store.save_table_metadata("c", "i", "s", "t", SCHEMA_DESC)
        expected = tmp_path / "c" / "i" / "s" / "t.json"
        assert expected.exists()


class TestExports:
    def test_markdown_and_okf_are_generated_by_default(self, store, tmp_path):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)

        markdown = tmp_path / "exports" / "markdown" / "cfg" / "inst" / "sch" / "users.md"
        okf = tmp_path / "exports" / "okf" / "catalog" / "cfg" / "inst" / "sch" / "users.md"
        index = tmp_path / "exports" / "okf" / "catalog" / "index.md"
        assert markdown.exists()
        assert okf.exists()
        assert index.exists()
        assert stat.S_IMODE(markdown.stat().st_mode) == 0o644
        assert stat.S_IMODE(okf.stat().st_mode) == 0o644
        assert stat.S_IMODE(index.stat().st_mode) == 0o644

    def test_okf_has_required_frontmatter(self, store, tmp_path):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)
        path = tmp_path / "exports" / "okf" / "catalog" / "cfg" / "inst" / "sch" / "users.md"
        content = path.read_text(encoding="utf-8")
        _, frontmatter_text, body = content.split("---", 2)
        frontmatter = yaml.safe_load(frontmatter_text)

        assert frontmatter["type"] == "Database Table"
        assert frontmatter["title"] == "sch.users"
        assert frontmatter["generated"]["by"] == "irides/0.1.0"
        assert "# Schema" in body

    def test_formats_can_be_disabled_explicitly(self, store, tmp_path):
        store.save_table_metadata(
            "cfg",
            "inst",
            "sch",
            "users",
            SCHEMA_DESC,
            export_options=ExportOptions(formats=[]),
        )

        assert not (tmp_path / "exports").exists()

    def test_single_format_can_be_selected(self, store, tmp_path):
        store.save_table_metadata(
            "cfg",
            "inst",
            "sch",
            "users",
            SCHEMA_DESC,
            export_options=ExportOptions(formats=[ExportFormat.OKF]),
        )

        assert not (tmp_path / "exports" / "markdown").exists()
        assert (tmp_path / "exports" / "okf" / "catalog" / "index.md").exists()

    def test_export_does_not_require_json_persistence(self, store, tmp_path):
        store.save_table_metadata(
            "cfg",
            "inst",
            "sch",
            "users",
            SCHEMA_DESC,
            save_metadata=False,
        )

        assert store.get_table_metadata("cfg", "inst", "sch", "users") is None
        assert (tmp_path / "exports" / "markdown" / "cfg" / "inst" / "sch" / "users.md").exists()

    def test_preformatter_is_enabled_by_default(self, store, tmp_path):
        schema = {
            **SCHEMA_DESC,
            "columns": [{"name": "id", "data_type": "int", "default_value": "nextval('users')"}],
            "indexes": [
                {"name": "idx_users", "column_names": ["id"], "is_unique": False, "is_primary": False},
                {"name": "uq_users_id", "column_names": ["id"], "is_unique": True, "is_primary": False},
            ],
        }
        store.save_table_metadata("cfg", "inst", "sch", "users", schema)
        markdown_path = tmp_path / "exports" / "markdown" / "cfg" / "inst" / "sch" / "users.md"
        okf_path = tmp_path / "exports" / "okf" / "catalog" / "cfg" / "inst" / "sch" / "users.md"
        markdown = markdown_path.read_text(encoding="utf-8")
        okf = okf_path.read_text(encoding="utf-8")

        assert "nextval" not in markdown
        assert "idx_users" not in markdown
        assert "idx_users" not in okf
        assert "uq_users_id" in markdown
        assert "uq_users_id" in okf

    def test_preformatter_can_be_disabled(self, store, tmp_path):
        schema = {
            **SCHEMA_DESC,
            "indexes": [{"name": "idx_users", "column_names": ["id"], "is_unique": False}],
        }
        store.save_table_metadata(
            "cfg",
            "inst",
            "sch",
            "users",
            schema,
            export_options=ExportOptions(preformat=False),
        )
        path = tmp_path / "exports" / "markdown" / "cfg" / "inst" / "sch" / "users.md"

        assert "idx_users" in path.read_text(encoding="utf-8")

    def test_preformatter_disabled_renders_default_column(self, store, tmp_path):
        schema = {
            **SCHEMA_DESC,
            "columns": [{"name": "status", "data_type": "text", "default_value": "'active'"}],
        }
        store.save_table_metadata(
            "cfg",
            "inst",
            "sch",
            "users",
            schema,
            export_options=ExportOptions(preformat=False),
        )
        path = tmp_path / "exports" / "markdown" / "cfg" / "inst" / "sch" / "users.md"
        md = path.read_text(encoding="utf-8")
        assert "| Name | Type | Nullable | Default | Description |" in md
        assert "'active'" in md

    def test_notes_and_classification_are_exported(self, store, tmp_path):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)
        store.update_table_metadata(
            "inst",
            "sch",
            "users",
            {"notes": "Critical operational note", "data_classification": "confidential"},
        )
        md_path = tmp_path / "exports" / "markdown" / "cfg" / "inst" / "sch" / "users.md"
        okf_path = tmp_path / "exports" / "okf" / "catalog" / "cfg" / "inst" / "sch" / "users.md"
        assert "Critical operational note" in md_path.read_text(encoding="utf-8")
        assert "confidential" in md_path.read_text(encoding="utf-8")
        assert "Critical operational note" in okf_path.read_text(encoding="utf-8")

    def test_table_named_index_is_included_in_okf_bundle_index(self, store, tmp_path):
        store.save_table_metadata("cfg", "inst", "sch", "index", {**SCHEMA_DESC, "table_name": "index"})
        index_md = (tmp_path / "exports" / "okf" / "catalog" / "index.md").read_text(encoding="utf-8")
        assert "sch.index" in index_md

    def test_frontmatter_with_dashes_in_description_is_indexed_correctly(self, store, tmp_path):
        ai_doc = {"summary": "Line one --- line two", "column_descriptions": {}}
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC, ai_documentation=ai_doc)
        index_md = (tmp_path / "exports" / "okf" / "catalog" / "index.md").read_text(encoding="utf-8")
        assert "sch.users" in index_md
        assert "Line one --- line two" in index_md

    def test_dynamodb_gsi_preserved_in_essential_export(self, store, tmp_path):
        schema = {
            **SCHEMA_DESC,
            "indexes": [
                {"name": "gsi_email", "column_names": ["email"], "is_unique": False, "is_primary": False, "type": "GSI"},
            ],
        }
        store.save_table_metadata("cfg", "inst", "sch", "users", schema)
        md = (tmp_path / "exports" / "markdown" / "cfg" / "inst" / "sch" / "users.md").read_text(encoding="utf-8")
        assert "gsi_email" in md
        assert "(GSI)" in md


class TestOnlyIfChanged:
    def test_unchanged_schema_returns_unchanged_flag(self, store):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)
        result = store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC, only_if_changed=True)
        assert result.get("_unchanged") is True

    def test_unchanged_schema_does_not_update_file(self, store):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)
        original = store.get_table_metadata("cfg", "inst", "sch", "users")["updated_at"]
        time.sleep(0.01)
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC, only_if_changed=True)
        reloaded = store.get_table_metadata("cfg", "inst", "sch", "users")["updated_at"]
        assert original == reloaded

    def test_changed_schema_writes_with_flag(self, store):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)
        new_schema = {**SCHEMA_DESC, "columns": [{"name": "id", "data_type": "bigint"}]}
        result = store.save_table_metadata("cfg", "inst", "sch", "users", new_schema, only_if_changed=True)
        assert "_unchanged" not in result
        loaded = store.get_table_metadata("cfg", "inst", "sch", "users")
        assert loaded["schema_description"]["columns"][0]["data_type"] == "bigint"

    def test_first_save_always_writes(self, store):
        result = store.save_table_metadata("cfg", "inst", "sch", "new_table", SCHEMA_DESC, only_if_changed=True)
        assert "_unchanged" not in result
        assert store.get_table_metadata("cfg", "inst", "sch", "new_table") is not None

    def test_ai_doc_change_writes_even_when_schema_unchanged(self, store):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC, ai_documentation=None)
        ai_doc = {"summary": "Newly generated summary", "column_descriptions": {}}
        result = store.save_table_metadata(
            "cfg",
            "inst",
            "sch",
            "users",
            SCHEMA_DESC,
            ai_documentation=ai_doc,
            only_if_changed=True,
        )
        assert "_unchanged" not in result
        loaded = store.get_table_metadata("cfg", "inst", "sch", "users")
        assert loaded["ai_documentation"] == ai_doc


class TestCustomFieldCarryForward:
    def test_custom_fields_preserved_on_resave(self, store):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)
        store.update_table_metadata("inst", "sch", "users", {"owner": "data-team", "tags": ["pii"]})

        new_schema = {**SCHEMA_DESC, "columns": [{"name": "id", "data_type": "bigint"}]}
        store.save_table_metadata("cfg", "inst", "sch", "users", new_schema)

        loaded = store.get_table_metadata("cfg", "inst", "sch", "users")
        assert loaded["owner"] == "data-team"
        assert loaded["tags"] == ["pii"]

    def test_system_key_updated_at_regenerated_on_resave(self, store):
        store.save_table_metadata("cfg", "inst", "sch", "users", SCHEMA_DESC)
        old_ts = store.get_table_metadata("cfg", "inst", "sch", "users")["updated_at"]
        time.sleep(0.01)
        new_schema = {**SCHEMA_DESC, "columns": [{"name": "id", "data_type": "bigint"}]}
        store.save_table_metadata("cfg", "inst", "sch", "users", new_schema)
        new_ts = store.get_table_metadata("cfg", "inst", "sch", "users")["updated_at"]
        assert new_ts != old_ts

    def test_multiple_custom_fields_all_preserved(self, store):
        store.save_table_metadata("cfg", "inst", "sch", "orders", SCHEMA_DESC)
        store.update_table_metadata("inst", "sch", "orders", {
            "owner": "billing",
            "notes": "Replicated every 6h",
            "data_classification": "confidential",
        })
        store.save_table_metadata("cfg", "inst", "sch", "orders", SCHEMA_DESC)

        loaded = store.get_table_metadata("cfg", "inst", "sch", "orders")
        assert loaded["owner"] == "billing"
        assert loaded["notes"] == "Replicated every 6h"
        assert loaded["data_classification"] == "confidential"


class TestListInstances:
    def test_empty_store_returns_empty(self, store):
        result = store.list_instances()
        assert result["items"] == []
        assert result["total"] == 0
        assert result["pages"] == 0

    def test_lists_instances_after_save(self, store):
        store.save_table_metadata("cfg", "host_a", "sch", "tbl", SCHEMA_DESC)
        store.save_table_metadata("cfg", "host_b", "sch", "tbl", SCHEMA_DESC)
        result = store.list_instances()
        assert "host_a" in result["items"]
        assert "host_b" in result["items"]
        assert result["total"] == 2

    def test_deduplicates_across_configs(self, store):
        store.save_table_metadata("cfg1", "host_x", "sch", "tbl", SCHEMA_DESC)
        store.save_table_metadata("cfg2", "host_x", "sch", "tbl", SCHEMA_DESC)
        result = store.list_instances()
        assert result["items"].count("host_x") == 1

    def test_pagination(self, store):
        for i in range(5):
            store.save_table_metadata("cfg", f"host_{i}", "sch", "tbl", SCHEMA_DESC)
        page1 = store.list_instances(page=1, page_size=3)
        page2 = store.list_instances(page=2, page_size=3)
        assert len(page1["items"]) == 3
        assert len(page2["items"]) == 2
        assert page1["pages"] == 2
        assert page1["total"] == 5


class TestListDatabases:
    def test_returns_databases_for_instance(self, store):
        store.save_table_metadata("cfg", "host_a", "db1", "tbl", SCHEMA_DESC)
        store.save_table_metadata("cfg", "host_a", "db2", "tbl", SCHEMA_DESC)
        result = store.list_databases("host_a")
        assert "db1" in result["items"]
        assert "db2" in result["items"]
        assert result["total"] == 2

    def test_empty_for_unknown_instance(self, store):
        result = store.list_databases("nonexistent")
        assert result["total"] == 0
        assert result["items"] == []

    def test_does_not_include_other_instances(self, store):
        store.save_table_metadata("cfg", "host_a", "db_a", "tbl", SCHEMA_DESC)
        store.save_table_metadata("cfg", "host_b", "db_b", "tbl", SCHEMA_DESC)
        result = store.list_databases("host_a")
        assert "db_b" not in result["items"]


class TestListTablesMeta:
    def test_returns_tables_for_instance_database(self, store):
        store.save_table_metadata("cfg", "host_a", "db1", "users", SCHEMA_DESC)
        store.save_table_metadata("cfg", "host_a", "db1", "orders", SCHEMA_DESC)
        result = store.list_tables_metadata("host_a", "db1")
        assert "users" in result["items"]
        assert "orders" in result["items"]
        assert result["total"] == 2

    def test_empty_for_unknown_database(self, store):
        result = store.list_tables_metadata("host_a", "nonexistent_db")
        assert result["total"] == 0

    def test_does_not_include_other_databases(self, store):
        store.save_table_metadata("cfg", "host_a", "db1", "users", SCHEMA_DESC)
        store.save_table_metadata("cfg", "host_a", "db2", "orders", SCHEMA_DESC)
        result = store.list_tables_metadata("host_a", "db1")
        assert "orders" not in result["items"]


class TestFindTableMetadata:
    def test_finds_table_across_configs(self, store):
        store.save_table_metadata("cfg", "host_a", "db1", "users", SCHEMA_DESC)
        result = store.find_table_metadata("host_a", "db1", "users")
        assert result is not None
        assert result["table_name"] == "users"

    def test_returns_none_for_missing_table(self, store):
        assert store.find_table_metadata("no_host", "no_db", "no_table") is None

    def test_returns_first_match_across_multiple_configs(self, store):
        store.save_table_metadata("cfg1", "host_a", "db1", "users", SCHEMA_DESC)
        store.save_table_metadata("cfg2", "host_a", "db1", "users", SCHEMA_DESC)
        result = store.find_table_metadata("host_a", "db1", "users")
        assert result is not None

    def test_strict_raises_ambiguous_error_across_multiple_configs(self, store):
        store.save_table_metadata("cfg1", "host_a", "db1", "users", SCHEMA_DESC)
        store.save_table_metadata("cfg2", "host_a", "db1", "users", SCHEMA_DESC)
        with pytest.raises(AmbiguousMetadataError):
            store.find_table_metadata("host_a", "db1", "users", strict=True)

    def test_config_name_disambiguates_across_multiple_configs(self, store):
        store.save_table_metadata("cfg1", "host_a", "db1", "users", SCHEMA_DESC)
        store.save_table_metadata("cfg2", "host_a", "db1", "users", {**SCHEMA_DESC, "columns": []})
        result = store.find_table_metadata("host_a", "db1", "users", config_name="cfg2", strict=True)
        assert result is not None
        assert result["config_name"] == "cfg2"
        assert result["schema_description"]["columns"] == []


class TestUpdateTableMetadata:
    def test_merges_custom_fields(self, store):
        store.save_table_metadata("cfg", "host_a", "db1", "users", SCHEMA_DESC)
        result = store.update_table_metadata("host_a", "db1", "users", {"owner": "team-a", "tags": ["pii"]})
        assert result["owner"] == "team-a"
        assert result["tags"] == ["pii"]

    def test_protected_fields_are_not_overwritten(self, store):
        store.save_table_metadata("cfg", "host_a", "db1", "users", SCHEMA_DESC)
        result = store.update_table_metadata("host_a", "db1", "users", {
            "metadata_key": "hacked",
            "config_name": "hacked",
            "instance_name": "hacked",
            "schema_name": "hacked",
            "table_name": "hacked",
            "updated_at": "hacked",
            "owner": "team-a",
        })
        assert result["owner"] == "team-a"
        assert result["metadata_key"] != "hacked"
        assert result["config_name"] == "cfg"
        assert result["instance_name"] == "host_a"
        assert result["table_name"] == "users"

    def test_returns_none_for_missing_table(self, store):
        result = store.update_table_metadata("no_host", "no_db", "no_table", {"owner": "x"})
        assert result is None

    def test_persists_update_to_disk(self, store):
        store.save_table_metadata("cfg", "host_a", "db1", "users", SCHEMA_DESC)
        store.update_table_metadata("host_a", "db1", "users", {"owner": "team-a"})
        loaded = store.get_table_metadata("cfg", "host_a", "db1", "users")
        assert loaded["owner"] == "team-a"

    def test_updates_updated_at(self, store):
        store.save_table_metadata("cfg", "host_a", "db1", "users", SCHEMA_DESC)
        original_ts = store.get_table_metadata("cfg", "host_a", "db1", "users")["updated_at"]
        time.sleep(0.01)
        store.update_table_metadata("host_a", "db1", "users", {"owner": "team-a"})
        updated = store.get_table_metadata("cfg", "host_a", "db1", "users")["updated_at"]
        assert updated != original_ts

    def test_regenerates_default_exports(self, store, tmp_path):
        store.save_table_metadata("cfg", "host_a", "db1", "users", SCHEMA_DESC)
        store.update_table_metadata("host_a", "db1", "users", {"owner": "team-a"})
        path = tmp_path / "exports" / "okf" / "catalog" / "cfg" / "host_a" / "db1" / "users.md"

        assert "owner: team-a" in path.read_text(encoding="utf-8")


class TestLegacyPathMigration:
    def _write_legacy_record(self, tmp_path, config="cfg", instance="host:3306", schema="db/main", table="users"):
        import json
        from datetime import datetime, timezone

        legacy_path = (
            tmp_path
            / FileMetadataStore._legacy_sanitize(config)
            / FileMetadataStore._legacy_sanitize(instance)
            / FileMetadataStore._legacy_sanitize(schema)
            / f"{FileMetadataStore._legacy_sanitize(table)}.json"
        )
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "metadata_key": build_metadata_key(config, instance, schema, table),
            "config_name": config,
            "instance_name": instance,
            "schema_name": schema,
            "table_name": table,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "schema_description": SCHEMA_DESC,
            "ai_documentation": None,
            "owner": "legacy-owner",
        }
        legacy_path.write_text(json.dumps(record), encoding="utf-8")
        return legacy_path

    def test_save_migrates_and_removes_legacy_file(self, store, tmp_path):
        legacy_path = self._write_legacy_record(tmp_path)
        assert legacy_path.exists()

        store.save_table_metadata("cfg", "host:3306", "db/main", "users", SCHEMA_DESC, only_if_changed=True)
        canonical_path = store._get_file_path("cfg", "host:3306", "db/main", "users")
        assert canonical_path.exists()
        assert not legacy_path.exists()
        loaded = store.get_table_metadata("cfg", "host:3306", "db/main", "users")
        assert loaded["owner"] == "legacy-owner"

    def test_update_migrates_and_removes_legacy_file_without_ambiguity(self, store, tmp_path):
        legacy_path = self._write_legacy_record(tmp_path)
        updated = store.update_table_metadata(
            "host:3306",
            "db/main",
            "users",
            {"notes": "migrated"},
            strict=True,
        )
        assert updated is not None
        assert updated["owner"] == "legacy-owner"
        assert updated["notes"] == "migrated"
        assert not legacy_path.exists()
        assert store._get_file_path("cfg", "host:3306", "db/main", "users").exists()

    def test_coexisting_legacy_and_canonical_in_same_config_not_ambiguous(self, store, tmp_path):
        legacy_path = self._write_legacy_record(tmp_path)
        store.save_table_metadata(
            "cfg",
            "host:3306",
            "db/main",
            "users",
            {**SCHEMA_DESC, "columns": []},
            export_options=ExportOptions(formats=[]),
        )
        # Re-create legacy file to simulate external pre-migration state with both files present
        self._write_legacy_record(tmp_path)
        assert legacy_path.exists()

        found = store.find_table_metadata("host:3306", "db/main", "users", strict=True)
        assert found is not None
        assert found["schema_description"]["columns"] == []
        instances = store.list_instances()
        assert instances["items"] == ["host:3306"]
        assert store.list_configs() == ["cfg"]
