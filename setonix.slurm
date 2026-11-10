#!/bin/bash --login
# Elephant seal haul-outs, Heard and Macquarie (DEA S1 NRB HH + Sentinel-2 L2A). Small job.
#
#   cd <this repo> && sbatch --account=pawsey1362 setonix.slurm
#
#SBATCH --job-name=mi-seals
#SBATCH --partition=work
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=00:45:00
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
python "$SRC" index  --island heard --threads "$T"
python "$SRC" s1     --island heard --threads "$T"
python "$SRC" figure --island heard
python "$SRC" index  --island macquarie --months 8 9 10 11 --threads "$T"
python "$SRC" s2     --island macquarie --max-cloud 40 --threads "$T"
python "$SRC" figure --island macquarie
