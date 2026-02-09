# BidMaster API 接口完整文档

> Freelancer AI 自动化系统 - 接口文档
>
> **参考**: [Freelancer API Documentation](https://developers.freelancer.com/docs)
>
> **最后更新**: 2026-01-11

---

## 文档说明

本文档采用统一格式编写每个 API 端点：

| 章节 | 说明 |
|------|------|
| **接口描述** | 接口功能简述 |
| **请求格式** | HTTP 方法和路径 |
| **请求参数** | Query/Path 参数说明 |
| **请求体** | POST/PUT 请求的 JSON 结构 |
| **响应格式** | 统一响应包装结构 |
| **响应参数** | 响应数据字段说明 |
| **请求示例** | cURL 命令 |
| **响应示例** | 完整 JSON 响应 |

---

## 目录

### Python Service API (本地服务)

| 模块 | 端点 | 说明 |
|------|------|------|
| **1. Projects** | | |
| | [1.1 搜索项目](#11-搜索项目) | GET /api/v1/projects/search |
| | [1.2 获取项目详情](#12-获取项目详情) | GET /api/v1/projects/{id} |
| | [1.3 更新 AI 分析结果](#13-更新-ai-分析结果) | PUT /api/v1/projects/{id} |
| | [1.4 项目 AI 评分](#14-项目-ai-评分) | POST /api/v1/projects/{id}/score |
| **2. Bids** | | |
| | [2.1 创建投标](#21-创建投标) | POST /api/v1/bids |
| | [2.2 获取我的投标](#22-获取我的投标) | GET /api/v1/bids/user |
| | [2.3 获取投标详情](#23-获取投标详情) | GET /api/v1/bids/{id} |
| | [2.4 更新投标](#24-更新投标) | PUT /api/v1/bids/{id} |
| | [2.5 撤销投标](#25-撤销投标) | DELETE /api/v1/bids/{id} |
| **3. Milestones** | | |
| | [3.1 创建里程碑](#31-创建里程碑) | POST /api/v1/milestones |
| | [3.2 获取项目里程碑](#32-获取项目里程碑) | GET /api/v1/milestones/{id} |
| | [3.3 接受里程碑](#33-接受里程碑) | POST /api/v1/milestones/{id}/accept |
| | [3.4 释放里程碑付款](#34-释放里程碑付款) | POST /api/v1/milestones/{id}/release |
| **4. Messages** | | |
| | [4.1 发送消息](#41-发送消息) | POST /api/v1/messages |
| | [4.2 同步消息](#42-同步消息) | POST /api/v1/messages/sync |
| | [4.3 获取未读消息](#43-获取未读消息) | GET /api/v1/messages/unread |
| | [4.4 获取消息线程列表](#44-获取消息线程列表) | GET /api/v1/messages/threads |
| | [4.5 获取线程消息](#45-获取线程消息) | GET /api/v1/messages/{id} |
| | [4.6 标记线程为已读](#46-标记线程为已读) | PUT /api/v1/messages/{id}/read |
| | [4.7 上传附件](#47-上传附件) | POST /api/v1/messages/upload |
| | [4.8 Telegram 回调处理](#48-telegram-回调处理) | POST /api/v1/messages/telegram/callback |
| **5. Kickoff** | | |
| | [5.1 触发项目启动](#51-触发项目启动) | POST /api/v1/kickoff/trigger |
| | [5.2 获取启动状态](#52-获取启动状态) | GET /api/v1/kickoff/{id} |
| | [5.3 列出最近的启动记录](#53-列出最近的启动记录) | GET /api/v1/kickoff/list/recent |
| | [5.4 检查并触发启动](#54-检查并触发启动) | POST /api/v1/kickoff/check/{id} |
| | [5.5 获取可用模板列表](#55-获取可用模板列表) | GET /api/v1/kickoff/templates |
| | [5.6 删除启动记录](#56-删除启动记录) | DELETE /api/v1/kickoff/{id} |
| **6. AI Replies** | | |
| | [6.1 生成 AI 回复候选项](#61-生成-ai-回复候选项) | POST /api/v1/ai/replies |
| **7. Client Risk** | | |
| | [7.1 获取客户信息](#71-获取客户信息) | GET /api/v1/client-risk/{id} |
| | [7.2 获取客户评价](#72-获取客户评价) | GET /api/v1/client-risk/{id}/reviews |
| **8. System** | | |
| | [8.1 健康检查](#81-健康检查) | GET /health |
| | [8.2 统计信息](#82-统计信息) | GET /api/v1/stats |

### Freelancer 官方 API

| 模块 | 说明 |
|------|------|
| [9. Freelancer 官方 API](#9-freelancer-官方-api) | SDK 封装与官方接口映射 |

### 通用说明

| 章节 | 说明 |
|------|------|
| [10. 认证与授权](#10-认证与授权) | API Key、OAuth 配置 |
| [11. 错误处理](#11-错误处理) | 错误码与处理方式 |
| [12. 速率限制](#12-速率限制) | 限流策略 |

### 附录

| 章节 | 说明 |
|------|------|
| [附录 A: 端点速查表](#附录-a-端点速查表) | 快速索引 |
| [附录 B: 统一响应包装](#附录-b-统一响应包装) | 响应格式规范 |

---

## 1. Projects (项目)

### 1.1 搜索项目

> 从 Freelancer.com 搜索项目并同步到本地数据库。

#### 请求格式

```http
GET /api/v1/projects/search
```

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:----:|--------|------|
| `query` | string | 否 | - | 搜索关键词 |
| `skills` | string | 否 | - | 技能 ID 列表，逗号分隔 |
| `budget_min` | number | 否 | - | 最低预算 |
| `budget_max` | number | 否 | - | 最高预算 |
| `status` | string | 否 | - | 项目状态 |
| `limit` | integer | 否 | 20 | 返回数量 (1-100) |
| `offset` | integer | 否 | 0 | 分页偏移 |

#### 响应格式

```json
{
  "status": "success",
  "data": [...],
  "total": 0
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态: `success` / `error` |
| `data` | array | 项目列表 |
| `total` | integer | 总数量 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/projects/search?query=python&limit=10" \
     -H "X-API-Key: your_api_key"
```

#### 响应示例

```json
{
  "status": "success",
  "data": [
    {
      "id": 38000123,
      "title": "Python Automation Script",
      "description": "...",
      "budget_minimum": 100,
      "budget_maximum": 500,
      "currency": "USD",
      "status": "active",
      "bid_count": 5,
      "owner_id": 1234567,
      "owner_username": "client_user"
    }
  ],
  "total": 1
}
```

---

### 1.2 获取项目详情

> 获取指定项目的详细信息。

#### 请求格式

```http
GET /api/v1/projects/{project_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_id` | integer | 是 | Freelancer 项目 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": {...}
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 项目详情对象 |
| `data.id` | integer | 项目 ID |
| `data.title` | string | 项目标题 |
| `data.description` | string | 项目描述 |
| `data.full_description` | string | 完整描述 |
| `data.budget_minimum` | number | 最低预算 |
| `data.budget_maximum` | number | 最高预算 |
| `data.currency` | string | 货币代码 |
| `data.status` | string | 项目状态 |
| `data.bid_count` | integer | 投标数量 |
| `data.owner_id` | integer | 雇主用户 ID |
| `data.owner_username` | string | 雇主用户名 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/projects/38000123" \
     -H "X-API-Key: your_api_key"
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": 38000123,
    "title": "Python Automation Script",
    "description": "Need a Python developer...",
    "full_description": "Long description...",
    "budget_minimum": 100,
    "budget_maximum": 500,
    "currency": "USD",
    "status": "active",
    "bid_count": 5,
    "owner_id": 1234567,
    "owner_username": "client_user"
  }
}
```

---

### 1.3 更新 AI 分析结果

> 更新项目的 AI 评分和提案草稿。

#### 请求格式

```http
PUT /api/v1/projects/{project_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_id` | integer | 是 | Freelancer 项目 ID |

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `ai_score` | number | 是 | AI 评分 (0-10) |
| `ai_reason` | string | 是 | 评分原因 |
| `ai_proposal_draft` | string | 是 | 投标提案草稿 |
| `suggested_bid` | number | 否 | 建议投标金额 |

#### 响应格式

```json
{
  "status": "success",
  "data": {...}
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 更新后的项目对象 |
| `data.id` | integer | 项目 ID |
| `data.ai_score` | number | AI 评分 |
| `data.ai_reason` | string | 评分原因 |
| `data.ai_proposal_draft` | string | 提案草稿 |
| `data.suggested_bid` | number | 建议投标金额 |

#### 请求示例

```bash
curl -X PUT "http://localhost:8000/api/v1/projects/38000123" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{"ai_score": 8.5, "ai_reason": "High budget match", "ai_proposal_draft": "Hello..."}'
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": 38000123,
    "ai_score": 8.5,
    "ai_reason": "High budget match",
    "ai_proposal_draft": "Hello...",
    "suggested_bid": 350.00
  }
}
```

---

### 1.4 项目 AI 评分

> 使用内置评分系统为项目打分。

#### 请求格式

```http
POST /api/v1/projects/{project_id}/score
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_id` | integer | 是 | Freelancer 项目 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "project_id": 0,
    "ai_score": 0,
    "ai_grade": "string",
    "ai_reason": "string",
    "ai_proposal_draft": "string",
    "suggested_bid": 0,
    "score_breakdown": {...}
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 评分结果对象 |
| `data.project_id` | integer | 项目 ID |
| `data.ai_score` | number | 综合评分 (0-10) |
| `data.ai_grade` | string | 评级 (A/B/C/D) |
| `data.ai_reason` | string | 评分原因 |
| `data.ai_proposal_draft` | string | 提案草稿 |
| `data.suggested_bid` | number | 建议投标金额 |
| `data.score_breakdown` | object | 评分细项 |
| `data.score_breakdown.budget_score` | number | 预算匹配度 (0-10) |
| `data.score_breakdown.competition_score` | number | 竞争程度 (0-10) |
| `data.score_breakdown.clarity_score` | number | 描述清晰度 (0-10) |
| `data.score_breakdown.customer_score` | number | 客户质量 (0-10) |
| `data.score_breakdown.tech_score` | number | 技术匹配度 (0-10) |
| `data.score_breakdown.risk_score` | number | 风险评估 (0-10) |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/projects/38000123/score" \
     -H "X-API-Key: your_api_key"
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "project_id": 38000123,
    "ai_score": 8.0,
    "ai_grade": "A",
    "ai_reason": "High budget match and required skills align perfectly.",
    "ai_proposal_draft": "Hello, I can help you with...",
    "suggested_bid": 350.00,
    "score_breakdown": {
      "budget_score": 9,
      "competition_score": 7,
      "clarity_score": 8,
      "customer_score": 9,
      "tech_score": 8,
      "risk_score": 7
    }
  }
}
```

---

## 2. Bids (投标)

### 2.1 创建投标

> 对指定项目进行投标。

#### 请求格式

```http
POST /api/v1/bids
```

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_id` | integer | 是 | 目标项目 ID |
| `amount` | number | 是 | 投标金额 |
| `period` | integer | 否 | 完成周期 (天数, 1-365) |
| `description` | string | 否 | 投标提案内容 |

#### 响应格式

```json
{
  "status": "success",
  "data": {...}
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 投标结果对象 |
| `data.id` | integer | 投标 ID |
| `data.project_id` | integer | 项目 ID |
| `data.amount` | number | 投标金额 |
| `data.period` | integer | 完成周期 |
| `data.status` | string | 投标状态 |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/bids" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{"project_id": 38000123, "amount": 150, "period": 7, "description": "Expert here."}'
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": 12345,
    "project_id": 38000123,
    "amount": 150.00,
    "period": 7,
    "description": "Expert here.",
    "status": "active"
  }
}
```

---

### 2.2 获取我的投标

> 获取当前账户的历史投标记录。

#### 请求格式

```http
GET /api/v1/bids/user
```

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:----:|--------|------|
| `status` | string | 否 | - | 筛选状态 |
| `limit` | integer | 否 | 50 | 返回数量 (1-200) |
| `offset` | integer | 否 | 0 | 分页偏移 |

#### 响应格式

```json
{
  "status": "success",
  "data": [...],
  "total": 0
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | array | 投标列表 |
| `total` | integer | 总数量 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/bids/user?limit=10" \
     -H "X-API-Key: your_api_key"
```

#### 响应示例

```json
{
  "status": "success",
  "data": [
    {
      "id": 12345,
      "project_id": 38000123,
      "amount": 150.00,
      "period": 7,
      "status": "active",
      "created_at": "2026-01-10T10:00:00Z"
    }
  ],
  "total": 1
}
```

---

### 2.3 获取投标详情

> 获取指定投标的详细信息。

#### 请求格式

```http
GET /api/v1/bids/{bid_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `bid_id` | integer | 是 | 投标 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": {...}
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 投标详情对象 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/bids/12345" \
     -H "X-API-Key: your_api_key"
```

---

### 2.4 更新投标

> 更新现有投标的金额、周期或描述。

#### 请求格式

```http
PUT /api/v1/bids/{bid_id}
```

> **注意**: 当前 SDK 版本不支持更新投标，返回 501。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `bid_id` | integer | 是 | 投标 ID |

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `amount` | number | 否 | 新投标金额 |
| `period` | integer | 否 | 新完成周期 |
| `description` | string | 否 | 新提案内容 |

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 更新后的投标对象 |

#### 请求示例

```bash
curl -X PUT "http://localhost:8000/api/v1/bids/12345" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{"amount": 200, "period": 10}'
```

---

### 2.5 撤销投标

> 撤回（删除）已提交的投标。

#### 请求格式

```http
DELETE /api/v1/bids/{bid_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `bid_id` | integer | 是 | 投标 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "message": "string"
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data.message` | string | 操作结果消息 |

#### 请求示例

```bash
curl -X DELETE "http://localhost:8000/api/v1/bids/12345" \
     -H "X-API-Key: your_api_key"
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "message": "Bid successfully retracted"
  }
}
```

---

## 3. Milestones (里程碑)

### 3.1 创建里程碑

> 为指定项目创建里程碑支付请求。

#### 请求格式

```http
POST /api/v1/milestones
```

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_id` | integer | 是 | 项目 ID |
| `amount` | number | 是 | 里程碑金额 |
| `description` | string | 是 | 里程碑描述 |
| `due_date` | string | 否 | 截止日期 (ISO格式) |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "milestone_id": 0,
    "project_id": 0,
    "amount": 0,
    "status": "string"
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 里程碑创建结果 |
| `data.milestone_id` | integer | 里程碑 ID |
| `data.project_id` | integer | 项目 ID |
| `data.amount` | number | 里程碑金额 |
| `data.status` | string | 状态: `created` |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/milestones" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{"project_id": 38000123, "amount": 500, "description": "Phase 1 completion"}'
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "milestone_id": 67890,
    "project_id": 38000123,
    "amount": 500.00,
    "status": "created"
  }
}
```

---

### 3.2 获取项目里程碑

> 获取指定项目的所有里程碑。

#### 请求格式

```http
GET /api/v1/milestones/{project_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_id` | integer | 是 | Freelancer 项目 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": [...]
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | array | 里程碑列表 |
| `data[].id` | integer | 里程碑 ID |
| `data[].project_id` | integer | 项目 ID |
| `data[].amount` | number | 金额 |
| `data[].description` | string | 描述 |
| `data[].status` | string | 状态 |
| `data[].due_date` | string | 截止日期 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/milestones/38000123" \
     -H "X-API-Key: your_api_key"
```

---

### 3.3 接受里程碑

> 接受客户创建的里程碑支付请求。

#### 请求格式

```http
POST /api/v1/milestones/{milestone_id}/accept
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `milestone_id` | integer | 是 | 里程碑 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "message": "string",
    "status": "string"
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data.message` | string | 操作消息 |
| `data.status` | string | 新状态: `accepted` |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/milestones/67890/accept" \
     -H "X-API-Key: your_api_key"
```

---

### 3.4 释放里程碑付款

> 为已完成的里程碑释放付款。

#### 请求格式

```http
POST /api/v1/milestones/{milestone_id}/release
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `milestone_id` | integer | 是 | 里程碑 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "message": "string",
    "status": "string"
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data.message` | string | 操作消息 |
| `data.status` | string | 新状态: `paid` |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/milestones/67890/release" \
     -H "X-API-Key: your_api_key"
```

---

## 4. Messages (消息)

### 4.1 发送消息

> 向指定线程或用户发送消息。

#### 请求格式

```http
POST /api/v1/messages
```

#### 请求体 (二选一)

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `thread_id` | integer | 否* | 消息线程 ID |
| `to_user_id` | integer | 否* | 收件人用户 ID |
| `message` | string | 是 | 消息内容 |

> `thread_id` 和 `to_user_id` 必须提供一个。

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "message_id": 0,
    "thread_id": 0,
    "sent_at": "string"
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data.message_id` | integer | 消息 ID |
| `data.thread_id` | integer | 线程 ID |
| `data.sent_at` | string | 发送时间 |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/messages" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{"thread_id": 12345, "message": "Hello, I have a question..."}'
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "message_id": 54321,
    "thread_id": 12345,
    "sent_at": "2026-01-10T10:00:00"
  }
}
```

---

### 4.2 同步消息

> 从 Freelancer 同步最新消息到本地数据库。

#### 请求格式

```http
POST /api/v1/messages/sync
```

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "new_messages_count": 0,
    "updated_threads_count": 0
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data.new_messages_count` | integer | 新消息数量 |
| `data.updated_threads_count` | integer | 更新的线程数量 |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/messages/sync" \
     -H "X-API-Key: your_api_key"
```

---

### 4.3 获取未读消息

> 获取所有包含未读消息的线程及其最新未读消息。

#### 请求格式

```http
GET /api/v1/messages/unread
```

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:----:|--------|------|
| `limit` | integer | 否 | 20 | 返回数量 (1-100) |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "threads": [...],
    "total": 0
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data.threads` | array | 未读线程列表 |
| `data.total` | integer | 线程总数 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/messages/unread?limit=10" \
     -H "X-API-Key: your_api_key"
```

---

### 4.4 获取消息线程列表

> 获取消息线程列表。

#### 请求格式

```http
GET /api/v1/messages/threads
```

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:----:|--------|------|
| `project_id` | integer | 否 | - | 筛选项目 ID |
| `unread_only` | boolean | 否 | false | 仅未读 |
| `limit` | integer | 否 | 50 | 返回数量 (1-200) |
| `offset` | integer | 否 | 0 | 分页偏移 |

#### 响应格式

```json
{
  "status": "success",
  "data": [...],
  "total": 0
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | array | 线程列表 |
| `total` | integer | 总数量 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/messages/threads?unread_only=true" \
     -H "X-API-Key: your_api_key"
```

---

### 4.5 获取线程消息

> 获取指定线程的所有消息。

#### 请求格式

```http
GET /api/v1/messages/{thread_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:----:|--------|------|
| `thread_id` | integer | 是 | - | 消息线程 ID |
| `limit` | integer | 否 | 50 | 返回数量 (1-200) |
| `offset` | integer | 否 | 0 | 分页偏移 |

#### 响应格式

```json
{
  "status": "success",
  "data": [...],
  "total": 0
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | array | 消息列表 |
| `total` | integer | 消息总数 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/messages/12345?limit=20" \
     -H "X-API-Key: your_api_key"
```

---

### 4.6 标记线程为已读

> 将指定线程标记为已读。

#### 请求格式

```http
PUT /api/v1/messages/{thread_id}/read
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `thread_id` | integer | 是 | 消息线程 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "message": "string"
  }
}
```

#### 请求示例

```bash
curl -X PUT "http://localhost:8000/api/v1/messages/12345/read" \
     -H "X-API-Key: your_api_key"
```

---

### 4.7 上传附件

> 向消息线程上传附件文件。

#### 请求格式

```http
POST /api/v1/messages/upload
```

#### 请求参数 (Query)

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `thread_id` | integer | 是 | 目标消息线程 ID |

#### 请求体 (Form Data)

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `file` | File | 是 | 要上传的文件 |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "attachment_url": "string",
    "thread_id": 0
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data.attachment_url` | string | 附件 URL |
| `data.thread_id` | integer | 线程 ID |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/messages/upload?thread_id=12345" \
     -H "X-API-Key: your_api_key" \
     -F "file=@/path/to/document.pdf"
```

---

### 4.8 Telegram 回调处理

> 处理来自 Telegram inline 按钮的回调请求。

#### 请求格式

```http
POST /api/v1/messages/telegram/callback
```

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `callback_data` | string | 是 | 回调数据 |

**回调格式**: `action:thread_id:reply_id`

| Action | 说明 |
|--------|------|
| `send` | 发送选中的 AI 回复 |
| `ignore` | 忽略该消息线程 |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "message": "string"
  }
}
```

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/messages/telegram/callback" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{"callback_data": "send:12345:1"}'
```

---

## 5. Kickoff (项目启动)

### 5.1 触发项目启动

> 触发项目启动自动化流程（创建仓库、协作空间等）。

#### 请求格式

```http
POST /api/v1/kickoff/trigger
```

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_freelancer_id` | integer | 是 | Freelancer 项目 ID |
| `bid_id` | integer | 是 | 中标 ID |

#### 响应格式

```json
{
  "success": true,
  "project_id": 0,
  "kickoff_id": 0,
  "template_type": "string",
  "results": {
    "repo_created": true,
    "repo_url": "string",
    "collab_space_created": true,
    "collab_space_url": "string"
  },
  "error": "string",
  "existing_kickoff": {...}
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 是否成功 |
| `project_id` | integer | 项目 ID |
| `kickoff_id` | integer | 启动记录 ID |
| `template_type` | string | 使用的模板类型 |
| `results` | object | 执行结果 |
| `results.repo_created` | boolean | 仓库是否创建 |
| `results.repo_url` | string | 仓库 URL |
| `results.collab_space_created` | boolean | 协作空间是否创建 |
| `results.collab_space_url` | string | 协作空间 URL |
| `error` | string | 错误信息（失败时） |
| `existing_kickoff` | object | 已存在的启动记录 |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/kickoff/trigger" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{"project_freelancer_id": 38000123, "bid_id": 12345}'
```

---

### 5.2 获取启动状态

> 获取项目的启动状态。

#### 请求格式

```http
GET /api/v1/kickoff/{project_freelancer_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_freelancer_id` | integer | 是 | Freelancer 项目 ID |

#### 响应格式

```json
{
  "id": 0,
  "project_id": 0,
  "repo_url": "string",
  "repo_status": "string",
  "collab_space_url": "string",
  "collab_status": "string",
  "template_type": "string",
  "notification_sent": true,
  "triggered_at": "string",
  "completed_at": "string"
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 启动记录 ID |
| `project_id` | integer | 项目 ID |
| `repo_url` | string | 仓库 URL |
| `repo_status` | string | 仓库状态 |
| `collab_space_url` | string | 协作空间 URL |
| `collab_status` | string | 协作空间状态 |
| `template_type` | string | 模板类型 |
| `notification_sent` | boolean | 是否已发送通知 |
| `triggered_at` | string | 触发时间 |
| `completed_at` | string | 完成时间 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/kickoff/38000123" \
     -H "X-API-Key: your_api_key"
```

---

### 5.3 列出最近的启动记录

> 列出最近的项目启动记录。

#### 请求格式

```http
GET /api/v1/kickoff/list/recent
```

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:----:|--------|------|
| `limit` | integer | 否 | 10 | 返回数量 (最大 100) |

#### 响应格式

```json
[
  {...}
]
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `[]` | array | 启动记录列表 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/kickoff/list/recent?limit=10" \
     -H "X-API-Key: your_api_key"
```

---

### 5.4 检查并触发启动

> 检查项目状态，如果已中标则自动触发启动。

#### 请求格式

```http
POST /api/v1/kickoff/check/{project_freelancer_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_freelancer_id` | integer | 是 | Freelancer 项目 ID |

#### 请求参数 (Query)

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `bid_id` | integer | 否 | 中标 ID |

#### 响应格式

```json
{
  "success": true,
  "action": "string",
  "message": "string",
  "project_status": "string",
  ...
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 是否成功 |
| `action` | string | 执行的操作: `none` / `triggered` |
| `message` | string | 状态消息 |
| `project_status` | string | 项目状态 |
| `...` | - | 其他启动结果字段 |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/kickoff/check/38000123" \
     -H "X-API-Key: your_api_key"
```

---

### 5.5 获取可用模板列表

> 获取可用的项目启动模板。

#### 请求格式

```http
GET /api/v1/kickoff/templates
```

#### 响应格式

```json
{
  "templates": [
    {
      "id": "string",
      "description": "string",
      "files": [...]
    }
  ]
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `templates` | array | 模板列表 |
| `templates[].id` | string | 模板 ID |
| `templates[].description` | string | 模板描述 |
| `templates[].files` | array | 包含的文件列表 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/kickoff/templates" \
     -H "X-API-Key: your_api_key"
```

#### 响应示例

```json
{
  "templates": [
    {
      "id": "web_app",
      "description": "Web Application with FastAPI backend",
      "files": ["main.py", "requirements.txt", "Dockerfile"]
    },
    {
      "id": "data_pipeline",
      "description": "Data Pipeline with scheduling",
      "files": ["pipeline.py", "config.yaml", "dags/"]
    }
  ]
}
```

---

### 5.6 删除启动记录

> 删除启动记录，允许重新触发。

#### 请求格式

```http
DELETE /api/v1/kickoff/{project_freelancer_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_freelancer_id` | integer | 是 | Freelancer 项目 ID |

#### 响应

HTTP 204 No Content

#### 请求示例

```bash
curl -X DELETE "http://localhost:8000/api/v1/kickoff/38000123" \
     -H "X-API-Key: your_api_key"
```

---

## 6. AI Replies (AI回复)

### 6.1 生成 AI 回复候选项

> 对话上下文生成 3 种语气的 AI 回复候选项。

#### 请求格式

```http
POST /api/v1/ai/replies
```

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `thread_id` | integer | 是 | Freelancer 线程 ID |
| `context_messages` | array | 否 | 对话上下文消息列表 |

#### 响应格式

```json
{
  "thread_id": 0,
  "replies": [
    {
      "id": 0,
      "tone": "string",
      "text": "string"
    }
  ]
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `thread_id` | integer | 线程 ID |
| `replies` | array | 回复候选项列表 |
| `replies[].id` | integer | 回复 ID |
| `replies[].tone` | string | 语气: `professional` / `enthusiastic` / `concise` |
| `replies[].text` | string | 回复内容 |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/ai/replies" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{"thread_id": 12345, "context_messages": [{"role": "client", "message": "Hello..."}]}'
```

#### 响应示例

```json
{
  "thread_id": 12345,
  "replies": [
    {
      "id": 1,
      "tone": "professional",
      "text": "Thank you for reaching out..."
    },
    {
      "id": 2,
      "tone": "enthusiastic",
      "text": "Hi! I'd love to work on this..."
    },
    {
      "id": 3,
      "tone": "concise",
      "text": "Yes, I'm available."
    }
  ]
}
```

---

## 7. Client Risk (客户风控)

### 7.1 获取客户信息

> 获取客户（雇主）基本信息。

#### 请求格式

```http
GET /api/v1/client-risk/{user_id}
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `user_id` | integer | 是 | Freelancer 用户 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "user_id": 0,
    "payment_verified": true,
    "deposit_made": true,
    "country": "string",
    "country_name": "string",
    "jobs_posted": 0,
    "jobs_hired": 0,
    "hire_rate": 0,
    "rating": 0,
    "review_count": 0
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 客户信息对象 |
| `data.user_id` | integer | 用户 ID |
| `data.payment_verified` | boolean | 支付是否验证 |
| `data.deposit_made` | boolean | 是否有押金 |
| `data.country` | string | 国家代码 |
| `data.country_name` | string | 国家名称 |
| `data.jobs_posted` | integer | 发布的工作数 |
| `data.jobs_hired` | integer | 雇佣的工作数 |
| `data.hire_rate` | number | 雇佣率 |
| `data.rating` | number | 评分 |
| `data.review_count` | integer | 评价数量 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/client-risk/1234567" \
     -H "X-API-Key: your_api_key"
```

---

### 7.2 获取客户评价

> 获取客户的历史评价。

#### 请求格式

```http
GET /api/v1/client-risk/{user_id}/reviews
```

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `user_id` | integer | 是 | Freelancer 用户 ID |

#### 响应格式

```json
{
  "status": "success",
  "data": [...]
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | array | 评价列表 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/client-risk/1234567/reviews" \
     -H "X-API-Key: your_api_key"
```

---

## 8. System (系统)

### 8.1 健康检查

> 检查服务运行状态。

#### 请求格式

```http
GET /health
```

#### 响应格式

```json
{
  "status": "string",
  "version": "string",
  "service": "string"
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态: `healthy` |
| `version` | string | 服务版本 |
| `service` | string | 服务名称 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/health"
```

#### 响应示例

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "service": "Freelancer Python API"
}
```

---

### 8.2 统计信息

> 查看本地数据库中的统计数据。

#### 请求格式

```http
GET /api/v1/stats
```

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "total_projects": 0,
    "total_bids": 0,
    "total_milestones": 0,
    "version": "string"
  }
}
```

#### 响应参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态 |
| `data` | object | 统计数据 |
| `data.total_projects` | integer | 项目总数 |
| `data.total_bids` | integer | 投标总数 |
| `data.total_milestones` | integer | 里程碑总数 |
| `data.version` | string | 服务版本 |

#### 请求示例

```bash
curl -X GET "http://localhost:8000/api/v1/stats" \
     -H "X-API-Key: your_api_key"
```

---

## 9. Freelancer 官方 API

> 本节记录 Freelancer.com 官方 API 的封装情况。

### 9.1 SDK 封装方法

| 功能 | Freelancer SDK | 本地封装方法 |
|------|----------------|-------------|
| 搜索项目 | `search_projects()` | `freelancer_client.search_projects()` |
| 获取项目详情 | `get_project_by_id()` | `freelancer_client.get_project()` |
| 创建投标 | `place_project_bid()` | `freelancer_client.create_bid()` |
| 撤销投标 | `retract_project_bid()` | `freelancer_client.retract_bid()` |
| 创建里程碑 | `create_milestone_payment()` | `freelancer_client.create_milestone()` |
| 接受里程碑 | `accept_milestone_request()` | `freelancer_client.accept_milestone()` |
| 释放里程碑 | `release_milestone_payment()` | `freelancer_client.release_milestone()` |
| 发送消息 | `post_message()` | `freelancer_client.send_message()` |
| 上传附件 | `post_attachment()` | `freelancer_client.upload_attachment()` |
| 获取消息 | `get_messages()` | `freelancer_client.get_messages()` |
| 获取线程 | `get_threads()` | `freelancer_client.get_threads()` |

### 9.2 官方文档链接

| API | 文档链接 |
|-----|---------|
| Projects | https://developers.freelancer.com/docs/projects |
| Bids | https://developers.freelancer.com/docs/bids |
| Milestones | https://developers.freelancer.com/docs/milestones |
| Messages | https://developers.freelancer.com/docs/messages |
| Users | https://developers.freelancer.com/docs/users |

---

## 10. 认证与授权

### 10.1 Python Service 认证

所有 Python Service API 端点需要通过 `X-API-Key` Header 进行认证：

```http
X-API-Key: replace_with_secure_random_key
```

### 10.2 Freelancer API 认证

```python
from freelancersdk.session import Session

session = Session(
    oauth_token=settings.FREELANCER_OAUTH_TOKEN,
    url="https://www.freelancer.com"
)
```

### 10.3 环境变量配置

| 变量名 | 说明 |
|--------|------|
| `PYTHON_API_KEY` | Python Service API 密钥 |
| `FREELANCER_OAUTH_TOKEN` | Freelancer OAuth Token |
| `ANTHROPIC_API_KEY` | Anthropic Claude API 密钥 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |

---

## 11. 错误处理

### 11.1 错误响应格式

```json
{
  "detail": "Error message description"
}
```

### 11.2 HTTP 状态码

| 状态码 | 说明 | 处理方式 |
|--------|------|----------|
| 200 | 成功 | 返回业务数据 |
| 400 | 请求参数错误 | 检查请求参数 |
| 401 | 认证失败 | 检查 API Key |
| 404 | 资源未找到 | 检查资源 ID |
| 429 | 速率限制 | 等待后重试 |
| 500 | 服务器错误 | 联系管理员 |
| 501 | 不支持 | 接口未实现 |
| 502 | 上游服务错误 | 检查外部 API |

### 11.3 自定义错误类

```python
class FreelancerAPIError(Exception):
    def __init__(self, message: str, status_code: int = None, retry_after: int = None):
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
```

---

## 12. 速率限制

### 12.1 限流策略

| 策略 | 值 |
|------|-----|
| 每分钟请求数 | 60 |
| 缓存 TTL | 600 秒 |

### 12.2 429 处理

```json
{
  "detail": "Rate limited",
  "retry_after": 30
}
```

---

## 附录 A: 端点速查表

| 功能 | 端点 | 方法 |
|------|------|------|
| 搜索项目 | `/api/v1/projects/search` | GET |
| 项目详情 | `/api/v1/projects/{id}` | GET |
| 项目评分 | `/api/v1/projects/{id}/score` | POST |
| 更新AI分析 | `/api/v1/projects/{id}` | PUT |
| 创建投标 | `/api/v1/bids` | POST |
| 我的投标 | `/api/v1/bids/user` | GET |
| 撤销投标 | `/api/v1/bids/{id}` | DELETE |
| 创建里程碑 | `/api/v1/milestones` | POST |
| 接受里程碑 | `/api/v1/milestones/{id}/accept` | POST |
| 释放里程碑 | `/api/v1/milestones/{id}/release` | POST |
| 发送消息 | `/api/v1/messages` | POST |
| 同步消息 | `/api/v1/messages/sync` | POST |
| AI回复生成 | `/api/v1/ai/replies` | POST |
| 触发启动 | `/api/v1/kickoff/trigger` | POST |
| 健康检查 | `/health` | GET |
| 统计信息 | `/api/v1/stats` | GET |

---

## 附录 B: 统一响应包装

所有 API 端点使用统一的响应格式：

```json
{
  "status": "success",
  "data": {...} | [...],
  "total": 0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `success` 或 `error` |
| `data` | object/array | 业务数据 |
| `total` | integer | 总数量（分页时） |
