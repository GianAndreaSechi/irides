from typing import Any, Dict

_SYSTEM_KEYS = frozenset(
    {
        "metadata_key",
        "config_name",
        "instance_name",
        "schema_name",
        "table_name",
        "updated_at",
        "schema_description",
        "ai_documentation",
    }
)


def essential_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return the compact, deterministic view used by the default exporters."""
    schema = record.get("schema_description") or {}
    ai_documentation = record.get("ai_documentation") or {}
    ai_descriptions = ai_documentation.get("column_descriptions") or {}

    columns = []
    for column in schema.get("columns") or []:
        description = ai_descriptions.get(column.get("name")) or column.get("comment")
        compact_column = {
            "name": column.get("name"),
            "data_type": column.get("data_type"),
            "is_nullable": column.get("is_nullable"),
        }
        if description:
            compact_column["description"] = description
        columns.append(compact_column)

    compact_schema = {
        "instance_name": schema.get("instance_name"),
        "schema_name": schema.get("schema_name"),
        "table_name": schema.get("table_name"),
        "columns": columns,
        "primary_key": schema.get("primary_key"),
        "sort_key": schema.get("sort_key"),
        "foreign_keys": schema.get("foreign_keys") or [],
        "indexes": [
            index
            for index in schema.get("indexes") or []
            if (index.get("is_unique") and not index.get("is_primary"))
            or index.get("type") in ("GSI", "LSI")
        ],
        "partitions": schema.get("partitions") or [],
    }

    compact: Dict[str, Any] = {}
    for key in (
        "metadata_key",
        "config_name",
        "instance_name",
        "schema_name",
        "table_name",
        "updated_at",
        "owner",
        "tags",
        "status",
        "notes",
        "classification",
        "data_classification",
    ):
        if record.get(key) not in (None, "", [], {}):
            compact[key] = record.get(key)

    # Carry forward any additional custom user annotations
    for key, value in record.items():
        if (
            key not in _SYSTEM_KEYS
            and key not in compact
            and not key.startswith("_")
            and value not in (None, "", [], {})
        ):
            compact[key] = value

    compact["schema_description"] = {
        key: value
        for key, value in compact_schema.items()
        if value not in (None, "", [], {})
    }
    if ai_documentation.get("summary"):
        compact["ai_documentation"] = {"summary": ai_documentation["summary"]}
    return compact
