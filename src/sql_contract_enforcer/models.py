"""Data-contract models — a deliberately small subset compatible with
data-contract-registry's field/constraint shape, enough to generate and
check DDL across dialects."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

LogicalType = Literal[
    "string",
    "integer",
    "decimal",
    "boolean",
    "timestamp",
    "date",
    "json",
]


class FieldCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None
    enum: list[str] | None = None


class ContractField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: LogicalType
    required: bool = False
    unique: bool = False
    check: FieldCheck | None = None
    description: str | None = None


class ForeignKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str]
    references_table: str
    references_columns: list[str]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_id: str
    version: str = "0.1.0"
    owner: str | None = None
    table: str | None = None  # defaults to contract_id if unset
    fields: list[ContractField]
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)

    def table_name(self) -> str:
        return self.table or self.contract_id

    def field_map(self) -> dict[str, ContractField]:
        return {f.name: f for f in self.fields}


class ObservedColumn(BaseModel):
    """A column as it actually exists in a target database (from introspection
    or a migration plan), for the `check` command."""

    model_config = ConfigDict(extra="forbid")

    name: str
    nullable: bool = True


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "missing_column",
        "unexpected_nullable",
        "missing_unique",
        "extra_column",
    ]
    column: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.kind}] {self.column}: {self.detail}"


def load_contract(data: dict[str, Any]) -> Contract:
    return Contract.model_validate(data)
