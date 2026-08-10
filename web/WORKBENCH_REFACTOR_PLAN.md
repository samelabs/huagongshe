# 工作台重构方案

## 问题

当前 `/me` 把5个功能平级塞在一个 Tab 条里，混淆了用户底座、基础能力和工作台能力的边界。

## 架构定义

三层分离：

```
用户底座（永久在顶部，不变）
├── 头像、用户名、加入时间
├── 关注/粉丝数（可点击）
└── 快捷操作（新建反应、AI助手）

工作台能力区（可扩展，纵向布局）
├── 我的反应（现有核心能力）
└── 未来扩展位（实验笔记、AI对话记录、自定义清单…）

基础能力区（横向次级导航，不是工作台）
├── 收藏（化合物 + 反应）
├── 关注动态
└── 社交关系（关注 / 粉丝）
```

## 视觉交互设计

### 桌面端

```
┌─────────────────────────────────────────┐
│ 用户底座                                 │
│  [头像]  用户名 @username                │
│          加入时间                        │
│          12 关注 · 8 粉丝    [新建反应]  │
│                           [AI助手]       │
├─────────────────────────────────────────┤
│ ── 工作台 ──────────────────────────── │
│                                         │
│  我的反应                    15条 →     │  ← 卡片式入口
│  你保存的全部反应记录                    │
│                                         │
│ ── 更多 ───────────────────────────── │
│                                         │
│  收藏 · 关注动态 · 关注 · 粉丝           │  ← 横向文字链接
│  （点击切换面板内容）                    │
│                                         │
│  [当前面板内容]                          │
└─────────────────────────────────────────┘
```

### 移动端

```
┌──────────────┐
│ 用户底座      │  ← 紧凑布局
│ [头像] 用户名 │
│ 12关注 8粉丝 │
│ [新建] [AI]  │
├──────────────┤
│ 我的反应 15→ │  ← 工作台卡片
├──────────────┤
│ 收藏 动态    │  ← 横向滚动次级导航
│ 关注 粉丝    │
├──────────────┤
│ [面板内容]   │
├──────────────┤
│ [底部TabBar] │
└──────────────┘
```

## 路由设计

保持 URL 驱动（SSR + 书签友好）：

| URL | 内容 |
|---|---|
| `/me` | 工作台首页：用户底座 + 我的反应（默认） |
| `/me?tab=reactions` | 我的反应 |
| `/me?tab=saved` | 收藏 |
| `/me?tab=activity` | 关注动态 |
| `/me?tab=following` | 关注 |
| `/me?tab=followers` | 粉丝 |

URL 结构不变（向后兼容），但视觉分层变了。

## 代码结构重构

### 当前（问题）
```
components/UserDashboard.tsx (300行单文件)
├── 5种数据状态耦合在一个useEffect里
├── 5个子组件全在同一文件
└── activeTab参数驱动一个巨型switch
```

### 重构后
```
components/dashboard/
├── DashboardShell.tsx       — 用户底座 + 布局骨架
├── WorkbenchCard.tsx        — 工作台能力卡片（可扩展）
├── panels/
│   ├── ReactionsPanel.tsx   — 我的反应
│   ├── SavedPanel.tsx       — 收藏（化合物+反应）
│   ├── ActivityPanel.tsx    — 关注动态
│   └── RelationshipsPanel.tsx — 关注/粉丝
└── shared/
    ├── Pagination.tsx
    └── PanelState.tsx       — loading/error/empty
```

每个 panel 独立，自带数据获取和渲染。新增工作台能力只需加一个 panel 文件 + 在 WorkbenchCard 列表里注册。

## 命名修正

| 旧 | 新 |
|---|---|
| "我的知识库" | "工作台" |
| nav.knowledgeBase "我的知识库" | nav.workbench "工作台" |
| me.title "我的知识库" | me.title "工作台" |
| MobileTabBar label "知识库" | "工作台" |
| MobileTabBar libraryIcon | 改用工作台/仪器图标 |

## 不做的事

- ❌ 不改 API（数据接口不变）
- ❌ 不改路由结构（URL不变，向后兼容）
- ❌ 不改 /me/settings（设置页不动）
- ❌ 不改 /user/[username]（公开主页不动）

## 改动范围

| 文件 | 改动 |
|---|---|
| `components/dashboard/` | 新目录，拆分 UserDashboard.tsx |
| `components/UserDashboard.tsx` | 删除（内容拆到 dashboard/） |
| `components/MobileTabBar.tsx` | label "知识库"→"工作台"，图标替换 |
| `app/globals.css` | 新增工作台布局CSS，清理旧dashboard CSS |
| `lib/i18n.ts` | 命名修正 |
