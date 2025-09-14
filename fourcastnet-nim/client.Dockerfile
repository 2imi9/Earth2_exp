# Base image: official FourCastNet NIM server
FROM nvcr.io/nim/nvidia/fourcastnet:latest

WORKDIR /opt/nim

# Install additional Python dependencies for client UI
COPY requirements.txt ./
RUN python3 -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt -i https://pypi.org/simple

# Copy application code
COPY *.py /opt/nim/

# Default command launches the Gradio app
CMD ["python3", "/opt/nim/app.py"]
