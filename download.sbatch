#!/bin/bash
# Baixa o AllClear (ROIs do JSON) via SLURM. Resumível e idempotente:
# se o job cair ou estourar o walltime, é só reenviar — o download.py pula
# os ROIs já extraídos (data/<roi>/ existe) e baixa só o que falta.
#
#SBATCH -J allclear-dl
#SBATCH -p cpuq                    # CPU-only: download é rede+disco, não usa GPU
#SBATCH --cpus-per-task=16
#SBATCH --mem=16G
#SBATCH --time=2-00:00:00          # ~2,2 TB restantes; ajusta se a partição tiver teto menor
#SBATCH --requeue                  # re-enfileira em falha de nó (seguro: skip cuida da retomada)
#SBATCH -o logs/slurm_%x_%j.out
#SBATCH -e logs/slurm_%x_%j.err

set -euo pipefail
module load miniconda3/py312_25.1.1
export PYTHONUNBUFFERED=1
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs

JSON="${JSON:-metadata/datasets/train_tx3_s2-s1_100pct.json}"
echo "JSON=$JSON  cpus=${SLURM_CPUS_PER_TASK:-8}"

uv run python download.py --data-only --from-json "$JSON" --cpus "${SLURM_CPUS_PER_TASK:-8}"

echo "job $SLURM_JOB_ID terminou em $(date)"
