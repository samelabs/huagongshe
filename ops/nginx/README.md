# nginx 站点配置（生产权威来源入库副本）

生产 nginx 的站点与 snippet 配置以本目录为权威来源。快照导自生产
（2026-10-17，只读），`huagongshe.conf` 在快照基础上补齐了对外数据服
务需要的 `/data/` location 与 `hgs_data_api` 限流 zone（生产尚未应用，
随本版本发布）。

## 安装位置

| 仓库文件 | 生产位置 |
|---|---|
| `huagongshe.conf` | `/etc/nginx/sites-enabled/huagongshe` |
| `00-default-444.conf` | `/etc/nginx/sites-enabled/00-default-444` |
| `snippets/cloudflare-realip.conf` | `/etc/nginx/snippets/cloudflare-realip.conf` |
| `snippets/security-headers.conf` | `/etc/nginx/snippets/security-headers.conf` |

证书路径（`/etc/letsencrypt/live/huagongshe.com/`）在 conf 内引用，证书
本身不入库。`/etc/letsencrypt/options-ssl-nginx.conf` 与 `ssl-dhparams.pem`
由 certbot 管理，同样不入库。

## 与 ops.deploy 的关系

`ops/deploy.py` 的日常发布**不触碰 nginx**（upstream 固定 127.0.0.1:
8000/3001，不随发布重写）。它提供的 `nginx-bootstrap` 子命令只在 site
文件已存在时做一次性 canonical 化（删除 generation include、恢复固定
upstream 名），随后 `sudo -n nginx -t` 校验并 reload。本目录是人工安装
与核对的标准来源：新机器初始化或漂移修复时，由 deployment user 把文
件复制到上表位置。

## 改动流程

1. 修改本目录下的 conf；
2. 复制到生产对应位置（经 deployment user，`sudo -n cp`）；
3. `sudo -n nginx -t` 必须通过；
4. `sudo -n nginx -s reload` 生效；
5. 用公网冒烟（`Huagongshe-Deploy-Smoke/1.0` UA）核对 `/api/health`
   与首页。

`cloudflare-realip.conf` 的信任网段清单必须与 Cloudflare 官方公布的一致
（https://www.cloudflare.com/ips/）；Cloudflare 调整网段时同步更新，否则
真实 IP 恢复失效、按 IP 的限流会按边缘节点分桶。
