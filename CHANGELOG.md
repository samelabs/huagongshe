# Changelog

All notable changes to huagongshe are documented here.
Production site: https://huagongshe.com

## [1.7.5] — 2026-10-22

**安全与并发加固（上线审计修复）**
- OAuth 撤销竞态收口：用户行共同锁覆盖令牌签发、授权码兑换、刷新与撤销，撤销一并清除待用授权，断开连接后旧凭据不可再换取有效令牌
- 头像解析在像素检查前拦截 PNG 画布尺寸（APNG 首帧提前分配防护），保留 JPEG/PNG/WEBP 白名单与既有字节/像素政策
- 损坏技能 ZIP（CRC/截断/加密/不支持算法）按输入异常分类为归档校验错误，REST 400 与 MCP ToolError 同源，目录穿越/压缩比等既有政策不变
- 笔记创建配额在用户锁内计数与写入，并发临界点只放行一个；slug 碰撞仅回滚 savepoint、不释放配额锁
- 注册用户名 search 与用户搜索路由冲突收口：新增 by-username 读取路径，个人主页与资料设置两处客户端同步迁移
- Data API 化合物 int4 / 反应 int8 与批量输入在实体 SQL 前校验，越界稳定 422
- 笔记引用与检索按被引用列类型设界（化合物 int4、反应 int8）；反应数值拒绝非有限值并对存量防御读取；AI Key 创建配额按用户串行化；名称检索未定义引用修复；代理上传上限对齐网关容量、超限明确 413
- 技能包上限上传入口与 MCP 端点独立放宽、三面同源；CIMD 文档拉取把 DNS 解析纳入总超时

**笔记系统**
- 笔记 URL 改 slug 公共标识；模型扩容可选标题与阅读量，关联表达成熟化
- 详情页「编辑」入口读取统一 slug、写入删除仍用数字 id；读取失败显式反馈不再静默回列表；保存加同步重入守卫
- 笔记 slug 回填迁移改碰撞可恢复分配

**技能与 MCP**
- skills 全站改登录后使用：REST/MCP/web 三面同墙；/skills 闸门按会话有效性判定，伪造/过期会话同样引导登录
- 用户技能自发布进公开池（分类沿袭词表），下载设登录墙；MCP 指南口径五语种同步

**通知与社交**
- 通知链路补全个人事件：新粉丝与反应被收藏；已读未读逐条表达，读写收编单一 owner
- 动态归位通知、工作台布局收口；Redis 连接池随事件循环收尾
- 收藏无作者的导入反应不再 500；feed 作者行补 @handle

**性能与外壳**
- 公开页面按路由判定边缘缓存，RSC 按请求头哈希可共享缓存；skipProxyUrlNormalize 开启；首屏登录占位与水合同形、顶栏账号位定宽槽，访客/登录与水合翻转零位移
- 登录态客户端刷新收窄：服务端已确认匿名不再复核（原条件对每个匿名访客多发一次必然 401 的 /users/me，爬虫潮下日增数十万废请求）；仅共享缓存页保留客户端补取
- 手机顶栏统一为登录即汉堡（全站一套）；手机键盘弹出底栏退场、收起恢复

**版本表达**
- 版本声明收口为仓库根 VERSION 单一真相：web 构建时读入注入，/api/health、MCP serverInfo 与全站页脚尾行三处同源、随发布自动更新；package.json 不再自带 version 字段

**工程治理**
- 统一检查入口 local/check.py（preflight/web/backend/worker/release），docs/TESTING.md 为唯一权威手册
- 本地与 CI 检查 fail-closed：exit/skip/xfail 共同定级、dev/build 互斥、超时与中断收尾、结果脱敏、Redis 锁跨 checkout、DB 保护顺序、前端测试单一 manifest 拒绝遗漏与重复
- 注释与文案词表检查升级，代码/测试/运维配置存量过程语言清零；首页一级入口契约对齐（MCP、Skills 与 Plugin）
- 代码结构收口：web 组件按域归组（chemical/reaction/shared/ui/samelabs，根层散件清零）；MCP 实现层与注册面分层（api/mcp 限值/错误映射/请求侧原语/输出投影四件套，工具注册面与历史导入/patch 面不变）
- 占位符卫生与检查脱敏的机制冲突收口：检查编排器遮蔽串改程序拼装（源码不再携带字面量），卫生扫描剪除运行时产物目录（local/.check-runs 按脱敏设计携带遮蔽串）

