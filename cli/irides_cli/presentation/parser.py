"""Argparse command definitions; no business logic belongs here."""

import argparse


def _add_scope_arguments(parser: argparse.ArgumentParser, *, table: bool = False) -> None:
    parser.add_argument("--config", dest="config_name", help="Configured database target")
    parser.add_argument("--instance", dest="instance_name", help="Database instance")
    if table: parser.add_argument("--schema", dest="schema_name", help="Schema/database name")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the Redis cache")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irides", description="Inspect databases through Iride core, without the API service.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("configurations", help="List active configurations")
    connect = subparsers.add_parser("connect", help="Test a configuration"); connect.add_argument("config_name")
    instances = subparsers.add_parser("instances", help="List instances"); instances.add_argument("--config", dest="config_name"); instances.add_argument("--no-cache", action="store_true")
    schemas = subparsers.add_parser("schemas", help="List schemas"); _add_scope_arguments(schemas)
    tables = subparsers.add_parser("tables", help="List tables"); _add_scope_arguments(tables, table=True); tables.add_argument("--limit", type=int); tables.add_argument("--offset", type=int)
    describe = subparsers.add_parser("describe", help="Describe tables and optionally save metadata")
    _add_scope_arguments(describe, table=True); describe.add_argument("--table", dest="table_name")
    describe.add_argument("--generate-ai-docs", action="store_true"); describe.add_argument("--no-save-metadata", dest="save_metadata", action="store_false", default=True); describe.add_argument("--only-if-changed", action="store_true")
    describe.add_argument("--no-export-markdown", dest="export_markdown", action="store_false", default=True, help="Do not generate the default Markdown export")
    describe.add_argument("--save-markdown", dest="export_markdown", action="store_true", help=argparse.SUPPRESS)
    describe.add_argument("--no-export-okf", dest="export_okf", action="store_false", default=True, help="Do not generate the default OKF bundle")
    describe.add_argument("--no-preformat", dest="preformat", action="store_false", default=True, help="Export the full metadata instead of the essential view")
    metadata = subparsers.add_parser("metadata", help="Read or update stored metadata"); metadata_sub = metadata.add_subparsers(dest="metadata_command", required=True)
    for name in ("instances", "databases", "tables"):
        command = metadata_sub.add_parser(name)
        if name != "instances": command.add_argument("instance")
        if name == "tables": command.add_argument("database")
        command.add_argument("--page", type=int, default=1); command.add_argument("--page-size", type=int, default=20)
    get = metadata_sub.add_parser("get"); get.add_argument("instance"); get.add_argument("database"); get.add_argument("table")
    update = metadata_sub.add_parser("update"); update.add_argument("instance"); update.add_argument("database"); update.add_argument("table"); update.add_argument("payload", help="JSON object to merge into the metadata")
    return parser
