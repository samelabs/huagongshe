# Changelog

All notable changes to huagongshe are documented here.
Production site: https://huagongshe.com

## [1.5.2] — 2026-09-19

- 应用层/传输层归属收口：transport ownership 全面闭合，HTTP 与 MCP 共享同一 application service owner，服务层零传输层依赖
- Chemical Detail 统一契约：唯一公开面 `GET /api/chemicals/{id}?enrich=core|full`；core 零 provider 访问（canonical+localized names+轻量上下文），full = core + semantic detail；测试证明 core 不触碰任何 provider service
- PB/CB semantic aggregation：后端 7-section semantic projection（description/names/properties/safety/industry/suppliers/provenance），PB/CB 不做一级 namespace，冲突事实双 value+source 保留不静默合并；单源失败标 unavailable，canonical 不因此 500；统一 enrichment 状态（current/queued/stale/none/unavailable）
- 历史分叉面删除：`/chemicals/{id}/details`（12 天零消费）与 `/chemicals/{id}/externals` 端点删除，无 compatibility wrapper；Web 详情页三请求改双请求（chemical full + reactions），metadata 只取 core，前端 PB/CB 组合职责下沉后端
- MCP chemical 面合流：get_chemical_externals 工具删除（14→13），get_chemical 契约统一 core/full；llms/Agent Guide/registry/契约测试同步
- Identity CONFLICT fail-closed：CONFLICT/AMBIGUOUS 一律禁止 INSERT（transport-neutral 异常，reaction 路径 409+rollback 零副作用，search 路径降级不 500 不建行）；真库回归锁死同 InChIKey 双 CID 场景第三行不可达
- Admin Pipeline 有界化：runtime 统计全部先时间窗口再聚合（today/last_1h only），删除 CB locale/PB all-time/supplier 8.67M listing/seed 的无界 count；LKG/SWR/single-flight 缓存机制保留；防回归测试静态锁定 SQL 边界
- Governance 伪能力删除：seed_enqueued_no_job（永久 deferred）与 resolver_events 假面移除；merge history/redirects/seed 账本保留，未新增 FK/event ledger
- WorkAPI completion receipt 维护命令：`scripts/prune_workapi_receipts.py`（retention 30d/batch 10000/逐批 commit/dry-run/DB 错误非零退出，不 import WorkAPI transport）
- WorkAPI/Worker trusted-plane 测试与治理收口：admin worker 删除三表 lease 预检 409 契约、治理面板精简，Worker/WorkAPI auth/HMAC/lease runtime semantics 未变（diff 零）
- 测试环境/CI 可移植性：测试桩对齐真实 SQLAlchemy result 链；真库冲突/有界 SQL/semantic 契约新测试族；full suite 1216 tests / 0 failures / 0 errors / 1 existing skip
- 部署代际基础设施：generation 切换无上游中断机制（E8）、worktree 状态卫生（generation build 不入 worktree）已就绪
- 性能/索引工作：E2 有界索引（≤0.3GB）与 migration 已准备就绪，待生产 migration 阶段执行（本版未部署）

## [1.5.1] — 2026-09-18

- API/MCP 治理：能力与契约治理账本落地（family / scenario / contract 对账），route↔scope 校验进入常驻治理测试；MCP 工具清单与 API 契约同源
- 架构收敛：reaction / skill 读写路径下沉为 transport-neutral 应用服务，HTTP 与 MCP 共用同一 owner，MCP→HTTP handler 调用归零，服务层不再依赖传输层对象
- 边界清理：限流与错误语义中立于传输层；写入事务与幂等语义显式化（skill slug 冲突、reaction 校验失败不再吞错）
- 修复：D001 更新反应后返回体与落库事实一致；D002 反应 SVG BFF 缓存契约保持上游 passthrough，上游缺失时降级 private, no-store
- 测试/治理收口：此前因缺少真实 PostgreSQL 而长期跳过（gated skip）的测试首次全量执行并通过，测试引用与 canonical service owner 对齐
- 债务说明：A002/A003 仍有残余项；D004（测试环境可移植性）、D010、T001/T002 等以 follow-up 形式登记，本版不声称全部技术债已清除

## [1.5.0] — 2026-09-14