**视觉收口**
- 化合物/反应互动视觉归一：中性胶囊行、CAS 归位、CID 退卡、头像色基准统一；实体页头部互动图标改静默图标钮
- 主页名片操作收口、信息区社交化重排，本人主页短链行（复制/分享）；主页 Tabs 笔记置于反应之前、手机默认笔记 tab
- 化合物详情页名称链重排（CAS 标签级优先）、结构图透明背景直出、动态方程式防塌陷
- 笔记承载面专业化：详情页去面包屑、列表行标题先行的内容序、署名行两端对齐
- 首页 hero 与 AI 接入区收敛为一条检索条；搜索结果行取阅读档宽、悬停标题转操作色；工作台搜索化合物结果行去卡片框
- 按钮内距随字号档匹配；徽章随场景收敛；分享面板抛错退回复制
- 搜索结果行重构：化合物与反应统一行语言（结构图/方程式图主视觉无框直出、名称先行、一行标识、行间发丝线分隔），撤结果卡片框与行内胶囊，行取页面全宽锚定网格；MCP 指南接入信息组去外层卡片框（免卡片套卡片）
- 阅读档正文列居中（笔记详情、指南、法务三页、MCP 指南、数据 API 文档）；阅读档 720→860，指南/MCP/数据API/Skills 升 content 1040 档；设计系统剥离对齐类纪律表述，页面排布由场景决定

**依赖升级**
- Next 16.4.1 + React/React-DOM 19.2.9；python-multipart 0.0.30 + Pillow 12.2.0（头像解码白名单）

## [1.7.4] — 2026-10-18

**化合物详情页信息架构**
- 页头收敛为标题块：标题（当地名→英文常用名→系统名→分子式→HCID 单链解析）、副标题（英文常用名，缺省以系统名兜底，不再单独成行展示）、身份与互动同一行（HCID 徽标、CAS 带复制、收藏、分享、打印），桌面不断行；收藏改为浅色 tonal 样式贴合语义
- 内容首屏 = 结构图卡（含子结构检索、查找相似结构入口，全宽度直接可见）｜基本信息（标准 SMILES/InChIKey 带复制、分子式、平均与单同位素分子量）并排；概述（来源编辑文本）通栏下移引领正文分区；分子式、质量、来源编号等标识信息保留在基本信息与数据库标识分区，不再重复出现在页头
- 「新建反应记录」入口移入相关反应分区头（分区级动作位），原侧栏推广卡移除，侧栏只留本页导航；结构图首屏优先加载（eager + 高抓取优先级）

**反应详情页可读性**
- 互动行分组独占一行：标识/分享/打印、收藏或本人编辑删除，组内不拆分、徽标六边形图标窄行不压缩
- 手机端方程式图在卡片内放大一倍横向滑动（多组分反应不压缩到不可读）；反应 SMILES 完整换行显示（CodeField 新增 wrap 形态，保留空白、逐字符断行、纵向限高内部滚动）

**外壳与移动端**
- 工作台手机动作（抽屉菜单、创建入口）改上下文驱动：站内切进/切出工作台随路由显隐，顶栏实例全程不卸载；整页打开工作台时手机动作随服务端 HTML 直接输出
- 手机端页脚可达：法务三页（隐私/条款/支持）链接随页脚显示在底栏上方，让位用外边距保持页脚上下内边距与桌面一致
- 首页 AI 接入分区电脑端收进阅读列居中，分区标题与卡片左缘对齐

**对外输出**
- MCP 化合物/反应输出改显式白名单（键集合冻结为当前输出，服务层新增键不自动外泄）；creator 子对象同规则；安全数据与实验物性的字段名经规范表统一为中性英文名
- 字段规范表补齐来源站多语言安全键（德/日/韩/中写法落到统一规范名，新增 Hazard note 等规范名；法规与清单专名保持原样），规范表提升至 services 层供站内与 MCP 共用
- 数据 API 反应投影删除恒为 public 的 visibility 字段（过滤条件不变）；反应摘要行同步

**部署与观测**
- PM2 三个应用日志行带时间戳；nginx 访问日志追加请求耗时、上游耗时与访客元信息，默认 vhost 443 拒绝 TLS 握手；部署脚本子进程最小环境不继承调用方终端
- 法务三页移出 sitemap 与 llms.txt，链接进页脚（五语言）；数据 API 文档页并入数据客户端分区

