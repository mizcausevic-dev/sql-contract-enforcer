"""Dialect definitions — the part that actually demands SQL knowledge.

Each dialect carries a logical→physical type map plus capability flags that
capture the real cross-dialect quirks:

  - BigQuery has NO CHECK constraints, and PK/FK are allowed only as
    `NOT ENFORCED` metadata.
  - Snowflake parses UNIQUE / CHECK / FK but does NOT enforce them
    (informational constraints) — only NOT NULL is enforced.
  - MySQL needs an explicit length on VARCHAR; CHECK is enforced from 8.0.16.
  - Postgres enforces everything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sql_contract_enforcer.models import LogicalType


@dataclass(frozen=True)
class Dialect:
    name: str
    type_map: dict[LogicalType, str]
    identifier_quote: str = '"'
    supports_check: bool = True
    allows_unique_syntax: bool = True
    enforces_unique: bool = True
    enforces_fk: bool = True
    # When PK/FK are allowed but not enforced (BigQuery), append this clause.
    constraint_suffix: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def quote(self, ident: str) -> str:
        q = self.identifier_quote
        return f"{q}{ident}{q}"

    def physical_type(self, logical: LogicalType) -> str:
        return self.type_map[logical]


POSTGRES = Dialect(
    name="postgres",
    identifier_quote='"',
    type_map={
        "string": "TEXT",
        "integer": "BIGINT",
        "decimal": "NUMERIC(38,9)",
        "boolean": "BOOLEAN",
        "timestamp": "TIMESTAMPTZ",
        "date": "DATE",
        "json": "JSONB",
    },
)

MYSQL = Dialect(
    name="mysql",
    identifier_quote="`",
    type_map={
        "string": "VARCHAR(255)",
        "integer": "BIGINT",
        "decimal": "DECIMAL(38,9)",
        "boolean": "TINYINT(1)",
        "timestamp": "DATETIME",
        "date": "DATE",
        "json": "JSON",
    },
)

SNOWFLAKE = Dialect(
    name="snowflake",
    identifier_quote='"',
    type_map={
        "string": "STRING",
        "integer": "NUMBER(38,0)",
        "decimal": "NUMBER(38,9)",
        "boolean": "BOOLEAN",
        "timestamp": "TIMESTAMP_TZ",
        "date": "DATE",
        "json": "VARIANT",
    },
    enforces_unique=False,
    enforces_fk=False,
    notes=(
        "Snowflake parses UNIQUE/CHECK/FOREIGN KEY but does not enforce them "
        "(informational constraints). Only NOT NULL is enforced.",
    ),
)

BIGQUERY = Dialect(
    name="bigquery",
    identifier_quote="`",
    type_map={
        "string": "STRING",
        "integer": "INT64",
        "decimal": "NUMERIC",
        "boolean": "BOOL",
        "timestamp": "TIMESTAMP",
        "date": "DATE",
        "json": "JSON",
    },
    supports_check=False,
    allows_unique_syntax=False,
    enforces_unique=False,
    enforces_fk=False,
    constraint_suffix=" NOT ENFORCED",
    notes=(
        "BigQuery does not support CHECK or UNIQUE constraints (emitted as comments). "
        "PRIMARY KEY / FOREIGN KEY are allowed only as NOT ENFORCED metadata.",
    ),
)

DIALECTS: dict[str, Dialect] = {d.name: d for d in (POSTGRES, MYSQL, SNOWFLAKE, BIGQUERY)}


def get_dialect(name: str) -> Dialect:
    key = name.lower()
    if key not in DIALECTS:
        raise KeyError(f"unknown dialect '{name}'. Known: {', '.join(sorted(DIALECTS))}")
    return DIALECTS[key]
