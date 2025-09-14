#!/usr/bin/env bash
set -euo pipefail

# ---- Settings ----
NIM_IMAGE="nvcr.io/nim/nvidia/fourcastnet:latest"
CLIENT_IMAGE="fourcastnet-client:latest"
DATA_DIR="$(pwd)/data"
PORT=8000

# ---- Prereqs ----
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found in PATH"; exit 1; }

# TIP: You need an NVIDIA GPU with recent drivers + NVIDIA Container Toolkit.
# Basic sanity check (non-fatal if nvidia-smi missing):
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "WARN: nvidia-smi not found; make sure this host has an NVIDIA GPU and container toolkit installed."
fi

# ---- NGC API Key ----
: "${NGC_API_KEY:=}"
if [[ -z "${NGC_API_KEY}" ]]; then
  read -r -p "Enter your NGC API Key: " NGC_API_KEY
  export NGC_API_KEY
fi

# ---- Pull NIM ----
echo "Pulling NIM image: ${NIM_IMAGE}"
docker pull "${NIM_IMAGE}"

# ---- Prepare data dir ----
mkdir -p "${DATA_DIR}"

# ---- Run NIM (daemonized) ----
echo "Starting FourCastNet NIM on port ${PORT}..."
# Stop any prior container on that port/name
RUN_NAME="fourcastnet-nim"
if docker ps -a --format '{{.Names}}' | grep -q "^${RUN_NAME}\$"; then
  docker rm -f "${RUN_NAME}" >/dev/null 2>&1 || true
fi

docker run -d --name "${RUN_NAME}" \
  --gpus all --shm-size 4g \
  -p "${PORT}:8000" \
  -e NGC_API_KEY \
  "${NIM_IMAGE}"

# ---- Wait for readiness ----
echo "Waiting for NIM readiness (http://localhost:${PORT}/v1/health/ready)..."
ATTEMPTS=60
SLEEP_SEC=2
for i in $(seq 1 ${ATTEMPTS}); do
  if curl -fsS "http://localhost:${PORT}/v1/health/ready" -H 'accept: application/json' >/dev/null 2>&1; then
    echo "NIM is ready."
    break
  fi
  if [[ "$i" -eq "${ATTEMPTS}" ]]; then
    echo "ERROR: NIM did not report ready after $((ATTEMPTS*SLEEP_SEC))s"
    docker logs --tail 200 "${RUN_NAME}" || true
    exit 1
  fi
  sleep "${SLEEP_SEC}"
done

# ---- Build client image (generates input array) ----
echo "Building client image: ${CLIENT_IMAGE}"
docker build -t "${CLIENT_IMAGE}" -f client.Dockerfile .

# ---- Generate input array with Earth2Studio ----
echo "Generating input NumPy array (fcn_inputs.npy) via client container..."
docker run --rm \
  -v "${DATA_DIR}:/work" \
  "${CLIENT_IMAGE}" \
  python /app/make_input.py /work/fcn_inputs.npy

# ---- Call inference ----
echo "Calling inference..."
curl -X POST \
  -F "input_array=@${DATA_DIR}/fcn_inputs.npy" \
  -F "input_time=2023-01-01T00:00:00Z" \
  -F "simulation_length=4" \
  -o "${DATA_DIR}/output.tar" \
  "http://localhost:${PORT}/v1/infer"

echo "Done."
echo "Artifacts:"
echo "  Input:   ${DATA_DIR}/fcn_inputs.npy"
echo "  Output:  ${DATA_DIR}/output.tar"

# ---- Optional: show last few logs
echo
echo "Recent NIM logs (last 40 lines):"
docker logs --tail 40 "${RUN_NAME}" || true

# Uncomment to auto-stop the NIM container after run:
# docker rm -f "${RUN_NAME}"
