"""Controller for managing Irides environment variables and database targets."""

import json
from typing import Any, Dict

from core.db_connector.configurations import (
    get_db_configurations,
    get_env_variables,
    mask_configurations,
    remove_target_configuration,
    save_target_configuration,
    set_env_variable,
    unset_env_variable,
)


class ConfigController:
    """Handles 'irides config ...' subcommands."""

    def execute(self, args: Any) -> Dict[str, Any]:
        cmd = args.config_command

        if cmd == "set-env":
            path = set_env_variable(
                args.key,
                args.value,
                env_file=args.env_file,
                allow_custom=bool(args.allow_custom),
            )
            return {
                "status": "saved",
                "key": args.key,
                "env_file": str(path),
            }

        if cmd == "unset-env":
            path = unset_env_variable(args.key, env_file=args.env_file)
            return {
                "status": "removed",
                "key": args.key,
                "env_file": str(path),
            }

        if cmd == "list-env":
            return get_env_variables(
                env_file=args.env_file,
                mask_secrets=not bool(args.show_secrets),
            )

        if cmd == "set-target":
            params = self._collect_target_params(args)
            return save_target_configuration(
                args.target_name,
                args.type,
                params,
                fmt=args.format,
                config_file=args.config_file,
                env_file=args.env_file,
                secrets_to_env=not bool(args.inline_secrets),
            )

        if cmd == "remove-target":
            return remove_target_configuration(
                args.target_name,
                fmt=args.format,
                config_file=args.config_file,
                env_file=args.env_file,
            )

        if cmd == "show":
            configs = get_db_configurations(config_file=args.config_file)
            return configs if args.show_secrets else mask_configurations(configs)

        raise ValueError(f"Unsupported config command: {cmd}")

    @staticmethod
    def _parse_param_value(key: str, raw: str) -> Any:
        lowered = raw.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if key == "session_properties" and raw.lstrip().startswith("{"):
            return json.loads(raw)
        return raw

    def _collect_target_params(self, args: Any) -> Dict[str, Any]:
        conn_type = args.type.strip().lower()
        params: Dict[str, Any] = {}

        if getattr(args, "host", None) is not None:
            params["host"] = args.host
        if getattr(args, "port", None) is not None:
            params["port"] = args.port
        if getattr(args, "user", None) is not None:
            key = "username" if conn_type == "mongodb" else "user"
            params[key] = args.user
        if getattr(args, "password", None) is not None:
            params["password"] = args.password
        if getattr(args, "database", None) is not None:
            params["database"] = args.database
        if getattr(args, "region", None) is not None:
            params["region"] = args.region
        if getattr(args, "catalog", None) is not None:
            params["catalog"] = args.catalog
        if getattr(args, "s3_output", None) is not None:
            params["s3_output_location"] = args.s3_output
        if getattr(args, "endpoint_url", None) is not None:
            params["endpoint_url"] = args.endpoint_url
        if getattr(args, "auth_source", None) is not None:
            params["authSource"] = args.auth_source
        if getattr(args, "http_scheme", None) is not None:
            params["http_scheme"] = args.http_scheme
        if getattr(args, "pool_size", None) is not None:
            params["pool_size"] = args.pool_size
        if getattr(args, "tls", False):
            params["tls"] = True
        if getattr(args, "tls_allow_invalid", False):
            params["tlsAllowInvalidCertificates"] = True

        for item in getattr(args, "param", []) or []:
            if "=" not in item:
                raise ValueError(f"Invalid --param '{item}': expected KEY=VALUE.")
            k, v = item.split("=", 1)
            k = k.strip()
            if not k:
                raise ValueError(f"Invalid --param '{item}': empty key.")
            params[k] = self._parse_param_value(k, v)

        return params
