# HGS 设计系统 v1.0（UI 与交互规范）

状态：**Stable**，v1.7.0 起生效，取代 `DESIGN_SYSTEM_V2.md`（Draft）。
适用范围：公开站点、实体页、搜索、文档、工作台、账户设置。后台 `/samelabs` 只做 token 别名化。

本规范有三份互相对应的产物，冲突时按以下顺序为准：

1. **`web/app/tokens.css`**：所有取值的唯一来源。
2. **本文档**：规则、组件契约、交互规范、页面结构。
3. **`docs/design/hgs-ui-reference.html`**：可交互的视觉参考，包括组件状态和真实尺寸的页面模板，直接用浏览器打开。实现时以它为像素参考，CSS 可以直接照搬。

非目标：不改数据库、身份裁定、API/MCP 语义；不做暗色模式；不重新设计后台。

---

## 1. 设计原则

1. **数据先于装饰**：层级由化学数据的语义决定，不由数据来源决定。
2. **用边框分层**：卡片和面板用 1px 边框；阴影只用于浮层。
3. **一套语言**：公开页和工作台使用同一套 token 和组件。
4. **操作必有回应**：每次点击都有可见的结果、进度或错误提示。
5. **来源可见**：多个来源的事实并列显示，UI 不合并互相冲突的数据。

## 2. 品牌

### 2.1 标志

- **图形标**：尖顶六边形（苯环的简化），里面是字母 H，横画是两条平行线（双键）。
- **字标**：HGS，等粗几何线条，以 SVG 路径交付。**禁止用文字字体排版字标。**
- **中文副标**：“化工社”只在 `zh-CN` 下出现在横版组合中，与字标之间用 1px × 16px 的分隔线隔开。其他语言只显示 HGS。

资源在 `web/public/brand/`：

| 文件 | 用途 |
|---|---|
| `hgs-mark.svg` | 图形标，浅色底（blue-500） |
| `hgs-mark-on-dark.svg` | 图形标，深色底（blue-400） |
| `hgs-mark-line.svg` | 线框图形标，`currentColor`，用于品牌色底和 App 图标 |
| `hgs-mark-16.svg` | 16px 简化版（单横画），用于 favicon |
| `hgs-wordmark.svg` | 字标，`currentColor` |
| `hgs-lockup.svg` | 横版组合（无中文），用于 OG 图等静态场景 |
| `hgs-app-icon.svg` | App 图标 / PWA 源文件（圆角 25%，蓝色渐变底） |

React 实现：`<HgsLogo variant="lockup" | "mark" | "wordmark" size={28} />`，SVG 内联，字标使用 `currentColor`。header 里中文副标由组件按 locale 渲染。

### 2.2 规则

- 最小尺寸 16px；16px 时使用 `hgs-mark-16`。
- 四周留白 ≥ 图形标宽度的 1/4。
- 不加渐变（App 图标除外）、阴影或描边；不改比例；不换色。
- 尺寸：网站顶栏 28，手机顶栏 24，登录页和空状态 44，App 图标 512。

## 3. 颜色

只有一种品牌色：蓝。绿色、橙色、红色只表示状态。**`--green*`（微信绿）和 `--warm*`（暖橙）删除。**

| 语义 token | 取值 | 用途 |
|---|---|---|
| `--text` / `--text-2` | n-900 / n-700 | 标题和数据值 / 次要正文 |
| `--text-muted` | n-500（4.9:1） | 标签、元数据；可读文字的最浅一档 |
| `--text-placeholder` / `--text-disabled` | n-400 / n-300 | 只用于占位符和禁用态 |
| `--action` / `-hover` / `-pressed` | blue-600 / 700 / 800 | 按钮、链接（5.4:1） |
| `--brand` / `--focus` | blue-500 | 标志、焦点环、选中指示条。**不能用作文字颜色** |
| `--action-subtle` / `--action-ink` | blue-50 / blue-700 | 浅蓝底和其上的文字（tonal 按钮、选中项） |
| `--bg-page` / `--bg-surface` / `--bg-subtle` | n-25 / 白 / n-50 | 页面底 / 卡片 / 次级面和 hover |
| `--border` / `--border-strong` | n-100 / n-200 | 卡片和分割线 / 输入框和次按钮 |
| `--entity-chem*` / `--entity-rx*` | 蓝 / 灰蓝 | 只用于 EntityBadge |
| `--ok*` `--warn*` `--err*` | 绿 / 琥珀 / 红 | 只表示状态 |

