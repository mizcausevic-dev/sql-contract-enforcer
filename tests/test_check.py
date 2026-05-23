from __future__ import annotations

from sql_contract_enforcer import check_schema, load_contract
from sql_contract_enforcer.models import ObservedColumn

CONTRACT = load_contract(
    {
        "contract_id": "orders",
        "fields": [
            {"name": "id", "type": "string", "required": True},
            {"name": "customer_id", "type": "string", "required": True},
            {"name": "amount", "type": "decimal", "required": True},
            {"name": "note", "type": "string"},
        ],
        "primary_key": ["id"],
    }
)


def cols(*specs):
    return [ObservedColumn(name=n, nullable=nl) for n, nl in specs]


def test_satisfying_schema_has_no_violations():
    observed = cols(("id", False), ("customer_id", False), ("amount", False), ("note", True))
    assert check_schema(CONTRACT, observed) == []


def test_missing_required_column():
    observed = cols(("id", False), ("amount", False), ("note", True))
    violations = check_schema(CONTRACT, observed)
    kinds = {(v.kind, v.column) for v in violations}
    assert ("missing_column", "customer_id") in kinds
    assert len(violations) == 1


def test_required_but_nullable():
    observed = cols(("id", False), ("customer_id", True), ("amount", False), ("note", True))
    violations = check_schema(CONTRACT, observed)
    assert any(v.kind == "unexpected_nullable" and v.column == "customer_id" for v in violations)


def test_extra_column_only_when_requested():
    observed = cols(
        ("id", False), ("customer_id", False), ("amount", False), ("note", True), ("legacy", True)
    )
    assert check_schema(CONTRACT, observed) == []  # default: don't report extras
    with_extra = check_schema(CONTRACT, observed, report_extra=True)
    assert any(v.kind == "extra_column" and v.column == "legacy" for v in with_extra)


def test_optional_field_missing_is_ok():
    observed = cols(("id", False), ("customer_id", False), ("amount", False))
    # 'note' is optional → its absence is not a violation.
    assert check_schema(CONTRACT, observed) == []
