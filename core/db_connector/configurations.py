import copy
import os
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import dotenv_values, load_dotenv, set_key, unset_key
from loguru import logger
import yaml

SUPPORTED_CONNECTOR_TYPES = frozenset(
    {"mysql", "postgres", "mongodb", "trino", "presto", "athena", "dynamodb", "sqlite", "duckdb"}
)

_SECRET_PARAM_KEYS = {
    "password": "PASSWORD",
    "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "aws_session_token": "AWS_SESSION_TOKEN",
}

SUPPORTED_ENV_KEYS = frozenset(
    {
        "DB_TARGETS",
        "DB_CONFIG_FILE",
        "IRIDES_CONFIG_FILE",
        "IRIDES_API_KEY",
        "METADATA_STORE_TYPE",
        "STORAGE_METADATA_DIR",
        "STORAGE_EXPORT_DIR",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_DB",
        "REDIS_TTL_SECONDS",
        "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
        "REDIS_CACHE_SOCKET_TIMEOUT_SECONDS",
        "SCAN_RESULTS_TTL_SECONDS",
        "WORKER_HEARTBEAT_INTERVAL_SECONDS",
        "LITELLM_MODEL",
        "LITELLM_API_KEY",
        "LITELLM_API_BASE",
        "LITELLM_TIMEOUT_SECONDS",
        "LITELLM_MAX_RETRIES",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    }
)

_dotenv_loaded = False