## 4. 字体、字号、间距、圆角、动效

- 字体：系统字（苹方 / HarmonyOS Sans / 微软雅黑）。等宽字体只用于 ID、SMILES、InChIKey、代码和 Key。
- **字号 8 档**：12 / 13 / 14 / 16 / 18 / 22 / 28 / 40，最小 12px。唯一例外是 EntityBadge xs 的前缀（11.5px）。
  - 40：实体名、首页标题（手机上用 28）。28：页面标题、统计数字。22：区块标题。18：弹窗标题。16：正文、卡片标题。14：数据值、界面默认。13：元数据。12：说明文字。
  - 字重 400 / 500 / 600；22px 及以上的标题用 650，并收紧字距（-1.5% ~ -2.5%）。
- **间距**：4 / 8 / 12 / 16 / 24 / 32 / 48 / 64。
- **圆角**：6（标签、徽标）/ 8（按钮、输入框）/ 12（卡片、面板）/ 16（弹窗、抽屉）/ pill（头像、计数）。
- **控件高度**：32 / 40 / 48；手机上的主要操作用 48，触控目标 ≥ 44。
- **布局宽度**：reading 720 / content 1040 / wide 1200；侧栏 232；右侧栏 260（详情页）或 320（工作台）。组件不得自己定义页面级 max-width。
- **阴影**：只有 `--shadow-float` 一档，用于下拉菜单、弹窗、Toast。
- **动效**：120ms（hover、按压；按钮按下缩到 0.98）/ 200ms（浮层进出）；用户开启“减少动态效果”时全部关闭。

## 5. EntityBadge（HCID / HRID 徽标）

全站唯一的实体标识组件，替换 `EntityId` 的视觉，props 向后兼容。

```
<EntityBadge kind="chemical" | "reaction" id={2244}
             size="xs" | "sm" | "md" | "lg"       // 20 / 24 / 28 / 32，默认 sm
             href?                                // 传入后整个徽标是链接
             copyable?                            // 右侧附带复制按钮
             compact?                             // 只显示字形 + 编号（表格列）
             state?="private" | "merged" | "deleted"
             redirectTo? />                       // merged 时显示 → 新编号
```

- **结构**：`[字形][前缀] | [编号]`。前缀段使用实体色的浅底，编号段白底；1px 实体色描边；圆角 6。
- **字形**：化合物用六边形（取自标志），反应用 → 箭头。黑白打印时也能区分两种实体。
- **编号**：等宽字体、`tabular-nums`，不加千分位，不补零，不截断。前缀 HCID / HRID 在任何语言下都不翻译。
- **状态**：
  - private（只有 HRID）：编号后加锁图标。
  - merged：虚线边框，编号加删除线，后面接 `→` 和新编号的徽标。
  - deleted：虚线边框，编号加删除线，后面跟“已删除”。
- **交互**：hover 时边框变为实体色；焦点用统一焦点环；aria-label 为“HCID 2244，化合物”（从字典取）。手机上，徽标是一行里唯一的链接时，点击区域扩展到 44px，外观不变。
- **禁止**：不经过本组件，自己拼写 HCID / HRID 的展示。

## 6. 组件

类名前缀 `.hg-`，组件放在 `web/components/ui/`。每个组件都要实现全部状态。

