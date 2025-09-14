# Base image: official FourCastNet NIM server
FROM nvcr.io/nim/nvidia/fourcastnet:latest

# Work inside NIM directory
# Base image: official FourCastNet NIM server
FROM nvcr.io/nim/nvidia/fourcastnet:latest

# Work inside NIM directory
WORKDIR /opt/nim

# Install additional Python dependencies for client UI
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code

# Install additional Python dependencies for client UI
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py /opt/nim/

# Default command launches the Gradio app
CMD ["python", "/opt/nim/app.py"]
