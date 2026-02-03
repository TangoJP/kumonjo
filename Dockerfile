FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY kumonjo/ ./kumonjo/
COPY mcp_server/ ./mcp_server/
COPY data/official/ ./data/official/

# The processed data catalog will be mounted at runtime
# The .env file will be mounted or passed via environment variable

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "mcp_server/server.py"]
