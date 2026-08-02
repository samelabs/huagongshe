# 前端代码审计报告 · 开源发布准备

审计范围：`/var/www/huagongshe/web/` 全部 `.ts` / `.tsx` 源文件（46 个）
审计日期：2026-07-31
TypeScript 编译：`tsc --noEmit` 通过（0 错误）

---

## 汇总

| 严重程度 | 数量 |
|----------|------|
| Critical | 0 |
| High     | 4 |
| Medium   | 9 |
| Low      | 8 |

**总体评价**：代码质量较高——TypeScript strict 模式、零 `any`、零 `@ts-ignore`、无 XSS 注入风险（3 处 `dangerouslySetInnerHTML` 均安全）、useEffect 普遍正确使用 cleanup flag。开源前需处理的主要是：第三方跟踪代码硬编码、3 处 i18n 字面量 bug、缺少 ESLint 配置。

---

## High（建议开源前修复）

### H1. i18n 字面量 bug — 标题渲染为代码而非文案
3 处将 `t.xxx` 误写为字符串字面量 `"t.xxx"`，导致用户看到代码文本而非中文文案：

| 文件:行号 | 当前代码 | 问题 | 修复 |
|-----------|----------|------|------|
| `app/reaction/[id]/page.tsx:86` | `title="t.reaction.reagentsCatalystsSolvents"` | **可见标题**渲染为字面量 `t.reaction.reagentsCatalystsSolvents` 而非"试剂、催化剂与溶剂" | `title={t.reaction.reagentsCatalystsSolvents}` |
| `app/chemical/[id]/page.tsx:29` | `description: "t.chemical.desc"` | meta description 为字面量 `t.chemical.desc` | `description: t.chemical.desc` |
| `app/reaction/[id]/page.tsx:21` | `description: "t.reaction.desc"` | meta description 为字面量 `t.reaction.desc` | `description: t.reaction.desc` |

这 3 个 key 在 `lib/i18n.ts` 中均存在（已确认），属于引用错误而非缺失 key。

### H2. 第三方分析跟踪器硬编码 — 隐私 + 开源合规
`app/layout.tsx:48-49`：
```tsx
<script charSet="UTF-8" id="LA_COLLECT" src="//sdk.51.la/js-sdk-pro.min.js" />
<script dangerouslySetInnerHTML={{ __html: 'LA.init({id:"1vMIAXQLAZjjdeBt",ck:"1vMIAXQLAZjjdeBt"})' }} />
```
- 跟踪 ID `1vMIAXQLAZjjdeBt` 硬编码在源码中
- 所有 fork/自部署实例都会向化工社原始账号发送访问数据
- 开源前应改为环境变量驱动（如 `NEXT_PUBLIC_ANALYTICS_ID`）或移除

### H3. AdSense 发布者 ID 硬编码在注释代码中
`app/layout.tsx:52-60`（注释块）：
```
client=ca-pub-2925838645350883
```
虽已禁用，但广告主 ID 仍残留在源码。开源前应清除或改为环境变量。

### H4. 缺少 ESLint 配置
项目中无 `.eslintrc*` 或 `eslint.config.*`，`package.json` 无 lint 脚本。开源项目应配置并强制执行 lint（H1 的字面量 bug 本可被 `no-const-ref` / react-hooks 规则捕获）。建议添加 `eslint-config-next`。

---

## Medium

### M1. AdminConsole — useEffect 依赖缺失 + 异步未处理
`components/AdminConsole.tsx:22`：
```tsx
useEffect(() => { load(); }, []);  // load 未列入依赖，且返回的 Promise 被忽略
```
- `load` 为组件内定义的 async 函数，未用 `useCallback` 包裹
- eslint `react-hooks/exhaustive-deps` 会报警
- `load()` 抛出的异常虽在内部 catch，但 Promise rejection 未处理
**修复**：`useEffect(() => { void load(); }, [])` 或将 load 提取到 effect 内部。

### M2. 大图缺少 lazy loading
`app/reaction/[id]/page.tsx:76`：
```tsx
<img src={reactionSvgUrl(reaction.id, 1500, 340)} width="1500" height="340" alt={...} />
```
该 1500×340 反应方程式 SVG 未加 `loading="lazy"`（同类图片 `ReactionResult.tsx:33`、`UserDashboard.tsx:193` 均已加）。首屏图可保留 eager，但此图在 fold 下方可加 lazy。

### M3. 头像 `<img>` 普遍缺少 lazy loading
以下头像 `<img>` 均未加 `loading="lazy"`（列表场景尤其应加）：
- `components/PersonList.tsx:26`（关注/粉丝列表，可能数十张）
- `components/UserDashboard.tsx:132`
- `components/HeaderAccount.tsx:84`（header 可保持 eager）
- `app/user/[username]/page.tsx:49`
- `app/reaction/[id]/page.tsx:125`
- `components/settings/AvatarSettings.tsx:17`

### M4. 模块级可变状态
`components/SubmissionForm.tsx:22`：
```tsx
let sequence = 1;  // 模块级，所有表单实例共享
```
当前因每页仅一个表单而正常工作，但属于代码异味。建议改为 `useRef` 或组件内 `useState`。

