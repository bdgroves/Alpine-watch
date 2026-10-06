#!/usr/bin/env python3
"""
Lake outlines from OpenStreetMap, via Overpass.

    python scripts/outlines.py            # only lakes without an outline yet
    python scripts/outlines.py --all      # refetch every lake

For each lake in lakes.yaml: find the water polygon named `osm_name` within
8 km of lat/lon (falling back to whatever water polygon contains lat/lon),
build the polygon with its islands cut out, and save it as
data/outlines/<id>.geojson in WGS84 with its area in the properties.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
import yaml
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import polygonize, transform, unary_union
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "outlines"
SERVERS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]


def overpass(q: str) -> dict:
    last = None
    for attempt in range(6):
        url = SERVERS[attempt % len(SERVERS)]
        try:
            r = requests.post(url, data={"data": q}, timeout=180,
                              headers={"User-Agent": "alpine-watch (github.com/bdgroves/Alpine-watch)"})
            if r.status_code == 200:
                return r.json()
            last = f"{url} HTTP {r.status_code}"
        except requests.RequestException as e:
            last = f"{url} {e.__class__.__name__}"
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass failed: {last}")


def element_geometry(el: dict):
    """Polygon (islands removed) for an OSM way or multipolygon relation with `out geom`."""
    if el["type"] == "way":
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(pts) < 4 or pts[0] != pts[-1]:
            return None
        return Polygon(pts).buffer(0)
    outers, inners = [], []
    for m in el.get("members", []):
        if m.get("type") != "way" or "geometry" not in m:
            continue
        line = LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
        (inners if m.get("role") == "inner" else outers).append(line)
    outer = unary_union(list(polygonize(unary_union(outers)))) if outers else None
    if outer is None or outer.is_empty:
        return None
    if inners:
        holes = unary_union(list(polygonize(unary_union(inners))))
        outer = outer.difference(holes)
    return outer.buffer(0)


def utm_for(lon: float, lat: float) -> str:
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def area_km2(geom, lon, lat) -> float:
    t = Transformer.from_crs("EPSG:4326", utm_for(lon, lat), always_xy=True).transform
    return transform(t, geom).area / 1e6


def find(lake: dict):
    lat, lon, name = lake["lat"], lake["lon"], lake["osm_name"]
    esc = name.replace('"', '\\"')
    q = f"""[out:json][timeout:120];
(
  way["natural"="water"]["name"="{esc}"](around:8000,{lat},{lon});
  relation["natural"="water"]["name"="{esc}"](around:8000,{lat},{lon});
  way["water"]["name"="{esc}"](around:8000,{lat},{lon});
  relation["water"]["name"="{esc}"](around:8000,{lat},{lon});
);
out geom;"""
    els = overpass(q).get("elements", [])
    how = "name"
    if not els:
        q = f"""[out:json][timeout:120];
is_in({lat},{lon})->.a;
(way(pivot.a)["natural"="water"]; relation(pivot.a)["natural"="water"];);
out geom;"""
        els = overpass(q).get("elements", [])
        how = "contains point"
    geoms = [(el, element_geometry(el)) for el in els]
    geoms = [(el, g) for el, g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return None
    # several pieces with the same name (a reservoir mapped in parts): merge them;
    # otherwise prefer the polygon that holds the point, then the biggest
    pt = Point(lon, lat)
    holding = [g for _, g in geoms if g.buffer(0.002).contains(pt) or g.contains(pt)]
    core = holding[0] if holding else max((g for _, g in geoms), key=lambda g: g.area)
    near = [g for _, g in geoms if g.distance(core) < 0.003]
    geom = unary_union(near) if len(near) > 1 else core
    ids = [f"{el['type']}/{el['id']}" for el, _ in geoms]
    return geom, ids, how


def main():
    lakes = yaml.safe_load((ROOT / "lakes.yaml").read_text())["lakes"]
    OUT.mkdir(parents=True, exist_ok=True)
    redo = "--all" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    ok = 0
    for lake in lakes:
        if only and lake["id"] not in only:
            continue
        path = OUT / f"{lake['id']}.geojson"
        if path.exists() and not redo and not only:
            ok += 1
            continue
        try:
            got = find(lake)
        except Exception as e:  # noqa: BLE001
            print(f"= {lake['name']}: Overpass error {e}")
            continue
        if got is None:
            print(f"= {lake['name']}: NO OUTLINE FOUND")
            continue
        geom, ids, how = got
        a = area_km2(geom, lake["lon"], lake["lat"])
        if isinstance(geom, Polygon):
            geom = MultiPolygon([geom])
        feat = {"type": "Feature", "geometry": mapping(geom),
                "properties": {"id": lake["id"], "name": lake["name"], "osm": ids,
                               "found_by": how, "area_km2": round(a, 4)}}
        path.write_text(json.dumps({"type": "FeatureCollection", "features": [feat]}))
        print(f"= {lake['name']}: {a:.3f} km² from {', '.join(ids[:4])} ({how})")
        ok += 1
        time.sleep(2)
    print(f"= outlines: {ok} of {len(lakes)} lakes")


if __name__ == "__main__":
    main()
