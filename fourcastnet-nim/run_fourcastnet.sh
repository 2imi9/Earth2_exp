#!/usr/bin/env bash
set -euo pipefail

NIM_IMAGE="nvcr.io/nim/nvidia/fourcastnet:latest"
CLIENT_IMAGE="fourcastnet-client:latest"
DATA_DIR="$(pwd)/data"
PORT=8000

command -v docker >/dev/null 2>&1 || { echo "docker not found"; exit 1; }

if [[ -z "${NGC_API_KEY:-}" ]]; then
  cfg="$HOME/.ngc/config"
  if [[ -f "$cfg" ]]; then
    NGC_API_KEY=$(grep -i '^apikey=' "$cfg" | head -n1 | cut -d'=' -f2 | tr -d '[:space:]')
  fi
fi

[[ -z "${NGC_API_KEY:-}" ]] && { echo "NGC_API_KEY not set"; exit 1; }

docker pull "${NIM_IMAGE}"
mkdir -p "${DATA_DIR}"

RUN_NAME="fourcastnet-nim"
docker rm -f "${RUN_NAME}" >/dev/null 2>&1 || true
docker run -d --name "${RUN_NAME}" \
  --gpus all --shm-size 4g \
  -p "${PORT}:8000" \
  -e NGC_API_KEY \
  "${NIM_IMAGE}"

for i in {1..60}; do
  if curl -fsS "http://localhost:${PORT}/v1/health/ready" >/dev/null 2>&1; then
    break
  fi
  [[ "$i" -eq 60 ]] && { echo "NIM not ready"; exit 1; }
  sleep 2
done

docker build -t "${CLIENT_IMAGE}" -f client.Dockerfile .
[[ -f "${DATA_DIR}/fcn_inputs.npy" ]] || { echo "missing ${DATA_DIR}/fcn_inputs.npy"; exit 1; }

curl -X POST \
  -F "input_array=@${DATA_DIR}/fcn_inputs.npy" \
  -F "input_time=2023-01-01T00:00:00Z" \
  -F "simulation_length=4" \
  -o "${DATA_DIR}/output.tar" \
  "http://localhost:${PORT}/v1/infer"

echo "input: ${DATA_DIR}/fcn_inputs.npy"
echo "output: ${DATA_DIR}/output.tar"
