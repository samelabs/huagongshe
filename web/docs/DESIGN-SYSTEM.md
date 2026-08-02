# 化工社设计系统

## 1. 设计令牌（CSS 变量）

所有颜色、字体、间距通过 `:root` 变量统一管理，禁止在组件中硬编码值。

### 色彩

| 令牌 | 值 | 用途 |
|---|---|---|
| `--blue` | `#1e90ff` | 主色：链接、按钮、强调 |
| `--blue-deep` | `#1577e0` | hover / active |
| `--blue-strong` | `#0f5fba` | pressed / 深色文字 |
| `--blue-pale` | `#e8f2ff` | badge / 极浅背景 |
| `--blue-tint` | `#f5f9ff` | 卡片微染背景 |
| `--blue-border` | `#b8dbff` | 蓝色系元素边框 |
| `--blue-glow` | `rgba(30,144,255,.10)` | focus 光晕 |

### 中性色

| 令牌 | 值 | 用途 |
|---|---|---|
| `--ink` | `#1a2b3c` | 正文 |
| `--heading` | `#243b53` | 标题 |
| `--heading-soft` | `#486581` | 标题次要 |
| `--muted` | `#5e7d99` | 次要文字 |
| `--quiet` | `#829ab1` | 最弱文字 |
| `--line` | `#dfe5ee` | 分割线 |
| `--line-strong` | `#cbd4e2` | 强分割线 |
| `--wash` | `#f6f8fb` | 洗白背景 |
| `--paper` | `#fff` | 底色 |

### 语义色

| 令牌 | 值 | 用途 |
|---|---|---|
| `--danger` | `#c0392b` | 错误、删除 |
| `--success` | `#1a7a4c` | 成功 |
| `--warning` | `#d48806` | 警告 |

### 字体

| 令牌 | 值 |
|---|---|
| `--font-ui` | `var(--font-inter), var(--font-noto-sc), ui-sans-serif, ...` |
| `--font-mono` | `"SFMono-Regular", Consolas, monospace` |
| `--title-weight` | `500` |
| `--section-weight` | `600` |

### 布局

| 令牌 | 值 | 用途 |
|---|---|---|
| `--max` | `1180px` | 页面最大宽度 |

---

## 2. 字号层级

| 层级 | 字号 | 字重 | 用途 |
|---|---|---|---|
| H1 | `clamp(26px, 3.2vw, 34px)` | `--title-weight` (500) | 页面主标题 |
| H2 | `23px` | `--section-weight` (600) | 区块标题 |
| H3 | `18px` | `--section-weight` (600) | 卡片标题 |
| 正文 | `14px` | 400 | 段落、描述 |
| 次要 | `13px` | 400 | 辅助说明 |
| 标签 | `12px` | 400 | 元信息 |
| 微标 | `10-11px` | 400-800 | badge、kicker、时间戳 |

---

## 3. 间距规范

使用 4px 网格：

| 名称 | 值 | 用途 |
|---|---|---|
| `xs` | 4px | 紧凑间距 |
| `sm` | 8px | 元素内间距 |
| `md` | 12-16px | 组件间距 |
| `lg` | 20-28px | 区块间距 |
| `xl` | 40-52px | 大区间距 |

---

## 4. 组件规范

### 按钮 `.button`

- `min-height: 40px`，`.small` 变体 `34px`
- 圆角 `7px`
- 三种类型：`.primary`（蓝底白字）、`.secondary`（白底边框）、`.danger`
- 过渡 `0.15s ease`
- `:disabled` → `opacity: .5`

### 输入框

- `border: 1px solid var(--line-strong)`
- `border-radius: 6px`
- `padding: 10px 11px`
- `:focus` → `border-color: var(--blue)` + `box-shadow: 0 0 0 3px var(--blue-glow)`
- 移动端 `font-size: 16px`（防 iOS 缩放）

### 卡片

- `border: 1px solid var(--line)`
- 无圆角（与数据密度匹配）
- 内边距按内容层级：`13px`（紧凑）/ `19px`（标准）/ `26px`（表单区）

### 标题区块 `.section-heading`

- 底部间距 `20px`
- 左侧标题 + 右侧操作
- kicker（上方小标签）：`color: var(--blue)`, `font-size: 10px`, `font-weight: 800`, `letter-spacing: .16em`

### 实体标识 `.entity-id`

- 行内块，左侧 2px 色条
- 化合物用蓝色系，反应用灰色系
- `.compact` 变体用于列表和卡片

### 页面通用容器 `.content-page`

- `width: min(var(--max), calc(100% - 40px))`
- `padding: 42px 0 90px`
- 移动端 `padding-top: 28px`

---

## 5. 响应式断点

| 断点 | 宽度 | 说明 |
|---|---|---|
| 桌面 | `> 900px` | 完整布局 |
| 平板 | `≤ 900px` | 侧栏变单列，表单变单列 |
| 手机 | `≤ 680px` | 头部压缩，hero 字号缩小，网格变单列 |
| 小屏 | `≤ 420px` | 进一步压缩边距和字号 |

---

## 6. 动效规范

| 类型 | 时长 | 缓动 |
|---|---|---|
| 按钮/链接 hover | `150ms` | `ease` |
| 侧栏/抽屉 | `200ms` | `ease` |
| 透明度过渡 | `150ms` | `ease` |

不使用 `transform` 动画做布局位移（会引起 reflow）。

---

## 7. CSS 编写规则

1. **禁止硬编码颜色**：必须使用 `:root` 变量
2. **禁止 `!important`**：通过特异性解决
3. **先布局后视觉**：先写 display/grid/flex/padding，再写 color/font
4. **移动端优先兼容**：所有布局必须通过 680px 和 420px 断点测试
5. **响应式写在主规则之后**：用 `@media` 覆盖，不重复声明
