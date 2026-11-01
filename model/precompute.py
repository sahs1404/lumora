"""
Precompute optimizer results for every village in data/villages.json.

The optimizer takes 1-2 minutes per run, too slow for a live app, so we solve
offline and the app reads results/<village_id>.json.

Run from the repo root:   python model/precompute.py
Faster test run:          python model/precompute.py --quick
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sizing_optimizer as so  # noqa: E402

# what-if scenarios shown in the app: name -> (label, how to change inputs)
SCENARIOS = {
    "base": "Base case",
    "mills3": "Finance 3 grain mills",
    "low_demand": "Demand comes in 50% below forecast (system already built)",
}


def run_village(v: dict, n_train: int, n_test: int) -> dict:
    f = v["forecast_kwh_customer_month"]
    kwh = (f["p10"], f["p50"], f["p90"])
    n_cust = v["features"]["est_customers"]
    biz = v["business_share_of_load"]
    out = {"village_id": v["id"], "scenarios": {}}
    base_rows = None
    for key, label in SCENARIOS.items():
        if key == "low_demand":
            # stress test: keep the systems already sized for the base case,
            # re-test them on scenarios where demand is half the forecast
            low = tuple(x * 0.5 for x in kwh)
            test = so.sample_scenarios(n_cust, low, biz, n_test, so.Tech(), seed=2024)
            rows = []
            for r in base_rows:
                d = so.Design(r["pv_kw"], r["batt_kwh"], r["diesel_kw"], r["design"])
                rows.append(so.evaluate(d, test))
        else:
            extra = so.mill_load_kw(3) if key == "mills3" else None
            rows = so.compare_designs(n_customers=n_cust, kwh=kwh, business_share=biz,
                                      n_train=n_train, n_test=n_test, extra_load_kw=extra)
            if key == "base":
                base_rows = rows
        out["scenarios"][key] = {"label": label, "designs": rows}
        print(f"  {v['id']} / {key}: Lumora reliable {rows[1]['reliable_share']}, "
              f"cost {rows[1]['cost_of_power_usd_kwh']} $/kWh")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="fewer scenarios, for testing")
    ap.add_argument("--only", help="run a single village id")
    a = ap.parse_args()
    n_train, n_test = (60, 300) if a.quick else (150, 1000)

    villages = json.loads((ROOT / "data" / "villages.json").read_text())["villages"]
    (ROOT / "results").mkdir(exist_ok=True)
    for v in villages:
        if a.only and v["id"] != a.only:
            continue
        print(f"Solving {v['name']} ...")
        res = run_village(v, n_train, n_test)
        res["settings"] = {"n_train": n_train, "n_test": n_test, "costs": "placeholder" }
        (ROOT / "results" / f"{v['id']}.json").write_text(json.dumps(res, indent=2, default=float))
    print("Done. Results in results/.")


if __name__ == "__main__":
    main()
