# The Lumina renderer: turns an assistant-written file into PDF, Word, Excel, PowerPoint or an image, and reads a customer's file into a structure for the
# knowledge index (parse.py). Image tag 2 carries the reader; agentai-render.service starts lumina-renderer:2.
# One container per job, started by agentai-render.service with: no network, read-only root, no capabilities, a non-root user.
# Build from the platform folder, into the CELL engine (it has its own image store):
#   DOCKER_HOST=<cell engine socket> docker build -f deploy/renderer/Dockerfile -t lumina-renderer:2 .
# The base is pinned by digest (recorded in runtime.lock.json "images"; first production build 2026-11-19).
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

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
COPY agentai_platform/render/parse.py /opt/render/parse.py

USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["python3", "-I", "/opt/render/engine.py", "/job"]
