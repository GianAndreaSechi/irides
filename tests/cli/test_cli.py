import json
import sqlite3
import pytest

from irides_core import Catalog
from irides_cli.main import main as cli_main


@pytest.fixture
def demo_env(tmp_path, monkeypatch):
    db_file = tmp_path / "demo.sqlite"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        """
    )
    conn.commit()
    conn.close()

    config_file = tmp_path / "irides.yaml"
    config_file.write_text(
        f"""targets:
  demo_sqlite:
    type: sqlite
    database: {db_file}
""",
        encoding="utf-8",
    )

    meta_dir = tmp_path / "storage" / "metadata"
    export_dir = tmp_path / "storage" / "exports"
    monkeypatch.setenv("STORAGE_METADATA_DIR", str(meta_dir))
    monkeypatch.setenv("STORAGE_EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("DB_TARGETS", "")

    return {
        "tmp_path": tmp_path,
        "db_file": str(db_file),
        "config_file": str(config_file),
        "meta_dir": meta_dir,
        "export_dir": export_dir,
    }


def test_catalog_python_api_sqlite_flow(demo_env):
    catalog = Catalog(config_file=demo_env["config_file"])
    assert catalog.configurations() == ["demo_sqlite"]

    instances = catalog.instances("demo_sqlite")
    assert len(instances) == 1
    assert instances[0].name == demo_env["db_file"]

    schemas = catalog.schemas("demo_sqlite")
    assert [s.name for s in schemas] == ["main"]

    tables = catalog.tables("demo_sqlite", schema_name="main")
    assert {t.name for t in tables} == {"customers", "orders"}

    outcomes = catalog.describe("demo_sqlite", schema_name="main")
    assert len(outcomes) == 2
    assert all(item.table.config_name == "demo_sqlite" for item in outcomes)


def test_cli_describe_and_metadata_update_and_export(demo_env, capsys):
    rc = cli_main(
        [
            "-c",
            demo_env["config_file"],
            "describe",
            "--target",
            "demo_sqlite",
            "--no-preformat",
        ]
    )
    assert rc == 0
    out, err = capsys.readouterr()
    parsed = json.loads(out)
    assert len(parsed) == 2

    rc_update = cli_main(
        [
            "metadata",
            "update",
            demo_env["db_file"],
            "main",
            "customers",
            '{"owner": "crm-team", "notes": "Core customer records"}',
            "--target",
            "demo_sqlite",
        ]
    )
    assert rc_update == 0
    out_update, _ = capsys.readouterr()
    updated_doc = json.loads(out_update)
    assert updated_doc["owner"] == "crm-team"
    assert updated_doc["notes"] == "Core customer records"

    rc_export = cli_main(
        [
            "metadata",
            "export",
            "--target",
            "demo_sqlite",
            "--no-preformat",
        ]
    )
    assert rc_export == 0
    out_export, _ = capsys.readouterr()
    export_summary = json.loads(out_export)
    assert export_summary["exported_count"] == 2


def test_cli_nonexistent_config_file_returns_nonzero(capsys):
    rc = cli_main(["-c", "/nonexistent/irides.yaml", "configurations"])
    assert rc == 1
    _, err = capsys.readouterr()
    assert "Configuration file not found" in err


def test_irides_core_submodule_aliasing_identity():
    import irides_core.storage as ic_storage
    import core.db_connector.storage as dc_storage
    from irides_core.storage import AmbiguousMetadataError as IcError
    from core.db_connector.storage import AmbiguousMetadataError as DcError

    assert ic_storage is dc_storage
    assert IcError is DcError


def test_relative_sqlite_config_preserves_instance_name_from_different_cwd(tmp_path, monkeypatch, capsys):
    subdir = tmp_path / "examples"
    subdir.mkdir()
    db_file = subdir / "demo.sqlite"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL);")
    conn.commit()
    conn.close()

    config_file = subdir / "irides.yaml"
    config_file.write_text(
        """targets:
  demo_sqlite:
    type: sqlite
    database: ./demo.sqlite
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("STORAGE_METADATA_DIR", str(tmp_path / "storage" / "metadata"))
    monkeypatch.setenv("STORAGE_EXPORT_DIR", str(tmp_path / "storage" / "exports"))
    monkeypatch.setenv("DB_TARGETS", "")
    monkeypatch.chdir(tmp_path)

    catalog = Catalog(config_file=str(config_file))
    instances = catalog.instances("demo_sqlite")
    assert [inst.name for inst in instances] == ["./demo.sqlite"]

    rc = cli_main(["-c", str(config_file), "describe", "--target", "demo_sqlite"])
    assert rc == 0
    capsys.readouterr()

    rc_upd = cli_main(
        [
            "metadata",
            "update",
            "./demo.sqlite",
            "main",
            "items",
            '{"owner": "inventory-team"}',
            "--target",
            "demo_sqlite",
        ]
    )
    assert rc_upd == 0
    out_upd, _ = capsys.readouterr()
    assert json.loads(out_upd)["owner"] == "inventory-team"


