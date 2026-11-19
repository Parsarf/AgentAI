#!/bin/sh
# Installs the knowledge index (roadmap Phase 4) on the Lumina server. Run as root; safe to run again (existing secrets and data are kept).
# What it makes:
#   * agentai-knowledge-db    PostgreSQL 17 with the vector extension, its own volume and its own password, published on 127.0.0.1:5433 only. It is NOT Hindsight's database:
#                             documents and the customer's memory are kept apart (the owner's choice, 2026-11-16).
#   * agentai-embeddings      a self-hosted embedding server (text-embeddings-inference, CPU, intfloat/multilingual-e5-small) on 127.0.0.1:8890 only. Documents are never sent
#                             outside the server to be embedded. It downloads the model once while installing, then runs with downloads switched off.
#   * /var/lib/agentai-platform/knowledge/index.url   the database address with its password (0600, the app user), read by the app, the tool relay and the worker
#   * /var/lib/agentai-platform/knowledge/model-key   a Lumina model key used ONLY to read pages that have no text (0600, the app user). Issued from the model proxy with the
#                             master key, which this script reads and never prints.
# It does NOT turn the feature on: that is the owner's `customer_knowledge` switch. It never prints a secret.
set -eu
umask 077
APPUSER=agentai-platform
STATE=/var/lib/agentai-platform/knowledge
CONF=/etc/agentai-knowledge
NET=agentai-knowledge
PG_IMAGE="${KNOWLEDGE_PG_IMAGE:-pgvector/pgvector:pg17}"
TEI_IMAGE="${KNOWLEDGE_TEI_IMAGE:-ghcr.io/huggingface/text-embeddings-inference:cpu-1.8}"
MODEL="${KNOWLEDGE_EMBED_MODEL:-intfloat/multilingual-e5-small}"
# The embedding server's memory and the tokens it puts through the model at once. At 1500m and 8192 it was killed by its memory cap on the first request of
# 32 long passages (a real 320 KB PDF, 2026-11-19; ten restarts that day). 4096 bounds one forward pass, 2500m leaves headroom; measured: 32 long passages in
# 5.4 s, no restart in ten requests. A container made with other settings is replaced (its label says what it was made with).
EMBED_MEMORY="${KNOWLEDGE_EMBED_MEMORY:-2500m}"
EMBED_BATCH_TOKENS="${KNOWLEDGE_EMBED_BATCH_TOKENS:-4096}"
EMBED_SETTINGS="image=$TEI_IMAGE model=$MODEL memory=$EMBED_MEMORY batch_tokens=$EMBED_BATCH_TOKENS"
WIRING=/etc/agentai-supervisor/native-wiring.json

install -d -m 0700 -o "$APPUSER" -g "$APPUSER" "$STATE"
install -d -m 0700 -o root -g root "$CONF"
gen() { head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c 40; }
[ -f "$CONF/db-password" ] || gen > "$CONF/db-password"
chmod 0600 "$CONF/db-password"
PW=$(cat "$CONF/db-password")

docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
docker volume inspect agentai-knowledge-pg >/dev/null 2>&1 || docker volume create agentai-knowledge-pg >/dev/null
docker volume inspect agentai-embeddings-models >/dev/null 2>&1 || docker volume create agentai-embeddings-models >/dev/null

if ! docker container inspect agentai-knowledge-db >/dev/null 2>&1; then
  docker run -d --name agentai-knowledge-db --restart unless-stopped --network "$NET" \
    --memory 1g --memory-swap 1g --shm-size 256m -p 127.0.0.1:5433:5432 \
    -e POSTGRES_USER=knowledge -e POSTGRES_DB=knowledge -e POSTGRES_PASSWORD_FILE=/run/secrets/pw \
    -v "$CONF/db-password:/run/secrets/pw:ro" -v agentai-knowledge-pg:/var/lib/postgresql/data \
    "$PG_IMAGE" >/dev/null
fi
for i in $(seq 1 30); do docker exec agentai-knowledge-db pg_isready -U knowledge -d knowledge >/dev/null 2>&1 && break; sleep 2; done
docker exec agentai-knowledge-db psql -U knowledge -d knowledge -qc 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null
printf 'postgresql://knowledge:%s@127.0.0.1:5433/knowledge\n' "$PW" > "$STATE/index.url"
chown "$APPUSER:$APPUSER" "$STATE/index.url"; chmod 0600 "$STATE/index.url"

