# The Lumina renderer: turns an assistant-written file into PDF, Word, Excel, PowerPoint or an image.
# One container per job, started by agentai-render.service with: no network, read-only root, no capabilities, a non-root user.
# Build from the platform folder, into the CELL engine (it has its own image store):
#   DOCKER_HOST=<cell engine socket> docker build -f deploy/renderer/Dockerfile -t lumina-renderer:1 .
# Pin the base by digest before the first production build and record it in runtime.lock.json.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-openpyxl python3-pil \
       libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
       pandoc chromium poppler-utils librsvg2-bin \
       fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji fonts-dejavu fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin render \
    && mkdir -p /job/in /job/out /opt/render

COPY agentai_platform/render/engine.py /opt/render/engine.py

USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["python3", "-I", "/opt/render/engine.py", "/job"]