**工程治理**
- 注释与文案词表检查升级：识别块注释全文（含无星号续行）、配置文件注释与新增残句形态，新增全量扫描模式；代码、测试与运维配置中的存量过程语言与编号代号清零，改写为领域语言
- 样式字面值棘轮随版式收口回落（重复选择器合并、废弃规则删除）

## [1.7.3] — 2026-10-17

**对外数据服务 /data/v1**
- 只读 GET 数据接口：HMAC 凭证签名鉴权（client_id + token + 时间窗 ±300s + nonce 防重放，按 (method, path, query, body 哈希) 签名），scope 精确映射到 (方法, 路径)；响应统一 JSON 带 request_id，错误统一 {error:{code,message}} 契约（含 422 参数校验的统一包络）
- 化合物/反应投影与站内详情页同分区同字段（slug 结构化投影，不新造字段）；lookup 按唯一标识或名称查候选（≤20，名称精确优先、归一后 ≥3 字符才做子串）
- lookup 未收录时按站内同一规则兜底：SMILES 本地建行并触发采集（返回新 HCID 与 updating 状态）、CAS 受控入列采集（pending 回查），采集入队走后台优先级档、沿用现有去重
- 批量接口上限（化合物 50 / 反应 20）与 30 秒整体耗时预算（到点剩余项进 missing 并置 timed_out，200 部分成功）；按凭证分钟/天双额度计量，超限 429 带 Retry-After；对外文档页 /data-api 与行为一致

**对外数据服务与发布加固**
- 凭证到期按「本地时钟 + 容差」三态比较（临近到期告警），相关反应输出去重，批量耗时预算，参数校验错误统一包络，鉴权失败加 per-IP 失败桶（30 次/分钟，桶满查库前即拒）
- /data/v1：SMILES 解析丢线程池（不卡事件循环）；nginx /data/ 文档补 limit_req
- /api/search：locale 参数加长度上限并按 CB locale 白名单归一后再拼缓存键（键空间有界）
- 发布流程写入「先迁移后部署」顺序（docs/DEPLOYMENT.md）
- 「找人」更名「发现作者」：工作台社交组 tab、搜索落地页与各空态文案去内部沟通语；动态/关注空态的下一步动作改为明确的「去发现作者」直达入口
- 工作台笔记列表行收口：行内操作改图标按钮（与收藏面板同范式）、空内容标题用「无标题笔记」、空态补一句说明；搜索结果空态的「清空查询」并入空态动作位；发现作者行去掉内联样式

**化合物名称多语言（I-086 / I-087）**
- name_index 的 CB 镜像推广到全部 locale：任意 locale 行落库（含转 error）都触发按"该化合物全部 locale ok 行并集"重建，日文、韩文、德文名可被搜索命中；供应商名改为镜像 supplier listing ⋈ profile（与刷新顺序无关）；lang 列放宽（zh-CN 沿用 'cn'，其余 ja/ko/de，迁移 20261015_03）
- 详情 enrich=core|full 与搜索结果接受 locale 参数，化合物条目新增 `name_local`（该 locale ok CB 行的当地名，多条按 cb_number 取第一条；zh-CN 与 name_cn 一致；无则 null）；core 保持零 provider 访问
- 新增可续跑回填脚本 scripts/backfill_name_index_locales.py（分批 500、--dry-run、断点续跑）

**用户搜索（I-082）**
- 新增 GET /api/users/search：username 前缀 / display_name 包含（均不区分大小写，完全匹配排第一），只返回 active 用户公开字段，page ≤ 50、page_size ≤ 50（默认 20）、返回 total；匿名按 IP、登录按用户限流 60/min

**列表分页与详情数组上限（I-083）**
- 详情嵌数组硬上限 + 总数字段：suppliers 50（suppliers_total）、cb_aliases 200（cb_aliases_total）、cb_price 50（cb_price_total）、cb_updown 每向 100（up_total/down_total）、cb_experimental 与六个文字组各 100（*_total，自定口径）；详情 synonyms 上限 20→200
- /chemicals/{id}/synonyms page_size 上限 500→100；/admin/workers SQL 加界（≤200）；/users/me/oauth-connections LIMIT 100；/users/me/tokens LIMIT 5（与创建上限一致）