| 组件 | 变体 / 尺寸 | 要点 |
|---|---|---|
| Button | primary · secondary · tonal · ghost · danger · danger-quiet；sm/md/lg；icon-only | 每个区域只放一个 primary；loading 时宽度不变并禁止点击；icon-only 必须有 aria-label |
| Input / Textarea / Select | md / lg | label 在上；错误提示在下方；焦点状态为 action 色边框加 4px 光晕；手机上字号 16 |
| Tag | neutral · blue · ok · warn · err · src | 高 24（src 为 20），圆角 6；状态标签带圆点 |
| Segmented | — | 用于检索方式、视图切换；取代 chip 组 |
| Tabs | — | 底部 2px 指示条，带计数；手机上可横向滚动 |
| CodeField + CopyButton | — | SMILES、InChIKey、Key；复制后图标变为 ✓ 并保持 1.5s，aria-live 播报 |
| Notice | info · warn · err · ok | 页面级提示，可带操作按钮 |
| Toast | ok · err | 全局队列，底部居中；成功 3s 后消失，失败需手动关闭；可带“撤销” |
| ConfirmDialog | danger | 标题是问句，正文写明对象名称；确认按钮写具体动作；默认焦点在“取消”；焦点锁在弹窗内；Esc 关闭 |
| EmptyState | — | 图标、一句标题、一句说明、一个下一步操作 |
| Skeleton | 卡片 · 列表行 | 首屏和列表加载时使用 |
| Avatar | 24 / 32 / 40 / 80 | 无图片时显示首字，颜色由用户 id 决定 |
| EntityCard | chemical · reaction | 搜索结果、收藏、主页统一使用 |
| DataRow (dl) | — | 标签列 140（手机 84–96）；值的后面跟来源标签 |

## 7. 交互规范

| 编号 | 规则 |
|---|---|
| IX-1 | 可点元素都有 default / hover / pressed / focus-visible / disabled；异步操作加 loading，可选元素加 selected。焦点环 2px `--focus`，只在键盘操作时出现。 |
| IX-2 | 反馈分三层：字段错误显示在输入框下方；操作结果用 Toast；页面级失败用 Notice 并附带重试。禁止使用 `alert()` / `confirm()`。 |
| IX-3 | 删除反应、删除笔记、撤销 AI Key、注销账号必须经过 ConfirmDialog 确认。 |
| IX-4 | 异步按钮点击后立即进入 loading 并禁止再次点击；列表用 Skeleton；超过 10s 提示“仍在处理”并提供重试。 |
| IX-5 | NoteEditor / SubmissionForm 显示保存状态（已保存 / 保存中 / 保存失败）；有未保存的改动时，离开页面要拦截；保存失败不清空输入。 |
| IX-6 | 关注和收藏立即切换状态（乐观更新），失败时回滚并 Toast；收藏和关注的 Toast 带“撤销”；“已关注”按钮 hover 时显示“取消关注”。 |
| IX-7 | ID、SMILES、InChIKey、Key 都可以复制，复制反馈见 CopyButton。 |
| IX-8 | 空状态必须给出下一步操作，禁止只写“暂无数据”。 |
| IX-9 | 事实值后面都带来源标签；来源之间的数据冲突并列显示；长段证据默认折叠。 |
| IX-10 | ⌘K 或 `/` 聚焦全局搜索；Esc 关闭浮层；弹窗关闭后焦点回到触发按钮；图标按钮必须有 aria-label。 |
| IX-11 | 手机端：触控目标 ≥ 44px；底部 4 个 tab（查询 / 工作台 / 动态 / 我的），处理 safe-area；右侧栏移到正文下方；本页导航改为吸顶的横向 tab。 |
| IX-12 | 所有界面文字都进入五种语言的字典；按钮用动词说清做什么；错误信息说明原因和解决办法，不暴露错误码。 |

## 8. 全局框架

**桌面 header（高 60）**：
- 内容从左到右：横版标志、主导航（查询 · Skills · MCP · 工作台）、全局搜索框（⌘K）、动态铃铛（未读红点，数据来自现有的 unread 计数）、语言切换、头像菜单。
- 白色 86% 透明加背景模糊。**不吸顶**，保留 v1.6 修复过的锚点偏移。
- 删除现有的 `.nav-guide` 绿色入口，指南并入主导航或页脚。

**手机 header（高 52）**：标志、搜索图标、头像。主导航移到底部 tab：查询 / 工作台 / 动态（带未读数）/ 我的。

## 9. 页面结构

### 9.1 化合物详情 `/chemical/[id]`（wide）

