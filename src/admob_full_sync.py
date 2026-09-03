#!/usr/bin/env python3
"""
AdMob dimension health check
============================
repo path: .github/scripts/dim_health.py

Run #214 (2026-09-03) mein `admob_ad_units_dim` se pub-5972202469838280 ki
SAARI 5,713 rows ud gayi thin — DELETE chali, uske baad adUnits par 401 aaya,
load kabhi hua hi nahi. Script `exit 1` de kar mar gayi, magar table din bhar
khaali padi rahi aur kisi ko pata nahi chala.

Ye check har run ke baad (`if: always()`) chalta hai aur job ko FAIL karta hai
agar is publisher ki koi bhi dimension table khaali ho — chahe sync khud
"success" keh chuki ho.
"""

import json
import os
import sys

from google.cloud import bigquery
from google.oauth2 import service_account

# .strip() lazmi — secrets mein trailing space/newline aam hai. Apple ke
# apple_console_terafort_us repo mein isi ki wajah se har query BadRequest
# de rahi thi jabke data bilkul theek tha.
PROJECT = os.environ["GCP_PROJECT_ID"].strip()
DATASET = os.environ.get("BQ_DATASET_ID", "Admob").strip() or "Admob"
LOCATION = os.environ.get("BQ_LOCATION", "US").strip() or "US"
PUBLISHER = os.environ["ADMOB_PUBLISHER_ID"].replace("accounts/", "").strip()

# table -> kam se kam kitni rows honi chahiye
EXPECTED = {
    "admob_account_dim": 1,
    "admob_apps_dim": 1,
    "admob_ad_units_dim": 1,
}


def main() -> int:
    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GCP_CREDENTIALS_JSON"]),
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    bq = bigquery.Client(project=PROJECT, credentials=creds, location=LOCATION)

    print(f"\n-- dimension health: {PROJECT}.{DATASET} / {PUBLISHER} " + "-" * 20)

    failed = []
    for table, minimum in EXPECTED.items():
        try:
            rows = list(
                bq.query(
                    f"SELECT COUNT(*) AS n, "
                    f"CAST(MAX(sync_timestamp) AS STRING) AS last_sync "
                    f"FROM `{PROJECT}.{DATASET}.{table}` "
                    f"WHERE publisher_id = @p",
                    job_config=bigquery.QueryJobConfig(
                        query_parameters=[
                            bigquery.ScalarQueryParameter("p", "STRING", PUBLISHER)
                        ]
                    ),
                ).result()
            )[0]
            n, last_sync = rows["n"], rows["last_sync"]
            mark = "OK   " if n >= minimum else "EMPTY"
            print(f"   [{mark}] {table:<22} {n:>8,} rows   last_sync={last_sync}")
            if n < minimum:
                failed.append(table)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the check
            print(f"   [ERROR] {table:<22} {type(exc).__name__}: {exc}")
            failed.append(table)

    # Fact table freshness — dims bhari hon magar fact purani ho to bhi problem
    try:
        row = list(
            bq.query(
                f"SELECT CAST(MAX(report_date) AS STRING) AS last_dt, "
                f"DATE_DIFF(CURRENT_DATE(), MAX(report_date), DAY) AS stale "
                f"FROM `{PROJECT}.{DATASET}.admob_unified_fact` "
                f"WHERE publisher_id = @p",
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("p", "STRING", PUBLISHER)
                    ]
                ),
            ).result()
        )[0]
        stale = row["stale"]
        mark = "OK   " if stale is not None and stale <= 4 else "STALE"
        print(f"   [{mark}] admob_unified_fact     last={row['last_dt']} ({stale}d old)")
    except Exception as exc:  # noqa: BLE001
        print(f"   [ERROR] admob_unified_fact  {type(exc).__name__}: {exc}")

    if failed:
        print("\n:: DIMENSION TABLE EMPTY FOR THIS PUBLISHER ::")
        print(f"   Affected: {', '.join(failed)}")
        print("   Ye #214 wali shakl hai: DELETE chali, fetch mara, load nahi hua.")
        print("   -> Workflow dobara chalao. Agar phir bhi khaali rahe to AdMob")
        print("      API is account ke liye apps/adUnits list refuse kar rahi hai.")
        return 1

    print("\n   Dimension health OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