**MCP 工具元数据（I-067）**
- tools/list：描述去除 docstring 缩进与首尾空白；每个参数补 description，固定取值补 enum，数值范围补 minimum/maximum（与运行时校验同组常量，单一来源）；工具数量 13 与名字不变。注：MCPServer v2 无法不声明空的 prompts/resources 能力（SDK 构造时无条件注册，测试已锁定现状）

**发布前修复**
- SSR 取数层转发访客身份（x-real-ip 与 cookie）：后端按访客 IP 分桶的匿名副作用约束（库外 SMILES 建行、CAS 采集入队 30 次/分钟）覆盖服务端渲染流量；缓存取数不携带请求身份；客户端与服务端取数层分离并加静态检查防交叉引用
- 数据服务 lookup 恢复「未收录按站内规则建行并触发采集」的规范口径（read 凭证即生效）；采集入队走后台优先级档
- 字段校验错误提示方向修正（数值大于上限/低于下限方向不再说反），补整数、格式与列表数量类中文映射，英文原文不直出
- 反应保存链路：前端校验层与后端 schema 同源（单一规则常量 + 逐项对账测试），错误定位覆盖全部输入字段（含参与物逐行逐输入），结构无法解析与重复参与物带行号定位到该行；身份冲突 409 统一携带 kind
- 笔记列表三处（工作台/概览/公开主页）统一标题派生（首行或「关于 {实体} 的笔记」中性写法）并显示正文摘要；行内删除操作与编辑统一为图标按钮形态
- 首页 AI 接入按钮手机端 2×2 等宽网格；同义词「加载更多」独立成行不再撑高胶囊；/u 短地址大小写归一 307、不合规名渲染站内 404；数据服务文档表列宽与手机堆叠布局；反应打印页压强单位本地化与长串断行
- OAuth CIMD 文档拉取加行缓冲与响应头上限，恶意超长行走既有错误页与 host 失败桶（不再 500）
- nginx 站点配置与 systemd 单元入库（ops/nginx/、ops/systemd/），生产基线（部署用户/sudoers/端口/PG 参数/pm2/出口代理/凭证流程）与 Cloudflare 依赖行为入文档
- 注释与文案存量过程语言清理；CI 增加注释词表检查（新增行拦编号代号与决策过程用语回流）

**其他**
- I-024：公开 GET /skills* 输出去掉 origin，改 `is_official: bool`（admin 保留 origin，数据库不动）
- I-058：剩余 6 个直读库地址的测试文件统一走 tests/db_gate.py
- I-069：CI push 触发只保留 main，消除 push+PR 双触发
- I-070：公网冒烟扩为 /api/health + 五语言首页 + HCID 4 详情页 + MCP initialize 版本对 VERSION（任一失败 deploy 非零退出）；docs/DEPLOYMENT.md 新增"生产配置"记录节（PG ALTER SYSTEM 参数与 needrestart 策略，只记录不自动变更）
**MCP OAuth：支持 Client ID Metadata Document（CIMD，I-072/I-073/I-071）**
- 授权服务器元数据声明 `client_id_metadata_document_supported`；三种客户端身份并存且平等：CIMD（client_id 为一个 https URL，推荐陌生/个人 Agent 使用）、动态客户端注册（DCR，行为不变）、预登记 client_id
- CIMD 拉取带 SSRF 防护：私网/回环/链路本地/保留/组播/CGNAT 地址拒绝（IPv4 与 IPv6，含映射写法）、按已校验 IP 建连防 DNS rebinding、不跟随重定向、5 秒超时、5 KB 上限、按文档 host 与匿名来源 IP 限流
- 文档按响应 Cache-Control max-age 缓存（夹在 5 分钟~24 小时，缺省 1 小时）；缓存过期后重新拉取，拉取失败拒绝本次授权，不用过期缓存兜底；/token 与 refresh 不重新拉取
- /oauth/authorize 先校验 client_id 与 redirect_uri 再判断登录；无效时返回错误页（不重定向到未校验地址，也不返回裸 400 JSON）
- CIMD 客户端授权确认页显示来源 host（名称自报、host 可信）；redirect_uri 为 localhost 时提示授权码将返回到本机应用；授权管理列表为 CIMD 客户端附出来源 host（client_host 字段）
- 受保护资源元数据新增 RFC 9728 标准路径 `/.well-known/oauth-protected-resource/mcp`（根路径保留为回退发现地址）；MCP 401 挑战的 resource_metadata 改指标准路径

