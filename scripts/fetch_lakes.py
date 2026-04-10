#!/usr/bin/env python3
"""
alpine-watch / fetch_lakes.py
================================
Pulls water quality data for sentinel alpine lakes across the
Sierra Nevada and Cascades.

Data source: USGS Water Quality Portal via dataretrieval-python
  wqp.get_results() with explicit bBox kwarg format.

Brooks Groves · bdgroves/alpine-watch
"""

import json
import os
import time
from datetime import datetime, timezone

import dataretrieval.wqp as wqp
import pandas as pd
import numpy as np

LAKES = [
    {
        "id": "lake_tahoe",
        "name": "Lake Tahoe",
        "range": "Sierra Nevada",
        "state": "CA/NV",
        "elevation_ft": 6225,
        "lat": 39.0968,
        "lon": -120.0324,
        "notes": "Iconic clarity barometer; decades of Secchi depth records",
    },
    {
        "id": "fallen_leaf",
        "name": "Fallen Leaf Lake",
        "range": "Sierra Nevada",
        "state": "CA",
        "elevation_ft": 6377,
        "lat": 38.8968,
        "lon": -120.0574,
        "notes": "Tahoe-adjacent; sensitive canary for basin nutrient loading",
    },
    {
        "id": "donner_lake",
        "name": "Donner Lake",
        "range": "Sierra Nevada",
        "state": "CA",
        "elevation_ft": 5936,
        "lat": 39.3196,
        "lon": -120.2296,
        "notes": "Recreation pressure + highway runoff; historical eutrophication",
    },
    {
        "id": "mono_lake",
        "name": "Mono Lake",
        "range": "Eastern Sierra",
        "state": "CA",
        "elevation_ft": 6383,
        "lat": 37.9799,
        "lon": -119.0198,
        "notes": "Saline terminal lake; water level + salinity are primary indicators",
    },
    {
        "id": "convict_lake",
        "name": "Convict Lake",
        "range": "Sierra Nevada",
        "state": "CA",
        "elevation_ft": 7583,
        "lat": 37.5896,
        "lon": -118.8577,
        "notes": "High-alpine; benchmarked against pristine baselines",
    },
    {
        "id": "twin_lakes_bridgeport",
        "name": "Twin Lakes (Bridgeport)",
        "range": "Eastern Sierra",
        "state": "CA",
        "elevation_ft": 7000,
        "lat": 38.2010,
        "lon": -119.3510,
        "notes": "Paired lakes; useful for spatial comparison",
    },
    {
        "id": "lake_chelan",
        "name": "Lake Chelan",
        "range": "North Cascades",
        "state": "WA",
        "elevation_ft": 1086,
        "lat": 47.8418,
        "lon": -120.0245,
        "notes": "One of deepest lakes in North America; exceptional clarity baseline",
    },
    {
        "id": "diablo_lake",
        "name": "Diablo Lake",
        "range": "North Cascades",
        "state": "WA",
        "elevation_ft": 1201,
        "lat": 48.7154,
        "lon": -121.1376,
        "notes": "Brilliant glacier-flour turquoise; color shift = glacial health signal",
    },
    {
        "id": "lake_cushman",
        "name": "Lake Cushman",
        "range": "Olympics",
        "state": "WA",
        "elevation_ft": 738,
        "lat": 47.4685,
        "lon": -123.2785,
        "notes": "Olympic Peninsula reservoir; lower-elevation comparison site",
    },
    {
        "id": "spirit_lake",
        "name": "Spirit Lake",
        "range": "Cascades / St. Helens",
        "state": "WA",
        "elevation_ft": 3417,
        "lat": 46.2754,
        "lon": -122.1413,
        "notes": "Post-1980 eruption recovery; ongoing USGS monitoring",
    },
    {
        "id": "crater_lake",
        "name": "Crater Lake",
        "range": "Cascades",
        "state": "OR",
        "elevation_ft": 6178,
        "lat": 42.9446,
        "lon": -122.1090,
        "notes": "Deepest U.S. lake; world clarity record holder; NPS long-term monitoring",
    },
    {
        "id": "odell_lake",
        "name": "Odell Lake",
        "range": "Cascades",
        "state": "OR",
        "elevation_ft": 4787,
        "lat": 43.5568,
        "lon": -122.0054,
        "notes": "High-elevation Cascade lake; oligotrophic benchmark",
    },
    {
        "id": "waldo_lake",
        "name": "Waldo Lake",
        "range": "Cascades",
        "state": "OR",
        "elevation_ft": 5414,
        "lat": 43.7318,
        "lon": -122.0454,
        "notes": "Among purest lakes in North America; ultraoligotrophic baseline",
    },
]

