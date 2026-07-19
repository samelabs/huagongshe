# 化工社前端

化工社是开放、非商业化的化学数据与反应协作入口。页面以查询为核心，支持化合物/反应检索、账户登录、受验证的化合物与反应提交，以及反应求助。

## 本地开发

```bash
npm install
npm run dev
```

默认通过同域 `/api` 访问后端；需要独立后端地址时设置 `API_BASE_URL`。

## 生产构建

```bash
npm run build
```

生产环境使用 Next.js standalone 输出，由 `huagongshe-web.service` 启动，Nginx 对外提供 `https://huagongshe.com`。

## 产品约束

- 查询始终是首页唯一主入口。
- 登录、提交和维护能力保持次级，不堆叠成后台式界面。
- 主色固定为化工社蓝 `#1677ff`。
- 前端只消费 API，不直接理解数据库或 ORD 内部结构。
