# 化工社开发日志

本文件是项目唯一的持续开发日志。产品规则与架构以 `README.md` 为准；已结束的一次性数据迁移保存在 `archive/`，不参与线上运行。

## 2026-07-21

- 确立 `chemistry.chemicals`、`chemistry.reactions` 与 `chemistry.reaction_chemicals` 为自主数据主线，PubChem、DSSTox、ORD 和 RDKit 只承担来源、补全与计算能力。
- 用户发布反应直接进入主表；创建者可维护、调整公开状态或删除，API Token 与网页共用同一字段模型和写入链路。
- PubChem worker 形成“本地闭环 + 受信任 `/workapi` 写回”机制，不修改 HCID、PubChem CID 或标准 SMILES。
- 前端围绕化合物、反应、用户仓库与 AI 提交重构，品牌统一为 `huagongshe.com`。
- 完成核心查询可靠性收口：限制分页和结构检索范围，化合物页面使用有界详情投影，缓存故障不影响数据库写入结果，RDKit 与图片处理移出 API 事件循环。
- 修复首页搜索框的移动端聚焦溢出：取消强制自动聚焦，保持 16px 输入字号以避免 iOS Safari 自动缩放，并固定查询按钮的可见宽度。
- 生产路径固定为 `/var/www/huagongshe`；服务为 `huagongshe-api`、`huagongshe-web`、`huagongshe-pubchem-worker`，前端运行 Next.js standalone。

### 当前基线

- Git 分支：`main`
- API 版本：`1.0`
- 生产域名：`https://huagongshe.com`
- 发布前验证：后端测试、Next.js production build、`/api/health`、核心查询抽样与服务日志检查。
