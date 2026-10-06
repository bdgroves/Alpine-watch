#!/usr/bin/env python3
"""
Turn the per-scene satellite readings into what the dashboard shows.

For each lake, summer by summer (July to September, ice-free scenes only):
  colour     median hue angle and its Forel-Ule number (lower hue = greener)
  NDCI       median chlorophyll index
  temp       Landsat surface temperature, July and August
  ice-out    the spring date the lake opened up, from Sentinel-2's ice class

Each lake is judged against its own past: this summer's values against the
median and spread of the summers before it. Writes docs/data/space.json
(overview) and docs/data/space/<id>.json (detail).
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

import fu
from shapely.geometry import shape
from shapely.ops import transform as shp_transform
from pyproj import Transformer

THERMAL_CORE_HA = 5.0   # open water 150 m+ from shore needed for Landsat's 100 m thermal pixels


def thermal_ok(lake, reg):
    """Landsat's thermal band sees 100 m pixels: in a narrow lake every pixel mixes
    in sun-baked granite from the shore, and reads hot. Only trust it where there's
    a core of water at least 150 m from any shore."""
    g = reg.get("sample_geom")
    if not g:
        return False
    zone = int((lake["lon"] + 180) // 6) + 1
    t = Transformer.from_crs("EPSG:4326", f"EPSG:{32600 + zone}", always_xy=True).transform
    core = shp_transform(t, shape(g)).buffer(-(150 - reg.get("s2_buffer_m", 40)))
    return (core.area / 1e4) >= THERMAL_CORE_HA

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "data" / "space"
OUT = ROOT / "docs" / "data"
SUMMER = (7, 8, 9)
WARM = (7, 8)
LABELS = {0: "STEADY", 1: "WATCH", 2: "ELEVATED", 3: "ALERT"}
MIN_SCENES = 3          # scenes for a summer to count
MIN_YEARS = 3           # summers of baseline before judging
# ESA moved Sentinel-2 to processing baseline 04.00 in January 2022, and the
# archive before that was corrected with older versions of Sen2Cor. Over dark
# water the change is big enough to shift the colour of most lakes by itself
# (bluer, less red-edge), so colour and NDCI are only compared from 2022 on.
COLOUR_FROM = 2022


def robust(vals, floor):
    v = np.asarray([x for x in vals if x is not None and not math.isnan(x)], float)
    if v.size == 0:
        return None, None
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) * 1.4826
    return med, max(mad, floor)


def ice_out(s2: pd.DataFrame):
    """Day-of-year the lake opened, per year, from Sentinel-2's ice/snow class."""
    out = {}
    if s2.empty or "f_ice" not in s2:
        return out, False
    d = s2.dropna(subset=["f_ice", "f_water"]).copy()
    d = d[(d.f_cloud.fillna(0) < 0.3) & (d.f_nodata.fillna(0) < 0.2)]
    d["date"] = pd.to_datetime(d["date"])
    # Sen2Cor sometimes calls cloud "snow", so a lake only counts as one that
    # freezes if a clear March or April look shows it ice-covered in 3+ years.
    w = d[(d.date.dt.month <= 4) & (d.f_cloud < 0.05) & (d.f_ice >= 0.8)]
    freezes = w.date.dt.year.nunique() >= 3
    if not freezes:
        return out, False
    for yr, g in d[d.date.dt.month.between(3, 8)].groupby(d.date.dt.year):
        g = g.sort_values("date")
        icy = g[g.f_ice >= 0.5]
        if icy.empty:
            continue
        last_ice = icy.date.max()
        opened = g[(g.date > last_ice) & (g.f_water >= 0.8) & (g.f_ice < 0.05)]
        if opened.empty:
            continue
        first_open = opened.date.min()
        gap = (first_open - last_ice).days
        if gap > 24:
            continue
        mid = last_ice + (first_open - last_ice) / 2
        out[int(yr)] = {"doy": int(mid.dayofyear), "date": mid.date().isoformat(),
                        "between": [last_ice.date().isoformat(), first_open.date().isoformat()]}
    return out, freezes


# A scene counts for colour only if the water looks like water: almost no cloud or
# ice over the lake, dark in the near-infrared (haze, smoke, glint, ice and slush
# all brighten it), and not under a smoke plume by Sen2Cor's aerosol estimate.
NIR_MAX = 0.02
AOT_MAX = 0.30


def clean(s2: pd.DataFrame) -> pd.DataFrame:
    if s2.empty or "B02" not in s2:
        return s2.iloc[0:0]
    d = s2.copy()
    rec = d.apply(lambda r: pd.Series(fu.reading({k: r.get(k) for k in ("B01", "B02", "B03", "B04", "B05")},
                                                 str(r.get("sat", "2A")))), axis=1)
    for c in ("hue", "fu", "swatch", "ndci"):
        d[c] = rec[c]
    ok = (d.f_water.fillna(0) >= 0.7) & (d.f_ice.fillna(0) < 0.02) & (d.f_cloud.fillna(0) < 0.1) \
        & (d.B08.fillna(1) < NIR_MAX) & d.hue.notna()
    if "aot" in d:
        ok &= d.aot.fillna(0) < AOT_MAX
    return d[ok]


