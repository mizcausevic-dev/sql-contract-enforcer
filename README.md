# sql-contract-enforcer

> Generate DDL from this package's SQL contract model and compare declared columns with an observed schema. Postgres · MySQL · Snowflake · BigQuery. Constraint enforcement varies by engine.

```bash
sql-contract-enforcer generate examples/orders.contract.json --dialect postgres
```

```sql
-- contract: orders v1.2.0
-- owner: revenue-platform
CREATE TABLE "orders" (
  "id" TEXT NOT NULL UNIQUE,
  "customer_id" TEXT NOT NULL,
  "amount" NUMERIC(38,9) NOT NULL,
  "currency" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "metadata" JSONB,
  "created_at" TIMESTAMPTZ NOT NULL,
  CHECK ("amount" >= 0),
  CHECK ("currency" IN ('USD', 'EUR', 'GBP')),
  CHECK ("status" IN ('pending', 'paid', 'refunded')),
  PRIMARY KEY ("id"),
  FOREIGN KEY ("customer_id") REFERENCES "customers" ("id")
);
```

This is a proposed fifth cross-ecosystem hook in the Kinetic Gain portfolio. [`data-contract-registry`](https://github.com/mizcausevic-dev/data-contract-registry) stores its own contract shape and [`csv-data-quality-rs`](https://github.com/mizcausevic-dev/csv-data-quality-rs) validates CSV rows. This package consumes a **different SQL contract shape** and generates table definitions. There is no adapter proving that all three enforce the same rules.

## The hard part: dialects actually differ

The value here is correct cross-dialect SQL, not string templating. The generator knows the quirks:

| Capability | Postgres | MySQL | Snowflake | BigQuery |
| --- | --- | --- | --- | --- |
| `CHECK` constraints | ✅ enforced | ✅ enforced (8.0.16+) | ✅ enforced on standard tables | ❌ **unsupported** → emitted as comments |
| `UNIQUE` | ✅ enforced | ✅ enforced | ⚠️ informational | ❌ **no syntax** → omitted + commented |
| `PRIMARY KEY` / `FOREIGN KEY` | ✅ enforced | ✅ enforced | ⚠️ informational | ⚠️ `NOT ENFORCED` metadata only |
| `string` type | `TEXT` | `VARCHAR(255)` | `STRING` | `STRING` |
| `decimal` type | `NUMERIC(38,9)` | `DECIMAL(38,9)` | `NUMBER(38,9)` | `NUMERIC` |
| `timestamp` type | `TIMESTAMPTZ` | `DATETIME` | `TIMESTAMP_TZ` | `TIMESTAMP` |
| `json` type | `JSONB` | `JSON` | `VARIANT` | `JSON` |

The SQL contract can be rendered for each engine. BigQuery gets `PRIMARY KEY (...) NOT ENFORCED` and unsupported constraints are surfaced as comments; Snowflake's standard tables enforce `NOT NULL` and `CHECK`, while key constraints are informational. Generated output has unit tests, but has **not** been executed against real Postgres, MySQL, Snowflake, or BigQuery instances. Review the output and test it on the target engine before applying it.

## Contract format

A SQL-specific JSON model:

```json
{
  "contract_id": "orders",
  "version": "1.2.0",
  "owner": "revenue-platform",
  "fields": [
    { "name": "id", "type": "string", "required": true, "unique": true },
    { "name": "amount", "type": "decimal", "required": true, "check": { "min": 0 } },
    { "name": "currency", "type": "string", "required": true, "check": { "enum": ["USD", "EUR", "GBP"] } }
  ],
  "primary_key": ["id"],
  "foreign_keys": [
    { "columns": ["customer_id"], "references_table": "customers", "references_columns": ["id"] }
  ]
}
```

Logical types: `string · integer · decimal · boolean · timestamp · date · json`. Per-field checks: `min`, `max`, `enum`.

Identifiers are limited to 1–64 ASCII letters, digits, or underscores and must start with a letter or underscore. DDL generation rejects enum strings with backslashes or control characters until their quoting is tested on each engine. Numeric bounds require an integer or decimal field, must fit `NUMERIC(38,9)`, and are parsed exactly from JSON; Python library callers should pass an integer, decimal string, or `Decimal`, rather than a binary float. Enum checks currently require a string field.

`required` produces `NOT NULL`; it does not reject an empty string. That differs from the CSV validator's empty-cell rule.

**Registry interoperability is not automatic.** The registry uses `dataset_id`, an `owners` list, `number` rather than `decimal`, and top-level field `enum`; this model uses `contract_id`, one optional `owner`, and nested `check.enum`. Registry contracts must be mapped and checked explicitly before use. Do not infer SQL enforcement from a successful registry or CSV check.

## Check an existing schema against the contract

Feed the columns you observe (from `information_schema` introspection or a migration plan) and get a violation report:

```bash
sql-contract-enforcer check examples/orders.contract.json examples/orders.observed.json --report-extra
```

```
[missing_column] status: contract requires column 'status' (string); not present
[unexpected_nullable] customer_id: contract marks field required, but observed column is nullable
[extra_column] legacy_notes: column present in schema but not declared in contract

3 violation(s).
```

Exit code is non-zero when violations exist. This comparison only checks **required** column presence and nullability against the supplied JSON observation; optional columns may be absent. It does not connect to a database or verify actual column types, uniqueness, checks, primary keys, foreign keys, or whether the target engine enforces those constraints. Supply trustworthy observations; do not treat this as a deployed-boundary check.

## Library use

```python
from sql_contract_enforcer import load_contract, generate_ddl, check_schema
from sql_contract_enforcer.models import ObservedColumn

contract = load_contract({...})
ddl = generate_ddl(contract, "snowflake")
violations = check_schema(contract, [ObservedColumn(name="id", nullable=False)])
```

## Test

```bash
pip install -e ".[dev]"
pytest -v          # asserts exact DDL per dialect + the check violations
ruff check src tests && mypy src
```

## Composes with

| Concern | Repo |
| --- | --- |
| Stores registry-shaped contracts | [`data-contract-registry`](https://github.com/mizcausevic-dev/data-contract-registry) |
| Validates rows against the registry shape (Rust) | [`csv-data-quality-rs`](https://github.com/mizcausevic-dev/csv-data-quality-rs) |
| Generates DDL from a separate SQL shape (this repo) | `sql-contract-enforcer` |
| Where contracts come from (buyer side) | [`procurement-decision-api`](https://github.com/mizcausevic-dev/procurement-decision-api) |

## Status

**v0.1.0 source** — generate + check, four dialects. Python 3.11/3.12/3.13 in CI. Release readiness requires the CI results for this change plus target-engine execution and rollback proof.

Roadmap: live `information_schema` introspection adapters · `ALTER TABLE` diff output (migrate an existing table to match the contract) · column type-drift detection in `check` · dbt model generation.

## License

MIT.