**仓库降噪**
- 删除过程文档 docs/PRD_V1.7.0.md 与 docs/PLUGIN_SUBMISSION_V1.7.0.md；仍然成立的事实（MCP 端点、scope、插件包结构、OAuth 接入方式含 CIMD）合并进 README 的「MCP 与 Agent 接入」一节

## [1.7.2] — 2026-10-15

补丁版：手机端与按钮视觉、分享与 SEO、公开资源有界化与边缘缓存、部署与任务表稳定性。

**界面**
- 手机顶栏让出顶部安全区（viewportFit cover 下 logo 与导航不再进状态栏）
- 按钮一律按内容自适应宽度，取消所有满宽按钮（含登录、搜索、提交、首页入口）
- 顶栏与手机底栏第一项改为「首页」；底栏「工作台」使用独立图标
- 公开页外层容器统一为顶栏宽度，正文左边缘与 logo 对齐；长文在容器内限制行长并左对齐
- 化合物 / 反应详情：HCID / HRID 徽标后的复制按钮改为分享按钮，桌面与手机常驻
- 图标尺寸档位调整为 16 / 18 / 20 / 24，按钮内默认 20，底栏 24，取消写死的像素值

**分享与 SEO**
- 所有公开页输出完整 og / twitter 标签与微信识别的 itemprop
- 化合物分享图改为结构图本身（800×800 白底方形）；反应分享图为 1200×630 与 800×800 两个固定尺寸

**公开资源与缓存**
- 结构图尺寸收敛为 4 档白名单，其余尺寸 404；结构图一律 public, immutable
- 查询参数形式的渲染接口（/api/mol/{id}/svg|png?w=&h=、/api/reactions/{id}/svg|png）不再对外
- 已带 locale 前缀的匿名公开页返回 public, s-maxage=300, stale-while-revalidate=86400；带登录会话、RSC / 预取请求与非公开页保持 private, no-store；可缓存响应不写 Set-Cookie

**运维与数据库**
- 部署顺序：API 与 Web 就绪后才重启 worker（修复部署时 worker 连续重启）
- 版本号单一来源：/api/health、FastAPI app.version 与 MCP serverInfo 都读 VERSION
- 迁移 20261015_01：maintenance.pubchem_identity_jobs 新增过期租约回收索引、领任务索引改为 (priority DESC, id)，消除每次领任务的全表扫描

## [1.7.1] — 2026-10-14

补丁版：MCP 对外输出契约收紧、供应商编号不外泄、README 如实化与测试库保护。

**REST 收为网站内部面（PM 裁定 2026-10-14）**
- 删除 `GET /api/agent-guide`；对外接入唯一入口是 MCP（`/mcp` 自描述 + OAuth 2.1）。`web/public/llms.txt` 中残留的 agent-guide 提法待前端轮次同步更新
- REST 不再接受 AI Key：所有网页接口对 Bearer AI Key 一律 401（`kind=rest_agent_forbidden`），网页登录会话与匿名公开读取行为不变；AI Key 只能用于 MCP，MCP 行为不变
- 后端用户可见业务错误统一错误码化：HTTP 错误响应 `detail` 由纯中文文案改为 `{"message": <中文原文>, "kind": <snake_case 错误码>}`（搜索类沿用 `invalid_doi`/`invalid_cas` 等既有 kind）；MCP 对外输出保持英文映射不变

