# Use UV's official Python image for faster builds
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Set working directory
WORKDIR /app

# Copy dependency files first (for better layer caching)
COPY pyproject.toml uv.lock ./

# Install Python dependencies using UV
# This creates a virtual environment and installs all dependencies
RUN uv sync --frozen --no-dev

# Copy the application code
COPY website_server/ ./website_server/
COPY sites/ ./sites/
COPY sites_to_scrape.txt ./

# Expose port (fly.io will set PORT env var)
EXPOSE 8080

# Set environment variable for port (fly.io uses PORT)
ENV PORT=8080

# Run the FastAPI server using UV's virtual environment
# uv run automatically uses the synced virtual environment
CMD uv run python -m uvicorn website_server.main:app --host 0.0.0.0 --port ${PORT:-8080}

