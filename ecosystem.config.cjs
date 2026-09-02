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
      cwd: "/var/www/huagongshe",
      script: "./venv/bin/python",
      args: "-m uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips=127.0.0.1",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONDONTWRITEBYTECODE: "1",
        HGS_DATABASE_URL: secrets.HGS_DATABASE_URL,
      },
    },
    {
      name: "huagongshe",
      cwd: "/var/www/huagongshe/web",
      script: "/usr/bin/npx",
      args: "next start -H 127.0.0.1 -p 3001",
      interpreter: "none",
      env: {
        NODE_ENV: "production",
      },
    },
    {
      name: "huagongshe-pubchem-worker",
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
        // 2026-08-29: 3 rps 缓放 + PB 专用 socks 出口(本机直连 IP 被封).
        // 双链全开(此前 pm2 set 事故残留 HGS_WORKER_SCOPES=cas 脏值导致 PB 单链缺席).
        // 2026-08-30: CB 链也走代理迁移进本 worker(双线程: PB 代理 + CB 代理,
        // 各自独立 session/出口), 原 server-local-2 专属 worker 保留为分发原型不再承担生产.
        HGS_PUBCHEM_REQUESTS_PER_SECOND: "3",
        HGS_CB_REQUESTS_PER_SECOND: "3",
        HGS_PUBCHEM_PROXY: "socks5://127.0.0.1:12345",
        HGS_CB_PROXY: "socks5://127.0.0.1:12345",
        HGS_WORKER_SCOPES: "pubchem,cas",
      },
    },

  ],
};