def ensure_dotenv_loaded() -> None:
    """Lazily load .env or DB_CONFIG_FILE when environment configurations are queried."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _db_config_file = os.getenv("DB_CONFIG_FILE")
    if _db_config_file and not any(
        _db_config_file.lower().endswith(ext) for ext in (".yaml", ".yml", ".json")
    ):
        load_dotenv(dotenv_path=_db_config_file, override=True)
    else:
        default_env = Path.cwd() / ".env"
        if default_env.is_file():
            load_dotenv(dotenv_path=default_env, override=False)
    _dotenv_loaded = True


CONFIG_SEARCH_FILENAMES = ["irides.yaml", "irides.yml", "irides.json"]


def discover_config_file(custom_path: Optional[str] = None) -> Optional[Path]:
    """Finds an explicit or default irides configuration file."""
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Configuration file not found: {custom_path}")
        return p

    # Check environment variable
    env_file = os.getenv("IRIDES_CONFIG_FILE") or os.getenv("DB_CONFIG_FILE")
    if env_file and any(env_file.lower().endswith(ext) for ext in (".yaml", ".yml", ".json")):
        p = Path(env_file).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Configuration file specified in environment not found: {env_file}")
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
            has_default = match.group(2) is not None
            default_val = match.group(2) if has_default else ""
            val = os.getenv(var_name)
            if val is None and not has_default:
                logger.warning(f"Environment variable '${{{var_name}}}' is not set; expanding to empty string.")
                return ""
            return val if val is not None else default_val

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

    suffix = config_path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        if file_path:
            raise ValueError(
                f"Unsupported configuration file format '{suffix}' for '{config_path}'. Use .yaml, .yml, or .json."
            )
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            if suffix in {".yaml", ".yml"}:
                raw = yaml.safe_load(f)
            else:
                raw = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read config file {config_path}: {e}")
        raise ValueError(f"Failed to parse configuration file '{config_path}': {e}") from e

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration file '{config_path}' must contain a top-level mapping.")

    raw = _expand_env_vars(raw)
    targets_dict = raw.get("targets", raw)
    if not isinstance(targets_dict, dict):
        raise ValueError(f"'targets' in '{config_path}' must be a mapping.")

    configs = {}
    base_dir = config_path.parent
    for target_name, target_data in targets_dict.items():
        if not isinstance(target_data, dict):
            raise ValueError(f"Target '{target_name}' in '{config_path.name}' must be a mapping.")

        conn_type = target_data.get("type") or target_data.get("connector_type")
        if not conn_type:
            conn_type = _infer_target_type(target_name)
        if not conn_type:
            raise ValueError(f"Target '{target_name}' in '{config_path.name}' is missing 'type'.")

        conn_type = conn_type.lower()

        if "connection_params" in target_data and isinstance(target_data["connection_params"], dict):
            params = dict(target_data["connection_params"])
        else:
            params = {k: v for k, v in target_data.items() if k not in {"type", "connector_type"}}

        # Resolve relative SQLite/DuckDB file paths relative to the config file directory if they don't exist in cwd
        if conn_type in {"sqlite", "duckdb"} and isinstance(params.get("database"), str):
            db_val = params["database"]
            if db_val and "instance_name" not in params:
                params["instance_name"] = db_val
            if db_val and db_val != ":memory:" and not Path(db_val).is_absolute():
                cwd_candidate = Path.cwd() / db_val
                cfg_candidate = base_dir / db_val
                if not cwd_candidate.exists() and cfg_candidate.exists():
                    params["database"] = str(cfg_candidate.resolve())

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
    ensure_dotenv_loaded()
    targets_raw = _env("DB_TARGETS")
    if not targets_raw:
        return {}

    configs = {}
    seen_keys: Dict[str, str] = {}
    target_names = [name.strip() for name in targets_raw.split(",") if name.strip()]
    for target_name in target_names:
        if target_name in configs:
            raise ValueError(f"Duplicate DB target name '{target_name}'.")
        norm_key = _target_key(target_name)
        if norm_key in seen_keys:
            raise ValueError(
                f"DB target '{target_name}' collides with '{seen_keys[norm_key]}' "
                f"after environment key normalization ('DB_TARGET_{norm_key}_*')."
            )
        seen_keys[norm_key] = target_name
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
    ensure_dotenv_loaded()
    file_configs = load_file_configurations(config_file)
    env_configs = get_target_configurations()
    configs = {**file_configs, **env_configs}
    logger.info(f"Active DB configurations: {list(configs.keys()) or 'none'}")
    return configs


_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DB_TARGET_KEY_PATTERN = re.compile(r"^DB_TARGET_[A-Z0-9_]+$")


def is_supported_env_key(key: str) -> bool:
    """Return True if key is a recognized Irides or DB target environment variable."""
    return key in SUPPORTED_ENV_KEYS or bool(_DB_TARGET_KEY_PATTERN.match(key))


def is_secret_key(key: str) -> bool:
    """Return True if key appears to hold a password, secret, token, or API key."""
    upper = key.upper()
    return any(token in upper for token in ("PASSWORD", "SECRET", "TOKEN", "API_KEY"))


def _resolve_env_path(env_file: Optional[str | Path] = None) -> Path:
    return Path(env_file).expanduser().resolve() if env_file else (Path.cwd() / ".env")


def _ensure_private_env_file(env_path: Path) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        env_path.touch()
    try:
        env_path.chmod(0o600)
    except OSError:
        pass


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def set_env_variable(
    key: str,
    value: str,
    env_file: Optional[str | Path] = None,
    *,
    update_environ: bool = True,
    allow_custom: bool = False,
) -> Path:
    """Persist an environment variable to a .env file (with 0600 permissions) and optionally os.environ."""
    if not _ENV_KEY_PATTERN.match(key):
        raise ValueError(f"Invalid environment variable name '{key}'.")
    if not allow_custom and not is_supported_env_key(key):
        raise ValueError(
            f"Unsupported Irides environment variable '{key}'. "
            "Pass allow_custom=True (or --allow-custom) to set custom variables."
        )
    env_path = _resolve_env_path(env_file)
    _ensure_private_env_file(env_path)
    set_key(str(env_path), key, str(value), quote_mode="auto")
    _ensure_private_env_file(env_path)
    if update_environ:
        os.environ[key] = str(value)
    return env_path


def unset_env_variable(
    key: str,
    env_file: Optional[str | Path] = None,
    *,
    update_environ: bool = True,
) -> Path:
    """Remove an environment variable from a .env file and optionally os.environ."""
    if not _ENV_KEY_PATTERN.match(key):
        raise ValueError(f"Invalid environment variable name '{key}'.")
    env_path = _resolve_env_path(env_file)
    if env_path.is_file():
        unset_key(str(env_path), key)
        _ensure_private_env_file(env_path)
    if update_environ:
        os.environ.pop(key, None)
    return env_path


def get_env_variables(
    env_file: Optional[str | Path] = None,
    *,
    mask_secrets: bool = True,
) -> Dict[str, str]:
    """Return Irides-supported environment variables and keys from the target .env file."""
    env_path = _resolve_env_path(env_file)
    file_vals = dotenv_values(env_path) if env_path.is_file() else {}
    merged: Dict[str, str] = {
        k: v for k, v in os.environ.items() if is_supported_env_key(k)
    }
    for k, v in file_vals.items():
        if v is not None:
            merged[k] = os.environ.get(k, v)

    result: Dict[str, str] = {}
    for k in sorted(merged.keys()):
        val = merged[k]
        if mask_secrets and is_secret_key(k) and val != "":
            result[k] = "***"
        else:
            result[k] = val
    return result


def _validate_target_params(
    target_name: str, connector_type: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    if connector_type not in SUPPORTED_CONNECTOR_TYPES:
        raise ValueError(
            f"Unsupported DB target type '{connector_type}' for target '{target_name}'."
        )
    clean_params = {k: v for k, v in params.items() if v is not None and v != ""}
    if connector_type in {"mysql", "postgres", "mongodb", "trino", "presto"}:
        if "host" not in clean_params:
            raise ValueError(
                f"DB target '{target_name}' ({connector_type}) requires parameter 'host'."
            )
    elif connector_type in {"athena", "dynamodb"}:
        if "region" not in clean_params:
            raise ValueError(
                f"DB target '{target_name}' ({connector_type}) requires parameter 'region'."
            )
    elif connector_type == "sqlite":
        if "database" not in clean_params:
            raise ValueError(
                f"DB target '{target_name}' (sqlite) requires parameter 'database'."
            )
    elif connector_type == "duckdb":
        clean_params.setdefault("database", ":memory:")

    if "port" in clean_params:
        clean_params["port"] = int(clean_params["port"])
    if "pool_size" in clean_params:
        clean_params["pool_size"] = int(clean_params["pool_size"])
    return clean_params


_PARAM_TO_ENV_SUFFIX = {
    "host": "HOST",
    "port": "PORT",
    "user": "USER",
    "username": "USERNAME",
    "password": "PASSWORD",
    "database": "DATABASE",
    "db": "DB",
    "pool_size": "POOL_SIZE",
    "region": "REGION",
    "catalog": "CATALOG",
    "s3_output": "S3_OUTPUT",
    "s3_output_location": "S3_OUTPUT",
    "endpoint_url": "ENDPOINT_URL",
    "authSource": "AUTH_SOURCE",
    "auth_source": "AUTH_SOURCE",
    "tls": "TLS",
    "tlsAllowInvalidCertificates": "TLS_ALLOW_INVALID",
    "tls_allow_invalid": "TLS_ALLOW_INVALID",
    "http_scheme": "HTTP_SCHEME",
    "session_properties": "SESSION_PROPERTIES",
    "aws_access_key_id": "AWS_ACCESS_KEY_ID",
    "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "aws_session_token": "AWS_SESSION_TOKEN",
}


def _resolve_writable_config_path(
    config_file: Optional[str | Path], fmt: str
) -> Path:
    if config_file:
        return Path(config_file).expanduser().resolve()
    cwd = Path.cwd()
    for name in CONFIG_SEARCH_FILENAMES:
        candidate = cwd / name
        if candidate.is_file():
            return candidate
    return cwd / ("irides.json" if fmt == "json" else "irides.yaml")


def _load_raw_config_doc(cfg_path: Path) -> Dict[str, Any]:
    if not cfg_path.is_file():
        return {"targets": {}}
    suffix = cfg_path.suffix.lower()
    with open(cfg_path, "r", encoding="utf-8") as f:
        if suffix == ".json":
            raw = json.load(f)
        elif suffix in {".yaml", ".yml"}:
            raw = yaml.safe_load(f)
        else:
            raise ValueError(
                f"Unsupported configuration file format '{suffix}' for '{cfg_path}'. Use .yaml, .yml, or .json."
            )
    if raw is None:
        return {"targets": {}}
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration file '{cfg_path}' must contain a top-level mapping.")
    if "targets" in raw:
        if not isinstance(raw["targets"], dict):
            raise ValueError(f"'targets' in '{cfg_path}' must be a mapping.")
        return raw
    return {"targets": dict(raw)}


def _dump_raw_config_doc(cfg_path: Path, data: Dict[str, Any]) -> None:
    if cfg_path.suffix.lower() == ".json":
        content = json.dumps(data, indent=2) + "\n"
    else:
        content = yaml.safe_dump(data, sort_keys=False)
    _atomic_write_text(cfg_path, content)


def save_target_configuration(
    target_name: str,
    connector_type: str,
    params: Dict[str, Any],
    *,
    fmt: str = "yaml",
    config_file: Optional[str | Path] = None,
    env_file: Optional[str | Path] = None,
    secrets_to_env: bool = True,
    update_environ: bool = True,
) -> Dict[str, Any]:
    """Create or update a database target in irides.yaml/.json or .env."""
    if not isinstance(target_name, str) or not target_name.strip() or "," in target_name:
        raise ValueError(
            "Target name must be a non-empty string without commas."
        )
    norm_type = connector_type.strip().lower()
    norm_fmt = fmt.strip().lower()
    if norm_fmt not in {"yaml", "json", "env"}:
        raise ValueError(f"Unsupported format '{fmt}'. Expected 'yaml', 'json', or 'env'.")

    clean_params = _validate_target_params(target_name, norm_type, params)
    env_path = _resolve_env_path(env_file)
    target_key = _target_key(target_name)
    written_env_keys: List[str] = []

    if norm_fmt == "env":
        existing_raw = (
            dotenv_values(env_path).get("DB_TARGETS") if env_path.is_file() else None
        ) or os.getenv("DB_TARGETS", "")
        existing_targets = [t.strip() for t in existing_raw.split(",") if t.strip()]
        for other in existing_targets:
            if other != target_name and _target_key(other) == target_key:
                raise ValueError(
                    f"DB target '{target_name}' collides with '{other}' "
                    f"after environment key normalization ('DB_TARGET_{target_key}_*')."
                )
        if target_name not in existing_targets:
            existing_targets.append(target_name)

        set_env_variable(
            "DB_TARGETS",
            ",".join(existing_targets),
            env_path,
            update_environ=update_environ,
        )
        written_env_keys.append("DB_TARGETS")

        type_var = f"DB_TARGET_{target_key}_TYPE"
        set_env_variable(type_var, norm_type, env_path, update_environ=update_environ)
        written_env_keys.append(type_var)

        for k, v in clean_params.items():
            suffix = _PARAM_TO_ENV_SUFFIX.get(k, _target_key(k))
            env_var = f"DB_TARGET_{target_key}_{suffix}"
            if isinstance(v, dict):
                str_val = json.dumps(v)
            elif v is True:
                str_val = "true"
            elif v is False:
                str_val = "false"
            else:
                str_val = str(v)
            set_env_variable(env_var, str_val, env_path, update_environ=update_environ)
            written_env_keys.append(env_var)

        return {
            "status": "saved",
            "target": target_name,
            "format": "env",
            "config_file": None,
            "env_file": str(env_path),
            "env_keys": written_env_keys,
        }

    cfg_path = _resolve_writable_config_path(config_file, norm_fmt)
    data = _load_raw_config_doc(cfg_path)
    entry: Dict[str, Any] = {"type": norm_type}
    for k, v in clean_params.items():
        if (
            secrets_to_env
            and k in _SECRET_PARAM_KEYS
            and isinstance(v, str)
            and not (v.startswith("${") and v.endswith("}"))
        ):
            env_var = f"DB_TARGET_{target_key}_{_SECRET_PARAM_KEYS[k]}"
            set_env_variable(env_var, v, env_path, update_environ=update_environ)
            written_env_keys.append(env_var)
            entry[k] = f"${{{env_var}}}"
        else:
            entry[k] = v

    data["targets"][target_name] = entry
    _dump_raw_config_doc(cfg_path, data)
    actual_fmt = "json" if cfg_path.suffix.lower() == ".json" else "yaml"
    return {
        "status": "saved",
        "target": target_name,
        "format": actual_fmt,
        "config_file": str(cfg_path),
        "env_file": str(env_path) if written_env_keys else None,
        "env_keys": written_env_keys,
    }


def remove_target_configuration(
    target_name: str,
    *,
    fmt: Optional[str] = None,
    config_file: Optional[str | Path] = None,
    env_file: Optional[str | Path] = None,
    update_environ: bool = True,
) -> Dict[str, Any]:
    """Remove a database target from irides.yaml/.json and/or .env."""
    if fmt is not None:
        norm_fmt = fmt.strip().lower()
        if norm_fmt not in {"yaml", "json", "env"}:
            raise ValueError(f"Unsupported format '{fmt}'. Expected 'yaml', 'json', or 'env'.")
    else:
        norm_fmt = None

    removed_from: List[str] = []

    if norm_fmt in (None, "yaml", "json"):
        cfg_path = discover_config_file(str(config_file) if config_file else None)
        if cfg_path and cfg_path.is_file():
            data = _load_raw_config_doc(cfg_path)
            if target_name in data["targets"]:
                del data["targets"][target_name]
                _dump_raw_config_doc(cfg_path, data)
                removed_from.append(str(cfg_path))

    if norm_fmt in (None, "env"):
        env_path = _resolve_env_path(env_file)
        target_key = _target_key(target_name)
        prefix = f"DB_TARGET_{target_key}_"

        if env_path.is_file():
            file_vals = dotenv_values(env_path)
            file_targets_raw = file_vals.get("DB_TARGETS") or ""
            file_targets = [t.strip() for t in file_targets_raw.split(",") if t.strip()]
            file_matching = [k for k in file_vals.keys() if k.startswith(prefix)]
            if target_name in file_targets or file_matching:
                remaining = [t for t in file_targets if t != target_name]
                if remaining:
                    set_env_variable(
                        "DB_TARGETS",
                        ",".join(remaining),
                        env_path,
                        update_environ=update_environ,
                    )
                elif "DB_TARGETS" in file_vals:
                    unset_env_variable("DB_TARGETS", env_path, update_environ=update_environ)
                for k in file_matching:
                    unset_env_variable(k, env_path, update_environ=update_environ)
                removed_from.append(str(env_path))

        if update_environ:
            env_targets_raw = os.getenv("DB_TARGETS", "")
            env_targets = [t.strip() for t in env_targets_raw.split(",") if t.strip()]
            env_matching = [k for k in list(os.environ.keys()) if k.startswith(prefix)]
            if target_name in env_targets or env_matching:
                remaining_env = [t for t in env_targets if t != target_name]
                if remaining_env:
                    os.environ["DB_TARGETS"] = ",".join(remaining_env)
                elif "DB_TARGETS" in os.environ and target_name in env_targets:
                    os.environ.pop("DB_TARGETS", None)
                for k in env_matching:
                    os.environ.pop(k, None)
                if str(env_path) not in removed_from:
                    removed_from.append("environ")

    if not removed_from:
        raise ValueError(f"Target '{target_name}' not found.")

    return {
        "status": "removed",
        "target": target_name,
        "removed_from": removed_from,
    }


def mask_configurations(configs: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of resolved configurations with secret fields masked."""
    masked = copy.deepcopy(configs)
    for target_cfg in masked.values():
        if not isinstance(target_cfg, dict):
            continue
        params = target_cfg.get("connection_params")
        if not isinstance(params, dict):
            continue
        for key, val in list(params.items()):
            if (key in _SECRET_PARAM_KEYS or is_secret_key(key)) and val not in (None, ""):
                params[key] = "***"
        hosts = params.get("hosts")
        if isinstance(hosts, list):
            for host_cfg in hosts:
                if not isinstance(host_cfg, dict):
                    continue
                for key, val in list(host_cfg.items()):
                    if (key in _SECRET_PARAM_KEYS or is_secret_key(key)) and val not in (None, ""):
                        host_cfg[key] = "***"
    return masked


