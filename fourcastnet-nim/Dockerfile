# Start from a lightweight Python image
FROM python:3.11-slim

# Set work directory inside container
WORKDIR /app

# Install system dependencies needed for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Do not automatically start the application. Keep the container running
# so commands can be executed manually inside it.
CMD ["tail", "-f", "/dev/null"]
