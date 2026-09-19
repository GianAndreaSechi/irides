import os
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from loguru import logger
import yaml

# Containers mount each component's configuration in a different directory.
# DB_CONFIG_FILE makes that location explicit while preserving normal local
# dotenv discovery when it is not set.
# An explicit DB_CONFIG_FILE is the authoritative source for database settings.
# This matters in containers where an auxiliary env file may define optional
# connector variables as empty strings.
load_dotenv(dotenv_path=os.getenv("DB_CONFIG_FILE") or None, override=bool(os.getenv("DB_CONFIG_FILE")))

CONFIG_SEARCH_FILENAMES = ["irides.yaml", "irides.yml", "irides.json"]


def discover_config_file(custom_path: Optional[str] = None) -> Optional[Path]:
    """Finds an explicit or default irides configuration file."""
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        return p if p.is_file() else None

    # Check environment variable
    env_file = os.getenv("IRIDES_CONFIG_FILE") or os.getenv("DB_CONFIG_FILE")
    if env_file and any(env_file.lower().endswith(ext) for ext in (".yaml", ".yml", ".json")):
        p = Path(env_file).expanduser().resolve()
        if p.is_file():
            return p

    # Check current working directory
    cwd = Path.cwd()
    for name in CONFIG_SEARCH_FILENAMES:
        p = cwd / name
        if p.is_file():
            return p

    # Check user-level config directories
    user_config_dir = Path.home() / ".config" / "irides"
    for name in CONFIG_SEARCH_FILENAMES:
        p = user_config_dir / name
        if p.is_file():
            return p

    legacy_home_dir = Path.home() / ".irides"
    for name in CONFIG_SEARCH_FILENAMES:
        p = legacy_home_dir / name
        if p.is_file():
            return p

    return None


def _expand_env_vars(data: Any) -> Any:
    """Recursively expand environment variables like ${VAR} or ${VAR:-default}."""
    if isinstance(data, str):
        pattern = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")

        def replace_var(match: re.Match) -> str:
            var_name = match.group(1)
            default_val = match.group(2) if match.group(2) is not None else ""
            return os.getenv(var_name, default_val)

        return pattern.sub(replace_var, data)
    elif isinstance(data, dict):
        return {k: _expand_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_expand_env_vars(item) for item in data]
    return data