- **头部**：左边依次是 EntityBadge lg（可复制）、实体名（40）、英文名、IUPAC 名、关键标识标签（分子式 / 分子量 / CAS / CID）、操作区（收藏为 primary，然后是子结构检索、相似结构、分享，最后是收藏人数和头像叠放）；右边是 300 宽的结构图。
- **正文顺序**：概述 → 名称与标识 → 性质 → 安全与法规 → 化学与工业 → 相关反应 → 笔记 → 来源。
- **右侧栏（260）**：本页导航，以及记录信息（来源、更新时间、补全状态）。
- **合并来源显示**：PubChem 和 ChemicalBook 不再各自占一个区块，同一个性质的多个来源合在一行显示。同义词统一放在“名称与标识”。

### 9.2 反应详情 `/reaction/[id]`（wide）

- **头部**：EntityBadge lg、中性标题（不用 AI 生成反应名）、根据结构化数据组成的事实摘要、操作。
- **正文顺序**：反应式（可以占满内容宽度）→ 反应物和产物（各带 HCID 徽标）→ 助剂 → 条件 → 步骤 → 后处理 → 安全和备注 → 来源。
- **右侧栏**：本页导航、创建者（Avatar 加关注按钮）、HRID 和状态、ORD / DOI / 专利引用。反应 SMILES 用 CodeField 显示。

### 9.3 搜索 `/search`（content）

- 顶部：页面标题、大搜索框（48）和检索方式切换（名称/CAS · 精确结构 · 子结构 · 相似结构）。
- 下方用 Tabs 分为化合物 / 反应（显示计数）。
- 每条结果是一张 EntityCard：结构缩略图、EntityBadge、名称、标识符，以及收藏按钮。

### 9.4 个人工作台 `/aichem`（工具在左，社交在右）

- **侧栏（232）**分四组：
  - 工作区：概览 / 笔记 / 我的反应 / 收藏
  - 工具：查询 / 投料计算 / Skills / MCP 与 AI Key
  - 社交：动态（未读）/ 关注 / 粉丝
  - 账户：设置
- **主区**：问候语和一句当前状态，右上角是“新建笔记”（secondary）和“新建反应”（primary），下面分两列：
  - 左列（工具）：快速检索框加 4 个快捷入口；“我的内容”面板，用 Tabs 分为 最近 / 反应 / 笔记 / 收藏，每行显示类型图标、标题、徽标、可见性和时间，笔记还显示保存状态。
  - 右列（320，社交）：我的主页卡片（头像、@用户名、公开反应 / 粉丝 / 关注的数字、“查看我的公开主页”、分享）；关注动态（**v1.7 只有 `new_reaction` 一种事件**：头像、“X 发布了公开反应 HRID”、时间、反应式缩略图、收藏和打开按钮）。
- 参考模板里的“关注了你 / 回关”“发布了笔记”这两类动态需要新增事件类型，**v1.7 不实现**。

### 9.5 公开主页 `/user/[username]`（wide）

- **头部（社交名片）**：Avatar 80、名字（28）、关系标签（关注了你 / 互相关注）、@用户名、简介、机构和加入时间、数据（公开反应 · 公开笔记 · 粉丝 · 关注）。
  - 访客看到“关注”（primary）和“分享”；本人看到“编辑资料”和“进入工作台”。
- **正文（研究档案）**：Tabs 分为 反应 / 笔记。
  - 反应用两列卡片：反应式、HRID md 徽标、关注人数、溶剂等摘要、日期、收藏按钮。
  - 笔记卡片：标题、两行摘要、关联的实体徽标。
- **右侧栏**：粉丝头像叠放和人数（如果没有公开的粉丝列表接口，就只显示人数）。“常用化合物”**留到 v1.8**（需要聚合接口）。

### 9.6 文档页（reading 720）

`/guide`、`/mcp-guide`、`/skills`、privacy / terms / support：正文宽度 720，少用卡片，代码用 CodeField 显示。

### 9.7 手机端

见参考模板第 12 节：化合物详情、工作台（检索、2×2 快捷入口，以及在“我的内容”和“关注动态”之间切换）、公开主页（头像和数字横排，两个主按钮并排）。

