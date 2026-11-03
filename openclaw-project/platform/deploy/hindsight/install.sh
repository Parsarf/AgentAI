#!/bin/sh
# Installs the long-term-memory index (Hindsight) on the Lumina server. Run as root; safe to run again (existing secrets and data are kept).
# What it makes: a private docker network, a pgvector Postgres container (own volume), the Hindsight container bound to 127.0.0.1:8888 only,
# and two private files for the platform app user: the Hindsight key and the bank-id secret. It never prints a secret.
# See deploy/LONG_TERM_MEMORY.md. It does NOT turn the feature on (that is the owner's switch file).
set -eu
umask 077
VERSION="${HINDSIGHT_VERSION:-1.1.0}"
APPUSER=agentai-platform
STATE=/var/lib/agentai-platform/hindsight         # read by the app; the app's ReadWritePaths cover it
CONF=/etc/agentai-hindsight                       # read by root/docker only
NET=agentai-hindsight

install -d -m 0700 -o "$APPUSER" -g "$APPUSER" "$STATE"
install -d -m 0700 -o root -g root "$CONF"

gen() { head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c 48; }

[ -f "$STATE/key" ]         || { gen > "$STATE/key"; }
[ -f "$STATE/bank-secret" ] || { gen > "$STATE/bank-secret"; }
[ -f "$CONF/db-password" ]  || { gen > "$CONF/db-password"; }
chown "$APPUSER:$APPUSER" "$STATE/key" "$STATE/bank-secret"; chmod 0600 "$STATE/key" "$STATE/bank-secret"
chmod 0600 "$CONF/db-password"

KEY=$(cat "$STATE/key"); PW=$(cat "$CONF/db-password")
cat > "$CONF/hindsight.env" <<EOF
HINDSIGHT_API_DATABASE_URL=postgresql://hindsight:${PW}@agentai-hindsight-db:5432/hindsight
HINDSIGHT_API_LLM_PROVIDER=none
HINDSIGHT_API_EMBEDDINGS_PROVIDER=local
HINDSIGHT_API_TENANT_EXTENSION=hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension
HINDSIGHT_API_TENANT_API_KEY=${KEY}
HINDSIGHT_API_TENANT_MCP_AUTH_DISABLED=true
HINDSIGHT_API_WORKER_ID=lumina-prod
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
EOF
chmod 0600 "$CONF/hindsight.env"

docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
docker volume inspect agentai-hindsight-pg >/dev/null 2>&1 || docker volume create agentai-hindsight-pg >/dev/null

if ! docker container inspect agentai-hindsight-db >/dev/null 2>&1; then
  docker run -d --name agentai-hindsight-db --restart unless-stopped --network "$NET" \
    --memory 1g --memory-swap 1g --shm-size 256m \
    -e POSTGRES_USER=hindsight -e POSTGRES_DB=hindsight -e POSTGRES_PASSWORD_FILE=/run/secrets/pw \
    -v "$CONF/db-password:/run/secrets/pw:ro" -v agentai-hindsight-pg:/var/lib/postgresql/data \
    pgvector/pgvector:pg17 >/dev/null
fi
for i in $(seq 1 30); do docker exec agentai-hindsight-db pg_isready -U hindsight -d hindsight >/dev/null 2>&1 && break; sleep 2; done
docker exec agentai-hindsight-db psql -U hindsight -d hindsight -c 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null

if ! docker container inspect agentai-hindsight >/dev/null 2>&1; then
  docker run -d --name agentai-hindsight --restart unless-stopped --network "$NET" \
    --memory 3g --memory-swap 3g --shm-size 512m \
    --env-file "$CONF/hindsight.env" -p 127.0.0.1:8888:8888 \
    "ghcr.io/vectorize-io/hindsight:${VERSION}" >/dev/null
fi
echo "waiting for Hindsight..."
for i in $(seq 1 90); do
  curl -fsS -m 3 http://127.0.0.1:8888/health >/dev/null 2>&1 && { echo "Hindsight is up on 127.0.0.1:8888"; exit 0; }
  sleep 4
done
echo "Hindsight did not answer in time; see: docker logs agentai-hindsight" >&2
exit 1
