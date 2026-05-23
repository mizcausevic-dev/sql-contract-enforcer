"""CLI: sql-contract-enforcer generate|check."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sql_contract_enforcer.check import check_schema
from sql_contract_enforcer.dialects import DIALECTS
from sql_contract_enforcer.generate import generate_ddl
from sql_contract_enforcer.models import ObservedColumn, load_contract


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sql-contract-enforcer")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="contract -> CREATE TABLE DDL")
    g.add_argument("contract", help="path to a contract JSON file")
    g.add_argument(
        "--dialect",
        required=True,
        choices=sorted(DIALECTS),
        help="target SQL dialect",
    )

    c = sub.add_parser("check", help="contract vs observed schema -> violations")
    c.add_argument("contract", help="path to a contract JSON file")
    c.add_argument("observed", help="path to observed-columns JSON ([{name, nullable}, ...])")
    c.add_argument(
        "--report-extra", action="store_true", help="also flag columns not in the contract"
    )

    args = parser.parse_args(argv)

    if args.command == "generate":
        contract = load_contract(_load(args.contract))
        print(generate_ddl(contract, args.dialect))
        return 0

    if args.command == "check":
        contract = load_contract(_load(args.contract))
        observed = [ObservedColumn.model_validate(o) for o in _load(args.observed)]
        violations = check_schema(contract, observed, report_extra=args.report_extra)
        if not violations:
            print("OK: schema satisfies the contract.")
            return 0
        for v in violations:
            print(str(v))
        print(f"\n{len(violations)} violation(s).")
        return 1

    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
