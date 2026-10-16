# db 镜像: 与 CI integration job 相同的 ubuntu 24.04 + PostgreSQL 16 + RDKit cartridge。
# 构建期 apt 安装后删掉 deb 自带的集群, 运行期集群整体落在命名卷
# /var/lib/postgresql/16/main(config 也在 PGDATA 内, 换容器不丢数据)。
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
# archive.ubuntu.com 拉 rdkit 大包偶发 500 EOF, 重试 3 次;
# pg_dropcluster 的 || true 只括住自己 — 不能吞掉 apt 的失败(shell 优先级)。
RUN apt-get update \
 && for i in 1 2 3; do \
      apt-get install -y --no-install-recommends postgresql-16 postgresql-16-rdkit \
      && break; \
      echo "apt install attempt $i failed, retrying after update"; \
      apt-get update; \
    done \
 && dpkg -s postgresql-16 postgresql-16-rdkit >/dev/null \
 && rm -rf /var/lib/apt/lists/* \
 && { pg_dropcluster --stop 16 main || true; }

COPY db-entrypoint.sh /usr/local/bin/db-entrypoint.sh
RUN chmod +x /usr/local/bin/db-entrypoint.sh

EXPOSE 5432
ENTRYPOINT ["/usr/local/bin/db-entrypoint.sh"]
