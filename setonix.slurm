#!/bin/bash --login
# Elephant seal haul-outs, Macquarie and Heard (DEA S1 NRB + Sentinel-2 L2A).
# Template only: the analysis script (seals.py) is not written yet.
#
#   cd <this repo> && sbatch --account=pawsey1362 setonix.slurm
#
#SBATCH --job-name=mi-seals
#SBATCH --partition=work
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=%x-%j.out

set -euo pipefail

# Setonix has no default module versions: name one, and use the same one the venv was built with.
module load "${PYTHON_MODULE:-python/3.11.6}"
source "${SEALS_VENV:-${MYSOFTWARE}/venvs/seals}/bin/activate"
export PYTHONUNBUFFERED=1

SRC="${SLURM_SUBMIT_DIR}/seals.py"
export SEALS_WORK="${MYSCRATCH}/mi-seals/work"
export SEALS_OUT="${MYSCRATCH}/mi-seals/out"
mkdir -p "$SEALS_WORK" "$SEALS_OUT"
export CPL_VSIL_CURL_CACHE_SIZE=200000000

T=${SLURM_CPUS_PER_TASK}
python "$SRC" index  --threads "$T"
python "$SRC" chips  --threads "$T"
python "$SRC" change --threads "$T"
python "$SRC" figure
