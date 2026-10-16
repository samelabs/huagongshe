#!/bin/bash
# api-entrypoint.sh — 装依赖 → 等 db → forward migrations → uvicorn。
set -euo pipefail

# 持久 venv: 首次创建, 之后 pip 幂等(依赖装满后秒过)
if [ ! -x /opt/venv/bin/python ]; then
  echo "[api-entrypoint] creating venv"
  python -m venv /opt/venv
fi
export PATH="/opt/venv/bin:$PATH"
pip install --quiet --disable-pip-version-check -r /repo/requirements.txt
echo "[api-entrypoint] python deps ready"

mkdir -p "${HGS_AVATAR_ROOT:-/tmp/hgs-data/avatars}" "${HGS_SKILL_ROOT:-/tmp/hgs-data/skills}"

until pg_isready -h db -p 5432 -U "${HGS_DB_USER}" -q; do
  echo "[api-entrypoint] waiting for db..."; sleep 2
done

# forward migrations(§10B runner, 幂等): 运行库 + 测试库(与 CI integration 相同)
for db in "$HGS_DB_NAME" "$HGS_TEST_DB_NAME"; do
  python /repo/scripts/migrate.py "postgresql://${HGS_DB_USER}:${HGS_DB_PASSWORD}@db:5432/${db}"
done
echo "[api-entrypoint] migrations up to date"

cd /repo
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
