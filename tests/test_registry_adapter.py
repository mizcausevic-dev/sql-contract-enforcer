"""The registry export shape is a separate contract from the SQL model."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from sql_contract_enforcer import plan_registry_sql

REGISTRY = {
    "dataset_id": "users.daily_active",
    "version": "1.0.0",
    "description": "Synthetic row data",
    "fields": [
        {
            "name": "user_id",
            "type": "string",
            "required": True,
            "description": None,
            "enum": None,
            "deprecated": False,
        },
        {
            "name": "plan",
            "type": "string",
            "required": True,
            "description": None,
            "enum": ["free", "pro"],
            "deprecated": False,
        },
        {
            "name": "session_count",
            "type": "integer",
            "required": True,
            "description": None,
            "enum": None,
            "deprecated": False,
        },
    ],
    "owners": [{"team": "growth-platform", "contact": "#growth-platform"}],
    "freshness_sla": {"max_lag_seconds": 86400, "measurement": "event_time"},
    "status": "active",
    "deprecation_uri": None,
    "primary_key": ["user_id"],
}


def test_registry_v02_maps_to_postgres_proposal_with_explicit_gaps() -> None:
    proposal = plan_registry_sql(REGISTRY, table="users_daily_active", dialect="postgres")
    assert proposal.dataset_id == "users.daily_active"
    assert proposal.contract.contract_id == "users_daily_active"
    assert proposal.contract.owner == "growth-platform"
    assert '"session_count" BIGINT NOT NULL' in proposal.ddl
    assert "CHECK (\"plan\" IN ('free', 'pro'))" in proposal.ddl
    assert 'PRIMARY KEY ("user_id")' in proposal.ddl
    assert any("freshness SLA" in gap for gap in proposal.semantic_gaps)
    assert any("empty strings" in gap for gap in proposal.semantic_gaps)
    assert any("authoritative readback" in gap for gap in proposal.semantic_gaps)


@pytest.mark.parametrize("status", ["draft", "deprecated", "archived"])
def test_nonactive_registry_contract_cannot_be_mapped(status: str) -> None:
    source = deepcopy(REGISTRY)
    source["status"] = status
    with pytest.raises(ValueError, match="only active"):
        plan_registry_sql(source, table="users_daily_active", dialect="postgres")


@pytest.mark.parametrize("dialect", ["snowflake", "bigquery"])
def test_informational_primary_key_fails_closed(dialect: str) -> None:
    with pytest.raises(ValueError, match="does not enforce"):
        plan_registry_sql(REGISTRY, table="users_daily_active", dialect=dialect)


def test_bigquery_string_enum_fails_closed_without_primary_key() -> None:
    source = deepcopy(REGISTRY)
    source["primary_key"] = []
    with pytest.raises(ValueError, match="cannot enforce.*enum"):
        plan_registry_sql(source, table="users_daily_active", dialect="bigquery")


@pytest.mark.parametrize("type_name,enum", [("number", None), ("integer", [1, 2])])
def test_unrepresentable_numeric_semantics_fail_closed(type_name: str, enum: object) -> None:
    source = deepcopy(REGISTRY)
    source["fields"][2]["type"] = type_name
    source["fields"][2]["enum"] = enum
    with pytest.raises(ValueError, match="no lossless SQL mapping|only string enum"):
        plan_registry_sql(source, table="users_daily_active", dialect="postgres")


def test_export_drift_unknown_field_fails_closed() -> None:
    source = deepcopy(REGISTRY)
    source["new_schema_feature"] = "allow"
    with pytest.raises(ValidationError):
        plan_registry_sql(source, table="users_daily_active", dialect="postgres")


@pytest.mark.parametrize(
    "path,value",
    [
        (("version",), "1"),
        (("fields", 1, "enum"), ["free", "free"]),
        (("owners", 0, "team"), " "),
        (("primary_key",), ["missing"]),
    ],
)
def test_invalid_registry_export_fails_closed(path: tuple[object, ...], value: object) -> None:
    source = deepcopy(REGISTRY)
    target = source
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        plan_registry_sql(source, table="users_daily_active", dialect="postgres")


def test_sql_identifier_and_comment_injection_fail_closed() -> None:
    with pytest.raises(ValidationError):
        plan_registry_sql(REGISTRY, table='users"; DROP TABLE accounts; --', dialect="postgres")
    source = deepcopy(REGISTRY)
    source["owners"][0]["team"] = "team\nDROP TABLE accounts;"
    with pytest.raises(ValidationError):
        plan_registry_sql(source, table="users_daily_active", dialect="postgres")
    source = deepcopy(REGISTRY)
    source["fields"][0]["name"] = 'id"; DROP TABLE accounts; --'
    source["primary_key"] = []
    with pytest.raises(ValidationError):
        plan_registry_sql(source, table="users_daily_active", dialect="postgres")


def test_mapping_does_not_mutate_registry_export() -> None:
    source = deepcopy(REGISTRY)
    plan_registry_sql(source, table="users_daily_active", dialect="postgres")
    assert source == REGISTRY
