# memex — 外置大脑 / personal knowledge specialist agent service
#
# Build:    docker build -t memex:latest .
# Run:
#   docker run -d --name memex \
#     -p 127.0.0.1:18766:18766 \
#     -v /path/to/your/wiki:/data/wiki \
#     -e MEMEX_WIKI_PATH=/data/wiki \
#     -e MEMEX_API_KEY="sk-..." \
#     -e MEMEX_BASE_URL="https://api.openai.com/v1" \
#     -e MEMEX_DEFAULT_MODEL="gpt-4o-mini" \
#     memex:latest
#
# Mounted wiki must be a git repo (memex 会 commit 进去)。

FROM python:3.13-slim

# System deps: git (for commits) + ripgrep (for search)
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ripgrep \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY service/ ./service/
COPY memex.yaml.example ./memex.yaml.example
COPY README.md ./README.md

# Default config: assume wiki mounted at /data/wiki
# (users can override via env or mount their own memex.yaml)
ENV MEMEX_WIKI_PATH=/data/wiki
ENV MEMEX_MCP_HOST=0.0.0.0
ENV MEMEX_MCP_PORT=18766

EXPOSE 18766

# Run MCP server in HTTP mode by default; for stdio mode override CMD
CMD ["python", "-m", "service.mcp_server", "--http"]
