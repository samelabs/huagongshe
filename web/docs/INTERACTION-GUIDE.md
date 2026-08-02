# 化工社前端交互规范

## 1. 数据获取

### API 请求

所有前端请求通过 `lib/api.ts` 的 `apiGet` / `apiPost` / `apiPatch` / `apiDelete` 统一发送。

```ts
// 正确
import { apiGet } from '@/lib/api'
const data = await apiGet<Chemical>(`/chemicals/${id}`)

// 错误 — 禁止直接 fetch
const res = await fetch('/api/chemicals/123')
```

**规则：**
- `apiGet` 内置错误处理和类型安全
- GET 请求可传 `cache` 参数控制 Next.js 缓存
- 服务端组件（SSR）使用 `apiGet`，客户端组件使用 `apiGet`（通过浏览器）
- 所有 API 返回 JSON，不返回 HTML

### 加载状态

每个异步数据块必须有三种状态：

```tsx
// 三态：loading → ready / error
if (state === 'loading') return <PanelLoading />
if (state === 'error') return <PanelError />
// ready
return <Content data={data} />
```

**禁止：**
- ❌ 无加载态——用户看到空白以为卡了
- ❌ 无错误态——API 失败用户看不到反馈
- ❌ 只有 loading 没有 error

### 分页

统一使用 `page` + `page_size` 参数，不使用 cursor（化工社数据量不需要）。

```ts
// 分页链接
<Link href={`/me?page=${page + 1}`}>下一页</Link>
```

---

## 2. 表单交互

### 表单结构

```
.form-section
  .form-section-head
    span (kicker)
    div
      h2 (标题)
      p  (说明)
  .form-fields
    label > input/span(inline-error)
```

### 提交规则

1. **禁用按钮**：提交过程中 `disabled={submitting}`，按钮显示"…中"
2. **成功反馈**：`form-message.ok`（绿色文字）
3. **失败反馈**：`form-message.bad`（红色文字），显示 API 返回的 detail
4. **不清空表单**：失败后保留用户输入
5. **不跳转**：表单提交后留在当前页，用内联反馈

### 输入验证

- 前端验证只做格式检查（必填、长度、正则）
- 业务验证交给后端 API（返回 400/422 + detail）
- 错误信息显示在输入框下方 `.inline-error`

### 移动端

- 所有 input `font-size: 16px`（防 iOS 自动缩放）
- 表单提交按钮在 680px 以下 `width: 100%`

---

## 3. 客户端状态

### 认证状态

通过 `AccountContext` 的 `useAccount()` 获取：

```tsx
const { user, authReady } = useAccount()

if (authReady && !user) return <LoginRequired />
if (!authReady) return <p>正在读取账号…</p>
```

**三态规则**：`authReady` 为 false 时不渲染内容，避免闪烁。

### 组件内状态

- 用 `useState` 管理简单 UI 状态（开关、选中项）
- 用 `useEffect` 做数据获取（配合 AbortController 防竞态）
- 服务端组件不使用 state

### 竞态处理

```tsx
useEffect(() => {
  let active = true
  fetchData().then(data => {
    if (!active) return  // 组件已卸载
    setData(data)
  })
  return () => { active = false }
}, [id])
```

---

## 4. 链接与导航

### 内部链接

使用 `<Link>` 组件：

```tsx
import Link from 'next/link'
<Link href="/chemical/123">查看</Link>
```

### 外部链接

添加 `target="_blank"` 和 `rel="noreferrer"`：

```tsx
<a href={doiUrl} target="_blank" rel="noreferrer">DOI</a>
```

### 导航反馈

- 导航不需要全局 loading——Next.js 路由切换有内置过渡
- 但如果目标页需要 SSR 数据，目标页自己处理 loading 态

---

## 5. 弹层与下拉菜单

### 下拉菜单

使用 `<details>` 元素（无 JS 原生展开收起）：

```tsx
<details className="account-menu">
  <summary>菜单</summary>
  <div className="account-dropdown">...</div>
</details>
```

**规则：**
- 点击外部关闭：通过 `onBlur` 或 `useEffect` 监听 document click
- 移动端：fixed 定位，避免被父容器裁剪

### 模态弹窗

当前不使用模态弹窗。确认操作（如删除）使用内联展开，不弹出遮罩。

---

## 6. 响应式行为

### 断点

| 断点 | 宽度 | 行为变化 |
|---|---|---|
| 桌面 | > 900px | 双列布局、sticky 侧栏 |
| 平板 | ≤ 900px | 侧栏变单列、卡片网格调整 |
| 手机 | ≤ 680px | 单列、头部压缩、字号缩小 |
| 小屏 | ≤ 420px | 进一步压缩、padding 最小化 |

### 触摸优化

- 所有可点击元素 `min-height: 40px`（手指触控最小尺寸）
- 移动端导航文字 ≥ `12px`
- `-webkit-tap-highlight-color: transparent`（去蓝闪）

---

## 7. 性能规则

### 图片

- 分子结构 SVG：通过 API 渲染，Redis 缓存 24h
- 用户头像：`next/image` 优化
- `loading="lazy"` 对非首屏图片

### 避免不必要的水合

- 纯展示页面使用 Server Component（默认）
- 只有需要交互的部分标 `'use client'`
- `'use client'` 边界尽量往上推，缩小客户端 JS 范围

### 数据缓存

- 首页统计数据：`revalidate = 3600`（1 小时）
- 化合物/反应详情：默认动态渲染
- API SVG 渲染：Redis 缓存

---

## 8. 禁止清单

| 禁止 | 原因 |
|---|---|
| 直接 `fetch` 不走 `apiGet` | 缺少错误处理和类型安全 |
| `useEffect` 不处理竞态 | 快速切换页面时数据错乱 |
| 表单提交后清空用户输入 | 用户需要修改重试 |
| 硬编码颜色值 | 无法统一换肤 |
| `window` / `document` 在 SSR 中直接访问 | 服务端渲染报错 |
| `alert()` / `confirm()` | 破坏用户体验，用内联反馈替代 |
| 中文文案硬编码在 JSX 中 | 统一走语言包 `t.xxx` |
