"""
Run the full support analytics pipeline:
    load exports  ->  clean  ->  load staging  ->  quality checks  ->  SQL metrics  ->  exports

    python run_pipeline.py

Outputs:
    data/warehouse.duckdb   staging tables and metric tables
    data/powerbi/*.csv      metric tables ready for Power BI, QuickSight or any BI tool
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import duckdb

from pipeline.clean import clean_all, load_raw
from pipeline.quality import run_checks

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "warehouse.duckdb"
MARTS = ROOT / "models" / "marts"
EXPORT = ROOT / "data" / "powerbi"


def table_name(sql_file: Path) -> str:
    return re.sub(r"^\d+_", "", sql_file.stem)   # "00_int_contacts" -> "int_contacts"


def main() -> int:
    print("1/5 Loading helpdesk, chatbot, order and help centre exports")
    raw = load_raw()
    for name, df in raw.items():
        print(f"     {name:<18} {len(df):>8,} rows")

    print("2/5 Cleaning, standardising tags and classifying untagged contacts")
    clean, cleaning_log = clean_all(raw)

    print("3/5 Loading staging tables")
    DB_PATH.unlink(missing_ok=True)
    con = duckdb.connect(str(DB_PATH))
    for name, df in {**clean, "cleaning_log": cleaning_log}.items():
        con.register("tmp", df)
        con.execute(f"CREATE TABLE {'meta' if name == 'cleaning_log' else 'stg'}_{name} AS SELECT * FROM tmp")
        con.unregister("tmp")

    print("4/5 Running data quality checks")
    checks = run_checks(con)
    con.register("tmp", checks)
    con.execute("CREATE TABLE meta_quality_checks AS SELECT * FROM tmp")
    con.unregister("tmp")
    for _, r in checks.iterrows():
        print(f"     [{r['status']:<4}] {r['check']} ({r['failing_rows']:,} rows)")
    if (checks["status"] == "FAIL").any():
        print("Pipeline stopped: a FAIL check must be fixed before metrics are rebuilt.")
        return 1

    print("5/5 Building metric tables and exports")
    EXPORT.mkdir(parents=True, exist_ok=True)
    for sql_file in sorted(MARTS.glob("*.sql")):
        name = table_name(sql_file)
        con.execute(f"CREATE TABLE {name} AS {sql_file.read_text().rstrip().rstrip(';')}")
        n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"     {name:<22} {n:>8,} rows")
        con.execute(f"COPY {name} TO '{(EXPORT / (name + '.csv')).as_posix()}' (HEADER, DELIMITER ',')")
    for name in ["meta_quality_checks", "meta_cleaning_log"]:
        con.execute(f"COPY {name} TO '{(EXPORT / (name + '.csv')).as_posix()}' (HEADER, DELIMITER ',')")

    con.close()
    print(f"Done. Warehouse: {DB_PATH.relative_to(ROOT)} | exports: {EXPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