if docker container inspect agentai-embeddings >/dev/null 2>&1 && \
   [ "$(docker inspect agentai-embeddings --format '{{index .Config.Labels "lumina.settings"}}' 2>/dev/null)" != "$EMBED_SETTINGS" ]; then
  echo "the embedding server was made with other settings: replacing it (requests in the next seconds are retried by the knowledge worker)"
  docker rm -f agentai-embeddings >/dev/null
fi
if ! docker container inspect agentai-embeddings >/dev/null 2>&1; then
  # First start downloads the model into its own volume; it is then restarted with downloads off.
  docker run -d --name agentai-embeddings --restart unless-stopped --network "$NET" \
    --memory "$EMBED_MEMORY" --memory-swap "$EMBED_MEMORY" --cpus 2 -p 127.0.0.1:8890:80 \
    -v agentai-embeddings-models:/data "$TEI_IMAGE" --model-id "$MODEL" --max-batch-tokens "$EMBED_BATCH_TOKENS" >/dev/null
  echo "waiting for the embedding server to download its model..."
  for i in $(seq 1 120); do curl -fsS -m 3 http://127.0.0.1:8890/health >/dev/null 2>&1 && break; sleep 5; done
  docker rm -f agentai-embeddings >/dev/null
  docker run -d --name agentai-embeddings --restart unless-stopped --network "$NET" --label "lumina.settings=$EMBED_SETTINGS" \
    --memory "$EMBED_MEMORY" --memory-swap "$EMBED_MEMORY" --cpus 2 -p 127.0.0.1:8890:80 -e HF_HUB_OFFLINE=1 \
    -v agentai-embeddings-models:/data "$TEI_IMAGE" --model-id "$MODEL" --max-batch-tokens "$EMBED_BATCH_TOKENS" >/dev/null
fi
for i in $(seq 1 60); do curl -fsS -m 3 http://127.0.0.1:8890/health >/dev/null 2>&1 && break; sleep 3; done
DIMS=$(curl -fsS -m 30 http://127.0.0.1:8890/embed -H 'Content-Type: application/json' -d '{"inputs":["query: test"]}' | python3 -c 'import json,sys; print(len(json.load(sys.stdin)[0]))')
[ "$DIMS" = 384 ] || { echo "the embedding server answers with $DIMS dimensions, expected 384" >&2; exit 1; }

if [ ! -s "$STATE/model-key" ]; then
  ENVFILE=$(python3 -c "import json; print(json.load(open('$WIRING'))['litellm_env'])")
  MASTER=$(sed -n 's/^LITELLM_MASTER_KEY=//p' "$ENVFILE" | tr -d '"'"'"'' | head -n1)
  KEY=$(curl -fsS -m 30 http://127.0.0.1:4000/key/generate -H "Authorization: Bearer $MASTER" -H 'Content-Type: application/json' \
        -d '{"key_alias":"lumina-knowledge-vision","models":["claude-sonnet-5-5"],"metadata":{"purpose":"reading pages with no text for the knowledge index"},"rpm_limit":60}' \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')
  unset MASTER
  printf '%s\n' "$KEY" > "$STATE/model-key"; unset KEY
  chown "$APPUSER:$APPUSER" "$STATE/model-key"; chmod 0600 "$STATE/model-key"
fi
docker image inspect "$PG_IMAGE" "$TEI_IMAGE" --format '{{index .RepoDigests 0}}' > "$CONF/image-digests"
echo "knowledge index on 127.0.0.1:5433, embeddings on 127.0.0.1:8890 ($DIMS dimensions). Add to /etc/agentai-platform/accounts.env:"
echo "  AGENTAI_KNOWLEDGE_INDEX_FILE=$STATE/index.url"
echo "  AGENTAI_EMBEDDINGS_URL=http://127.0.0.1:8890"
echo "  AGENTAI_KNOWLEDGE_MODEL_KEY_FILE=$STATE/model-key"
echo "Image digests recorded in $CONF/image-digests (copy them into runtime.lock.json)."
