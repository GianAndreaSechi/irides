import os
import tempfile
from pathlib import Path
import pytest
import yaml

from core.db_connector.configurations import (
    discover_config_file,
    load_file_configurations,
    get_db_configurations,
    _expand_env_vars,
)


def test_expand_env_vars():
    os.environ["TEST_IRIDES_HOST"] = "remote.host"
    try:
        data = {
            "host": "${TEST_IRIDES_HOST}",
            "port": "${TEST_IRIDES_PORT:-5432}",
            "user": "postgres",
            "nested": ["${TEST_IRIDES_HOST}", 123],
        }
        expanded = _expand_env_vars(data)
        assert expanded["host"] == "remote.host"
        assert expanded["port"] == "5432"
        assert expanded["user"] == "postgres"
        assert expanded["nested"][0] == "remote.host"
        assert expanded["nested"][1] == 123
    finally:
        os.environ.pop("TEST_IRIDES_HOST", None)


def test_load_file_configurations_flat_yaml():
    yaml_content = """
targets:
  sales_pg:
    type: postgres
    host: pg.local
    port: 5433
    user: pguser
    password: pgpassword
    database: salesdb
  app_sqlite:
    type: sqlite
    database: /path/to/db.sqlite
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        configs = load_file_configurations(tmp_path)
        assert "sales_pg" in configs
        assert configs["sales_pg"]["connector_type"] == "postgres"
        assert configs["sales_pg"]["connection_params"]["host"] == "pg.local"
        assert configs["sales_pg"]["connection_params"]["port"] == 5433
        assert configs["sales_pg"]["connection_params"]["database"] == "salesdb"

        assert "app_sqlite" in configs
        assert configs["app_sqlite"]["connector_type"] == "sqlite"
        assert configs["app_sqlite"]["connection_params"]["database"] == "/path/to/db.sqlite"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_load_file_configurations_nested_yaml():
    yaml_content = """
targets:
  prod_mysql:
    connector_type: mysql
    connection_params:
      host: mysql.prod
      port: 3306
      user: root
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        configs = load_file_configurations(tmp_path)
        assert "prod_mysql" in configs
        assert configs["prod_mysql"]["connector_type"] == "mysql"
        assert configs["prod_mysql"]["connection_params"]["host"] == "mysql.prod"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_get_db_configurations_env_override():
    yaml_content = """
targets:
  shared_db:
    type: postgres
    host: from-yaml.local
    database: test
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    os.environ["DB_TARGETS"] = "shared_db"
    os.environ["DB_TARGET_SHARED_DB_TYPE"] = "postgres"
    os.environ["DB_TARGET_SHARED_DB_HOST"] = "from-env.local"

    try:
        configs = get_db_configurations(config_file=tmp_path)
        assert "shared_db" in configs
        # Env should override YAML
        assert configs["shared_db"]["connection_params"]["host"] == "from-env.local"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        os.environ.pop("DB_TARGETS", None)
        os.environ.pop("DB_TARGET_SHARED_DB_TYPE", None)
        os.environ.pop("DB_TARGET_SHARED_DB_HOST", None)


def test_explicit_missing_config_file_raises():
    with pytest.raises(FileNotFoundError, match="Configuration file not found"):
        load_file_configurations("/nonexistent/path/to/irides.yaml")


def test_invalid_yaml_config_file_raises(tmp_path):
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("targets: [unterminated", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to parse configuration file"):
        load_file_configurations(bad_file)


def test_normalized_target_key_collision_raises():
    os.environ["DB_TARGETS"] = "sales-db,sales_db"
    os.environ["DB_TARGET_SALES_DB_TYPE"] = "sqlite"
    os.environ["DB_TARGET_SALES_DB_DATABASE"] = "/tmp/test.db"
    try:
        with pytest.raises(ValueError, match="collides with"):
            get_db_configurations()
    finally:
        os.environ.pop("DB_TARGETS", None)
        os.environ.pop("DB_TARGET_SALES_DB_TYPE", None)
        os.environ.pop("DB_TARGET_SALES_DB_DATABASE", None)