## 10. 旧 token 迁移表

| 旧 | 新 |
|---|---|
| `--blue` | 文字和按钮用 `--action`；装饰、焦点、选中指示用 `--brand` |
| `--blue-deep` / `--blue-strong` / `--blue-pale` / `--blue-tint` / `--blue-border` / `--blue-glow` | `--action-hover` / `--action-ink` / `--action-subtle` / `--bg-subtle` / `--action-border` / `--focus-halo` |
| `--ink` `--heading` / `--heading-soft` / `--muted` / `--quiet` | `--text` / `--text-2` / `--text-muted` / `--text-placeholder`（如果用来显示可读文字，改为 `--text-muted`） |
| `--line` / `--line-strong` / `--wash` / `--paper` | `--border` / `--border-strong` / `--bg-page` / `--bg-surface` |
| `--reaction` / `--reaction-ink` / `--reaction-bg` | `--entity-rx-line` / `--entity-rx` / `--entity-rx-bg` |
| `--danger*` / `--success*` / `--warning*` | `--err*` / `--ok*` / `--warn*` |
| `--green*` / `--warm*` | **删除** |
| `--text-lg` 15 / `--text` 13 / `--text-sm` 11 / `--text-xs` 10 | 14 或 16（按语义）/ 13 / 12 / 12 |
| `--fs-caption…--fs-title` | `--fs-12` … `--fs-22`；`--fs-title` 从 30 改为 `--fs-28` |
| `--space-N` | `--sp-N`（取值相同） |
| `--radius-sm` 6 / `-md` 10 / `-lg` 14 | `--r-xs` 6 / 控件用 `--r-sm` 8，卡片用 `--r-md` 12 / `--r-lg` 16 |
| `--layout-reading` 760 / `-content` / `-wide` 1180 / `--rail-width` 270 | `--w-reading` 720 / `--w-content` / `--w-wide` 1200 / `--rail-w` 260 |
| `--wb-*` | 全部改为上述 token 的别名，不再自带取值：`--wb-fs-micro` 7 和 `--wb-fs-xs` 11 → 12；`--wb-fs-lg` 15 → 16；`--wb-fs-stat` 24 → 28；`--wb-r-xs` 3 → 6；`--wb-r-md` 8 → 12；`--wb-sidebar` 200 → 232；`--wb-topbar-h` 56 → 60；`--wb-tabbar-h` 50 → 64；`--wb-btn-h` 38 → 40 |

## 11. 禁止项（由 `tests/test_ui_token_contract.py` 在 CI 中检查）

1. 在 `tokens.css` 以外的 CSS 或 TSX 中写 hex / rgb / hsl 色值。品牌 SVG 文件除外。
2. font-size 不在 8 档字号之内，或可见文字小于 12px（EntityBadge xs 前缀除外）。
3. border-radius 不在 6 / 8 / 12 / 16 / 999 之内，或不是 token。
4. 给卡片或面板加 box-shadow（只有浮层组件允许使用 `--shadow-float`）。
5. `--wb-*` 自带取值。
6. 出现 `--green` 或 `--warm` 这两类 token。
7. 调用 `alert(` / `confirm(` / `prompt(`。
8. 在 EntityBadge 之外，用字面量拼写 `HCID` / `HRID` 的展示。i18n 字典和 aria 文案不在此列。

## 12. 验收清单

- [ ] 5 类页面（Discovery / Entity / Workspace / Documentation / Profile）× 375 / 768 / 1440 宽度 × zh-CN / en 的截图，与参考模板一致
- [ ] 只用键盘完成：登录 → 搜索 → 化合物详情 → 收藏 → 工作台 → 新建并保存笔记 → 删除笔记
- [ ] Lighthouse（手机）：首页、化合物详情、`/aichem` 三个页面的 Accessibility ≥ 90
- [ ] 375 宽度下没有任何页面出现横向滚动
- [ ] `npm run build`、`npm run test:locale`、`pytest` 全部通过，并通过 token 契约测试
- [ ] favicon、apple-icon、PWA 图标、OG 图都已换成 HGS 标志
