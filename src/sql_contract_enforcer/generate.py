"""Contract → CREATE TABLE DDL, dialect-aware."""

from __future__ import annotations

from decimal import Decimal

from sql_contract_enforcer.dialects import Dialect, get_dialect
from sql_contract_enforcer.models import Contract, ContractField


def _column_def(field: ContractField, dialect: Dialect) -> str:
    parts = [dialect.quote(field.name), dialect.physical_type(field.type)]
    if field.required:
        parts.append("NOT NULL")
    if field.unique and dialect.allows_unique_syntax:
        # Inline UNIQUE; on dialects that allow the syntax but don't enforce it
        # (Snowflake) it's informational. Dialects without the syntax
        # (BigQuery) get a comment in generate_ddl instead.
        parts.append("UNIQUE")
    return " ".join(parts)


def _check_clauses(field: ContractField, dialect: Dialect) -> list[str]:
    """Return CHECK constraint SQL fragments for a field (may be empty)."""
    if not field.check:
        return []
    col = dialect.quote(field.name)
    clauses: list[str] = []
    if field.check.min is not None:
        clauses.append(f"CHECK ({col} >= {_num(field.check.min)})")
    if field.check.max is not None:
        clauses.append(f"CHECK ({col} <= {_num(field.check.max)})")
    if field.check.enum:
        literals = ", ".join(_string_literal(v, dialect) for v in field.check.enum)
        clauses.append(f"CHECK ({col} IN ({literals}))")
    return clauses


def _string_literal(value: str, dialect: Dialect) -> str:
    # Backslash and control-character interpretation differs by engine and
    # session settings. Reject them until a dialect-specific encoder is tested
    # against real engines. Both quote forms below are documented for their
    # respective dialects.
    if any(char == "\\" or ord(char) < 32 or ord(char) in (127, 133, 8232, 8233) for char in value):
        raise ValueError("enum literals cannot contain backslashes or control characters")
    escaped = value.replace("'", "\\'" if dialect.name == "bigquery" else "''")
    return f"'{escaped}'"


def _num(value: Decimal) -> str:
    # Input was validated as an exact, finite decimal within NUMERIC(38,9).
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def generate_ddl(contract: Contract, dialect_name: str) -> str:
    """Generate a CREATE TABLE statement for the given dialect."""
    dialect = get_dialect(dialect_name)
    table = dialect.quote(contract.table_name())

    lines: list[str] = []

    # Header comment with provenance.
    lines.append(f"-- contract: {contract.contract_id} v{contract.version}")
    if contract.owner:
        lines.append(f"-- owner: {contract.owner}")
    for note in dialect.notes:
        lines.append(f"-- {dialect.name} note: {note}")

    body: list[str] = [f"  {_column_def(f, dialect)}" for f in contract.fields]

    # UNIQUE on dialects without the syntax (BigQuery) — surface as a comment
    # so the contract intent isn't silently lost.
    if not dialect.allows_unique_syntax:
        for f in contract.fields:
            if f.unique:
                lines.append(
                    f"-- unsupported on {dialect.name} (no UNIQUE): column {dialect.quote(f.name)} "
                    "is declared unique in the contract"
                )

    # CHECK constraints — emitted inline as table constraints, or as comments
    # on dialects without CHECK support (BigQuery).
    for f in contract.fields:
        for clause in _check_clauses(f, dialect):
            if dialect.supports_check:
                body.append(f"  {clause}")
            else:
                lines.append(f"-- unsupported on {dialect.name} (no CHECK): {clause}")

    # PRIMARY KEY
    if contract.primary_key:
        cols = ", ".join(dialect.quote(c) for c in contract.primary_key)
        body.append(f"  PRIMARY KEY ({cols}){dialect.constraint_suffix}")

    # FOREIGN KEYs
    for fk in contract.foreign_keys:
        local = ", ".join(dialect.quote(c) for c in fk.columns)
        ref_table = dialect.quote(fk.references_table)
        ref_cols = ", ".join(dialect.quote(c) for c in fk.references_columns)
        fk_sql = f"FOREIGN KEY ({local}) REFERENCES {ref_table} ({ref_cols})"
        body.append(f"  {fk_sql}{dialect.constraint_suffix}")

    lines.append(f"CREATE TABLE {table} (")
    lines.append(",\n".join(body))
    lines.append(");")
    return "\n".join(lines)
