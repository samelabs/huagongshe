# api 镜像: python:3.12-slim + psql 客户端(scripts/migrate.py 依赖)。
# Python 依赖不在镜像里 — 由 api-entrypoint.sh 在启动时 pip install 到
# 持久卷的 venv, 始终与挂载的仓库分支 requirements.txt 同步。
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
# rdkit.Chem.Draw(反应/分子渲染)在 slim 上的系统依赖: X11 绘图栈 + expat;
# nodejs: tests 里的 sitemap/SSR harness 子进程需要 node(CI runner 预装, 容器对齐)。
# tester: 测试按 CI 一样以非 root 跑(部分故障注入测试在 root 下不生效)。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-client libxrender1 libxext6 libsm6 libx11-6 libxcb1 libexpat1 nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash tester

COPY api-entrypoint.sh /usr/local/bin/api-entrypoint.sh
RUN chmod +x /usr/local/bin/api-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/api-entrypoint.sh"]