def yearly(s2: pd.DataFrame, ls: pd.DataFrame):
    years = {}
    if not s2.empty:
        d = clean(s2)
        d["date"] = pd.to_datetime(d["date"])
        d = d[d.date.dt.month.isin(SUMMER) & (d.date.dt.year >= COLOUR_FROM)]
        for yr, g in d.groupby(d.date.dt.year):
            if len(g) < MIN_SCENES:
                continue
            hue = float(g.hue.median())
            years.setdefault(int(yr), {}).update({
                "hue": round(hue, 1), "fu": fu.forel_ule(hue),
                "ndci": round(float(g.ndci.median()), 4) if g.ndci.notna().any() else None,
                "n_s2": int(len(g))})
    if not ls.empty and "lswt_c" in ls:
        d = ls.dropna(subset=["lswt_c"]).copy()
        d["date"] = pd.to_datetime(d["date"])
        d = d[d.date.dt.month.isin(WARM)]
        for yr, g in d.groupby(d.date.dt.year):
            if len(g) < 2:
                continue
            years.setdefault(int(yr), {}).update({
                "lswt": round(float(g.lswt_c.median()), 1), "n_ls": int(len(g))})
    return years


def judge(years: dict, ice: dict, now_year: int, kind: str = "clear"):
    """This summer against the lake's own baseline."""
    ys = sorted(years)
    cur_year = max((y for y in ys if {"hue", "lswt", "ice_out_doy"} & set(years[y])), default=None)
    if cur_year is None:
        return None
    base = [y for y in ys if y < cur_year]
    cur = years[cur_year]
    sig = {}

    def z_of(key, floor, sign):
        b = [years[y][key] for y in base if years[y].get(key) is not None]
        if len(b) < MIN_YEARS or cur.get(key) is None:
            return None
        med, spread = robust(b, floor)
        z = sign * (cur[key] - med) / spread
        return {"now": cur[key], "baseline": round(med, 3), "spread": round(spread, 3),
                "z": round(z, 2), "years": len(b)}

    sig["colour"] = z_of("hue", 8.0, -1)          # hue falling = greener; 8° floor: summers swing that much on their own
    sig["ndci"] = z_of("ndci", 0.02, +1)
    sig["temp"] = z_of("lswt", 0.75, +1)
    ice_base = [ice[y]["doy"] for y in ice if y < cur_year]
    if cur_year in ice and len(ice_base) >= MIN_YEARS:
        med, spread = robust(ice_base, 5)
        sig["ice_out"] = {"now": ice[cur_year]["doy"], "baseline": round(med), "spread": round(spread, 1),
                          "z": round(-(ice[cur_year]["doy"] - med) / spread, 2), "years": len(ice_base)}
    else:
        sig["ice_out"] = None

    zs = {k: v["z"] for k, v in sig.items() if v}
    if not zs:
        return {"year": cur_year, "level": None, "label": "BASELINE", "signals": sig,
                "why": "Not enough past summers yet to say what normal looks like."}
    # Diablo's colour is glacial flour and Mono's is brine shrimp and salt-loving
    # algae: their colour and chlorophyll index are shown but don't raise a flag.
    context_only = {"ice_out"} | ({"colour", "ndci"} if kind in ("glacial", "saline") else set())
    level = 0
    for k, z in zs.items():
        if k in context_only:
            continue                          # early ice-out is context, not an alarm on its own
        if z >= 2.5:
            level = max(level, 2)
        elif z >= 1.5:
            level = max(level, 1)
    raised = [k for k, z in zs.items() if k not in context_only and z >= 1.5]
    if len(raised) >= 2:
        level = max(level, 2)
    if ("colour" not in context_only and zs.get("colour", 0) >= 2.5 and zs.get("ndci", 0) >= 2.5
            and (sig["ndci"]["now"] or 0) > 0.05):
        level = 3
    words = {"colour": "greener than usual", "ndci": "more chlorophyll signal than usual",
             "temp": "warmer than usual", "ice_out": "ice went out early"}
    why = [words[k] for k, z in sorted(zs.items(), key=lambda kv: -kv[1])
           if z >= 1.5 and k not in context_only]
    nwords = {"colour": "greener than usual", "ndci": "showing more chlorophyll signal than usual"}
    note = [nwords[k] for k, z in sorted(zs.items(), key=lambda kv: -kv[1])
            if z >= 1.5 and k in nwords and k in context_only]
    return {"year": cur_year, "level": level, "label": LABELS[level], "signals": sig,
            "why": (("; ".join(why).capitalize() + ".") if why else "Within its usual range.")
                   + (f" It's {' and '.join(note)}, but for a {'glacial' if kind == 'glacial' else 'salt'} lake that isn't a warning sign on its own." if note else "")}


