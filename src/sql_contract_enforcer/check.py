"""Check an observed schema against a contract → list of violations.

The observed schema is a list of ObservedColumn (name + nullable), as you'd
get from introspecting a target database (information_schema) or from a
migration plan. Pure function — no DB connection here, so it unit-tests
cleanly and you can wire your own introspection upstream.
"""

from __future__ import annotations

from sql_contract_enforcer.models import Contract, ObservedColumn, Violation


def check_schema(
    contract: Contract,
    observed: list[ObservedColumn],
    *,
    report_extra: bool = False,
) -> list[Violation]:
    observed_map = {c.name: c for c in observed}
    violations: list[Violation] = []

    for field in contract.fields:
        col = observed_map.get(field.name)
        if col is None:
            # Only required fields must exist. A declared-but-optional field
            # being absent is acceptable schema evolution, not a violation.
            if field.required:
                violations.append(
                    Violation(
                        kind="missing_column",
                        column=field.name,
                        detail=f"required field '{field.name}' ({field.type}) not present",
                    )
                )
            continue
        if field.required and col.nullable:
            violations.append(
                Violation(
                    kind="unexpected_nullable",
                    column=field.name,
                    detail="contract marks field required, but observed column is nullable",
                )
            )

    if report_extra:
        contract_cols = {f.name for f in contract.fields}
        for col in observed:
            if col.name not in contract_cols:
                violations.append(
                    Violation(
                        kind="extra_column",
                        column=col.name,
                        detail="column present in schema but not declared in contract",
                    )
                )

    return violations