### M5. 缺少 Content-Security-Policy 头
`next.config.ts` 已配置 `X-Content-Type-Options`、`Referrer-Policy`、`Permissions-Policy`（良好），但缺少 CSP。开源前建议添加 CSP 以强化 XSS 防御（当前依赖 React 自动转义）。

### M6. 重复的 apiError 辅助函数
三处近乎相同的实现：
- `components/SubmissionForm.tsx:239-243`
- `components/AccountForm.tsx:69-75`
- `components/settings/ApiTokenSettings.tsx:94-98`

建议提取到 `lib/api.ts` 统一导出。

### M7. UserDashboard 第二个 useEffect — 分支式 fetch 调度器
`components/UserDashboard.tsx:56-103`：单个 useEffect 内根据 `activeTab` 分支发起不同 API 请求。功能正确且用了 `active` flag 防 race，但：
- 未使用 AbortController 取消实际网络请求（flag 只阻止 setState，请求仍完成）
- 分支逻辑较长（40+ 行），可拆分为独立 hook 或按 tab 拆分 effect

### M8. 内联中文硬编码混入 i18n
`app/reaction/[id]/page.tsx:14`：
```tsx
INTERNAL_STANDARD: "内标", UNKNOWN: "其他",
```
以及 `:46` 的 `"是"`、`:163` 的 `"次"`、`:187` 的 `"天"`——散落硬编码中文未走 `t.xxx`，与 i18n 体系不一致。

### M9. AvatarSettings 消息类型靠字符串比对判断
`components/settings/AvatarSettings.tsx:55`：
```tsx
className={message === t.settings.avatar.updated || message === t.settings.avatar.removed ? "form-message ok" : "form-message bad"}
```
通过比对文案字符串判断消息类型，文案改动即失效。建议用独立的 `messageKind` state（如 `ProfileSettings.tsx:28` 的做法）。

---

## Low

### L1. 未使用的 import
`app/layout.tsx:7`：`import Script from "next/script"` 仅在注释代码中引用，实际未使用。eslint 会标记。

### L2. 实验性 API
`app/error.tsx:6,8,15`：使用 `unstable_retry`，属 Next.js 实验性 API，版本升级时可能破坏。

### L3. 魔法数字未集中
分页大小（20/40/50）、限制（100/50000）、头像大小（5MB=`5*1024*1024`）等散落各文件。建议常量化。

### L4. next-env.d.ts 被 .gitignore 忽略但文件存在
`.gitignore:41` 忽略 `next-env.d.ts`，但该文件实际存在于仓库。Next.js 会自动生成，通常应忽略，当前状态一致但文件不应提交。

### L5. 大型内联事件处理函数
- `components/AccountForm.tsx:20-48`：onSubmit 内联 28 行
- `components/settings/ApiTokenSettings.tsx:80-88`：onClick 内联 revoke 逻辑

可提取为命名函数提升可读性，但当前规模可接受。

### L6. ParticipantGroup 空 items 时的标题文案
`app/reaction/[id]/page.tsx:171`：
```tsx
<p className="quiet-empty">{t.chemical.knowledge.noData(title)}</p>
```
在反应详情页的参与者分组中，引用了 `t.chemical.knowledge.noData`（化学知识库域的 key），跨域复用略易混淆。

### L7. sitemap generateSitemaps 边界
`app/sitemap.ts:25`：当第一批恰好等于 PAGE_SIZE 时 `Math.ceil(count / PAGE_SIZE) + 1` 可能多生成一个空 sitemap。建议确认边界。

### L8. robots.ts 无 Disallow 规则
`app/robots.ts`：`allow: "/"` 允许全部爬取。`/me`、`/admin`、`/me/settings/*` 虽页面级有 `robots: { index: false }`，但 robots.txt 层面无额外防护。可考虑 `Disallow: /me` `/admin` `/api`。

---

## 已验证良好的实践（无需修改）

- ✅ `dangerouslySetInnerHTML` 3 处均安全（LA.init 静态字符串 × 1、JSON-LD `JSON.stringify` × 2，无用户输入注入）
- ✅ 零 `any` 类型、零 `@ts-ignore` / `@ts-expect-error`
- ✅ 所有 `target="_blank"` 链接均带 `rel="noreferrer"`（4 处）
- ✅ 无 `eval` / `new Function` / `innerHTML` / `document.cookie` / `localStorage`
- ✅ 源码中无硬编码密钥/密码
- ✅ Client 组件边界合理（仅交互组件标 `"use client"`，数据获取页为 Server Component）
- ✅ useEffect 普遍正确使用 `active` flag cleanup（SubmissionForm、UserDashboard、HeaderAccount、ApiTokenSettings）
- ✅ `crypto.randomUUID()` 用于幂等键（SubmissionForm）
- ✅ `encodeURIComponent` 用于所有动态 URL 拼接
- ✅ 开放重定向防护（`login/page.tsx:12` `safeNextPath` 校验 `//`）
- ✅ 安全头配置（nosniff / referrer-policy / permissions-policy）
- ✅ metadata 完整（title template / OG / Twitter / canonical / robots）
- ✅ 私有页面 `robots: { index: false }`（me / admin / settings）
- ✅ ISR + 动态渲染策略合理（匿名 ISR 1h，登录用户 dynamic）