def latest(s2: pd.DataFrame, ls: pd.DataFrame):
    out = {}
    if not s2.empty:
        d = clean(s2)
        if not d.empty:
            r = d.sort_values("date").iloc[-1]
            out["colour"] = {"date": r.date, "hue": float(r.hue), "fu": int(r.fu) if pd.notna(r.fu) else None,
                             "swatch": r.swatch if isinstance(r.swatch, str) else None,
                             "ndci": float(r.ndci) if pd.notna(r.ndci) else None}
    if not ls.empty and "lswt_c" in ls:
        d = ls.dropna(subset=["lswt_c"])
        if not d.empty:
            r = d.sort_values("date").iloc[-1]
            out["temp"] = {"date": r.date, "c": float(r.lswt_c)}
    return out


def recent_series(s2: pd.DataFrame, ls: pd.DataFrame, years_back=3):
    cut = (dt.date.today() - dt.timedelta(days=365 * years_back)).isoformat()
    ser = {"colour": [], "temp": [], "ice": []}
    if not s2.empty:
        for r in clean(s2[s2.date >= cut]).itertuples():
            ser["colour"].append([r.date, round(float(r.hue), 1),
                                  int(r.fu) if pd.notna(r.fu) else None,
                                  round(float(r.ndci), 4) if pd.notna(r.ndci) else None,
                                  r.swatch if isinstance(r.swatch, str) else None])
        for r in s2[s2.date >= cut].itertuples():
            if pd.notna(getattr(r, "f_ice", np.nan)) and (r.f_cloud or 0) < 0.3:
                ser["ice"].append([r.date, round(float(r.f_ice), 2)])
    if not ls.empty and "lswt_c" in ls:
        d = ls[(ls.date >= cut)].dropna(subset=["lswt_c"])
        ser["temp"] = [[r.date, float(r.lswt_c)] for r in d.itertuples()]
    return ser


def main():
    lakes = yaml.safe_load((ROOT / "lakes.yaml").read_text())["lakes"]
    (OUT / "space").mkdir(parents=True, exist_ok=True)
    rows = []
    now_year = dt.date.today().year
    for lake in lakes:
        s2p, lsp = SPACE / f"{lake['id']}_s2.csv", SPACE / f"{lake['id']}_ls.csv"
        regp = SPACE / f"{lake['id']}_region.json"
        s2 = pd.read_csv(s2p) if s2p.exists() else pd.DataFrame()
        ls = pd.read_csv(lsp) if lsp.exists() else pd.DataFrame()
        reg = json.loads(regp.read_text()) if regp.exists() else {}
        ice, freezes = ice_out(s2)
        t_ok = thermal_ok(lake, reg)
        years = yearly(s2, ls if t_ok else pd.DataFrame())
        for y, v in ice.items():
            years.setdefault(y, {})["ice_out_doy"] = v["doy"]
        verdict = judge(years, ice, now_year, lake.get("kind", "clear")) if years else None
        n_clear = int(len(clean(s2))) if not s2.empty else 0
        n_temp = int(ls["lswt_c"].notna().sum()) if ("lswt_c" in ls and t_ok) else 0
        summary = {k: lake.get(k) for k in ("id", "name", "range", "state", "elevation_ft", "lat", "lon",
                                            "kind", "notes")}
        summary.update({
            "backcountry": bool(lake.get("backcountry")),
            "area_km2": reg.get("area_km2"),
            "sampled": "3 km circle" if reg.get("clipped") else "whole lake",
            "scenes": {"s2": int(len(s2)), "s2_clear": n_clear, "landsat": int(len(ls)), "landsat_temp": n_temp},
            "first_year": int(min(years)) if years else None,
            "freezes": freezes,
            "thermal_ok": t_ok,
            "latest": latest(s2, ls if t_ok else pd.DataFrame()),
            "verdict": verdict,
        })
        rows.append(summary)
        detail = {"summary": summary,
                  "years": [{"year": y, **years[y]} for y in sorted(years)],
                  "ice_out": {str(k): v for k, v in sorted(ice.items())},
                  "recent": recent_series(s2, ls if t_ok else pd.DataFrame()),
                  "region": reg.get("sample_geom")}
        (OUT / "space" / f"{lake['id']}.json").write_text(json.dumps(detail, separators=(",", ":")))
        lv = verdict["label"] if verdict else "NO DATA"
        print(f"= {lake['name']}: {n_clear} clear colour scenes, {n_temp} temperatures, "
              f"{len(years)} years -> {lv}")
    meta = {"updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "lakes": len(rows),
            "sources": ["Copernicus Sentinel-2 L2A", "USGS Landsat 8/9 Collection 2 L2",
                        "Microsoft Planetary Computer", "OpenStreetMap"]}
    (OUT / "space.json").write_text(json.dumps({"meta": meta, "lakes": rows}, indent=1))


if __name__ == "__main__":
    main()
