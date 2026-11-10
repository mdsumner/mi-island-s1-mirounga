"""Quicklook figures for seals.py. Heard: DEA S1 HH seasonal change. Macquarie: S2 true colour."""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Approximate site positions (lon, lat) for orientation only; replace with surveyed haul-out polygons.
SITES = {
    "macquarie": {"Isthmus": (158.937, -54.497), "Lusitania Bay": (158.84, -54.70), "Hurd Point": (158.84, -54.76)},
}


def db(x):
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10 * np.log10(x)


def heard(work: Path, out: Path) -> None:
    s = rasterio.open(work / "s1_heard.tif")
    d = list(s.descriptions)

    def mean(names):
        names = [n for n in names if n in d]
        return np.nanmean([s.read(d.index(n) + 1) for n in names], 0)

    t100 = [n for n in d if n.endswith("t100")]
    pre = mean([n for n in t100 if n.startswith("2026-08")])
    peak = mean([n for n in t100 if n.startswith("2026-10")])
    moult = mean([n for n in t100 if n[:4] in ("2024", "2025")])
    ref = db(mean(["2026-08-29_t100", "2026-09-22_t100"])) - db(mean(["2026-08-05_t100", "2026-08-17_t100"]))
    fig, ax = plt.subplots(2, 2, figsize=(16, 11))
    ax[0, 0].imshow(db(pre), cmap="bone", vmin=-25, vmax=5); ax[0, 0].set_title("HH dB, Aug 2026 mean (before breeding)")
    ax[0, 1].imshow(db(peak), cmap="bone", vmin=-25, vmax=5); ax[0, 1].set_title("HH dB, Oct 2026 mean (breeding peak)")
    ax[1, 0].imshow(db(peak) - db(pre), cmap="RdBu_r", vmin=-6, vmax=6); ax[1, 0].set_title("Oct - Aug 2026 (dB)")
    ax[1, 1].imshow(db(moult) - db(pre), cmap="RdBu_r", vmin=-6, vmax=6); ax[1, 1].set_title("Dec 2024-Mar 2025 (moult) - Aug 2026 (dB)")
    for a in ax.flat:
        a.set_xticks([]); a.set_yticks([])
    fig.suptitle("Heard Island, DEA Sentinel-1 NRB HH gamma0, track 100 ascending, 20 m UTM 43S")
    plt.tight_layout(); plt.savefig(out / "heard_s1_season.png", dpi=60); plt.close()

    regs = {"east (Spit Bay side)": (slice(780, 1120), slice(1450, 1900)),
            "north-west (Laurens Peninsula)": (slice(150, 620), slice(100, 700))}
    fig, ax = plt.subplots(2, 4, figsize=(22, 10))
    for i, (k, (ys, xs)) in enumerate(regs.items()):
        ax[i, 0].imshow(db(pre)[ys, xs], cmap="bone", vmin=-25, vmax=5); ax[i, 0].set_title(f"{k}: Aug")
        ax[i, 1].imshow(db(peak)[ys, xs], cmap="bone", vmin=-25, vmax=5); ax[i, 1].set_title("Oct")
        ax[i, 2].imshow((db(peak) - db(pre))[ys, xs], cmap="RdBu_r", vmin=-8, vmax=8); ax[i, 2].set_title("Oct - Aug (dB)")
        ax[i, 3].imshow(ref[ys, xs], cmap="RdBu_r", vmin=-8, vmax=8); ax[i, 3].set_title("reference: late Aug/Sep - early Aug (dB)")
    for a in ax.flat:
        a.set_xticks([]); a.set_yticks([])
    plt.tight_layout(); plt.savefig(out / "heard_s1_zoom.png", dpi=55); plt.close()


def s2_rgb(f, sl=(slice(None), slice(None)), scale=3000):
    s = rasterio.open(f)
    return np.clip(np.dstack([s.read(b)[sl] for b in (3, 2, 1)]) / scale, 0, 1) ** 0.6, s


def macquarie(work: Path, out: Path, dates=("2023-08-13", "2021-10-04", "2023-11-08", "2026-10-21")) -> None:
    files = {Path(f).name.split("_")[2]: f for f in glob.glob(str(work / "s2_macquarie_*.tif"))}
    dates = [x for x in dates if x in files]
    fig, ax = plt.subplots(1, len(dates), figsize=(5 * len(dates), 12))
    for k, d in enumerate(dates):
        im, s = s2_rgb(files[d])
        ax[k].imshow(im[::3, ::3]); ax[k].set_title(d)
        lon, lat = zip(*SITES["macquarie"].values())
        xs, ys = transform("EPSG:4326", s.crs, list(lon), list(lat))
        for n, x, y in zip(SITES["macquarie"], xs, ys):
            c, r = ~s.transform * (x, y)
            ax[k].plot(c / 3, r / 3, "o", mfc="none", mec="red", ms=14); ax[k].text(c / 3 + 15, r / 3, n, color="yellow")
        ax[k].set_xticks([]); ax[k].set_yticks([])
    fig.suptitle("Macquarie Island, Sentinel-2 L2A (sentinel-cogs), 30 m display")
    plt.tight_layout(); plt.savefig(out / "macquarie_s2_island.png", dpi=50); plt.close()

    lon, lat = SITES["macquarie"]["Isthmus"]
    fig, ax = plt.subplots(2, len(dates), figsize=(5.5 * len(dates), 11))
    for k, d in enumerate(dates):
        s = rasterio.open(files[d])
        (x0,), (y0,) = transform("EPSG:4326", s.crs, [lon], [lat])
        c, r = (int(v) for v in ~s.transform * (x0, y0))
        sl = (slice(max(r - 200, 0), r + 200), slice(c - 200, c + 200))
        im, _ = s2_rgb(files[d], sl, 2500)
        ax[0, k].imshow(im); ax[0, k].set_title(f"{d}, 4 km around the Isthmus, 10 m")
        with np.errstate(divide="ignore", invalid="ignore"):
            ax[1, k].imshow(s.read(3)[sl] / s.read(1)[sl], cmap="magma", vmin=0.6, vmax=2.0)
        ax[1, k].set_title("red / blue")
        for a in ax[:, k]:
            a.plot(200, min(r, 200), "o", mfc="none", mec="cyan", ms=16); a.set_xticks([]); a.set_yticks([])
    plt.tight_layout(); plt.savefig(out / "macquarie_s2_isthmus.png", dpi=55); plt.close()


def run(island: str, work: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    {"heard": heard, "macquarie": macquarie}[island](work, out)
    print(f"figures -> {out}")