def test_cli_config_env_commands(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "irides.env"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)

    assert cli_main(["-e", str(env_file), "config", "set-env", "LITELLM_MODEL", "gpt-4o-mini"]) == 0
    capsys.readouterr()
    assert cli_main(["-e", str(env_file), "config", "set-env", "LITELLM_API_KEY", "sk-demo-123"]) == 0
    capsys.readouterr()

    assert cli_main(["-e", str(env_file), "config", "list-env"]) == 0
    out_masked, _ = capsys.readouterr()
    listed = json.loads(out_masked)
    assert listed["LITELLM_MODEL"] == "gpt-4o-mini"
    assert listed["LITELLM_API_KEY"] == "***"

    assert cli_main(["-e", str(env_file), "config", "unset-env", "LITELLM_API_KEY"]) == 0
    capsys.readouterr()
    assert cli_main(["-e", str(env_file), "config", "list-env"]) == 0
    out_after, _ = capsys.readouterr()
    assert "LITELLM_API_KEY" not in json.loads(out_after)

    assert cli_main(["-e", str(env_file), "config", "set-env", "BAD_CUSTOM", "val"]) == 1
    capsys.readouterr()


def test_cli_config_target_yaml_and_env_roundtrip(tmp_path, monkeypatch, capsys):
    cfg_file = tmp_path / "irides.yaml"
    env_file = tmp_path / ".env"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DB_TARGETS", raising=False)
    monkeypatch.delenv("DB_TARGET_ANALYTICS_PG_PASSWORD", raising=False)
    monkeypatch.delenv("DB_TARGET_APP_SQLITE_TYPE", raising=False)
    monkeypatch.delenv("DB_TARGET_APP_SQLITE_DATABASE", raising=False)

    rc_set = cli_main(
        [
            "-c",
            str(cfg_file),
            "-e",
            str(env_file),
            "config",
            "set-target",
            "analytics_pg",
            "--type",
            "postgres",
            "--host",
            "pg.internal",
            "--port",
            "5432",
            "--user",
            "reader",
            "--password",
            "topsecret",
            "--database",
            "warehouse",
        ]
    )
    assert rc_set == 0
    res_set = json.loads(capsys.readouterr()[0])
    assert res_set["format"] == "yaml"
    assert "DB_TARGET_ANALYTICS_PG_PASSWORD" in res_set["env_keys"]

    assert cli_main(["-c", str(cfg_file), "config", "show"]) == 0
    shown_masked = json.loads(capsys.readouterr()[0])
    assert shown_masked["analytics_pg"]["connection_params"]["password"] == "***"

    assert cli_main(["-c", str(cfg_file), "config", "show", "--show-secrets"]) == 0
    shown_unmasked = json.loads(capsys.readouterr()[0])
    assert shown_unmasked["analytics_pg"]["connection_params"]["password"] == "topsecret"

    assert (
        cli_main(
            [
                "-e",
                str(env_file),
                "config",
                "set-target",
                "app_sqlite",
                "--type",
                "sqlite",
                "--database",
                "./app.db",
                "--format",
                "env",
            ]
        )
        == 0
    )
    res_env = json.loads(capsys.readouterr()[0])
    assert res_env["format"] == "env"

    assert (
        cli_main(
            ["-c", str(cfg_file), "-e", str(env_file), "config", "remove-target", "analytics_pg"]
        )
        == 0
    )
    capsys.readouterr()
    assert cli_main(["-e", str(env_file), "config", "remove-target", "app_sqlite", "--format", "env"]) == 0
    capsys.readouterr()


def test_catalog_iter_describe_rebuilds_okf_index_once_per_batch(demo_env):
    from unittest.mock import patch
    from core.db_connector.exporting import ExportOptions, FileArtifactStore

    catalog = Catalog(config_file=demo_env["config_file"])
    with patch.object(
        FileArtifactStore,
        "rebuild_okf_index",
        autospec=True,
        side_effect=FileArtifactStore.rebuild_okf_index,
    ) as spy_rebuild:
        outcomes = list(
            catalog.iter_describe(
                config_name="demo_sqlite",
                schema_name="main",
                save_metadata=True,
                export_options=ExportOptions(),
            )
        )

    assert len(outcomes) == 2
    assert all(item.ok for item in outcomes)
    assert spy_rebuild.call_count == 1
    assert (demo_env["export_dir"] / "okf" / "catalog" / "index.md").exists()


def test_catalog_iter_describe_fail_fast_vs_collect_errors():
    from unittest.mock import MagicMock
    from core.db_connector.models import Schema, Table

    cs = MagicMock()
    cs.get_available_configurations.return_value = ["cfg"]
    cs.resolve_instance_names.return_value = ["host"]
    connector = MagicMock()
    connector.list_schemas.return_value = [Schema(name="sch")]
    connector.list_tables.return_value = [
        Table(name="broken", schema_name="sch"),
        Table(name="healthy", schema_name="sch"),
    ]
    connector.describe_table.side_effect = [
        RuntimeError("boom"),
        MagicMock(
            model_copy=lambda update=None: MagicMock(
                model_dump=lambda exclude=None: {
                    "instance_name": "host",
                    "schema_name": "sch",
                    "table_name": "healthy",
                    "columns": [],
                }
            )
        ),
    ]
    cs._get_connector_for_host.return_value = connector

    catalog = Catalog(config_service=cs)
    outcomes = list(catalog.iter_describe(config_name="cfg", fail_fast=False))
    assert len(outcomes) == 2
    assert outcomes[0].ok is False
    assert "boom" in outcomes[0].error
    assert outcomes[1].ok is True

    connector.describe_table.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        list(catalog.iter_describe(config_name="cfg", fail_fast=True))
