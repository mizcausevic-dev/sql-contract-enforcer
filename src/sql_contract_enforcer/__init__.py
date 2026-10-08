"""Generate SQL DDL from a SQL-specific contract model.

This model differs from data-contract-registry's JSON shape. Constraint
enforcement varies by engine; check_schema only compares supplied column
presence and nullability, without connecting to a database.

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
from sql_contract_enforcer.registry_adapter import RegistrySqlProposal, plan_registry_sql

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
    "RegistrySqlProposal",
    "plan_registry_sql",
]
__version__ = "0.1.0"
