"""sql-contract-enforcer — turn a data contract into enforceable, cross-dialect DDL.

Cross-ecosystem hook #5 in the Kinetic Gain portfolio: where
data-contract-registry stores the contract and csv-data-quality-rs validates
rows against it, this turns the same contract into the CHECK / NOT NULL /
UNIQUE / PRIMARY KEY / FOREIGN KEY constraints that stop bad data at the
table boundary — for Postgres, MySQL, Snowflake, and BigQuery.

    from sql_contract_enforcer import Contract, generate_ddl, check_schema
"""

from sql_contract_enforcer.check import check_schema
from sql_contract_enforcer.dialects import DIALECTS, get_dialect
from sql_contract_enforcer.generate import generate_ddl
from sql_contract_enforcer.models import (
    Contract,
    ContractField,
    ObservedColumn,
    Violation,
    load_contract,
)

__all__ = [
    "Contract",
    "ContractField",
    "ObservedColumn",
    "Violation",
    "DIALECTS",
    "check_schema",
    "generate_ddl",
    "get_dialect",
    "load_contract",
]
__version__ = "0.1.0"
