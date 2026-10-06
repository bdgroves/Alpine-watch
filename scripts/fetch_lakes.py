#!/usr/bin/env python3
"""
alpine-watch / fetch_lakes.py — ground truth from the Water Quality Portal
==========================================================================
For every lake in lakes.yaml with `wqp: true`: surface samples (top 3 m) of
chlorophyll-a, Secchi depth, water temperature and total phosphorus since 2019,
inside the lake's own outline box, with units put on one footing.

Writes docs/data/lakes.json and docs/data/<id>.json (the dashboard's "on the
ground" panel) and docs/data/manifest.json, which says honestly how many lakes
had any samples at all.

Brooks Groves · bdgroves/Alpine-watch
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

import dataretrieval.wqp as wqp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data"
START = "01-01-2019"
CHARS = {
    "chl": ["Chlorophyll a", "Chlorophyll a, corrected for pheophytin", "Chlorophyll a, uncorrected for pheophytin"],
    "secchi": ["Depth, Secchi disk depth"],
    "temp": ["Temperature, water"],
    "tp": ["Phosphorus"],
}
UNIT = {   # to µg/L for chl, m for Secchi, °C for temperature, mg/L for phosphorus
    "chl": {"ug/l": 1, "µg/l": 1, "mg/m3": 1, "ug/l chla": 1, "mg/l": 1000, "ppb": 1},
    "secchi": {"m": 1, "ft": 0.3048, "in": 0.0254, "cm": 0.01},
    "tp": {"mg/l": 1, "mg/l as p": 1, "ug/l": 0.001, "µg/l": 0.001, "ppb": 0.001, "mg/l p": 1},
}


def bbox(lake):
    p = ROOT / "data" / "outlines" / f"{lake['id']}.geojson"
    if p.exists():
        from shapely.geometry import shape
        g = shape(json.loads(p.read_text())["features"][0]["geometry"])
        w, s, e, n = g.bounds
        return f"{w - .005:.4f},{s - .005:.4f},{e + .005:.4f},{n + .005:.4f}"
    lat, lon = lake["lat"], lake["lon"]
    return f"{lon - .05:.4f},{lat - .05:.4f},{lon + .05:.4f},{lat + .05:.4f}"


def fetch(lake):
    frames, errors = [], []
    for key, names in CHARS.items():
        for name in names:
            try:
                df, _ = wqp.get_results(bBox=bbox(lake), characteristicName=name, startDateLo=START)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {e.__class__.__name__}")
                continue
            if df is not None and not df.empty:
                df = df.copy()
                df["key"] = key
                frames.append(df)
            time.sleep(1.0)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), errors


def tidy(df):
    if df.empty:
        return df
    c = df.columns
    out = pd.DataFrame({
        "key": df["key"],
        "date": pd.to_datetime(df.get("ActivityStartDate"), errors="coerce"),
        "value": pd.to_numeric(df.get("ResultMeasureValue"), errors="coerce"),
        "unit": df.get("ResultMeasure/MeasureUnitCode", pd.Series("", index=df.index)).astype(str).str.strip().str.lower(),
        "fraction": df.get("ResultSampleFractionText", pd.Series("", index=df.index)).astype(str),
        "depth": pd.to_numeric(df.get("ActivityDepthHeightMeasure/MeasureValue"), errors="coerce"),
        "depth_unit": df.get("ActivityDepthHeightMeasure/MeasureUnitCode", pd.Series("", index=df.index)).astype(str).str.lower(),
        "org": df.get("OrganizationIdentifier", pd.Series("", index=df.index)).astype(str),
    }).dropna(subset=["date", "value"])
    out.loc[out.depth_unit.str.startswith("ft"), "depth"] *= 0.3048
    keep = out.depth.isna() | (out.depth <= 3) | (out.key == "secchi")
    out = out[keep]
    rows = []
    for key, g in out.groupby("key"):
        if key == "temp":
            g = g.copy()
            f = g.unit.str.contains("f")
            g.loc[f, "value"] = (g.loc[f, "value"] - 32) / 1.8
            rows.append(g[g.value.between(-1, 35)])
            continue
        if key == "tp":
            g = g[g.fraction.str.contains("total", case=False, na=False) | (g.fraction.isin(["", "nan"]))]
        factor = g.unit.map(UNIT[key])
        g = g[factor.notna()].copy()
        g["value"] = g.value * factor[factor.notna()]
        rows.append(g)
    return pd.concat(rows) if rows else out.iloc[0:0]


def summary(lake, t, errors):
    base = {k: lake.get(k) for k in ("id", "name", "range", "state", "elevation_ft", "lat", "lon")}
    if t.empty:
        return {**base, "status": "no_data", "sample_count": 0, "errors": errors[:5]}, []

    def latest(key):
        g = t[t.key == key].sort_values("date")
        return (round(float(g.value.iloc[-1]), 3), g.date.iloc[-1].date().isoformat()) if len(g) else (None, None)

    chl, chl_d = latest("chl")
    sec, sec_d = latest("secchi")
    tmp, _ = latest("temp")
    tp, _ = latest("tp")
    # summer (Jun-Sep) chlorophyll medians by year, for the detail chart
    ch = t[(t.key == "chl") & t.date.dt.month.between(6, 9)]
    yearly = [{"year": int(y), "chl": round(float(g.value.median()), 2), "n": int(len(g))}
              for y, g in ch.groupby(ch.date.dt.year)]
    return {**base, "status": "ok", "sample_count": int(len(t)),
            "last_sample_date": t.date.max().date().isoformat(),
            "chlorophyll_latest": chl, "chlorophyll_date": chl_d,
            "secchi_latest": sec, "secchi_date": sec_d,
            "temp_latest": tmp, "phosphorus_latest_mg_l": tp,
            "orgs": sorted(set(t.org))[:6], "errors": errors[:5]}, yearly


def main():
    lakes = [l for l in yaml.safe_load((ROOT / "lakes.yaml").read_text())["lakes"] if l.get("wqp")]
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for lake in lakes:
        raw, errors = fetch(lake)
        t = tidy(raw)
        s, yearly = summary(lake, t, errors)
        rows.append(s)
        (OUT / f"{lake['id']}.json").write_text(json.dumps({"summary": s, "summer_chlorophyll": yearly}, indent=1))
        print(f"= {lake['name']}: {s['sample_count']} surface samples"
              + (f", latest {s.get('last_sample_date')}" if s["status"] == "ok" else "")
              + (f" ({len(errors)} query errors)" if errors else ""))
    n_ok = sum(r["status"] == "ok" for r in rows)
    meta = {"updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "Water Quality Portal (USGS, EPA, states) via dataretrieval-python", "since": START}
    (OUT / "lakes.json").write_text(json.dumps({"meta": meta, "lakes": rows}, indent=1))
    (OUT / "manifest.json").write_text(json.dumps({
        "last_run": meta["updated_utc"], "lakes_queried": len(rows), "lakes_with_samples": n_ok,
        "status": "ok" if n_ok else "no ground data returned"}, indent=1))
    print(f"= ground truth: {n_ok} of {len(rows)} lakes have samples since 2019")


if __name__ == "__main__":
    main()
