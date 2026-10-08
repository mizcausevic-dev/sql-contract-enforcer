"""SQL-specific contract models; registry JSON needs an explicit mapping."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")


def validate_identifier(value: str) -> str:
    """Accept the portable identifier subset supported by all four dialects."""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("SQL identifier must match [A-Za-z_][A-Za-z0-9_]{0,63}")
    return value


def _single_line(value: str) -> str:
    if any(ord(char) < 32 or ord(char) in (127, 133, 8232, 8233) for char in value):
        raise ValueError("metadata used in SQL comments must be a single line")
    return value


def _version(value: str) -> str:
    if not _SEMVER.fullmatch(value):
        raise ValueError("version must be MAJOR.MINOR.PATCH")
    return value


Identifier = Annotated[str, AfterValidator(validate_identifier)]
CommentText = Annotated[str, AfterValidator(_single_line)]
Version = Annotated[str, AfterValidator(_version)]

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

    min: Decimal | None = None
    max: Decimal | None = None
    enum: list[str] | None = Field(default=None, min_length=1)

    @field_validator("enum")
    @classmethod
    def _safe_enum(cls, values: list[str] | None) -> list[str] | None:
        if values is not None:
            for value in values:
                if any(
                    char == "\\" or ord(char) < 32 or ord(char) in (127, 133, 8232, 8233)
                    for char in value
                ):
                    raise ValueError(
                        "enum literals cannot contain backslashes or control characters"
                    )
        return values

    @field_validator("min", "max", mode="before")
    @classmethod
    def _no_binary_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("numeric bounds must be exact integers, decimal strings, or Decimal")
        return value

    @field_validator("min", "max")
    @classmethod
    def _finite_sql_number(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite() or abs(value) >= Decimal("1e29"):
            raise ValueError("numeric bound must fit NUMERIC(38,9)")
        if value == 0:
            return Decimal(0)
        digits = value.as_tuple().digits
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < 0:
            trailing_zeros = 0
            for digit in reversed(digits):
                if digit != 0:
                    break
                trailing_zeros += 1
            if -exponent - trailing_zeros > 9:
                raise ValueError("numeric bound cannot exceed nine decimal places")
        return value

    @model_validator(mode="after")
    def _bounds(self) -> FieldCheck:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("check.min must not exceed check.max")
        return self


class ContractField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Identifier
    type: LogicalType
    required: bool = False
    unique: bool = False
    check: FieldCheck | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _check_type(self) -> ContractField:
        if self.check is not None:
            if (self.check.min is not None or self.check.max is not None) and self.type not in (
                "integer",
                "decimal",
            ):
                raise ValueError("numeric bounds require an integer or decimal field")
            if self.check.enum is not None and self.type != "string":
                raise ValueError("enum checks currently support string fields only")
        return self


class ForeignKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[Identifier] = Field(min_length=1)
    references_table: Identifier
    references_columns: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def _same_arity(self) -> ForeignKey:
        if len(self.columns) != len(self.references_columns):
            raise ValueError("foreign-key column counts must match")
        return self


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_id: Identifier
    version: Version = "0.1.0"
    owner: CommentText | None = None
    table: Identifier | None = None  # defaults to contract_id if unset
    fields: list[ContractField] = Field(min_length=1)
    primary_key: list[Identifier] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)

    @model_validator(mode="after")
    def _declared_columns(self) -> Contract:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("field names must be unique")
        if len(self.primary_key) != len(set(self.primary_key)):
            raise ValueError("primary-key columns must be unique")
        if any(name not in names for name in self.primary_key):
            raise ValueError("primary-key columns must be declared fields")
        if any(field.name in self.primary_key and not field.required for field in self.fields):
            raise ValueError("primary-key fields must be required")
        for key in self.foreign_keys:
            if any(name not in names for name in key.columns):
                raise ValueError("foreign-key columns must be declared fields")
        return self

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
