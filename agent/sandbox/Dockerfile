# sandbox/Dockerfile — image for user code execution (one container per task).
# Minimal but useful; NO secrets are baked in. Build from the agent/ dir:
#   docker build -t agent-sandbox:latest -f sandbox/Dockerfile .

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# A small, useful standard library of packages for agent tasks.
RUN pip install --no-cache-dir requests httpx beautifulsoup4 pandas matplotlib

# Non-root user; workspace is mounted at /workspace by tools/sandbox.py.
RUN useradd --create-home --shell /bin/bash sandbox
USER sandbox
WORKDIR /workspace

CMD ["sleep", "infinity"]
