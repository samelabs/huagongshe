#!/bin/bash
# db-entrypoint.sh — 初始化/启动本地 PostgreSQL 16 + RDKit。
# 集群(PGDATA 含配置)整体在命名卷 /var/lib/postgresql/16/main:
#   - 卷为空 → initdb → 建角色/数据库 → 跑 baseline + bootstrap 迁移
#   - 卷已有数据 → 直接启动(全部步骤幂等, 重复执行无害)
set -euo pipefail
PGBIN=/usr/lib/postgresql/16/bin
PGDATA=/var/lib/postgresql/16/main

mkdir -p "$PGDATA" /var/run/postgresql
chown -R postgres:postgres /var/lib/postgresql /var/run/postgresql

# su(1) 会重置 PATH → 全部用绝对路径
as_pg() { su postgres -s /bin/bash -c "$*"; }

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "[db-entrypoint] fresh volume: initdb"
  as_pg "$PGBIN/initdb -D $PGDATA --username=postgres --auth-local=trust --auth-host=scram-sha-256" >/dev/null
  cat >>"$PGDATA/postgresql.conf" <<EOF
listen_addresses = '*'
EOF
  cat >>"$PGDATA/pg_hba.conf" <<EOF
host all all 0.0.0.0/0 scram-sha-256
host all all ::/0 scram-sha-256
EOF
  chown postgres:postgres "$PGDATA/postgresql.conf" "$PGDATA/pg_hba.conf"
fi

as_pg "$PGBIN/pg_ctl -D $PGDATA -w -t 60 start" >/dev/null
until as_pg "$PGBIN/pg_isready -q"; do sleep 1; done

# 角色 + 两个数据库(hgs_local 运行库 / test_hgs 测试库), 幂等
if [ "$(as_pg "$PGBIN/psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='$HGS_DB_USER'\"")" != "1" ]; then
  as_pg "$PGBIN/psql -c \"CREATE ROLE $HGS_DB_USER LOGIN SUPERUSER PASSWORD '$HGS_DB_PASSWORD'\"" >/dev/null
  echo "[db-entrypoint] created role $HGS_DB_USER"
fi
for db in "$HGS_DB_NAME" "$HGS_TEST_DB_NAME"; do
  if [ "$(as_pg "$PGBIN/psql -tAc \"SELECT 1 FROM pg_database WHERE datname='$db'\"")" != "1" ]; then
    as_pg "$PGBIN/createdb -O $HGS_DB_USER $db"
    echo "[db-entrypoint] created database $db"
  fi
done

# baseline + bootstrap: 以 chemistry.chemicals 存在与否为闸门(与 CI 相同的两个文件)
for db in "$HGS_DB_NAME" "$HGS_TEST_DB_NAME"; do
  if [ "$(PGPASSWORD="$HGS_DB_PASSWORD" psql -h 127.0.0.1 -U "$HGS_DB_USER" -d "$db" -tAc \
        "SELECT to_regclass('chemistry.chemicals') IS NOT NULL")" != "t" ]; then
    echo "[db-entrypoint] applying baseline migrations to $db"
    PGPASSWORD="$HGS_DB_PASSWORD" psql -h 127.0.0.1 -U "$HGS_DB_USER" -d "$db" \
      -v ON_ERROR_STOP=1 -f /repo/migrations/0000_baseline.sql >/dev/null
    PGPASSWORD="$HGS_DB_PASSWORD" psql -h 127.0.0.1 -U "$HGS_DB_USER" -d "$db" \
      -v ON_ERROR_STOP=1 -f /repo/migrations/0001_bootstrap_reference_data.sql >/dev/null
  fi
done

as_pg "$PGBIN/pg_ctl -D $PGDATA -m fast -w stop" >/dev/null
echo "[db-entrypoint] ready; handing over to postgres in foreground"
exec su postgres -s /bin/bash -c "$PGBIN/postgres -D $PGDATA"
