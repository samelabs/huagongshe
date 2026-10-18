/**
 * PM2 ecosystem config for huagongshe.
 *
 * Secrets are loaded from /etc/huagongshe.env (git-ignored, chmod 600).
 * See ecosystem.config.cjs.example for required variables.
 */
const fs = require('fs');

function loadEnv() {
  const envFile = '/etc/huagongshe.env';
  const env = {};
  try {
    for (const line of fs.readFileSync(envFile, 'utf8').split('\n')) {
      const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
      if (m) env[m[1]] = m[2];
    }
  } catch {
    console.error('Missing /etc/huagongshe.env — see ecosystem.config.cjs.example');
    process.exit(1);
  }
  return env;
}

const secrets = loadEnv();

module.exports = {
  apps: [
    {
      name: "huagongshe-api",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      cwd: "/var/www/huagongshe",
      script: "./venv/bin/python",
      args: "-m uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips=127.0.0.1 --no-access-log",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONDONTWRITEBYTECODE: "1",
        HGS_DATABASE_URL: secrets.HGS_DATABASE_URL,
      },
    },
    {
      name: "huagongshe",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      cwd: "/var/www/huagongshe/web",
      script: "/usr/bin/npx",
      // 3001 只经 nginx 反向代理访问, 主机防火墙不对外开放该端口。
      args: "next start -p 3001",
      interpreter: "none",
      env: {
        NODE_ENV: "production",
        // /.well-known/openai-apps-challenge 的唯一来源(PM2 不继承 daemon 外的
        // /etc/huagongshe.env; 缺省空串 = route fail closed 404)。
        HGS_OPENAI_APPS_CHALLENGE: secrets.HGS_OPENAI_APPS_CHALLENGE || "",
      },
    },
    {
      name: "huagongshe-pubchem-worker",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      cwd: "/var/www/huagongshe",
      script: "./venv/bin/python",
      args: "-m worker.main",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONDONTWRITEBYTECODE: "1",
        HGS_WORKAPI_URL: "http://127.0.0.1:8000",
        HGS_WORKER_ID: "server-local-1",
        HGS_WORKER_TOKEN: secrets.HGS_WORKER_TOKEN,
        HGS_WORKER_CONCURRENCY: "2",
        LOG_LEVEL: "INFO",
        // Rate limits per upstream; both chains use dedicated local SOCKS ingress.
        HGS_PUBCHEM_REQUESTS_PER_SECOND: "3",
        HGS_CB_REQUESTS_PER_SECOND: "3",
        HGS_PUBCHEM_PROXY: "socks5://127.0.0.1:12345",
        HGS_CB_PROXY: "socks5://127.0.0.1:12346",
        // PubChem and CAS worker scopes are enabled.
        HGS_WORKER_SCOPES: "pubchem,cas",
      },
    },

  ],
};