**MCP 对外输出变化（只改出口，共享服务/网页 REST/数据链不变）**
- get_chemical 去掉字段：`similarity`（空槽位，相似度检索时保留实值）、`follower_count`、`is_following`、`enrichment`，以及 `details` 内的 `provenance`、`suppliers[].ref` 和各证据块的 `references`/`normalization`
- get_chemical `details` 改键名：`description.record_description` → `description`；`names.cb_identity.{cn,en,formula,mw}` → `names.{chinese_name,english_name,formula,molecular_weight}`；`names.cb_aliases[].value` → `names.aliases`；`properties.pb_computed` → `computed_properties`；`properties.pb_physical_properties` → `experimental_properties`（证据拉平为值列表）；`properties.cb_experimental` → `physical_data`（`label`→`name`、`text`→`value`）；`properties.cb_prose` → `chemical_properties`；`safety.pb_sections.*` → `safety.{ghs_classification,hazards,safety_measures,toxicity,regulatory}`；`safety.cb_safety` → `safety.safety_data`；`safety.cb_toxicity` → `safety.toxicity_notes`；`safety.cb_packaging` → `safety.storage_and_transport`；`industry.pb_sections.{pharmacology,uses_and_manufacturing}` → `applications.*`；`industry.cb_uses/cb_preparation/cb_notes` → `applications.uses/preparation/handling_notes`；`industry.cb_updown` → `related_products.{upstream_materials,downstream_materials}`；`industry.cb_price` → `reagent_prices`
- get_reaction / list_my_reactions 去掉字段：`moderation_status`、`ord_record_id`、`is_following`、`follower_count`、`creator.avatar_url`；`dataset_name` 的 `user_submitted` 显示为 `User submitted`
- search_chemistry_data 去掉字段：`cas_fetch_pending`/`cas_fetch_chemical_id`（改以 `lookup_pending` 布尔表达）、命中反应的 `match_basis`
- list_skills / get_skill 去掉字段：`origin`、`owner_id`
- 标识（PubChem CID/CAS/HCID/HRID）与业务数据不丢；REST `/api/chemicals/{id}` 契约不变（full 仍含 provenance/供应商明细）

**供应商编号不外泄（I-056）**
- 公开详情供应商明细的 `ref` 由库内原站标识形态（`cb-supplier:{cbsid}`）改为出口计算的不透明哈希（`caslib/redact.supplier_ref`）；库内存储键与数据不变

**插件包**
- plugin.json 去掉 `repository` 字段（仓库非公开，不对外展示），`homepage` 仍指向官网；下载 zip 重新打包
- 首页新增 Agent Plugin 下载入口；MCP 指南页去掉仓库链接

**HTTP 语义修复（I-057）**
- Notes 创建/编辑触发写入限流时按统一口径映射：`RateLimited` → 429（带 Retry-After / X-RateLimit-Remaining），`LimiterUnavailable` → 503；此前未捕获会以 500 冒出

**前端（延续本分支既有修复）**
- 顶栏下拉菜单被工作台正文遮挡；手机端公开页面补语言切换入口
- 化合物详情页不展示采集来源（PubChem/ChemicalBook 标签、底部记录区）

**文档与测试**
- README 如实化：合并后旧 HCID 不再可访问（反应参与关系改指保留行）；AI Key 说明改为可在设置页再次查看和复制（随下方明文恢复裁定，撤销 I-060 的「只显示一次」改动）
- tests/test_migration_runner.py 与 tests/test_admin_pipeline_health.py 改经 db_gate 双闸（库名模式 + sentinel）取测试库，不再直读 `TEST_DATABASE_URL`

**AI Key 恢复明文保存与再次查看（2026-10-14 项目负责人裁定）**
- 撤销 1.7.0「AI Key 明文不再落库、不再回传」收口：新建 Key 重新写入 `token_plain`，本人网页会话的 `GET /users/me/tokens` 重新返回明文（`token` 字段；无明文的旧 Key 返回 null）；鉴权仍按哈希，改密码删除全部 Key、MCP/日志/错误信息不含明文、列表 `no-store` 与只认网页会话均不变
- 原因：每个账号最多 5 个有效 Key，能在设置页再次查看、复制可降低使用摩擦；此前「只显示一次、明文不落库」是对通用安全规则的误套。此为有意的产品取舍，列注释与代码注释已写明，再变更须经项目负责人确认
- migration：删除从未在生产执行的 `20261011_01_drop_user_api_tokens_token_plain`；新增 `20261014_02_user_api_tokens_token_plain`（`ADD COLUMN IF NOT EXISTS`，生产为 no-op，恢复已删列的环境），列注释记录裁定
- tests/test_token_plaintext_contract.py 由反向锁（列必须不存在）重写为正向锁（列存在且有裁定注释、新建落明文、本人会话可取回、AI Key/匿名拿不到、旧 Key 返回 null）

## [1.7.0] — 2026-10-12

Notes 用户笔记、MCP OAuth 身份层、OpenAI Plugin 提交包与 agent-facing 契约收口；HGS 视觉体系（DESIGN_SYSTEM v1.0）全站落地；数据链与安全收口。

