FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user
RUN useradd -m appuser
WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

USER appuser
EXPOSE 5000
CMD ["uvicorn", "mcp_server:app", "--host", "0.0.0.0", "--port", "5000"]