- 搜索系统治理：名称 exact/fuzzy 候选流统一；分页 deterministic bounded，has_more 语义事实化；CJK 短查询性能与排序正确性修复
- Worker trusted plane：method+exact-path scope 校验 fail-closed；completion receipt 幂等确认；worker enable/disable 生命周期语义明确（停权不删记录）；post-commit housekeeping 不再反转成功事务
- Schema/CI：baseline + forward migration runner 上线，migration checksum/tracking 落库；CI 迁移到全新 PostgreSQL/RDKit/Redis hermetic 环境，覆盖前后端 build/typecheck 与 full test suite
- Admin 工作台：Users / Reactions / Skills 分页、筛选与 URL state；Workers / Pipeline / Governance 面板；Pipeline 健康度改为事实语义；危险操作（停用 worker、角色变更）二次确认；Config 保存不再覆盖其他未保存草稿；Dashboard 会话统计改为事实标签
- Web/mobile：Admin 移动端导航与 dashboard 紧凑布局；huagongshe.com wordmark；PWA 搜索输入兼容性修复；favicon 资产契约固化
- 生产治理：统一 production checkout / PM2 runtime / 干净环境变量；清除测试库环境变量与历史开发运行残留

## [1.4.1] — 2026-09-09

- 工作台反应模块：列表头部常驻「新建反应」入口
- 数据链 worker 配置：PubChem 限速调整与作用域恢复
- 维护脚本与配套测试移出仓库，归档至运维目录
- PWA 缓存版本更新

## [1.4.0] — 2026-09-08

- 化合物身份治理上线：多来源数据统一身份裁定（结构证据授权合并、无判据挂起、冲突拒绝写入），合并全程留审计记录与旧 ID 重定向
- ChemicalBook 数据链接入：按 CAS 异步获取化合物页面，中英日韩德法语言页独立入库；来源记录以 (HCID, 来源编号, 语言) 粒度保留
- 检索未命中且输入为 CAS 时自动入队获取，命中后直达详情页
- MCP 工具增强：分子结构图支持直接传入 SMILES 渲染；技能详情支持数字 ID 或 slug 查询；投料计算工具内置调用示例
- 化合物主表新增 InChIKey 与来源编号字段，支撑跨来源结构对齐
- 受控 SSR 数据缓存层（A 档）：仅低频无用户态读取走 revalidate，带用户凭据的请求禁缓存

## [1.3.0] — 2026-08-22

- AIchem 新增投料计算工具：角色化组分 + 基准换算（质量/摩尔/当量）+ 理论收率 + 溶剂定容，RDKit 后端（api/stoichiometry.py），agent-guide 与 llms.txt 同步宣告
- 投料计算基准修复：前端基准索引重映射（删行/空行后不再错指），后端基准行恒归一 1.00 eq 与 basis.mass_g 自洽，基准空行专用报错文案
- 技能注册表收口：DB+FS 存储、zip 上传/校验/下载/幂等/限流，公开池 159 技能，静态源退役，/skills 公开页改吃 /api/skills
- 技能分类字典治理：分类唯一来源字典 API，visibility 单一路径（用户恒 private，公开唯一入口 admin），配额校准 128 文件 + 二进制放行 assets/+examples/
- 后台新增 /samelabs/skills 技能治理（发布/下架/删除 + 分类字典管理），返回 owner 嵌套结构对齐全站契约（修复后台技能页白屏）
- 工作台新增「我的技能」面板（上传 zip/下载/删除），上传区布局与按钮变体收口
- 移动端底栏两连修：锚定视口根除 dvh 壳重算竞态；浏览器模式几何零 env() 输入，根除 iOS 工具栏折叠引起的 inset 跳变
- /config 走 A 档 revalidate 缓存（300s），消除每渲染一次的内部风暴（~85 req/s → 每窗口 1 次）
- 全站滚动条规范收口：细 6px 圆角两层基线替代 UA 裸默认；全站内容宽度两档 token（760px/1040px），globals 17 种随机 max-width 清零
- 术语统一收口：产品名 AIchem、凭据统一 API Token、动作统一「接入」；aichem 域色值/字号 token 化清零硬编码

## [1.2.1] — 2026-08-14

- 修复 rate_limit 伪造 Bearer token 无限绕过：有效 token 按所属用户独立预算，无效/伪造/DB 故障回落 IP 预算
- 反应编辑路径补 moderation_status 守卫，隐藏反应不再计入补偿统计，与 admin/delete 语义对齐
- public_profile 仅本人返回 email；新增 DELETE /users/me/avatar 镜像清理 512 原图与 -128 变体
- 工作台重组为注册表模式（components/workbench）+ 跨端共享组件（components/shared）
- aichem 面板样式自包含（aichem-tokens.css + aichem.css，--wb-* token 零依赖 globals）
- 工作台面板手机端满宽修复；设置页卡片圆角收口、kicker 占位隐藏；用户列表卡片化
- 修复 --success-bg 自引用（恢复 #ecfdf5 并补 --success-border）；--text-base 未定义引用归位；硬编码字号归 4 级 token
- SearchPanel / AccountForm 竞态守卫，过期响应丢弃；ReactionList 计数改用 SSR 权威 reactionTotal
- i18n 收口约 30 处硬编码文案；FollowButton label 语义化（follow/favor）
- 工作台顶栏头像对齐 -128 变体

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
