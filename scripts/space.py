#!/usr/bin/env python3
"""
Satellite readings for each lake, one row per clear-enough overpass.

    python scripts/space.py                 # every lake
    python scripts/space.py kibbie_lake     # one lake
    python scripts/space.py --since 2024-01-01 crater_lake

Sentinel-2 L2A (2017-) -> data/space/<id>_s2.csv
    open-water, ice and cloud fractions over the lake, median surface
    reflectance in the visible bands, hue angle and Forel-Ule colour,
    and NDCI, a chlorophyll index.
Landsat 8/9 Collection 2 L2 (2013-) -> data/space/<id>_ls.csv
    median lake surface temperature from the thermal band.

Both come from Microsoft Planetary Computer's STAC catalog and are read a
window at a time, so nothing is downloaded whole. Runs are incremental: scenes
already in the CSV are skipped. A true-colour chip of the newest clear scene
is saved to docs/chips/<id>.jpg.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import yaml
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import nearest_points, transform, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fu  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "space"
CHIPS = ROOT / "docs" / "chips"
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
BIG_KM2 = 25.0          # lakes bigger than this are sampled inside a circle
CIRCLE_M = 3000.0
S2_BUFFER_M = 40.0      # stay this far in from the shore (adjacency, shallows)
LS_BUFFER_M = 60.0
S2_MONTHS = range(3, 12)
LS_MONTHS = range(4, 12)
WORKERS = int(os.environ.get("AW_WORKERS", "16"))

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF")


def utm_for(lon, lat):
    return f"EPSG:{(32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1}"


def regions(lake):
    """Sampling geometry in WGS84: the lake (or a 3 km circle of a big lake), shrunk from shore."""
    fc = json.loads((ROOT / "data" / "outlines" / f"{lake['id']}.geojson").read_text())
    feat = fc["features"][0]
    lake4326 = shape(feat["geometry"])
    utm = utm_for(lake["lon"], lake["lat"])
    fwd = Transformer.from_crs("EPSG:4326", utm, always_xy=True).transform
    inv = Transformer.from_crs(utm, "EPSG:4326", always_xy=True).transform
    poly = transform(fwd, lake4326)
    pt = transform(fwd, Point(lake["lon"], lake["lat"]))
    if not poly.contains(pt):                       # snap a shore point into the water
        pt = nearest_points(poly.buffer(-150) if not poly.buffer(-150).is_empty else poly, pt)[0]
    area = poly.area / 1e6
    clipped = area > BIG_KM2
    region = poly.intersection(pt.buffer(CIRCLE_M)) if clipped else poly
    out = {"area_km2": area, "clipped": clipped}
    for key, buf in (("s2", S2_BUFFER_M), ("ls", LS_BUFFER_M)):
        g = region.buffer(-buf)
        while g.is_empty or g.area < 4 * (20 if key == "s2" else 30) ** 2:
            buf /= 2
            if buf < 5:
                g = region
                break
            g = region.buffer(-buf)
        out[key] = transform(inv, g)
        out[key + "_buffer_m"] = buf
    out["region"] = transform(inv, region)
    return out


def item_epsg(item):
    p = item.properties
    if "proj:epsg" in p and p["proj:epsg"]:
        return int(p["proj:epsg"])
    code = p.get("proj:code", "")
    return int(str(code).split(":")[-1])


def window_grid(geom4326, epsg, res, pad):
    g = transform(Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform, geom4326)
    minx, miny, maxx, maxy = g.bounds
    step = 60.0 if res == 20 else 30.0
    minx = math.floor((minx - pad) / step) * step
    miny = math.floor((miny - pad) / step) * step
    maxx = math.ceil((maxx + pad) / step) * step
    maxy = math.ceil((maxy + pad) / step) * step
    w, h = int(round((maxx - minx) / res)), int(round((maxy - miny) / res))
    tr = rasterio.transform.from_origin(minx, maxy, res, res)
    mask = geometry_mask([mapping(g)], out_shape=(h, w), transform=tr, invert=True)
    return (minx, miny, maxx, maxy), (h, w), mask


def read(href, bounds, shape_hw, resampling=Resampling.nearest):
    with rasterio.open(href) as src:
        win = from_bounds(*bounds, transform=src.transform)
        return src.read(1, window=win, out_shape=shape_hw, boundless=True, fill_value=0,
                        resampling=resampling)


# ── Sentinel-2 ────────────────────────────────────────────────────────────────
S2_BANDS = ("B01", "B02", "B03", "B04", "B05", "B08")


def s2_one(item, geom):
    item = planetary_computer.sign(item)
    epsg = item_epsg(item)
    bounds, hw, mask = window_grid(geom, epsg, 20, 60)
    n = int(mask.sum())
    row = {"id": item.id, "date": item.datetime.date().isoformat(),
           "sat": item.properties.get("platform", "")[-2:].upper().replace("-", ""),
           "tile": item.properties.get("s2:mgrs_tile", ""),
           "cloud_cover": round(float(item.properties.get("eo:cloud_cover", np.nan)), 1),
           "n_mask": n}
    if n == 0:
        return row, None
    scl = read(item.assets["SCL"].href, bounds, hw)
    sm = scl[mask]
    row["f_nodata"] = round(float(np.mean(sm == 0)), 3)
    row["f_water"] = round(float(np.mean(sm == 6)), 3)
    row["f_ice"] = round(float(np.mean(sm == 11)), 3)
    row["f_cloud"] = round(float(np.mean(np.isin(sm, (3, 8, 9, 10)))), 3)
    if row["f_nodata"] > 0.5:
        return row, None
    water = mask & (scl == 6)
    if row["f_water"] < 0.5 or water.sum() < 5:
        return row, None
    base = str(item.properties.get("s2:processing_baseline", "0"))
    try:
        offset = 1000 if float(base) >= 4.0 else 0
    except ValueError:
        offset = 0
    refl = {}
    for b in S2_BANDS:
        rs = Resampling.average if b in ("B02", "B03", "B04", "B08") else Resampling.nearest
        a = read(item.assets[b].href, bounds, hw, rs).astype("float32")
        a = (a - offset) / 10000.0
        refl[b] = a
    good = water & (refl["B02"] > -0.05)
    med = {b: float(np.median(refl[b][good])) for b in S2_BANDS}
    for b in S2_BANDS:
        row[b] = round(med[b], 5)
    sat = "S2" + row["sat"][-1:] if row["sat"] else "S2A"
    if min(med[b] for b in ("B01", "B02", "B03", "B04")) > 0:
        a = fu.hue_angle(med["B01"], med["B02"], med["B03"], med["B04"], med["B05"], sat)
        row["hue"] = round(a, 2) if a is not None else None
        row["fu"] = fu.forel_ule(a)
        row["swatch"] = fu.swatch(med["B01"], med["B02"], med["B03"], med["B04"], med["B05"])
    s = med["B05"] + med["B04"]
    row["ndci"] = round((med["B05"] - med["B04"]) / s, 4) if s > 0 else None
    # a little true-colour chip, kept only for the newest scene
    rgb = np.dstack([refl["B04"], refl["B03"], refl["B02"]])
    return row, rgb


# ── Landsat ───────────────────────────────────────────────────────────────────
def ls_one(item, geom):
    item = planetary_computer.sign(item)
    epsg = item_epsg(item)
    bounds, hw, mask = window_grid(geom, epsg, 30, 60)
    n = int(mask.sum())
    row = {"id": item.id, "date": item.datetime.date().isoformat(),
           "platform": item.properties.get("platform", ""),
           "cloud_cover": round(float(item.properties.get("eo:cloud_cover", np.nan)), 1),
           "n_mask": n}
    if n == 0:
        return row
    qa = read(item.assets["qa_pixel"].href, bounds, hw).astype("uint16")
    q = qa[mask]
    fill = (q & 1) > 0
    row["f_nodata"] = round(float(np.mean(fill | (q == 0))), 3)
    if row["f_nodata"] > 0.5:
        return row
    cloudy = (q & 0b11110) > 0
    clear = (q >> 6) & 1
    wat = (q >> 7) & 1
    snow = (q >> 5) & 1
    ok = (clear == 1) & (wat == 1) & ~cloudy & ~fill
    row["f_valid"] = round(float(ok.mean()), 3)
    row["f_snow"] = round(float(snow.mean()), 3)
    if row["f_valid"] < 0.5 or ok.sum() < 4:
        return row
    st = read(item.assets["lwir11"].href, bounds, hw).astype("float32")
    v = st[mask][ok]
    v = v[v > 0] * 0.00341802 + 149.0 - 273.15
    if v.size < 4:
        return row
    row["lswt_c"] = round(float(np.median(v)), 2)
    row["lswt_iqr"] = round(float(np.subtract(*np.percentile(v, [75, 25]))), 2)
    return row


# ── driver ────────────────────────────────────────────────────────────────────
def search(client, collection, geom, since, months, extra=None):
    q = {"eo:cloud_cover": {"lt": 70}}
    if extra:
        q.update(extra)
    end = dt.date.today().isoformat()
    items = []
    for attempt in range(4):
        try:
            res = client.search(collections=[collection], intersects=mapping(geom.envelope),
                                datetime=f"{since}/{end}", query=q, max_items=20000)
            items = [it for it in res.items() if it.datetime.month in months]
            break
        except Exception as e:  # noqa: BLE001
            print(f"  search retry {attempt + 1}: {e.__class__.__name__}: {e}")
            time.sleep(15 * (attempt + 1))
    return items


def run_pool(fn, items, geom, label):
    rows, chips, done, t0 = [], [], 0, time.time()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(fn, it, geom): it for it in items}
        for f in cf.as_completed(futs):
            done += 1
            try:
                out = f.result()
            except Exception as e:  # noqa: BLE001
                print(f"  {label} {futs[f].id}: {e.__class__.__name__}: {str(e)[:120]}")
                continue
            if isinstance(out, tuple):
                row, chip = out
                rows.append(row)
                if chip is not None and (not chips or row["date"] > chips[0][0]):
                    chips[:] = [(row["date"], chip)]     # keep only the newest
            else:
                rows.append(out)
            if done % 100 == 0:
                print(f"  {label}: {done}/{len(items)} in {time.time() - t0:.0f} s")
    return rows, chips


def save_chip(lake_id, chips):
    if not chips:
        return
    date, rgb = max(chips, key=lambda c: c[0])
    from PIL import Image
    a = np.clip(rgb / 0.12, 0, 1) ** (1 / 1.8)     # water is dark: stretch generously
    img = Image.fromarray((a * 255).astype("uint8"))
    img = img.resize((img.width * 3, img.height * 3), Image.NEAREST) if img.width < 120 else img
    CHIPS.mkdir(parents=True, exist_ok=True)
    img.save(CHIPS / f"{lake_id}.jpg", quality=88)
    (CHIPS / f"{lake_id}.json").write_text(json.dumps({"date": date}))


def update(path, rows, key="id"):
    old = pd.read_csv(path) if path.exists() else pd.DataFrame()
    new = pd.DataFrame(rows)
    df = pd.concat([old, new], ignore_index=True) if not old.empty else new
    if df.empty:
        return df
    df = df.drop_duplicates(subset=[key], keep="last").sort_values(["date", key])
    path.write_text(df.to_csv(index=False))
    return df


def do_lake(client, lake, since, s2=True, ls=True):
    t0 = time.time()
    reg = regions(lake)
    print(f"── {lake['name']}: {reg['area_km2']:.2f} km²"
          f"{' (3 km circle)' if reg['clipped'] else ''}, shore buffer "
          f"{reg['s2_buffer_m']:.0f}/{reg['ls_buffer_m']:.0f} m")
    DATA.mkdir(parents=True, exist_ok=True)
    meta = {"id": lake["id"], "area_km2": round(reg["area_km2"], 3), "clipped": reg["clipped"],
            "s2_buffer_m": reg["s2_buffer_m"], "ls_buffer_m": reg["ls_buffer_m"],
            "sample_geom": mapping(reg["s2"])}
    (DATA / f"{lake['id']}_region.json").write_text(json.dumps(meta))
    if s2:
        path = DATA / f"{lake['id']}_s2.csv"
        seen = set(pd.read_csv(path)["id"]) if path.exists() else set()
        items = search(client, "sentinel-2-l2a", reg["s2"], since, S2_MONTHS)
        # one scene per day: the tile that covers the lake, least cloudy first
        items = [it for it in items if shape(it.geometry).contains(reg["s2"])] or items
        best = {}
        for it in sorted(items, key=lambda i: i.properties.get("eo:cloud_cover", 100)):
            best.setdefault(it.datetime.date(), it)
        todo = [it for it in best.values() if it.id not in seen]
        print(f"  Sentinel-2: {len(best)} days, {len(todo)} new")
        rows, chips = run_pool(s2_one, todo, reg["s2"], "S2")
        df = update(path, rows)
        good = df.dropna(subset=["hue"]) if "hue" in df else df.iloc[0:0]
        print(f"  Sentinel-2: {len(df)} scenes on file, {len(good)} with a clear colour reading")
        if chips:
            save_chip(lake["id"], chips)
    if ls:
        path = DATA / f"{lake['id']}_ls.csv"
        seen = set(pd.read_csv(path)["id"]) if path.exists() else set()
        items = search(client, "landsat-c2-l2", reg["ls"], max(since, "2013-04-01"), LS_MONTHS,
                       {"platform": {"in": ["landsat-8", "landsat-9"]}})
        items = [it for it in items if shape(it.geometry).contains(reg["ls"])] or items
        todo = [it for it in items if it.id not in seen]
        print(f"  Landsat: {len(items)} scenes, {len(todo)} new")
        rows, _ = run_pool(ls_one, todo, reg["ls"], "LS")
        df = update(path, rows)
        good = df.dropna(subset=["lswt_c"]) if "lswt_c" in df else df.iloc[0:0]
        print(f"  Landsat: {len(df)} scenes on file, {len(good)} with a temperature")
    print(f"  {lake['name']} done in {time.time() - t0:.0f} s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lakes", nargs="*")
    ap.add_argument("--since", default="2017-03-01")
    ap.add_argument("--no-s2", action="store_true")
    ap.add_argument("--no-ls", action="store_true")
    a = ap.parse_args()
    lakes = yaml.safe_load((ROOT / "lakes.yaml").read_text())["lakes"]
    if a.lakes:
        lakes = [l for l in lakes if l["id"] in a.lakes]
    client = pystac_client.Client.open(STAC)
    for lake in lakes:
        if not (ROOT / "data" / "outlines" / f"{lake['id']}.geojson").exists():
            print(f"= {lake['name']}: no outline yet, skipped")
            continue
        do_lake(client, lake, a.since, s2=not a.no_s2, ls=not a.no_ls)


if __name__ == "__main__":
    main()
