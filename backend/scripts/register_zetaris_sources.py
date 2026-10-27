#!/usr/bin/env python3
"""
Register Receipts' exported evidence CSVs in a Zetaris instance.

Steps (mirrors scripts/register_zetaris_sources.sql):

1. Start your Zetaris instance and sign in to its web UI.
2. Export the evidence store (the app does this on every
   /evidence/insights call, writing runs.csv, claims.csv and
   sources.csv under data/zetaris/). The CSV files must sit at a path
   the Zetaris instance itself can read: on a single machine install
   that is the same path this script prints.
3. Run the generated statements in the Zetaris SQL Workspace, one
   statement at a time (the workspace splits on semicolons). On a
   fresh instance run all four; if the receipts_evidence database
   already exists, skip the CREATE LIGHTNING DATABASE statement.
4. Create an API key in the Zetaris GUI (Management, API Tokens) and
   note the numeric organisation ID (Management, Organisation).
5. Set the environment for the Receipts app and restart it:

       ZETARIS_BASE_URL=http://localhost:3000
       ZETARIS_API_KEY=<the API key>
       ZETARIS_ORG_ID=<numeric organisation ID>
       ZETARIS_JDBC_URL=jdbc:zetaris:lightning@localhost:10000 (optional, for JDBC tools)

Usage:

    python3 scripts/register_zetaris_sources.py            # print the SQL
    python3 scripts/register_zetaris_sources.py --out x.sql
    python3 scripts/register_zetaris_sources.py --register # execute it too
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zetaris_client


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export-dir",
        default=zetaris_client.DEFAULT_EXPORT_DIR,
        help="Directory holding runs.csv, claims.csv and sources.csv "
             "(default: the app export directory).",
    )
    parser.add_argument(
        "--database",
        default=zetaris_client.DATABASE_NAME,
        help="Lightning database name (default: receipts_evidence).",
    )
    parser.add_argument("--out", help="Write the SQL to this file instead of printing.")
    parser.add_argument(
        "--register",
        action="store_true",
        help="Also execute the statements against the Zetaris instance "
             "configured in the environment.",
    )
    args = parser.parse_args()

    export_dir = os.path.abspath(args.export_dir)
    file_paths = {
        table: os.path.join(export_dir, f"{table}.csv")
        for table in zetaris_client.TABLES
    }
    missing = [p for p in file_paths.values() if not os.path.exists(p)]
    if missing and not args.out:
        print(
            "Warning: these export files do not exist yet; run the app "
            "or one /evidence/insights call first:",
            file=sys.stderr,
        )
        for path in missing:
            print(f"  {path}", file=sys.stderr)

    statements = zetaris_client.registration_sql(file_paths, args.database)
    sql_text = "\n\n".join(stmt + ";" for stmt in statements) + "\n"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(sql_text)
        print(f"Wrote {len(statements)} statements to {args.out}")
    else:
        print(sql_text)

    if args.register:
        if not zetaris_client.zetaris_configured():
            print(
                "Cannot register: ZETARIS_BASE_URL and ZETARIS_API_KEY "
                "are not both set.",
                file=sys.stderr,
            )
            return 2
        results = zetaris_client.register_sources(file_paths, args.database)
        for res in results:
            status = "OK" if res["ok"] else f"FAILED: {res.get('error')}"
            print(f"[{status}] {res['sql']}")
        return 0 if all(r["ok"] for r in results) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