**HGS 视觉体系（DESIGN_SYSTEM v1.0）**
- 单一 token 源 + `components/ui` 组件库，全站（含工作台、设置、管理端、错误/404 页）统一迁移，旧类名与样式定义删除
- 全局顶栏 + 手机底部 4 tab；实体页、搜索、工作台、公开主页、文档/法务/登录/设置页按 §9 重做
- 交互规范 IX-1~12 落地：ConfirmDialog 二次确认、乐观更新 + Toast 撤销、笔记未保存拦截（含后退/前进与保存中切换）、慢加载提示
- 契约测试新增组件层禁止项（§11 规则 9–11）；运行时视觉门禁（字号/圆角/触控 ≥44/横向溢出）纳入验收

**安全**
- AI Key 明文不再落库、不再回传：创建时只显示一次，列表仅返回元数据；鉴权仍按哈希（1.7.1 已按项目负责人裁定撤销：恢复明文保存与再次查看，见 1.7.1「AI Key 恢复明文保存与再次查看」）
- 管理员停用账号同事务撤销 OAuth 授权请求、code、access、refresh 凭证；refresh 与 code 兑换前复核账号状态
- 停用账号主页展示停用态，其公开内容保留可见并标注「已停用」
- CSP（report-only）、笔记写入限流与存量上限、OAuth 动态注册全站限流（120 次/小时）、OAuth 过期凭证定期清理

**化学数据完整性**
- PubChem 回补：以已验证的 query binding 回写主表 `pubchem_cid`；同可信 CID 的 IK 差异照写事实并记录溯源，任务状态如实
- 同 CID 合并：主表核心字段补空迁移、反应计量与 PB 证据不丢失，冲突写入 merge_log；≥3 行同 CID 循环收敛
- ChemicalBook：多来源供应商分行合并；SMILES / InChIKey / MOL 交叉校验；仅 SMILES 时推导 InChIKey
- 恢复 GHS 危险性分类在详情（REST / MCP full）中的输出
- 名称模糊检索按字面量匹配（转义 `%` / `_`）

**运维**
- worker 依赖补 `aiohttp-socks`，CI 增加 worker 启动导入检查；部署只允许 `npm ci`
- migration runner 增加 `lock_timeout`；`--dry-run` 不再建表

**数据库 migration**
- `20261011_01_drop_user_api_tokens_token_plain`：删除 `community.user_api_tokens.token_plain` 列（不可逆，存量 Key 继续有效）（1.7.1 撤销：从未在生产执行，文件已删除，由 `20261014_02` 恢复该列）
- 化合物 / 反应主表无 schema 变更

**Notes（用户自有笔记）**
- 用户自有笔记，可关联 HCID/HRID 引用（每篇合计 ≤20 条），支持公开/私有可见性
- Web session 专属能力边界：无 MCP 工具、无 API Key 面、无 `note:write` scope

**MCP OAuth 2.1 identity layer**
- DCR（动态客户端注册）+ Authorization Code + PKCE S256；scope 为 `read` / `reaction:write` / `skill:write`
- OAuth access token 仅由 MCP adapter 解析，不进入 REST Bearer resolver；既有 `hgs_*` AI Key 兼容面保持不变

**OpenAI Plugin 提交包**
- `plugins/huagongshe/` 提交包（独立 1.0.0 版本轴，与产品版本解耦）
- `/.well-known/openai-apps-challenge` fail-closed 路由（env 未配置时返回 404）

**agent-facing 契约英文化**
- `/api/agent-guide` / `llms.txt` / MCP 错误消息 / 五语言 MCP 连接节统一英文：MCP 为主接入层，AI Key 为兼容区块；MCP reaction 校验错误在 adapter 边界完成英文转换（字段位置保留，未知消息安全 fallback）

**首页一级入口收敛**
- 首页一级入口收敛为 MCP / Skills / Workbench；兼容路由（agent-guide、AI Key 设置页）全保留

**数据库 migration**
- 新增 `20261006_01_notes`（community.notes / note_chemicals / note_reactions）与 `20261006_02_oauth`（OAuth 表）

**法务页与数据留存**
- Privacy / Terms / Support 页上线
- OAuth token 生命周期：code 5min / access 1h / refresh 30d；操作与安全日志留存 ≤30 天

## [1.6.0] — 2026-10-06

