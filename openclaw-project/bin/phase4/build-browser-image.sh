set -eu
cd /opt/openclaw-production
build_dir=/opt/openclaw-production/phase4-browser-image
mkdir -p "$build_dir/scripts/docker/sandbox"
curl --fail --silent --show-error --location https://raw.githubusercontent.com/openclaw/openclaw/v2026.9.6/scripts/docker/sandbox/Dockerfile.browser -o "$build_dir/scripts/docker/sandbox/Dockerfile.browser"
curl --fail --silent --show-error --location https://raw.githubusercontent.com/openclaw/openclaw/v2026.9.6/scripts/sandbox-browser-entrypoint.sh -o "$build_dir/scripts/sandbox-browser-entrypoint.sh"
sha256sum "$build_dir/scripts/docker/sandbox/Dockerfile.browser" "$build_dir/scripts/sandbox-browser-entrypoint.sh"
DOCKER_BUILDKIT=1 docker build -t openclaw-sandbox-browser:phase4-2026.9.6 -f "$build_dir/scripts/docker/sandbox/Dockerfile.browser" "$build_dir"
docker image inspect openclaw-sandbox-browser:phase4-2026.9.6 --format '{{.Id}} {{index .Config.Labels "org.openclaw.sandbox-browser.contract"}}'
