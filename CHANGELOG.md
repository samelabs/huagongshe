# Changelog

All notable changes to huagongshe are documented here.
Production site: https://huagongshe.com

## [1.2.0] — 2026-08-03

- SSR 用户态：layout 通过 headers() 读取 cookie，SSR 阶段获取用户信息，消除头像布局抖动
- Guide 页面重构为 AI 化学工作台指南，新增 llms.txt / agent-guide / OpenAPI 对外文档
- 首页 AI 卡片改为整卡链接热点，微信绿 + 暖橙双色视觉
- 全站字号统一为 4 级 CSS 变量（--text-lg / text / text-sm / text-xs），清除 146 处硬编码 px
- 移动端可读性修复：SMILES / 化学名 / 反应数据允许换行，禁止 overflow:hidden 截断
- 完整剥离 Next.js ISR / revalidate / force-cache 机制，apiGet 固定 no-store
- 修复 6 个自引用 CSS 变量（--reaction / --danger-border / --success-bg 等）导致样式失效
- 修复 /api/agent-guide 和 /api/openapi.json 中文乱码（nginx charset_types application/json）
- 移除页尾分割线与 hero 副标题，页脚改为 AIchem 开放计划联系方式
- 导航 AI 图标手机端固定 38×38px 正圆，消除布局抖动

## [1.1.0] — 2026-07-21

- 确立 chemistry.chemicals / reactions / reaction_chemicals 自主数据主线
- PubChem worker 本地闭环 + /workapi 受信任写回机制
- 前端围绕化合物、反应、用户仓库与 AI 提交重构，品牌统一 huagongshe.com
- 核心查询可靠性收口：限制分页/结构检索范围，有界详情投影
- RDKit 与图片处理移出 API 事件循环
- 全站移动端布局收口（个人中心、公开主页、结果列表、反应卡片、表单、设置）
- 修复移动端搜索框聚焦溢出（16px 输入字号避免 iOS Safari 缩放）

## [1.0.0] — 2026-07-20

- 初始版本：搜索、ISR 缓存、sitemap、社交功能
- InChIKey 体系：查重优先、Worker 验证比对、回填 CID+SMILES
- Enrichment 兜底：SMILES → InChIKey → Worker 队列
- 反应表达式补全、用户行为分析
