from typing import Any, Dict

import yaml

from .markdown import render_markdown


def render_okf(record: Dict[str, Any]) -> str:
    ai_documentation = record.get("ai_documentation") or {}
    frontmatter: Dict[str, Any] = {
        "type": "Database Table",
        "title": f"{record['schema_name']}.{record['table_name']}",
    }
    if ai_documentation.get("summary"):
        frontmatter["description"] = ai_documentation["summary"]
    if record.get("tags"):
        frontmatter["tags"] = record["tags"]
    frontmatter["generated"] = {
        "by": "irides/0.1.0",
        "at": record["updated_at"],
    }
    if record.get("status"):
        frontmatter["status"] = record["status"]
    frontmatter.update(
        {
            "config": record["config_name"],
            "instance": record["instance_name"],
            "schema": record["schema_name"],
            "table": record["table_name"],
        }
    )
    if record.get("owner"):
        frontmatter["owner"] = record["owner"]
    classification = record.get("classification") or record.get("data_classification")
    if classification:
        frontmatter["classification"] = classification
    if record.get("notes"):
        frontmatter["notes"] = record["notes"]

    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{yaml_text}\n---\n\n{render_markdown(record, okf_body=True)}"
