# Dockerfile for apparel-mcp (Railway / generic container hosts)
# Built from the existing Containerfile but renamed so Railway's
# Docker builder picks it up automatically.

FROM python:3.12-slim

# Prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      "fastmcp>=2.3.0" \
      "zeep>=4.2.1" \
      "httpx>=0.27.0" \
      "pydantic>=2.6.0" \
      "python-dotenv>=1.0.0" \
      "tenacity>=8.2.0" \
      "aiosqlite>=0.20.0" \
      "streamlit>=1.38.0" \
      "plotly>=5.22.0"

# Copy source
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY dashboard/ ./dashboard/

# Create data directory. On Railway this path is backed by a
# persistent Volume so the SQLite DB survives redeploys.
RUN mkdir -p /app/data

# Default DB path inside container — can be overridden by env var.
ENV DB_PATH=/app/data/apparel.db

# Initialize database schema on build so the server can start
# even before the first sync has run. Data is still empty until
# sync populates it.
RUN python scripts/setup_db.py || true

# Railway (and Heroku/Fly) inject $PORT at runtime. The server reads it
# from the environment so we don't need shell expansion here.
EXPOSE 8000

CMD ["python", "-m", "src.server.mcp_server", "--transport", "streamable-http", "--host", "0.0.0.0"]
