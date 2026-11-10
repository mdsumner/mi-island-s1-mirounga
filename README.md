# Southern elephant seals (Mirounga leonina) on Macquarie and Heard islands

Status: setup notes only (2026-11-10). No analysis has been run yet.

Aim: see what public satellite data (DEA Sentinel-1 NRB radar, Sentinel-2 L2A) can say about
haul-out sites on Macquarie Island and Heard Island, and run it on Pawsey Setonix in the same way
as [tasmania-s1-change](https://github.com/mdsumner/tasmania-s1-change).

## Data

- **Sentinel-2 L2A** from the public `sentinel-cogs` bucket (us-west-2). MGRS tiles:
  - `57FVV`: all of Macquarie (Sandy Bay, the Isthmus, Hurd Point, Lusitania Bay)
  - `43FDB`: Heard Island; `43FCB`: Atlas Cove
  - Each item JSON sits next to its COGs, e.g.
    `https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/57/F/VV/YYYY/M/<id>/<id>.json`,
    so no STAC API is needed (earth-search is blocked from some sandboxes anyway).
- **DEA Sentinel-1 NRB** (IW, per-burst COGs) in `s3://dea-public-data-dev/baseline/ga_s1_nrb_iw_*_1/`,
  unsigned over HTTPS. Coverage of either island is **not yet checked**. The bucket-walk `index`
  step from tasmania-s1-change works for this with a new bbox.

## Science notes (untested)

- Elephant seals are 3-5 m long and lie on dark cobble and sand beaches. Individuals will not show
  at 10-20 m. Published satellite counts used about 0.5 m imagery (McMahon et al. 2014, PLoS ONE
  9(3): e92613, GeoEye-1, the Isthmus, Macquarie). At 10-20 m the best hope is a change signal on
  known beaches from dense harems or moult wallows: pre-season (August) vs peak (mid October).
- Seasons: breeding haul-out September to November (female peak about mid October); moult
  December to April.
- Easier 10 m targets on the same islands: penguin guano colonies (royal penguins at Hurd Point,
  king penguins at Lusitania Bay, and Heard's king penguin colonies), using a rock-masked red/blue
  ratio as in the earlier Amanda Bay emperor work.
- Heard is very cloudy, so expect few clear Sentinel-2 dates; S1 does not care about cloud.

## Plan

1. `index`: count clear S2 dates on 57FVV / 43FDB / 43FCB (2019-2026) and list DEA S1 NRB bursts
   over both islands.
2. `chips`: S2 and S1 chips over known haul-out beaches and penguin colonies, per date.
3. `change`: per-beach statistics over the season (S2 reflectance, S1 VV/VH or HH dB), August vs
   October, and year to year.
4. `figure`: quicklook panels.

Each step will be a subcommand of one script so the per-scene step can be a Slurm array task.

## Setonix notes (from the Tasmania S1 run, which worked on 2026-11-10)

- **Environment:** no Docker on Setonix. Use a plain venv under `$MYSOFTWARE/venvs/<name>` and
  `pip install -r requirements.txt` (or `uv pip install -r requirements.txt`). The rasterio wheel
  bundles GDAL, so no GDAL module is needed.
- **Modules:** Setonix disables default module versions, so a bare `module load python` fails.
  Use `module load python/3.11.6` (the only `python/` module; `cray-python/3.12.12` also exists).
  The venv and the job must use the same module. The slurm files take `PYTHON_MODULE` and
  `SEALS_VENV` env vars to override both.
- **Paths:** account `pawsey1362`, partition `work`. Keep the repo in `$MYSOFTWARE`, write outputs
  to `$MYSCRATCH`. Scratch gets purged, so copy keepers off.
- **Logging:** set `PYTHONUNBUFFERED=1` in the job, or the `.out` log stays empty until the end.
- **Submit from inside the repo dir**, since the script is found via `$SLURM_SUBMIT_DIR`.
- **Network:** compute nodes reach `dea-public-data-dev` S3 over HTTPS (GDAL `/vsicurl/`, unsigned).
  `sentinel-cogs` (us-west-2) is untested from Setonix.
- **Caching gotcha:** in Tasmania a coarse smoke-test output was silently reused by the full run,
  because the skip-if-exists check ignored settings. Record the settings (overview level, boxcar,
  etc.) in GeoTIFF tags and only reuse a file when they match.
- **Timing reference:** Tasmania index (S3 listing of 9.8k bursts plus about 580 STAC JSONs) took
  about 2 min on a login node; 248 bursts at native 20 m took about 3 min on 1 node, 32 threads,
  96G. These islands are tiny by comparison, so one node with a few threads will be plenty.

### Setup (once, on a login node)

```bash
cd $MYSOFTWARE && git clone https://github.com/mdsumner/mi-island-s1-mirounga
module load python/3.11.6
python -m venv $MYSOFTWARE/venvs/seals
source $MYSOFTWARE/venvs/seals/bin/activate
pip install -r mi-island-s1-mirounga/requirements.txt
```

Then, once the script exists: `cd mi-island-s1-mirounga && sbatch --account=pawsey1362 setonix.slurm`.
