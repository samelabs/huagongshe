#!/bin/bash
# 端点冒烟网 — 搬迁重启前必跑(每端点独立进程, 避免跨请求状态污染)
# 用法: bash /var/www/huagongshe/tests/smoke.sh   期望: 全 OK, exit 0
cd /var/www/huagongshe
export $(grep -v '^#' /etc/huagongshe.env | xargs)
PATHS=(
 '/api/health:200' '/api/stats:200' '/api/config:200'
 '/api/search?q=benzene:200' '/api/chemicals/224:200'
 '/api/chemicals/224/externals:200' '/api/chemicals/224/details:200'
 '/api/chemicals/224/synonyms:200' '/api/chemicals/224/reactions:200'
 '/api/chemicals/224/substructure:401' '/api/chemicals/224/similarity:401'
 '/api/datasets:200' '/api/sitemap/reactions:200'
 '/api/reactions/1:200' '/api/mol/224/svg:200'
)
bad=0
for p in "${PATHS[@]}"; do
  path="${p%:*}"; want="${p##*:}"
  code=$(venv/bin/python -c "
from fastapi.testclient import TestClient
from api.main import app
c = TestClient(app, client=('127.0.0.1', 50000))
print(c.get('$path').status_code)" 2>/dev/null | tail -1)
  if [ "$code" = "$want" ]; then echo "$code OK $path"; else echo "$code BAD $path (want $want)"; bad=1; fi
done
exit $bad
