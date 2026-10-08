"""Explicit, proposal-only mapping from registry v0.2 JSON to SQL DDL.

This module mirrors the registry's exported v0.2 wire fields with strict
validation rather than importing a potentially different installed release.
It rejects constraints the SQL model cannot represent and reports the
remaining row/engine semantics that DDL alone cannot prove.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sql_contract_enforcer.dialects import get_dialect
from sql_contract_enforcer.generate import generate_ddl
from sql_contract_enforcer.models import Contract, ContractField, FieldCheck


class _RegistryField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    type: Literal["string", "integer", "number", "boolean", "timestamp", "json"]
    required: bool = True
    description: str | None = None
    enum: list[Any] | None = Field(default=None, max_length=256)
    deprecated: bool = False

    @model_validator(mode="after")
    def _check_registry_field(self) -> _RegistryField:
        if not self.name.strip():
            raise ValueError("registry field name must not be blank")
        if self.enum is None:
            return self
        if not self.enum or self.type in ("timestamp", "json"):
            raise ValueError("registry enum is empty or unsupported for this field type")
        for value in self.enum:
            valid = (
                (self.type == "string" and type(value) is str)
                or (self.type == "integer" and type(value) is int)
                or (self.type == "number" and type(value) in (int, float))
                or (self.type == "boolean" and type(value) is bool)
            )
            if not valid or (type(value) is float and not math.isfinite(value)):
                raise ValueError("registry enum value does not match field type")
        if len(set(self.enum)) != len(self.enum):
            raise ValueError("registry enum values must be unique")
        return self


class _RegistryOwner(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    team: str = Field(min_length=1)
    contact: str | None = None

    @model_validator(mode="after")
    def _nonblank(self) -> _RegistryOwner:
        if not self.team.strip() or (self.contact is not None and not self.contact.strip()):
            raise ValueError("registry owner team/contact must not be blank")
        return self


class _RegistryFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    max_lag_seconds: int = Field(gt=0)
    measurement: str = "event_time"


class _RegistryContractV02(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    dataset_id: str = Field(min_length=1, max_length=128)
    version: str
    description: str | None = None
    fields: list[_RegistryField] = Field(min_length=1, max_length=4096)
    owners: list[_RegistryOwner] = Field(min_length=1, max_length=32)
    freshness_sla: _RegistryFreshness | None = None
    status: Literal["draft", "active", "deprecated", "archived"] = "draft"
    deprecation_uri: str | None = None
    primary_key: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_fields_and_keys(self) -> _RegistryContractV02:
        if not self.dataset_id.strip() or not re.fullmatch(
            r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", self.version
        ):
            raise ValueError("registry identity/version is invalid")
        fields = {field.name: field for field in self.fields}
        if len(fields) != len(self.fields):
            raise ValueError("registry field names must be unique")
        if len(self.primary_key) != len(set(self.primary_key)):
            raise ValueError("registry primary_key entries must be unique")
        if any(key not in fields or not fields[key].required for key in self.primary_key):
            raise ValueError("registry primary_key entries must name required fields")
        return self


@dataclass(frozen=True)
class RegistrySqlProposal:
    """DDL proposal plus differences that require independent controls/tests."""

    dataset_id: str
    version: str
    dialect: str
    contract: Contract
    ddl: str
    semantic_gaps: tuple[str, ...]


def plan_registry_sql(
    registry_json: dict[str, Any], *, table: str, dialect: str
) -> RegistrySqlProposal:
    """Map a registry v0.2 export into a proposed SQL table definition.

    The table name is an explicit operator choice because registry dataset IDs
    can contain dots and need not be safe SQL identifiers. Unsupported types
    and unenforced constraints raise; reported gaps must be handled outside
    this package before anyone claims registry/CSV/SQL behavior is equivalent.
    No database connection or DDL execution occurs here.
    """
    source = _RegistryContractV02.model_validate(registry_json)
    target = get_dialect(dialect)
    if source.status != "active":
        raise ValueError("only active registry contracts can be proposed for SQL")
    if source.primary_key and not target.enforces_unique:
        raise ValueError(f"{target.name} does not enforce registry primary_key")

    fields: list[ContractField] = []
    gaps: list[str] = ["registry source identity and version require authoritative readback"]
    if source.description:
        gaps.append("registry description is not included in generated DDL")
    for field in source.fields:
        if field.type == "number":
            raise ValueError(f"field {field.name!r}: registry number has no lossless SQL mapping")
        checks: FieldCheck | None = None
        if field.enum is not None:
            if (
                field.type != "string"
                or not field.enum
                or any(type(value) is not str for value in field.enum)
            ):
                raise ValueError(f"field {field.name!r}: only string enum maps to SQL CHECK")
            if not target.supports_check:
                raise ValueError(f"{target.name} cannot enforce field {field.name!r} enum")
            checks = FieldCheck(enum=field.enum)
            gaps.append(f"{field.name}: SQL collation may change string enum matching")
            if target.name == "mysql":
                gaps.append(f"{field.name}: MySQL CHECK enforcement requires 8.0.16 or later")
            if target.name == "snowflake":
                gaps.append(f"{field.name}: Snowflake CHECK enforcement assumes a standard table")
        fields.append(
            ContractField(
                name=field.name,
                type=field.type,
                required=field.required,
                check=checks,
                description=field.description,
            )
        )
        if field.type == "string":
            if field.required:
                gaps.append(f"{field.name}: SQL NOT NULL permits empty strings; CSV rejects them")
            if target.name == "mysql":
                gaps.append(f"{field.name}: MySQL VARCHAR(255) narrows registry string values")
        if field.type == "timestamp":
            gaps.append(
                f"{field.name}: timestamp parsing and timezone behavior require a target test"
            )
        if field.type == "json":
            gaps.append(f"{field.name}: JSON validation and normalization differ by engine")
        if field.type == "integer" and target.name == "snowflake":
            gaps.append(f"{field.name}: Snowflake NUMBER(38,0) is wider than CSV i64")
        if field.type == "boolean":
            gaps.append(f"{field.name}: boolean input representations require a target test")
        if field.type == "boolean" and target.name == "mysql":
            gaps.append(f"{field.name}: MySQL TINYINT(1) also accepts non-boolean integers")
        if field.deprecated:
            gaps.append(f"{field.name}: registry field deprecation is metadata only")
        if field.description:
            gaps.append(f"{field.name}: registry field description is not included in DDL")

    if source.freshness_sla is not None:
        gaps.append("registry freshness SLA needs a separate monitored control")
    if source.deprecation_uri is not None:
        gaps.append("registry deprecation URI is metadata only")

    # SQL Contract validates portable identifiers and single-line owner metadata.
    contract = Contract(
        contract_id=table,
        table=table,
        version=source.version,
        owner=", ".join(owner.team for owner in source.owners),
        fields=fields,
        primary_key=source.primary_key,
    )
    return RegistrySqlProposal(
        dataset_id=source.dataset_id,
        version=source.version,
        dialect=target.name,
        contract=contract,
        ddl=generate_ddl(contract, target.name),
        semantic_gaps=tuple(gaps),
    )
