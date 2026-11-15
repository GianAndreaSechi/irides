from typing import Any, Dict

_KNOWN_KEYS = frozenset(
    {
        "metadata_key",
        "config_name",
        "instance_name",
        "schema_name",
        "table_name",
        "updated_at",
        "schema_description",
        "ai_documentation",
        "owner",
        "tags",
        "status",
        "notes",
        "classification",
        "data_classification",
    }
)


def _escape(value: Any) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")


def _column_description(column: Dict[str, Any], ai_descriptions: Dict[str, str]) -> str:
    return str(
        column.get("description")
        or ai_descriptions.get(column.get("name"), "")
        or column.get("comment")
        or ""
    )


def render_markdown(record: Dict[str, Any], *, okf_body: bool = False) -> str:
    schema = record.get("schema_description") or {}
    ai_documentation = record.get("ai_documentation") or {}
    ai_descriptions = ai_documentation.get("column_descriptions") or {}
    heading = "#" if okf_body else "##"
    lines = [] if okf_body else [f"# {record['schema_name']}.{record['table_name']}"]

    if not okf_body:
        lines.extend(
            [
                "",
                "## Source",
                "",
                f"- Configuration: `{record['config_name']}`",
                f"- Instance: `{record['instance_name']}`",
                f"- Schema: `{record['schema_name']}`",
                f"- Table: `{record['table_name']}`",
                f"- Metadata updated: `{record['updated_at']}`",
            ]
        )

    governance_lines = []
    if record.get("owner"):
        governance_lines.append(f"- Owner: `{record['owner']}`")
    if record.get("status"):
        governance_lines.append(f"- Status: `{record['status']}`")
    classification = record.get("classification") or record.get("data_classification")
    if classification:
        governance_lines.append(f"- Classification: `{classification}`")
    if record.get("tags"):
        tags_val = record["tags"]
        tags_str = ", ".join(f"`{t}`" for t in tags_val) if isinstance(tags_val, list) else f"`{tags_val}`"
        governance_lines.append(f"- Tags: {tags_str}")
    for key, val in record.items():
        if key not in _KNOWN_KEYS and not key.startswith("_") and val not in (None, "", [], {}):
            governance_lines.append(f"- {key}: `{val}`")

    if governance_lines:
        lines.extend(["", f"{heading} Governance", ""] + governance_lines)

    if ai_documentation.get("summary"):
        lines.extend(["", f"{heading} Description", "", str(ai_documentation["summary"])])

    if record.get("notes"):
        lines.extend(["", f"{heading} Notes", "", str(record["notes"])])

    columns = schema.get("columns") or []
    if columns:
        show_defaults = any(col.get("default_value") is not None for col in columns)
        if show_defaults:
            lines.extend(
                [
                    "",
                    f"{heading} Schema" if okf_body else f"{heading} Columns",
                    "",
                    "| Name | Type | Nullable | Default | Description |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for column in columns:
                lines.append(
                    "| {name} | {data_type} | {nullable} | {default} | {description} |".format(
                        name=_escape(column.get("name")),
                        data_type=_escape(column.get("data_type")),
                        nullable=_escape(column.get("is_nullable")),
                        default=_escape(column.get("default_value")),
                        description=_escape(_column_description(column, ai_descriptions)),
                    )
                )
        else:
            lines.extend(
                [
                    "",
                    f"{heading} Schema" if okf_body else f"{heading} Columns",
                    "",
                    "| Name | Type | Nullable | Description |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for column in columns:
                lines.append(
                    "| {name} | {data_type} | {nullable} | {description} |".format(
                        name=_escape(column.get("name")),
                        data_type=_escape(column.get("data_type")),
                        nullable=_escape(column.get("is_nullable")),
                        description=_escape(_column_description(column, ai_descriptions)),
                    )
                )

    primary_key = schema.get("primary_key") or {}
    key_columns = primary_key.get("column_names", []) if isinstance(primary_key, dict) else []
    sort_key = schema.get("sort_key")
    foreign_keys = schema.get("foreign_keys") or []
    if key_columns or sort_key or foreign_keys:
        lines.extend(["", f"{heading} Keys and Relationships", ""])
        if key_columns:
            lines.append("- Primary key: " + ", ".join(f"`{column}`" for column in key_columns))
        if sort_key:
            lines.append(f"- Sort key: `{sort_key}`")
        for key in foreign_keys:
            ref_schema = key.get("referenced_schema")
            ref_table = key.get("referenced_table")
            if ref_schema and ref_schema != record.get("schema_name"):
                target_table = f"{ref_schema}.{ref_table}"
            else:
                target_table = str(ref_table)
            lines.append(
                f"- `{key.get('column_name')}` -> "
                f"`{target_table}.{key.get('referenced_column')}`"
            )

    indexes = schema.get("indexes") or []
    if indexes:
        lines.extend(["", f"{heading} Indexes", ""])
        for index in indexes:
            columns_text = ", ".join(f"`{column}`" for column in index.get("column_names", []))
            unique = " unique" if index.get("is_unique") else ""
            idx_type = f" ({index['type']})" if index.get("type") in ("GSI", "LSI") else ""
            lines.append(f"- `{index.get('name')}`{idx_type}:{unique} {columns_text}")

    partitions = schema.get("partitions") or []
    if partitions:
        lines.extend(["", f"{heading} Partitions", ""])
        for partition in partitions:
            lines.append(
                f"- `{partition.get('column_name')}` ({partition.get('data_type')})"
            )

    return "\n".join(lines).lstrip("\n") + "\n"
