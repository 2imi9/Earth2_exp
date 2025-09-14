# Small Python image to run Earth2Studio input generation
FROM python:3.11-slim

# System deps commonly needed for scientific Python & remote data
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps
# earth2studio pulls xarray, numpy, etc.
# If wheels change, pip may compile—build-essential covers that.
RUN pip install --no-cache-dir \
    numpy \
    earth2studio

# App code
WORKDIR /app
COPY make_input.py /app/make_input.py

# Default command (overridden in script)
CMD ["python", "/app/make_input.py", "/work/fcn_inputs.npy"]
