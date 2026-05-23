from __future__ import annotations

import pytest

from sql_contract_enforcer import generate_ddl, load_contract
from sql_contract_enforcer.dialects import get_dialect

CONTRACT = {
    "contract_id": "orders",
    "version": "1.2.0",
    "owner": "revenue-platform",
    "fields": [
        {"name": "id", "type": "string", "required": True, "unique": True},
        {"name": "customer_id", "type": "string", "required": True},
        {"name": "amount", "type": "decimal", "required": True, "check": {"min": 0}},
        {"name": "currency", "type": "string", "required": True, "check": {"enum": ["USD", "EUR"]}},
        {"name": "metadata", "type": "json"},
    ],
    "primary_key": ["id"],
    "foreign_keys": [
        {"columns": ["customer_id"], "references_table": "customers", "references_columns": ["id"]}
    ],
}


def gen(dialect):
    return generate_ddl(load_contract(CONTRACT), dialect)


def test_postgres_types_and_constraints():
    ddl = gen("postgres")
    assert '"id" TEXT NOT NULL UNIQUE' in ddl
    assert '"amount" NUMERIC(38,9) NOT NULL' in ddl
    assert '"metadata" JSONB' in ddl
    assert 'CHECK ("amount" >= 0)' in ddl
    assert "CHECK (\"currency\" IN ('USD', 'EUR'))" in ddl
    assert 'PRIMARY KEY ("id")' in ddl
    assert 'FOREIGN KEY ("customer_id") REFERENCES "customers" ("id")' in ddl
    assert "NOT ENFORCED" not in ddl  # postgres enforces


def test_mysql_varchar_length_and_backticks():
    ddl = gen("mysql")
    assert "`id` VARCHAR(255) NOT NULL UNIQUE" in ddl
    assert "`amount` DECIMAL(38,9) NOT NULL" in ddl
    assert "`metadata` JSON" in ddl
    assert "CHECK (`amount` >= 0)" in ddl


def test_snowflake_informational_note_and_types():
    ddl = gen("snowflake")
    assert '"id" STRING NOT NULL UNIQUE' in ddl  # syntax allowed (informational)
    assert '"amount" NUMBER(38,9) NOT NULL' in ddl
    assert '"metadata" VARIANT' in ddl
    assert "informational constraints" in ddl  # the dialect note is emitted
    assert "NOT ENFORCED" not in ddl  # snowflake uses informational, not NOT ENFORCED


def test_bigquery_no_check_no_unique_and_not_enforced():
    ddl = gen("bigquery")
    # CHECK becomes a comment, not a table constraint.
    assert "-- unsupported on bigquery (no CHECK): CHECK (`amount` >= 0)" in ddl
    # UNIQUE is omitted from the column def AND surfaced as a comment.
    assert "`id` STRING NOT NULL UNIQUE" not in ddl
    assert "`id` STRING NOT NULL" in ddl
    assert "no UNIQUE" in ddl
    # PK / FK become NOT ENFORCED.
    assert "PRIMARY KEY (`id`) NOT ENFORCED" in ddl
    assert "FOREIGN KEY (`customer_id`) REFERENCES `customers` (`id`) NOT ENFORCED" in ddl
    assert "INT64" not in ddl  # no integer fields here; sanity that types come from bigquery map
    assert "`metadata` JSON" in ddl


def test_header_provenance():
    ddl = gen("postgres")
    assert "-- contract: orders v1.2.0" in ddl
    assert "-- owner: revenue-platform" in ddl


def test_integer_type_maps_per_dialect():
    c = {"contract_id": "t", "fields": [{"name": "n", "type": "integer"}]}
    assert "BIGINT" in generate_ddl(load_contract(c), "postgres")
    assert "BIGINT" in generate_ddl(load_contract(c), "mysql")
    assert "NUMBER(38,0)" in generate_ddl(load_contract(c), "snowflake")
    assert "INT64" in generate_ddl(load_contract(c), "bigquery")


def test_unknown_dialect_raises():
    with pytest.raises(KeyError):
        get_dialect("oracle")


def test_decimal_min_max_render_without_trailing_zero():
    c = {
        "contract_id": "t",
        "fields": [{"name": "pct", "type": "decimal", "check": {"min": 0, "max": 100}}],
    }
    ddl = generate_ddl(load_contract(c), "postgres")
    assert 'CHECK ("pct" >= 0)' in ddl
    assert 'CHECK ("pct" <= 100)' in ddl