CHARACTERISTICS = [
    "Chlorophyll a",
    "Depth, Secchi disk depth",
    "Temperature, water",
    "Phosphorus",
]

START_DATE = "01-01-2019"


def fetch_lake(lake: dict) -> pd.DataFrame:
    """
    Fetch water quality data for one lake.
    Passes bBox as a comma-separated string — the format WQP expects.
    """
    lat, lon = lake["lat"], lake["lon"]
    # WQP bBox format: "W-lon,S-lat,E-lon,N-lat"
    bbox_str = f"{lon-0.05:.4f},{lat-0.05:.4f},{lon+0.05:.4f},{lat+0.05:.4f}"

    frames = []
    for char in CHARACTERISTICS:
        try:
            df, _ = wqp.get_results(
                **{
                    "bBox": bbox_str,
                    "characteristicName": char,
                    "startDateLo": START_DATE,
                }
            )
            if df is not None and not df.empty:
                frames.append(df)
                print(f"    [{char}]: {len(df)} records")
            else:
                print(f"    [{char}]: 0 records")
        except Exception as e:
            print(f"    [{char}] ERROR: {e}")
        time.sleep(1.5)

    if not frames:
        print(f"  {lake['name']}: 0 records total")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    print(f"  {lake['name']}: {len(combined)} records total")
    return combined


def parse_df(df: pd.DataFrame, lake_id: str) -> list[dict]:
    """Normalize WQP DataFrame into tidy observation list."""
    if df.empty:
        return []

    cols = set(df.columns)

    def get_col(candidates):
        for c in candidates:
            if c in cols:
                return c
        return None

    val_col  = get_col(["ResultMeasureValue"])
    char_col = get_col(["CharacteristicName"])
    date_col = get_col(["ActivityStartDate"])
    unit_col = get_col(["ResultMeasure/MeasureUnitCode", "MeasureUnitCode"])
    org_col  = get_col(["OrganizationIdentifier"])

    if not val_col or not char_col or not date_col:
        print(f"  WARNING: missing columns for {lake_id}: {list(df.columns[:8])}")
        return []

    parsed = []
    for _, row in df.iterrows():
        try:
            val_str = str(row.get(val_col, "")).strip()
            if val_str in ("", "nan", "None", "ND", "NaN"):
                continue
            val = float(val_str)
            parsed.append({
                "lake_id":        lake_id,
                "date":           str(row.get(date_col, "")),
                "characteristic": str(row.get(char_col, "")),
                "value":          val,
                "unit":           str(row.get(unit_col, "")) if unit_col else "",
                "org":            str(row.get(org_col, "")) if org_col else "",
            })
        except (ValueError, TypeError):
            continue
    return parsed