def load_file_configurations(file_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Loads database target configurations from a YAML or JSON file."""
    config_path = discover_config_file(file_path)
    if not config_path:
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            if config_path.suffix.lower() in {".yaml", ".yml"}:
                raw = yaml.safe_load(f) or {}
            elif config_path.suffix.lower() == ".json":
                raw = json.load(f) or {}
            else:
                return {}
    except Exception as e:
        logger.error(f"Failed to read config file {config_path}: {e}")
        return {}

    raw = _expand_env_vars(raw)
    targets_dict = raw.get("targets", raw)
    if not isinstance(targets_dict, dict):
        return {}

    configs = {}
    for target_name, target_data in targets_dict.items():
        if not isinstance(target_data, dict):
            continue

        conn_type = target_data.get("type") or target_data.get("connector_type")
        if not conn_type:
            conn_type = _infer_target_type(target_name)
        if not conn_type:
            logger.warning(f"Target '{target_name}' in {config_path.name} is missing 'type'.")
            continue

        conn_type = conn_type.lower()

        if "connection_params" in target_data and isinstance(target_data["connection_params"], dict):
            params = dict(target_data["connection_params"])
        else:
            params = {k: v for k, v in target_data.items() if k not in {"type", "connector_type"}}

        # Default port handling if missing and applicable
        if conn_type == "mysql" and "port" not in params:
            params["port"] = 3306
        elif conn_type == "postgres" and "port" not in params:
            params["port"] = 5432
        elif conn_type == "mongodb" and "port" not in params:
            params["port"] = 27017

        configs[target_name] = {
            "connector_type": conn_type,
            "connection_params": params,
        }

    return configs


def _env(key: str) -> str | None:
    """Returns the env var value only if explicitly set and non-empty, else None."""
    val = os.getenv(key)
    return val if val else None


def _target_key(target_name: str) -> str:
    """Convert a target name into its DB_TARGET_<KEY> env segment."""
    return re.sub(r"[^A-Za-z0-9]", "_", target_name).upper()


def _target_env(target_key: str, suffix: str) -> str | None:
    return _env(f"DB_TARGET_{target_key}_{suffix}")


def _target_env_default(target_key: str, suffix: str, default: str) -> str:
    return _target_env(target_key, suffix) or default


def _target_int_env(target_key: str, suffix: str, default: int) -> int:
    return int(_target_env(target_key, suffix) or default)


def _target_bool_env(target_key: str, suffix: str, default: bool = False) -> bool:
    val = _target_env(target_key, suffix)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes", "on"}


def _target_required(target_name: str, target_key: str, suffix: str) -> str:
    val = _target_env(target_key, suffix)
    if not val:
        raise ValueError(f"DB target '{target_name}' is missing DB_TARGET_{target_key}_{suffix}.")
    return val


def _infer_target_type(target_name: str) -> str | None:
    target_key = _target_key(target_name).lower()
    prefix_map = {
        "mysql": "mysql",
        "mariadb": "mysql",
        "postgres": "postgres",
        "postgresql": "postgres",
        "pg": "postgres",
        "mongodb": "mongodb",
        "mongo": "mongodb",
        "trino": "trino",
        "presto": "presto",
        "athena": "athena",
        "dynamodb": "dynamodb",
        "sqlite": "sqlite",
        "duckdb": "duckdb",
    }
    for prefix, connector_type in prefix_map.items():
        if target_key == prefix or target_key.startswith(f"{prefix}_"):
            return connector_type
    return None


def _target_type(target_name: str, target_key: str) -> str:
    configured_type = _target_env(target_key, "TYPE")
    if configured_type:
        return configured_type.lower()

    inferred_type = _infer_target_type(target_name)
    if inferred_type:
        logger.warning(
            "DB target '{}' is missing DB_TARGET_{}_TYPE; inferred connector type '{}'.",
            target_name,
            target_key,
            inferred_type,
        )
        return inferred_type

    raise ValueError(f"DB target '{target_name}' is missing DB_TARGET_{target_key}_TYPE.")


def _target_or_global(target_key: str, suffix: str, global_key: str) -> str | None:
    return _target_env(target_key, suffix) or _env(global_key)


def _json_env(value: str | None, default: dict | None = None) -> dict:
    if not value:
        return default or {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JSON env value must decode to an object.")
    return parsed


def _build_target_config(target_name: str) -> dict:
    target_key = _target_key(target_name)
    connector_type = _target_type(target_name, target_key)

    if connector_type == "mysql":
        return {
            "connector_type": "mysql",
            "connection_params": {
                "host": _target_required(target_name, target_key, "HOST"),
                "user": _target_env_default(target_key, "USER", "root"),
                "password": _target_env(target_key, "PASSWORD") or "",
                "port": _target_int_env(target_key, "PORT", 3306),
                "pool_size": _target_int_env(target_key, "POOL_SIZE", 5),
            },
        }

    if connector_type == "postgres":
        return {
            "connector_type": "postgres",
            "connection_params": {
                "host": _target_required(target_name, target_key, "HOST"),
                "port": _target_int_env(target_key, "PORT", 5432),
                "user": _target_env_default(target_key, "USER", "postgres"),
                "password": _target_env(target_key, "PASSWORD") or "",
                "database": (
                    _target_env(target_key, "DATABASE")
                    or _target_env(target_key, "DB")
                    or "postgres"
                ),
                "pool_size": _target_int_env(target_key, "POOL_SIZE", 5),
            },
        }

    if connector_type in {"trino", "presto"}:
        return {
            "connector_type": connector_type,
            "connection_params": {
                "host": _target_required(target_name, target_key, "HOST"),
                "port": _target_int_env(target_key, "PORT", 8080),
                "user": _target_env_default(target_key, "USER", connector_type),
                "password": _target_env(target_key, "PASSWORD"),
                "http_scheme": _target_env_default(target_key, "HTTP_SCHEME", "http"),
                "session_properties": _json_env(
                    _target_env(target_key, "SESSION_PROPERTIES"), {}
                ),
            },
        }

    if connector_type == "mongodb":
        return {
            "connector_type": "mongodb",
            "connection_params": {
                "host": _target_required(target_name, target_key, "HOST"),
                "port": _target_int_env(target_key, "PORT", 27017),
                "username": (
                    _target_env(target_key, "USERNAME")
                    or _target_env(target_key, "USER")
                ),
                "password": _target_env(target_key, "PASSWORD"),
                "authSource": (
                    _target_env(target_key, "AUTH_SOURCE")
                    or _target_env(target_key, "AUTHSOURCE")
                    or "admin"
                ),
                "tls": _target_bool_env(target_key, "TLS", False),
                "tlsAllowInvalidCertificates": _target_bool_env(
                    target_key, "TLS_ALLOW_INVALID", False
                ),
            },
        }

    if connector_type == "athena":
        return {
            "connector_type": "athena",
            "connection_params": {
                "catalog": _target_env_default(target_key, "CATALOG", "AwsDataCatalog"),
                "region": _target_required(target_name, target_key, "REGION"),
                "s3_output_location": _target_env(target_key, "S3_OUTPUT") or "",
                "aws_access_key_id": _target_or_global(
                    target_key, "AWS_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"
                ),
                "aws_secret_access_key": _target_or_global(
                    target_key, "AWS_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"
                ),
                "aws_session_token": _target_or_global(
                    target_key, "AWS_SESSION_TOKEN", "AWS_SESSION_TOKEN"
                ),
            },
        }

    if connector_type == "dynamodb":
        return {
            "connector_type": "dynamodb",
            "connection_params": {
                "region": _target_required(target_name, target_key, "REGION"),
                "aws_access_key_id": _target_or_global(
                    target_key, "AWS_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"
                ),
                "aws_secret_access_key": _target_or_global(
                    target_key, "AWS_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"
                ),
                "aws_session_token": _target_or_global(
                    target_key, "AWS_SESSION_TOKEN", "AWS_SESSION_TOKEN"
                ),
                "endpoint_url": _target_env(target_key, "ENDPOINT_URL"),
            },
        }

    if connector_type == "sqlite":
        return {
            "connector_type": "sqlite",
            "connection_params": {
                "database": _target_required(target_name, target_key, "DATABASE"),
            },
        }

    if connector_type == "duckdb":
        return {
            "connector_type": "duckdb",
            "connection_params": {
                "database": _target_env_default(target_key, "DATABASE", ":memory:"),
            },
        }

    raise ValueError(f"Unsupported DB target type '{connector_type}' for target '{target_name}'.")


def get_target_configurations() -> dict:
    targets_raw = _env("DB_TARGETS")
    if not targets_raw:
        return {}

    configs = {}
    target_names = [name.strip() for name in targets_raw.split(",") if name.strip()]
    for target_name in target_names:
        if target_name in configs:
            raise ValueError(f"Duplicate DB target name '{target_name}'.")
        configs[target_name] = _build_target_config(target_name)
    return configs


def get_db_configurations(config_file: Optional[str] = None) -> dict:
    """
    Builds active database configurations from YAML/JSON file and environment variables.
    Environment variables take precedence over file configurations with matching names.

    Supported formats:
      - irides.yaml / irides.json (targets section or flat targets)
      - Environment variables:
          DB_TARGETS=sales_mysql,analytics_pg
          DB_TARGET_SALES_MYSQL_TYPE=mysql
          DB_TARGET_SALES_MYSQL_HOST=...
    """
    file_configs = load_file_configurations(config_file)
    env_configs = get_target_configurations()
    configs = {**file_configs, **env_configs}
    logger.info(f"Active DB configurations: {list(configs.keys()) or 'none'}")
    return configs


