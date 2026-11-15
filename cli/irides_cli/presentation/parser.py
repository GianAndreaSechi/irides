"""Argparse command definitions; no business logic belongs here."""

import argparse

from core.db_connector.configurations import SUPPORTED_CONNECTOR_TYPES


def _add_scope_arguments(parser: argparse.ArgumentParser, *, table: bool = False) -> None:
    parser.add_argument(
        "-t", "--target", "--config", dest="config_name", help="Configured database target name"
    )
    parser.add_argument("--instance", dest="instance_name", help="Database instance")
    if table:
        parser.add_argument("--schema", dest="schema_name", help="Schema/database name")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the Redis cache")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="irides",
        description="Inspect databases and generate Git-ready documentation through Irides core.",
    )
    parser.add_argument("--version", action="version", version="irides 0.1.3")
    parser.add_argument(
        "-e", "--env-file", dest="env_file", help="Path to .env file to load variables from"
    )
    parser.add_argument(
        "-c",
        "--config-file",
        dest="config_file",
        help="Path to YAML/JSON configuration file (e.g. irides.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser(
        "init", help="Initialize a template configuration file (irides.yaml or .env)"
    )
    init_cmd.add_argument(
        "-f",
        "--format",
        choices=["yaml", "env"],
        default="yaml",
        help="Config format: yaml (default) or env",
    )
    init_cmd.add_argument(
        "--force", action="store_true", help="Overwrite existing configuration file"
    )

    subparsers.add_parser("configurations", help="List active configurations")

    connect = subparsers.add_parser("connect", help="Test a configuration")
    connect.add_argument("config_name", metavar="TARGET", help="Database target name to connect to")

    instances = subparsers.add_parser("instances", help="List instances")
    instances.add_argument(
        "-t", "--target", "--config", dest="config_name", help="Configured database target name"
    )
    instances.add_argument("--no-cache", action="store_true")

    schemas = subparsers.add_parser("schemas", help="List schemas")
    _add_scope_arguments(schemas)

    tables = subparsers.add_parser("tables", help="List tables")
    _add_scope_arguments(tables, table=True)
    tables.add_argument("--limit", type=int)
    tables.add_argument("--offset", type=int)

    describe = subparsers.add_parser("describe", help="Describe tables and optionally save metadata")
    _add_scope_arguments(describe, table=True)
    describe.add_argument("--table", dest="table_name")
    describe.add_argument("--generate-ai-docs", action="store_true")
    describe.add_argument(
        "--no-save-metadata", dest="save_metadata", action="store_false", default=True
    )
    describe.add_argument("--only-if-changed", action="store_true")
    describe.add_argument(
        "--no-export-markdown",
        dest="export_markdown",
        action="store_false",
        default=True,
        help="Do not generate the default Markdown export",
    )
    describe.add_argument(
        "--save-markdown", dest="export_markdown", action="store_true", help=argparse.SUPPRESS
    )
    describe.add_argument(
        "--no-export-okf",
        dest="export_okf",
        action="store_false",
        default=True,
        help="Do not generate the default OKF bundle",
    )
    describe.add_argument(
        "--no-preformat",
        dest="preformat",
        action="store_false",
        default=True,
        help="Include column defaults and non-unique indexes in exported documents",
    )

    metadata = subparsers.add_parser("metadata", help="Read or update stored metadata")
    metadata_sub = metadata.add_subparsers(dest="metadata_command", required=True)
    for name in ("instances", "databases", "tables"):
        command = metadata_sub.add_parser(name)
        if name != "instances":
            command.add_argument("instance")
        if name == "tables":
            command.add_argument("database")
        command.add_argument(
            "-t", "--target", "--config", dest="config_name", help="Filter by configuration target"
        )
        command.add_argument("--page", type=int, default=1)
        command.add_argument("--page-size", type=int, default=20)

    get = metadata_sub.add_parser("get")
    get.add_argument("instance")
    get.add_argument("database")
    get.add_argument("table")
    get.add_argument(
        "-t", "--target", "--config", dest="config_name", help="Configuration target name"
    )

    update = metadata_sub.add_parser("update")
    update.add_argument("instance")
    update.add_argument("database")
    update.add_argument("table")
    update.add_argument("payload", help="JSON object to merge into the metadata")
    update.add_argument(
        "-t", "--target", "--config", dest="config_name", help="Configuration target name"
    )

    export_cmd = metadata_sub.add_parser(
        "export", help="Regenerate Markdown/OKF exports from stored metadata offline"
    )
    export_cmd.add_argument(
        "-t", "--target", "--config", dest="config_name", help="Filter by configuration target"
    )
    export_cmd.add_argument(
        "--no-export-markdown", dest="export_markdown", action="store_false", default=True
    )
    export_cmd.add_argument(
        "--no-export-okf", dest="export_okf", action="store_false", default=True
    )
    export_cmd.add_argument(
        "--no-preformat", dest="preformat", action="store_false", default=True
    )

    manifest_cmd = subparsers.add_parser(
        "manifest", help="Validate project database manifests (database.md / YAML) and build backlinks"
    )
    manifest_sub = manifest_cmd.add_subparsers(dest="manifest_command", required=True)
    validate_cmd = manifest_sub.add_parser(
        "validate", help="Validate a project manifest against stored metadata"
    )
    validate_cmd.add_argument("manifest_path", help="Path to database.md, YAML, or JSON manifest")
    validate_cmd.add_argument(
        "--require-owner",
        action="store_true",
        help="Fail validation if any referenced catalog resource lacks an owner",
    )

    links_cmd = manifest_sub.add_parser(
        "links", help="Build reverse links from catalog resources to one or more project manifests"
    )
    links_cmd.add_argument(
        "manifest_paths", nargs="+", help="One or more paths to database.md, YAML, or JSON manifests"
    )

    config_cmd = subparsers.add_parser(
        "config", help="Manage Irides environment variables and database targets"
    )
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)

    set_env_cmd = config_sub.add_parser("set-env", help="Set an environment variable in .env")
    set_env_cmd.add_argument("key", help="Environment variable name")
    set_env_cmd.add_argument("value", help="Environment variable value")
    set_env_cmd.add_argument(
        "--allow-custom",
        action="store_true",
        help="Allow setting variables outside the Irides supported key list",
    )

    unset_env_cmd = config_sub.add_parser(
        "unset-env", help="Remove an environment variable from .env"
    )
    unset_env_cmd.add_argument("key", help="Environment variable name")

    list_env_cmd = config_sub.add_parser(
        "list-env", help="List Irides environment variables from .env and process env"
    )
    list_env_cmd.add_argument(
        "--show-secrets",
        action="store_true",
        help="Show unmasked secret values",
    )

    set_target_cmd = config_sub.add_parser(
        "set-target", help="Create or update a database target in irides.yaml/.json or .env"
    )
    set_target_cmd.add_argument("target_name", help="Target configuration name")
    set_target_cmd.add_argument(
        "--type",
        required=True,
        choices=sorted(SUPPORTED_CONNECTOR_TYPES),
        help="Database connector type",
    )
    set_target_cmd.add_argument(
        "--format",
        choices=["yaml", "json", "env"],
        default="yaml",
        help="Storage format: yaml (default), json, or env",
    )
    set_target_cmd.add_argument(
        "--inline-secrets",
        action="store_true",
        help="Keep passwords/secrets inline in YAML/JSON instead of storing them in .env",
    )
    set_target_cmd.add_argument("--host", help="Database host or URI")
    set_target_cmd.add_argument("--port", type=int, help="Database port")
    set_target_cmd.add_argument("--user", help="Database username")
    set_target_cmd.add_argument("--password", help="Database password")
    set_target_cmd.add_argument("--database", help="Database name or file path")
    set_target_cmd.add_argument("--region", help="AWS region (Athena / DynamoDB)")
    set_target_cmd.add_argument("--catalog", help="Glue catalog name (Athena)")
    set_target_cmd.add_argument("--s3-output", dest="s3_output", help="S3 output URI (Athena)")
    set_target_cmd.add_argument("--endpoint-url", dest="endpoint_url", help="Custom endpoint URL")
    set_target_cmd.add_argument("--auth-source", dest="auth_source", help="MongoDB authSource")
    set_target_cmd.add_argument("--http-scheme", dest="http_scheme", help="Trino/Presto HTTP scheme")
    set_target_cmd.add_argument("--pool-size", dest="pool_size", type=int, help="Connection pool size")
    set_target_cmd.add_argument("--tls", action="store_true", help="Enable TLS")
    set_target_cmd.add_argument(
        "--tls-allow-invalid",
        dest="tls_allow_invalid",
        action="store_true",
        help="Allow invalid TLS certificates",
    )
    set_target_cmd.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional connection parameter (repeatable)",
    )

    remove_target_cmd = config_sub.add_parser(
        "remove-target", help="Remove a database target from irides.yaml/.json and/or .env"
    )
    remove_target_cmd.add_argument("target_name", help="Target configuration name")
    remove_target_cmd.add_argument(
        "--format",
        choices=["yaml", "json", "env"],
        default=None,
        help="Limit removal to a specific format",
    )

    show_cfg_cmd = config_sub.add_parser(
        "show", help="Show resolved target configurations"
    )
    show_cfg_cmd.add_argument(
        "--show-secrets",
        action="store_true",
        help="Show unmasked secret values",
    )
    return parser
