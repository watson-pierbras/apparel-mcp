# Containerfile for apparel-mcp
# Build:  podman build -t apparel-mcp .
# Run:    podman run -d --name apparel-mcp -p 127.0.0.1:8020:8000 \
#           --env-file ~/.config/mcp-env/apparel-mcp.env \
#           -v apparel-mcp-data:/app/data:Z \
#           apparel-mcp

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || \
    (pip install --no-cache-dir \
      "fastmcp>=2.3.0" \
      "zeep>=4.2.1" \
      "httpx>=0.27.0" \
      "pydantic>=2.6.0" \
      "python-dotenv>=1.0.0" \
      "tenacity>=8.2.0" \
      "aiosqlite>=0.20.0" \
      "streamlit>=1.38.0" \
      "plotly>=5.22.0")

# Copy source
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY dashboard/ ./dashboard/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Default DB path inside container
ENV DB_PATH=/app/data/apparel.db

# Initialize database on build
RUN python scripts/setup_db.py

# Expose MCP (8000) and Streamlit dashboard (8501)
EXPOSE 8000 8501

# Default: run MCP server in streamable-http mode for networked access
# Override with --transport stdio for direct Claude Desktop pipe
CMD ["python", "-m", "src.server.mcp_server", "--transport", "streamable-http", "--host", "0.0.0.0"]
