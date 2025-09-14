# Multi-stage build to install Python deps without internet access in runtime image
# Stage 1: download wheels using internet-enabled base
FROM python:3.11-slim AS builder
WORKDIR /wheelhouse
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip wheel \
    && pip download --dest /wheelhouse -r requirements.txt

# Stage 2: runtime image that installs from local wheelhouse
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /wheelhouse /wheelhouse
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --no-index --find-links=/wheelhouse -r /wheelhouse/requirements.txt
COPY make_input.py point_stats.py app.py /app/
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "/app/make_input.py", "/work/fcn_inputs.npy"]
