# sql-contract-enforcer

> Turn a data contract into **enforceable, cross-dialect DDL** — and check an existing schema against the contract. Postgres · MySQL · Snowflake · BigQuery.

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

This is **cross-ecosystem hook #5** in the Kinetic Gain portfolio. Where [`data-contract-registry`](https://github.com/mizcausevic-dev/data-contract-registry) *stores* the contract and [`csv-data-quality-rs`](https://github.com/mizcausevic-dev/csv-data-quality-rs) *validates rows* against it, this tool turns the same contract into the table-level constraints that stop bad data at the boundary — `NOT NULL`, `CHECK`, `UNIQUE`, `PRIMARY KEY`, `FOREIGN KEY` — in whatever dialect your warehouse speaks.

## The hard part: dialects actually differ

The value here is correct cross-dialect SQL, not string templating. The generator knows the quirks:

| Capability | Postgres | MySQL | Snowflake | BigQuery |
| --- | --- | --- | --- | --- |
| `CHECK` constraints | ✅ enforced | ✅ enforced (8.0.16+) | ⚠️ parsed, not enforced | ❌ **unsupported** → emitted as comments |
| `UNIQUE` | ✅ enforced | ✅ enforced | ⚠️ informational | ❌ **no syntax** → omitted + commented |
| `PRIMARY KEY` / `FOREIGN KEY` | ✅ enforced | ✅ enforced | ⚠️ informational | ⚠️ `NOT ENFORCED` metadata only |
| `string` type | `TEXT` | `VARCHAR(255)` | `STRING` | `STRING` |
| `decimal` type | `NUMERIC(38,9)` | `DECIMAL(38,9)` | `NUMBER(38,9)` | `NUMERIC` |
| `timestamp` type | `TIMESTAMPTZ` | `DATETIME` | `TIMESTAMP_TZ` | `TIMESTAMP` |
| `json` type | `JSONB` | `JSON` | `VARIANT` | `JSON` |

So the **same contract** yields valid, idiomatic DDL on each engine — BigQuery gets `PRIMARY KEY (...) NOT ENFORCED` and its un-expressible constraints surfaced as comments instead of silently dropped; Snowflake gets a header note that its UNIQUE/CHECK/FK are informational; MySQL gets explicit `VARCHAR` lengths.

## Contract format

A small JSON subset compatible with `data-contract-registry`:

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

Exit code is non-zero when violations exist — drop it into CI to fail a deploy when a migration drifts from the contract.

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
| Stores the contract | [`data-contract-registry`](https://github.com/mizcausevic-dev/data-contract-registry) |
| Validates rows against it (Rust, streaming) | [`csv-data-quality-rs`](https://github.com/mizcausevic-dev/csv-data-quality-rs) |
| **Enforces it at the table boundary (this repo)** | `sql-contract-enforcer` |
| Where contracts come from (buyer side) | [`procurement-decision-api`](https://github.com/mizcausevic-dev/procurement-decision-api) |

## Status

**v0.1.0** — generate + check, four dialects. Python 3.11/3.12/3.13. CI green (ruff + mypy strict + pytest).

Roadmap: live `information_schema` introspection adapters · `ALTER TABLE` diff output (migrate an existing table to match the contract) · column type-drift detection in `check` · dbt model generation.

## License

MIT.
