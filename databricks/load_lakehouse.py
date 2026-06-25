"""Load the energy customer + meter-reading seed data into Unity Catalog Delta
tables, ready for Genie (NL-to-SQL) and the Genie MCP server.

Creates:
  adbdemo1.fraud.customers
  adbdemo1.fraud.transactions

Auth (env):
  DATABRICKS_HOST, DATABRICKS_TOKEN, WAREHOUSE_ID

Usage:
  python databricks/load_lakehouse.py --data <path-to-seed-data-dir>
"""

from __future__ import annotations

import argparse
import json
import os

from databricks.sdk import WorkspaceClient

CATALOG = os.environ.get("UC_CATALOG", "adbdemo1")
SCHEMA = os.environ.get("UC_SCHEMA", "fraud")


def sql_val(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def load_table(w: WorkspaceClient, warehouse_id: str, name: str, rows: list[dict], columns: list[str], select_overrides: dict[str, str] | None = None) -> None:
    select_overrides = select_overrides or {}
    values = ",\n".join(
        "(" + ", ".join(sql_val(r.get(c)) for c in columns) + ")" for r in rows
    )
    collist = ", ".join(f"`{c}`" for c in columns)
    select_cols = ", ".join(select_overrides.get(c, f"`{c}`") for c in columns)
    stmt = (
        f"CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.{name} AS\n"
        f"SELECT {select_cols} FROM (VALUES\n{values}) AS t({collist})"
    )
    res = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=stmt, wait_timeout="50s"
    )
    state = res.status.state.value if res.status and res.status.state else "UNKNOWN"
    if state != "SUCCEEDED":
        err = res.status.error.message if res.status and res.status.error else "unknown error"
        raise RuntimeError(f"Failed to create {name}: {state}: {err}")
    print(f"  ✓ {CATALOG}.{SCHEMA}.{name} ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Directory with customers.json and transactions.json")
    args = parser.parse_args()

    warehouse_id = os.environ["WAREHOUSE_ID"]
    w = WorkspaceClient()

    with open(os.path.join(args.data, "customers.json")) as f:
        customers = json.load(f)
    with open(os.path.join(args.data, "transactions.json")) as f:
        transactions = json.load(f)

    print(f"Loading into {CATALOG}.{SCHEMA} via warehouse {warehouse_id}...")

    load_table(
        w, warehouse_id, "customers", customers,
        ["customer_id", "name", "region", "account_age_days", "meter_trust_score", "past_fraud", "property_type", "baseline_consumption_kwh"],
    )
    load_table(
        w, warehouse_id, "transactions", transactions,
        ["reading_id", "customer_id", "consumption_kwh", "meter_id", "reading_type", "timestamp"],
        select_overrides={"timestamp": "to_timestamp(`timestamp`) AS `timestamp`"},
    )
    print("Done.")


if __name__ == "__main__":
    main()