五语言 runtime locale 发布与生产单实例收口。

**五语言 runtime locale（zh-CN / en / ja / ko / de）**
- locale-prefixed 公开 URL（`/en/…`、`/ja/…` 等）：Next proxy 按 cookie > Accept-Language > en 协商 307 redirect，已带前缀路径 rewrite 到现有路由并透传 `x-site-locale`；排除路径（/api、/mcp、/samelabs、/.well-known、/_next 与静态资源）不参与 locale
- 五语言完整字典注册（Dictionary 类型从中文字典推导，tsc 校验结构一致）；runtime dictionary 按 locale 分发
- locale-aware 导航 / 登录 / Workbench / 搜索 / 化学详情 / 反应工作流 / 指南 / 账户与个人资料全站本地化
- canonical / hreflang 五语言 alternates / x-default→en 与 OG locale metadata
- CB localized detail：详情读路径 locale-aware（requested→en fallback），en/ja/ko/de prose 经 caslib 分类器进入正确语义分组
- locale 路径 helper 单一权威（splitLocalePrefix / stripLocalePrefix / withLocale / replaceLocalePrefix / applyLocale / NON_LOCALIZED_PREFIXES），全站无第二套 locale regex / prefix 表

**CB locale 生命周期与确定性（post-deploy 修复）**
- 生命周期与 stale refresh 跟随实际命中 row locale（不再回退 zh-CN 默认），MCP 未传 locale 保持 en 默认
- legacy fallback 确定性：同 locale 多个非-imprint source row 时 `ORDER BY cb_number ASC NULLS LAST` 稳定 tie-break（生产 84 组暴露面实证），不改数据、不参与身份裁定
- CB locale 白名单收口单一权威 tuple（normalize / row selection / lifecycle 共用，消除双列表 silent drift）
- CB 本地名称标签：非 zh-CN locale 显示"本地名称/Local name/現地名/현지명/Lokaler Name"而非"中文名"（presentation 层，canonical `identity.cn` 键与数据不变）

**PWA**
- manifest 动态输出（随 site_locale 变化），单一身份：`id="/"`、`start_url="/"`，en→HGS / zh-CN→化工社
- Service Worker 缓存治理：只缓存不可变静态资源（带内容哈希的 `/_next/static` 与站内图标），用户态内容禁入缓存；升版清污染

**locale/PWA post-deploy 修复**
- 登录页切语言后，登录成功回跳 `applyLocale()` 强制落在当前 locale（不再被旧 locale next 拉回）
- malformed `site_locale` cookie 不再 500：decode 异常保护后继续 Accept-Language → en 协商
- 公共 header 非 sticky 化后，详情页 local-nav / scroll anchor / rail 的遗留 offset 同步修正

**生产部署事实（single-instance SSOT）**
- 生产部署最终以 single-instance 为准：`/var/www/huagongshe` + main + PM2 三 app（huagongshe-api / huagongshe / huagongshe-pubchem-worker，127.0.0.1:8000 / 3001）+ nginx fixed upstream；**历史 generation / blue-green 路径已退出运行与配置面**（无运行中代际、nginx 无 generations/ 引用）
- public deploy smoke 修复：smoke 改为 canonical HTTPS ingress（`https://huagongshe.com/api/health`，一次请求验证 nginx vhost + TLS + API upstream 整链；fail closed），替换会被 default_server 444 断连的裸 loopback 探针；使用明确的 deploy probe User-Agent（`Huagongshe-Deploy-Smoke/1.0`，真实身份标识，非浏览器伪装——Cloudflare bot 规则会 403 拦截 `Python-urllib` 默认 UA）

**测试与门禁**
- locale runtime 行为测试正式进入 GitHub CI（`npm run test:locale`，tsx 直接加载真实 TS SUT）：proxy redirect/rewrite 契约（含 malformed cookie）、withLocale/applyLocale 登录回跳、NON_LOCALIZED_PREFIXES 边界、语言切换器、runtime 字典、canonical/hreflang/x-default
- deploy public smoke 契约单测（canonical URL 锁定、fail closed、零真实公网访问）
- CB locale SSOT 与 deterministic fallback 回归测试

**不包含**
- 本版不包含 ChatGPT Plugin / MCP 新 tool surface 开发
- 未做 Next.js 升级、依赖整体升级、数据库 migration、CB 存量数据重写

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
