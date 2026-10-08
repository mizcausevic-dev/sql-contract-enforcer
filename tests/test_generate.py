from __future__ import annotations

import pytest
from pydantic import ValidationError

from sql_contract_enforcer import generate_ddl, load_contract
from sql_contract_enforcer.__main__ import main
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
    assert "UNIQUE/PRIMARY KEY/FOREIGN KEY are informational" in ddl
    assert "enforce NOT NULL and CHECK" in ddl
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


def test_large_numeric_bound_keeps_exact_integer():
    c = {
        "contract_id": "t",
        "fields": [{"name": "amount", "type": "decimal", "check": {"min": 9007199254740993}}],
    }
    ddl = generate_ddl(load_contract(c), "postgres")
    assert 'CHECK ("amount" >= 9007199254740993)' in ddl


def test_cli_preserves_fractional_json_number(tmp_path, capsys):
    path = tmp_path / "contract.json"
    path.write_text(
        '{"contract_id":"t","fields":[{"name":"amount","type":"decimal",'
        '"check":{"min":9007199254740993.1}}]}',
        encoding="utf-8",
    )
    assert main(["generate", str(path), "--dialect", "postgres"]) == 0
    assert 'CHECK ("amount" >= 9007199254740993.1)' in capsys.readouterr().out


@pytest.mark.parametrize("bound", [0.1, "1e29", "0.0000000001"])
def test_imprecise_or_out_of_range_numeric_bounds_fail_closed(bound):
    c = {
        "contract_id": "t",
        "fields": [{"name": "amount", "type": "decimal", "check": {"min": bound}}],
    }
    with pytest.raises(ValidationError):
        load_contract(c)


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "snowflake", "bigquery"])
def test_enum_quote_stays_inside_one_literal(dialect):
    contract = load_contract(
        {
            "contract_id": "orders",
            "fields": [{"name": "status", "type": "string", "check": {"enum": ["O'Brien"]}}],
        }
    )
    ddl = generate_ddl(contract, dialect)
    literal = "'O\\'Brien'" if dialect == "bigquery" else "'O''Brien'"
    assert f"IN ({literal})" in ddl


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_id", "orders\nDROP TABLE customers;"),
        ("table", 'orders"; DROP TABLE customers; --'),
        ("owner", "data-team\nDROP TABLE customers;"),
        ("version", "1.0.0\nDROP TABLE customers;"),
    ],
)
def test_sql_header_and_table_inputs_reject_statement_breaks(field, value):
    data = {"contract_id": "orders", "fields": [{"name": "id", "type": "string"}]}
    data[field] = value
    with pytest.raises(ValidationError):
        load_contract(data)


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "snowflake", "bigquery"])
def test_direct_dialect_quote_rejects_untrusted_identifier(dialect):
    with pytest.raises(ValueError):
        get_dialect(dialect).quote('id"; DROP TABLE customers; --')


@pytest.mark.parametrize(
    "field",
    [
        {"name": 'id"; DROP TABLE customers; --', "type": "string"},
        {"name": "id", "type": "string", "check": {"enum": ["x\\' OR TRUE --"]}},
        {"name": "id", "type": "string", "check": {"min": 0}},
        {"name": "id", "type": "decimal", "check": {"min": 2, "max": 1}},
        {"name": "id", "type": "decimal", "check": {"min": "NaN"}},
        {"name": "id", "type": "string", "check": {"enum": []}},
    ],
)
def test_unsafe_or_impossible_field_constraints_fail_closed(field):
    data = {"contract_id": "orders", "fields": [field]}
    with pytest.raises((ValidationError, ValueError)):
        contract = load_contract(data)
        generate_ddl(contract, "postgres")


def test_key_columns_must_be_declared_and_foreign_key_arity_must_match():
    data = {
        "contract_id": "orders",
        "fields": [{"name": "id", "type": "string", "required": True}],
        "primary_key": ["missing"],
    }
    with pytest.raises(ValidationError):
        load_contract(data)
    data["primary_key"] = ["id"]
    data["foreign_keys"] = [
        {
            "columns": ["id"],
            "references_table": "customers",
            "references_columns": ["id", "other"],
        }
    ]
    with pytest.raises(ValidationError, match="foreign-key column counts must match"):
        load_contract(data)


def test_primary_key_cannot_be_optional_when_target_key_is_informational():
    data = {
        "contract_id": "orders",
        "fields": [{"name": "id", "type": "string", "required": False}],
        "primary_key": ["id"],
    }
    with pytest.raises(ValidationError, match="primary-key fields must be required"):
        load_contract(data)
