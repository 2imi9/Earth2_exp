# Multi-stage build to install Python deps without internet access in runtime image
# Stage 1: download wheels using internet-enabled base
FROM python:3.10-slim AS builder
WORKDIR /wheelhouse
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip wheel \
    && pip download --dest /wheelhouse -r requirements.txt

# Stage 2: runtime image that installs from local wheelhouse
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
WORKDIR /opt/nim
COPY --from=builder /wheelhouse /wheelhouse
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/nim/.venv \
    && /opt/nim/.venv/bin/pip install --no-index --find-links=/wheelhouse -r /wheelhouse/requirements.txt
COPY *.py /opt/nim/
ENV PATH="/opt/nim/.venv/bin:$PATH"
CMD ["python", "/opt/nim/app.py"]