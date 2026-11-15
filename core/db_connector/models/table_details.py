from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .column import Column


class PrimaryKey(BaseModel):
    """Represents a primary key constraint."""
    column_names: List[str]


class ForeignKey(BaseModel):
    """Represents a foreign key constraint."""
    column_name: str
    referenced_table: str
    referenced_column: str
    referenced_schema: Optional[str] = None
    constraint_name: Optional[str] = None
    ordinal_position: Optional[int] = None


class Index(BaseModel):
    """Represents an index on a table."""
    name: str
    column_names: List[str]
    is_unique: bool
    is_primary: bool  # True if this index is also the primary key
    type: Optional[str] = None  # e.g., 'BTREE', 'HASH', 'GSI', 'LSI'


class Partition(BaseModel):
    """Represents a partition key column of a table."""
    column_name: str
    data_type: str
    comment: Optional[str] = None


class TableDescription(BaseModel):
    """
    A comprehensive description of a database table, including columns,
    primary keys, foreign keys, indexes, and partition keys.

    sort_key is used by key-value stores (e.g. DynamoDB) where a range/sort key
    coexists with the partition key to form the composite primary key.
    """
    config_name: Optional[str] = None
    instance_name: str
    schema_name: str
    table_name: str
    columns: List[Column]
    primary_key: Optional[PrimaryKey] = None
    sort_key: Optional[str] = None
    foreign_keys: List[ForeignKey] = Field(default_factory=list)
    indexes: List[Index] = Field(default_factory=list)
    partitions: List[Partition] = Field(default_factory=list)
    ai_documentation: Optional[Dict[str, Any]] = None
    ai_generation_status: Optional[str] = None
    ai_generation_error: Optional[str] = None