def compute_summary(observations: list[dict], lake: dict) -> dict:
    """Compute dashboard summary with EPA NLA alert levels."""
    if not observations:
        return {
            "id": lake["id"], "name": lake["name"], "range": lake["range"],
            "state": lake["state"], "elevation_ft": lake["elevation_ft"],
            "lat": lake["lat"], "lon": lake["lon"], "notes": lake["notes"],
            "status": "no_data", "alert_level": 0, "alert_label": "WATCH",
            "chlorophyll_latest": None, "chlorophyll_unit": "µg/L",
            "chlorophyll_trend": None,
            "secchi_latest": None, "secchi_unit": "m", "secchi_trend": None,
            "temp_latest": None, "temp_unit": "°C",
            "phosphorus_latest": None, "phosphorus_unit": "mg/L",
            "last_sample_date": None, "sample_count": 0,
        }

    df = pd.DataFrame(observations)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    def latest_and_trend(key):
        sub = df[df["characteristic"].str.contains(key, case=False, na=False)]
        if sub.empty:
            return None, None
        latest = sub.iloc[-1]["value"]
        if len(sub) >= 4:
            slope = np.polyfit(np.arange(len(sub)), sub["value"].values, 1)[0]
            trend = "rising" if slope > 0.01 else ("falling" if slope < -0.01 else "stable")
        else:
            trend = "insufficient_data"
        return round(latest, 3), trend

    chl_val, chl_trend = latest_and_trend("Chlorophyll")
    sec_val, sec_trend = latest_and_trend("Secchi")
    temp_val, _        = latest_and_trend("Temperature")
    phos_val, _        = latest_and_trend("Phosphorus")
    last_date = df["date"].max().strftime("%Y-%m-%d") if not df["date"].isna().all() else None

    alert = 0
    if chl_val is not None:
        if chl_val > 10:     alert = max(alert, 3)
        elif chl_val > 5:    alert = max(alert, 2)
        elif chl_val > 2.5:  alert = max(alert, 1)
    if chl_trend == "rising":
        alert = max(alert, 1)
    if sec_val is not None and sec_val < 3:
        alert = max(alert, 2)

    labels = {0: "WATCH", 1: "CAUTION", 2: "ELEVATED", 3: "CRITICAL"}
    return {
        "id": lake["id"], "name": lake["name"], "range": lake["range"],
        "state": lake["state"], "elevation_ft": lake["elevation_ft"],
        "lat": lake["lat"], "lon": lake["lon"], "notes": lake["notes"],
        "status": "ok", "alert_level": alert, "alert_label": labels[alert],
        "chlorophyll_latest": chl_val, "chlorophyll_unit": "µg/L",
        "chlorophyll_trend": chl_trend,
        "secchi_latest": sec_val, "secchi_unit": "m", "secchi_trend": sec_trend,
        "temp_latest": temp_val, "temp_unit": "°C",
        "phosphorus_latest": phos_val, "phosphorus_unit": "mg/L",
        "last_sample_date": last_date, "sample_count": len(df),
    }


def build_timeseries(observations: list[dict]) -> list[dict]:
    """Monthly-averaged chlorophyll-a for sparklines."""
    if not observations:
        return []
    df = pd.DataFrame(observations)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    chl = df[df["characteristic"].str.contains("Chlorophyll", case=False, na=False)].copy()
    if chl.empty:
        return []
    chl = chl.dropna(subset=["date", "value"])
    chl["month"] = chl["date"].dt.to_period("M").astype(str)
    monthly = chl.groupby("month")["value"].mean().reset_index()
    return [{"month": r["month"], "chl": round(r["value"], 3)} for _, r in monthly.iterrows()]


def main():
    print(f"\n{'='*60}")
    print(f"  ALPINE-WATCH  //  fetch_lakes.py")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Source: dataretrieval-python / USGS WQP legacy endpoint")
    print(f"{'='*60}\n")

    os.makedirs("docs/data", exist_ok=True)
    all_summaries, lake_detail = [], {}

    for lake in LAKES:
        print(f"── {lake['name']} ({lake['state']}) ──")
        df      = fetch_lake(lake)
        obs     = parse_df(df, lake["id"])
        summary = compute_summary(obs, lake)
        ts      = build_timeseries(obs)
        all_summaries.append(summary)
        lake_detail[lake["id"]] = {"summary": summary, "chlorophyll_timeseries": ts}
        time.sleep(2.0)

    meta = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "lake_count": len(LAKES),
        "data_source": "USGS Water Quality Portal via dataretrieval-python",
        "note": "Chlorophyll-a threshold: >10 µg/L = eutrophic per EPA NLA",
    }
    with open("docs/data/lakes.json", "w") as f:
        json.dump({"meta": meta, "lakes": all_summaries}, f, indent=2)
    print(f"\n✓ Wrote docs/data/lakes.json ({len(all_summaries)} lakes)")

    for lake_id, detail in lake_detail.items():
        with open(f"docs/data/{lake_id}.json", "w") as f:
            json.dump(detail, f, indent=2)
    print(f"✓ Wrote {len(lake_detail)} per-lake detail files")

    with open("docs/data/manifest.json", "w") as f:
        json.dump({
            "last_run": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "lakes_fetched": len(LAKES),
            "source": "dataretrieval-python / USGS WQP",
        }, f, indent=2)
    print(f"✓ Wrote docs/data/manifest.json\n")
    print("DONE.\n")


if __name__ == "__main__":
    main()
