#!/usr/bin/env bash
# rsync a survey/knowledge bundle to ECS staging and trigger server-side import.
set -euo pipefail

BUNDLE_DIR="${1:?bundle dir required}"
JOB_ID="${2:?job id required}"

SSH_TARGET="${SSH_TARGET:?SSH_TARGET is required (e.g. deploy@ecs-host)}"
IMPORT_STAGING_DIR="${IMPORT_STAGING_DIR:-/data/import-staging}"
REMOTE_DIR="${IMPORT_STAGING_DIR%/}/${JOB_ID}"

MANIFEST="${BUNDLE_DIR}/import.manifest.json"
if [[ ! -f "${MANIFEST}" ]]; then
  echo "missing import.manifest.json in ${BUNDLE_DIR}" >&2
  exit 1
fi

# Disk pre-check on remote (need ~2x bundle size).
BUNDLE_BYTES=$(du -sk "${BUNDLE_DIR}" | awk '{print $1}')
REQUIRED_KB=$((BUNDLE_BYTES * 2))
AVAIL_KB=$(ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10 "${SSH_TARGET}" \
  "df -k '${IMPORT_STAGING_DIR}' 2>/dev/null | tail -1 | awk '{print \$4}'" || echo "0")
if [[ "${AVAIL_KB}" -gt 0 && "${AVAIL_KB}" -lt "${REQUIRED_KB}" ]]; then
  echo "remote disk insufficient: need ${REQUIRED_KB}KB, avail ${AVAIL_KB}KB" >&2
  exit 1
fi

ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10 "${SSH_TARGET}" "mkdir -p '${REMOTE_DIR}'"

# Do NOT use -z on pre-compressed .jsonl.gz
rsync -av --progress \
  --partial --append-verify \
  --timeout=600 \
  -e "ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10" \
  "${BUNDLE_DIR}/" "${SSH_TARGET}:${REMOTE_DIR}/"

# Verify SHA256 on remote using manifest (supports embedding_shards[] or single file)
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10 "${SSH_TARGET}" bash -s <<EOF
set -euo pipefail
cd '${REMOTE_DIR}'
python3 - <<'PY'
import hashlib, json, sys
from pathlib import Path
manifest = json.loads(Path('import.manifest.json').read_text())
shards = manifest.get('embedding_shards') or []
if not shards:
    embedded = manifest.get('files', {}).get('chunks_embedded.jsonl.gz')
    if embedded:
        shards = [{'name': 'chunks_embedded.jsonl.gz', **embedded}]
for shard in shards:
    name = shard['name']
    p = Path(name)
    if not p.is_file():
        print(f'missing shard: {name}', file=sys.stderr)
        sys.exit(1)
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if h != shard['sha256']:
        print(f'sha256 mismatch {name}: {h} != {shard["sha256"]}', file=sys.stderr)
        sys.exit(1)
    if p.stat().st_size != shard['bytes']:
        print(f'size mismatch {name}', file=sys.stderr)
        sys.exit(1)
for name, entry in manifest.get('files', {}).items():
    if name == 'chunks_embedded.jsonl.gz' and len(shards) > 1:
        continue
    p = Path(name)
    if not p.is_file():
        continue
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if h != entry['sha256']:
        print(f'sha256 mismatch {name}', file=sys.stderr)
        sys.exit(1)
print('sha256 ok')
PY
EOF

# Trigger import inside app container or on host
IMPORT_CMD="${REMOTE_IMPORT_CMD:-docker exec userbank-prod-app-1 node dist/scripts/import-staging-bundle.js --job ${JOB_ID}}"
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10 "${SSH_TARGET}" "${IMPORT_CMD}"

echo "rsync + import done: job=${JOB_ID}"
