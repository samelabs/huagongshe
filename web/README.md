# 化工社前端

`web/` 是 `huagongshe.com` 的用户入口。产品对象只有化合物与反应；PubChem、DSSTox、ORD 和 RDKit 均是数据来源或能力，不作为前端并列产品域。

## 信息结构

- 首页：唯一的全局身份查询入口与精确数据规模。
- 查询：化合物结果和反应结果分区展示。名称、CAS、SMILES 与外部标识定位化合物；稳定 reaction ID、ORD ID 和 DOI 定位反应。
- 化合物：结构身份、外部标识、计算/实验扩展信息、别名、参与反应和反应求助。
- 反应：方程式、反应物、生成物、辅助组分、条件、过程、后处理、结果和来源证据。
- 贡献：按 chemicals / reactions 的写入结构提交；自动校验后进入人工审核。
- 审核：核对结构、身份、角色、条件与来源后决定是否写入核心数据。

子结构和相似结构检索是具体化合物的上下文工具，不是全局搜索模式。数据集名称和 ORD 原始文本只作为来源证据，不作为页面标题。

## 运行

```bash
npm install
npm run dev
npm run build
```

服务端渲染默认通过 `API_BASE` 访问 FastAPI；浏览器通过同域 `/api` 访问。生产环境使用 Next.js standalone，由 `huagongshe-web.service` 在 `127.0.0.1:3001` 运行，Nginx 对外提供 `https://huagongshe.com`。

主色使用化工社蓝 `#1677ff`。前端不直连数据库，也不自行解释 ORD 表结构。
