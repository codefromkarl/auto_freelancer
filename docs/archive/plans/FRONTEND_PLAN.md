# Freelancer 自动化系统 - Next.js 前端实施计划

## 技术栈
- **Next.js 14+** (App Router)
- **TypeScript**
- **Tailwind CSS**
- **shadcn/ui** (组件库)
- **React Query** (数据获取与缓存)
- **Zustand** (状态管理)
- **Recharts** (图表展示)

## 项目结构
```
typescript/
├── app/
│   ├── layout.tsx           # 根布局（Provider配置）
│   ├── page.tsx             # Dashboard 主页
│   ├── projects/
│   │   ├── page.tsx         # 项目列表页
│   │   └── [id]/
│   │       └── page.tsx     # 项目详情页
│   ├── proposals/
│   │   └── page.tsx         # 提案管理页
│   └── actions/             # Server Actions（如果需要）
├── components/
│   ├── ui/                  # shadcn/ui 组件
│   ├── dashboard/
│   │   ├── ProjectTable.tsx
│   │   ├── ProjectCard.tsx
│   │   ├── StatsCards.tsx
│   │   └── ScriptExecutor.tsx
│   └── proposal/
│       ├── ProposalPreview.tsx
│       └── ProposalEditor.tsx
├── lib/
│   ├── api.ts               # API 客户端
│   ├── types.ts             # TypeScript 类型
│   └── utils.ts             # 工具函数
├── hooks/
│   ├── useProjects.ts       # 项目数据 Hook
│   └── useScriptExecution.ts # 脚本执行 Hook
├── store/
│   └── appStore.ts          # Zustand 全局状态
└── public/
```

## 核心功能模块

### 1. Dashboard 主页 (`/`)
- 统计卡片：总项目数、今日新增、平均评分、待处理投标
- 快速操作按钮：刷新数据、执行评分、生成提案
- 最近项目列表（带评分）
- 实时状态指示器

### 2. 项目列表页 (`/projects`)
- 高级筛选：预算范围、评分阈值、状态、技能
- 排序选项：按评分、预算、发布时间
- 数据表格展示（shadcn/ui DataTable）
- 批量操作：选中多个项目批量评分/生成提案

### 3. 项目详情页 (`/projects/[id]`)
- 完整项目信息展示
- AI 评分详情（6维度评分分解）
- 提案草稿预览/编辑
- 投标操作按钮
- 客户风控信息展示

### 4. 提案管理页 (`/proposals`)
- 已生成提案列表
- 提案编辑器（所见即所得）
- 一键提交投标
- 提案历史版本

### 5. 脚本执行模块
- 按钮触发后台脚本
- 执行进度展示（WebSocket 或轮询）
- 执行日志实时显示
- 任务队列管理

## API 集成

### 后端端点映射
| 功能 | 后端 API | 前端调用 |
|------|---------|---------|
| 搜索项目 | `GET /api/v1/projects/search` | `useProjects()` |
| 项目详情 | `GET /api/v1/projects/{id}` | `fetchProject(id)` |
| 项目评分 | `POST /api/v1/projects/{id}/score` | `scoreProject(id)` |
| 创建投标 | `POST /api/v1/bids` | `createBid(data)` |
| 统计数据 | `GET /api/v1/stats` | `useStats()` |
| 客户风控 | `GET /api/v1/client-risk/{user_id}` | `fetchClientRisk(id)` |

### API 客户端配置
```typescript
// lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;
```

## 实施任务

### 阶段 1：项目初始化
- [ ] 创建 Next.js 项目
- [ ] 配置 Tailwind CSS
- [ ] 安装并初始化 shadcn/ui
- [ ] 配置 ESLint、Prettier
- [ ] 设置环境变量

### 阶段 2：基础设施
- [ ] 创建 API 客户端 (`lib/api.ts`)
- [ ] 定义 TypeScript 类型 (`lib/types.ts`)
- [ ] 设置 React Query Provider
- [ ] 创建 Zustand store
- [ ] 配置路由布局

### 阶段 3：UI 组件
- [ ] 安装/配置 shadcn/ui 组件
  - [ ] Button, Input, Select
  - [ ] Table, Card
  - [ ] Dialog, Sheet
  - [ ] Badge, Progress
  - [ ] Charts (Recharts 集成)
- [ ] 创建自定义组件
  - [ ] ProjectCard
  - [ ] StatsCards
  - [ ] ScriptExecutor

### 阶段 4：Dashboard 主页
- [ ] 实现统计卡片
- [ ] 实现快速操作按钮
- [ ] 实现最近项目列表
- [ ] 添加实时数据刷新

### 阶段 5：项目列表
- [ ] 实现筛选表单
- [ ] 实现数据表格
- [ ] 实现排序功能
- [ ] 添加批量操作

### 阶段 6：项目详情
- [ ] 实现详情页面布局
- [ ] 实现评分详情展示
- [ ] 实现提案预览/编辑
- [ ] 添加投标操作

### 阶段 7：脚本执行
- [ ] 实现脚本触发 API
- [ ] 实现进度追踪
- [ ] 实现日志展示
- [ ] 添加任务队列 UI

### 阶段 8：优化与部署
- [ ] 性能优化
- [ ] 响应式设计
- [ ] 错误处理
- [ ] Docker 配置

## 环境变量
```env
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_KEY=your-api-key
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

## Docker 集成
更新 `docker-compose.yml` 添加 Next.js 服务：
```yaml
frontend:
  build: ./typescript
  ports:
    - "3000:3000"
  environment:
    - NEXT_PUBLIC_API_URL=http://python_service:8000
  depends_on:
    - python_service
```
