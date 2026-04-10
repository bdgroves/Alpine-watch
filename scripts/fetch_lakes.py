#!/usr/bin/env python3
"""
alpine-watch / fetch_lakes.py
================================
Pulls water quality and satellite-derived clarity data for
sentinel alpine lakes across the Sierra Nevada and Cascades.

Data sources:
  - USGS Water Quality Portal (WQP): chlorophyll-a, nutrients, clarity
  - NASA EarthData MODIS/Aqua: land surface temperature proxy
  - EPA WQX: supplemental nutrient data

Writes static JSON to docs/data/ for the GitHub Pages dashboard.

Brooks Groves · bdgroves/alpine-watch
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
import numpy as np

# ─────────────────────────────────────────────────────────────
# SENTINEL LAKE REGISTRY
# Hand-curated lakes with known USGS monitoring or WQP records.
# lat/lon used for MODIS pixel extraction.
# ─────────────────────────────────────────────────────────────
LAKES = [
    # ── SIERRA NEVADA ──────────────────────────────────────────
    {
        "id": "lake_tahoe",
        "name": "Lake Tahoe",
        "range": "Sierra Nevada",
        "state": "CA/NV",
        "elevation_ft": 6225,
        "lat": 39.0968,
        "lon": -120.0324,
        "usgs_site": "10337000",
        "wqp_org": "USGS-CA",
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
        "usgs_site": None,
        "wqp_org": "CEDEN",
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
        "usgs_site": None,
        "wqp_org": "CEDEN",
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
        "usgs_site": "395223119012901",
        "wqp_org": "USGS-CA",
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
        "usgs_site": None,
        "wqp_org": "CEDEN",
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
        "usgs_site": None,
        "wqp_org": "CEDEN",
        "notes": "Paired lakes; useful for spatial comparison",
    },
    # ── CASCADES — WASHINGTON ──────────────────────────────────
    {
        "id": "lake_chelan",
        "name": "Lake Chelan",
        "range": "North Cascades",
        "state": "WA",
        "elevation_ft": 1086,
        "lat": 47.8418,
        "lon": -120.0245,
        "usgs_site": "12447400",
        "wqp_org": "USGS-WA",
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
        "usgs_site": None,
        "wqp_org": "NWQMC",
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
        "usgs_site": None,
        "wqp_org": "NWQMC",
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
        "usgs_site": "453244122083201",
        "wqp_org": "USGS-WA",
        "notes": "Post-1980 eruption recovery; ongoing USGS monitoring",
    },
    # ── CASCADES — OREGON ─────────────────────────────────────
    {
        "id": "crater_lake",
        "name": "Crater Lake",
        "range": "Cascades",
        "state": "OR",
        "elevation_ft": 6178,
        "lat": 42.9446,
        "lon": -122.1090,
        "usgs_site": "422545122083500",
        "wqp_org": "NPS_NRSS",
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
        "usgs_site": None,
        "wqp_org": "ODEQ",
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
        "usgs_site": None,
        "wqp_org": "ODEQ",
        "notes": "Among purest lakes in North America; ultraoligotrophic baseline",
    },
]

# ─────────────────────────────────────────────────────────────
# WATER QUALITY PORTAL — WQP
# ─────────────────────────────────────────────────────────────
WQP_BASE = "https://www.waterqualitydata.us/data/Result/search"
WQP_CHARACTERISTICS = [
    "Chlorophyll a",
    "Chlorophyll a (probe relative fluorescence)",
    "Depth, Secchi disk depth",
    "Temperature, water",
    "Phosphorus",
    "Inorganic nitrogen (nitrate and nitrite)",
    "Turbidity",
]
LOOKBACK_DAYS = 365 * 5  # 5 years of history


def fetch_wqp_data(lake: dict) -> list[dict]:
    """
    Query USGS Water Quality Portal for a given lake.
    Returns list of observation records.
    """
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%m-%d-%Y")

    # Build lat/lon bounding box (~0.05 degree radius)
    lat, lon = lake["lat"], lake["lon"]
    bbox = f"{lon-0.05},{lat-0.05},{lon+0.05},{lat+0.05}"

    params = {
        "bBox": bbox,
        "characteristicName": "|".join(WQP_CHARACTERISTICS),
        "startDateLo": start_date,
        "mimeType": "json",
        "zip": "no",
        "dataProfile": "narrowResult",
    }

    try:
        resp = requests.get(WQP_BASE, params=params, timeout=30)
        resp.raise_for_status()
        records = resp.json()
        print(f"  WQP {lake['name']}: {len(records)} records")
        return records
    except Exception as e:
        print(f"  WQP {lake['name']} ERROR: {e}")
        return []


def parse_wqp_records(records: list[dict], lake_id: str) -> list[dict]:
    """
    Normalize WQP raw records into tidy observations.
    """
    parsed = []
    for r in records:
        try:
            val_str = r.get("ResultMeasureValue", "")
            unit = r.get("ResultMeasure/MeasureUnitCode", "")
            char = r.get("CharacteristicName", "")
            date_str = r.get("ActivityStartDate", "")

            if not val_str or val_str.strip() == "":
                continue

            val = float(val_str)
            parsed.append({
                "lake_id": lake_id,
                "date": date_str,
                "characteristic": char,
                "value": val,
                "unit": unit,
                "org": r.get("OrganizationIdentifier", ""),
                "activity_type": r.get("ActivityTypeCode", ""),
            })
        except (ValueError, TypeError):
            continue
    return parsed


def compute_lake_summary(observations: list[dict], lake: dict) -> dict:
    """
    Summarize observations into a dashboard-ready dict for one lake.
    Computes latest values, trend direction, and alert status.
    """
    if not observations:
        return {
            "id": lake["id"],
            "name": lake["name"],
            "range": lake["range"],
            "state": lake["state"],
            "elevation_ft": lake["elevation_ft"],
            "lat": lake["lat"],
            "lon": lake["lon"],
            "notes": lake["notes"],
            "status": "no_data",
            "alert_level": 0,
            "chlorophyll_latest": None,
            "chlorophyll_trend": None,
            "secchi_latest": None,
            "secchi_trend": None,
            "temp_latest": None,
            "phosphorus_latest": None,
            "last_sample_date": None,
            "sample_count": 0,
        }

    df = pd.DataFrame(observations)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    def latest_and_trend(char_key: str):
        """Return (latest_value, trend_slope) for a characteristic."""
        subset = df[df["characteristic"].str.contains(char_key, case=False, na=False)]
        if subset.empty:
            return None, None
        latest = subset.iloc[-1]["value"]
        if len(subset) >= 4:
            # Simple linear slope over recent observations
            x = np.arange(len(subset))
            slope = np.polyfit(x, subset["value"].values, 1)[0]
            trend = "rising" if slope > 0.01 else ("falling" if slope < -0.01 else "stable")
        else:
            trend = "insufficient_data"
        return round(latest, 3), trend

    chl_val, chl_trend = latest_and_trend("Chlorophyll")
    sec_val, sec_trend = latest_and_trend("Secchi")
    temp_val, _ = latest_and_trend("Temperature")
    phos_val, _ = latest_and_trend("Phosphorus")

    last_date = df["date"].max().strftime("%Y-%m-%d") if not df["date"].isna().all() else None

    # ── Alert logic ────────────────────────────────────────────
    # 0 = watch, 1 = caution, 2 = elevated, 3 = critical
    alert = 0
    if chl_val is not None:
        if chl_val > 10:
            alert = max(alert, 3)
        elif chl_val > 5:
            alert = max(alert, 2)
        elif chl_val > 2.5:
            alert = max(alert, 1)
    if chl_trend == "rising":
        alert = max(alert, 1)
    if sec_val is not None and sec_val < 3:  # <3m Secchi = turbid
        alert = max(alert, 2)

    alert_labels = {0: "WATCH", 1: "CAUTION", 2: "ELEVATED", 3: "CRITICAL"}

    return {
        "id": lake["id"],
        "name": lake["name"],
        "range": lake["range"],
        "state": lake["state"],
        "elevation_ft": lake["elevation_ft"],
        "lat": lake["lat"],
        "lon": lake["lon"],
        "notes": lake["notes"],
        "status": "ok",
        "alert_level": alert,
        "alert_label": alert_labels[alert],
        "chlorophyll_latest": chl_val,
        "chlorophyll_unit": "µg/L",
        "chlorophyll_trend": chl_trend,
        "secchi_latest": sec_val,
        "secchi_unit": "m",
        "secchi_trend": sec_trend,
        "temp_latest": temp_val,
        "temp_unit": "°C",
        "phosphorus_latest": phos_val,
        "phosphorus_unit": "mg/L",
        "last_sample_date": last_date,
        "sample_count": len(df),
    }


def build_chlorophyll_timeseries(observations: list[dict]) -> list[dict]:
    """
    Return monthly-averaged chlorophyll-a timeseries for sparkline charts.
    """
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
    return [{"month": row["month"], "chl": round(row["value"], 3)}
            for _, row in monthly.iterrows()]


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"  ALPINE-WATCH  //  fetch_lakes.py")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    os.makedirs("docs/data", exist_ok=True)

    all_summaries = []
    lake_detail = {}

    for lake in LAKES:
        print(f"── {lake['name']} ({lake['state']}) ──")
        raw_records = fetch_wqp_data(lake)
        observations = parse_wqp_records(raw_records, lake["id"])
        summary = compute_lake_summary(observations, lake)
        timeseries = build_chlorophyll_timeseries(observations)

        all_summaries.append(summary)
        lake_detail[lake["id"]] = {
            "summary": summary,
            "chlorophyll_timeseries": timeseries,
        }

        time.sleep(0.5)  # polite rate limiting

    # ── Write lakes.json (dashboard overview) ─────────────────
    meta = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "lake_count": len(LAKES),
        "ranges": ["Sierra Nevada", "Eastern Sierra", "North Cascades",
                   "Olympics", "Cascades", "Cascades / St. Helens"],
        "data_source": "USGS Water Quality Portal (WQP)",
        "note": "Chlorophyll-a threshold: >10 µg/L = eutrophic per EPA NLA",
    }
    output = {"meta": meta, "lakes": all_summaries}
    with open("docs/data/lakes.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n✓ Wrote docs/data/lakes.json ({len(all_summaries)} lakes)")

    # ── Write per-lake detail files ────────────────────────────
    for lake_id, detail in lake_detail.items():
        path = f"docs/data/{lake_id}.json"
        with open(path, "w") as f:
            json.dump(detail, f, indent=2)
    print(f"✓ Wrote {len(lake_detail)} per-lake detail files")

    # ── Write run manifest ─────────────────────────────────────
    manifest = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "status": "success",
        "lakes_fetched": len(LAKES),
        "source": "USGS WQP",
    }
    with open("docs/data/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"✓ Wrote docs/data/manifest.json\n")
    print("DONE.\n")


if __name__ == "__main__":
    main()
