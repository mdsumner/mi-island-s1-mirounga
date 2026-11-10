#!/usr/bin/env python3
"""Elephant seal haul-outs on Heard and Macquarie islands from public satellite data.

Data
  S1: Geoscience Australia / DEA Sentinel-1 NRB Collection 1, IW HH gamma0 (linear), per-burst COGs
      in s3://dea-public-data-dev/baseline/ga_s1_nrb_iw_hh_1/ (unsigned, read over HTTPS).
      Checked 2026-11-10: Heard has 12-day repeats Dec 2024 - Mar 2025 and Aug - Oct 2026 on
      tracks 027, 100 and 173 (all ascending). Macquarie has no bursts in any DEA NRB product.
  S2: Sentinel-2 L2A COGs in the public sentinel-cogs bucket (us-west-2), item JSON next to the
      COGs, so no STAC API is needed. Tiles: 57FVV (Macquarie), 43FDB and 43FCB (Heard).

Steps (each a subcommand):
  index   find S1 bursts and S2 items over each island -> work/index_<island>.json
  s1      per-date HH gamma0 mosaic on a 20 m UTM grid, layover/shadow masked
          -> work/s1_<island>.tif (one band per date, linear gamma0, tags hold dates + settings)
  s2      per-date L2A chips (B02 B03 B04 B08 SCL) on a 10 m UTM grid for items under --max-cloud
          -> work/s2_<island>_<date>.tif
  figure  quicklooks -> out/*.png

Usage
  python seals.py index --island heard
  python seals.py s1 --island heard
  python seals.py s2 --island macquarie --months 8 9 10 11
  python seals.py figure --island heard
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

for _k, _v in {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "5",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "VSI_CACHE": "TRUE",
    "AWS_NO_SIGN_REQUEST": "YES",
}.items():
    os.environ.setdefault(_k, _v)

import rasterio  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.warp import Resampling, reproject, transform_bounds  # noqa: E402

S1_BASE = "https://dea-public-data-dev.s3.ap-southeast-2.amazonaws.com"
S1_PRODUCT = "baseline/ga_s1_nrb_iw_hh_1"
S2_BASE = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
S2_PREFIX = "sentinel-s2-l2a-cogs"
WORK = Path(os.environ.get("SEALS_WORK", "work"))
OUT = Path(os.environ.get("SEALS_OUT", "out"))

# lon/lat bbox, UTM grid, S2 tiles, S1 burst ranges (track, first, last) found by the scan in
# `index --scan`; rerun that when DEA adds tracks.
ISLANDS = {
    "heard": dict(bbox=(73.22, -53.22, 73.88, -52.95), crs="EPSG:32743", s2_tiles=["43FDB", "43FCB"],
                  s1_ranges=[("t027", 57660, 57676), ("t100", 214455, 214470), ("t173", 371250, 371265)]),
    "macquarie": dict(bbox=(158.75, -54.79, 158.97, -54.46), crs="EPSG:32757", s2_tiles=["57FVV"],
                      s1_ranges=[]),
}


# ---------------------------------------------------------------- http helpers
def urlopen(url: str, tries: int = 6):
    for i in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=60)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def s3_list(base: str, prefix: str, delimiter: str | None = None) -> tuple[list[str], list[str]]:
    keys, prefixes, token = [], [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if delimiter:
            q["delimiter"] = delimiter
        if token:
            q["continuation-token"] = token
        x = urlopen(f"{base}/?{urllib.parse.urlencode(q)}").read().decode()
        keys += re.findall(r"<Key>([^<]*)</Key>", x)
        prefixes += [p for p in re.findall(r"<Prefix>([^<]*)</Prefix>", x) if p != prefix]
        m = re.search(r"<NextContinuationToken>([^<]*)<", x)
        if not m:
            return keys, prefixes
        token = m.group(1)


def get_json(url: str) -> dict:
    return json.load(urlopen(url))


def intersects(a, b) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def geom_bbox(g: dict) -> tuple:
    xy = np.array(g["coordinates"][0])
    return (xy[:, 0].min(), xy[:, 1].min(), xy[:, 0].max(), xy[:, 1].max())


def grid(island: str, res: float):
    cfg = ISLANDS[island]
    l, b, r, t = transform_bounds("EPSG:4326", cfg["crs"], *cfg["bbox"])
    l, b, r, t = (np.floor(l / res) * res, np.floor(b / res) * res, np.ceil(r / res) * res, np.ceil(t / res) * res)
    w, h = int(round((r - l) / res)), int(round((t - b) / res))
    return cfg["crs"], from_origin(l, t, res, res), w, h


# ---------------------------------------------------------------- index
def s1_burst_items(burst: str, bbox) -> list[dict]:
    keys, _ = s3_list(S1_BASE, f"{S1_PRODUCT}/{burst}/")
    out = []
    for k in sorted(k for k in keys if k.endswith("_stac-item.json")):
        d = get_json(f"{S1_BASE}/{k}")
        # the item bbox is oversized; use the footprint polygon
        if not intersects(geom_bbox(d["geometry"]), bbox):
            continue
        folder = k.rsplit("/", 1)[0]
        h = {a: f"{S1_BASE}/{folder}/{d['assets'][a]['href']}" for a in ("hh_gamma0", "oa_layover_shadow_mask")}
        p = d["properties"]
        out.append(dict(burst=burst, datetime=p["datetime"], orbit=p.get("sat:orbit_state"),
                        platform=p.get("platform"), assets=h))
    return out


def s2_items(tile: str, years, months, bbox) -> list[dict]:
    zone, band, sq = tile[:2], tile[2], tile[3:]
    prefixes = []
    for y in years:
        for m in months:
            _, p = s3_list(S2_BASE, f"{S2_PREFIX}/{int(zone)}/{band}/{sq}/{y}/{m}/", "/")
            prefixes += p

    def one(p):
        sid = p.rstrip("/").split("/")[-1]
        try:
            d = get_json(f"{S2_BASE}/{p}{sid}.json")
        except Exception:
            return None
        pr = d["properties"]
        return dict(id=sid, tile=tile, datetime=pr["datetime"], cloud=pr.get("eo:cloud_cover"),
                    nodata=pr.get("s2:nodata_pixel_percentage"),
                    assets={a: d["assets"][a]["href"] for a in ("blue", "green", "red", "nir", "scl") if a in d["assets"]})

    with ThreadPoolExecutor(8) as ex:
        items = [i for i in ex.map(one, prefixes) if i]
    # processing baseline reruns give _1, _2 ids for the same date; keep the latest
    by = {}
    for i in sorted(items, key=lambda i: i["id"]):
        by[(i["tile"], i["datetime"][:10])] = i
    return sorted(by.values(), key=lambda i: i["datetime"])


def cmd_index(a) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    cfg = ISLANDS[a.island]
    _, prefixes = s3_list(S1_BASE, f"{S1_PRODUCT}/", "/")
    have = {p.rstrip("/").split("/")[-1] for p in prefixes}
    cand = [f"{t}_{k:06d}_iw{s}" for t, lo, hi in cfg["s1_ranges"] for k in range(lo, hi + 1) for s in (1, 2, 3)]
    cand = [c for c in cand if c in have]
    with ThreadPoolExecutor(a.threads) as ex:
        s1 = [i for lst in ex.map(lambda b: s1_burst_items(b, cfg["bbox"]), cand) for i in lst]
    s1.sort(key=lambda i: (i["datetime"], i["burst"]))
    s2 = [i for t in cfg["s2_tiles"] for i in s2_items(t, a.years, a.months, cfg["bbox"])]
    idx = dict(island=a.island, s1=s1, s2=s2)
    (WORK / f"index_{a.island}.json").write_text(json.dumps(idx, indent=1))
    dates = sorted({i["datetime"][:10] for i in s1})
    print(f"{a.island}: {len(s1)} S1 burst-items on {len(dates)} dates, {len(s2)} S2 items")
    print("  S1 dates:", " ".join(dates))
    print("  S2 under 50% cloud:", sum(1 for i in s2 if (i["cloud"] or 100) < 50))


# ---------------------------------------------------------------- S1 stack
def read_to_grid(href: str, crs, transform, w, h, resampling, dtype="float32", src_nodata=None):
    dst = np.full((h, w), np.nan if dtype == "float32" else 255, dtype=dtype)
    with rasterio.open(href) as src:
        reproject(rasterio.band(src, 1), dst, dst_transform=transform, dst_crs=crs,
                  src_nodata=src.nodata if src_nodata is None else src_nodata,
                  dst_nodata=np.nan if dtype == "float32" else 255, resampling=resampling)
    return dst


def cmd_s1(a) -> None:
    idx = json.loads((WORK / f"index_{a.island}.json").read_text())
    crs, tr, w, h = grid(a.island, a.res)
    groups = {}
    for i in idx["s1"]:
        groups.setdefault((i["datetime"][:10], i["burst"][:4]), []).append(i)
    keys = sorted(groups)
    out = WORK / f"s1_{a.island}.tif"
    settings = dict(res=str(a.res), track_filter=",".join(a.tracks or []), n=str(len(keys)))
    if out.exists() and not a.force:
        with rasterio.open(out) as s:
            if all(s.tags().get(k) == v for k, v in settings.items()):
                print(f"{out} up to date (settings match)")
                return
    if a.tracks:
        keys = [k for k in keys if k[1] in a.tracks]

    def one(key):
        acc = np.zeros((h, w), "float64")
        n = np.zeros((h, w), "uint8")
        for i in groups[key]:
            g = read_to_grid(i["assets"]["hh_gamma0"], crs, tr, w, h, Resampling.bilinear)
            m = read_to_grid(i["assets"]["oa_layover_shadow_mask"], crs, tr, w, h, Resampling.nearest, "uint8")
            ok = np.isfinite(g) & (g > 0) & (m == 0)
            acc[ok] += g[ok]
            n[ok] += 1
        with np.errstate(invalid="ignore", divide="ignore"):
            return key, np.where(n > 0, acc / n, np.nan).astype("float32")

    with ThreadPoolExecutor(a.threads) as ex:
        res = list(ex.map(one, keys))
    prof = dict(driver="GTiff", width=w, height=h, count=len(res), dtype="float32", crs=crs, transform=tr,
                nodata=np.nan, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(out, "w", **prof) as d:
        for b, (k, arr) in enumerate(res, 1):
            d.write(arr, b)
            d.set_band_description(b, f"{k[0]}_{k[1]}")
        d.update_tags(**settings, dates=",".join(f"{k[0]}_{k[1]}" for k, _ in res))
    print(f"{len(res)} date/track mosaics -> {out}")


# ---------------------------------------------------------------- S2 chips
def cmd_s2(a) -> None:
    idx = json.loads((WORK / f"index_{a.island}.json").read_text())
    crs, tr, w, h = grid(a.island, 10)
    items = [i for i in idx["s2"] if (i["cloud"] if i["cloud"] is not None else 100) <= a.max_cloud
             and int(i["datetime"][5:7]) in a.months]

    def one(i):
        out = WORK / f"s2_{a.island}_{i['datetime'][:10]}_{i['tile']}.tif"
        if out.exists():
            with rasterio.open(out) as o:  # reuse only if the grid matches (see README: caching gotcha)
                if (o.width, o.height, o.transform) == (w, h, tr):
                    return out
        bands = [read_to_grid(i["assets"][b], crs, tr, w, h, Resampling.bilinear, src_nodata=0) for b in ("blue", "green", "red", "nir")]
        scl = read_to_grid(i["assets"]["scl"], crs, tr, w, h, Resampling.nearest, "uint8", src_nodata=0)
        if np.all(scl == 255):
            return None
        prof = dict(driver="GTiff", width=w, height=h, count=5, dtype="float32", crs=crs, transform=tr,
                    nodata=np.nan, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
        with rasterio.open(out, "w", **prof) as d:
            for k, arr in enumerate(bands + [scl.astype("float32")], 1):
                d.write(arr, k)
            d.descriptions = ("B02", "B03", "B04", "B08", "SCL")
            d.update_tags(id=i["id"], cloud=str(i["cloud"]))
        return out

    with ThreadPoolExecutor(a.threads) as ex:
        done = [o for o in ex.map(one, items) if o]
    print(f"{len(done)} S2 chips for {a.island}")


# ---------------------------------------------------------------- main
def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("index", "s1", "s2", "figure"):
        s = sub.add_parser(name)
        s.add_argument("--island", choices=sorted(ISLANDS), required=True)
        s.add_argument("--threads", type=int, default=8)
    sub.choices["index"].add_argument("--years", type=int, nargs="+", default=list(range(2019, 2027)))
    sub.choices["index"].add_argument("--months", type=int, nargs="+", default=list(range(1, 13)))
    sub.choices["s1"].add_argument("--res", type=float, default=20)
    sub.choices["s1"].add_argument("--tracks", nargs="*", help="e.g. t100")
    sub.choices["s1"].add_argument("--force", action="store_true")
    sub.choices["s2"].add_argument("--max-cloud", type=float, default=60)
    sub.choices["s2"].add_argument("--months", type=int, nargs="+", default=[8, 9, 10, 11])
    a = p.parse_args(argv)
    if a.cmd == "figure":
        import figures
        figures.run(a.island, WORK, OUT)
        return
    {"index": cmd_index, "s1": cmd_s1, "s2": cmd_s2}[a.cmd](a)


if __name__ == "__main__":
    main()
