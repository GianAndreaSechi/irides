"""Typed command inputs, independent from argparse and core models."""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ScopeRequest:
    config_name: Optional[str] = None
    instance_name: Optional[str] = None
    no_cache: bool = False


@dataclass(frozen=True)
class TablesRequest(ScopeRequest):
    schema_name: Optional[str] = None
    limit: Optional[int] = None
    offset: Optional[int] = None


@dataclass(frozen=True)
class DescribeRequest(TablesRequest):
    table_name: Optional[str] = None
    generate_ai_docs: bool = False
    save_metadata: bool = True
    only_if_changed: bool = False
    export_markdown: bool = True
    export_okf: bool = True
    preformat: bool = True


@dataclass(frozen=True)
class PageRequest:
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class MetadataUpdateRequest:
    instance_name: str
    database_name: str
    table_name: str
    payload: Dict[str, Any]
