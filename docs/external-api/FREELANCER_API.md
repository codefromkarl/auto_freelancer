# Freelancer 官方 API 端点参考

> Freelancer.com Platform API v0.1
>
> **参考**: https://developers.freelancer.com/docs

---

## 目录

1. [Projects API](#1-projects-api)
2. [Bids API](#2-bids-api)
3. [Milestones API](#3-milestones-api)
4. [Messages API](#4-messages-api)
5. [Users API](#5-users-api)
6. [常见错误码](#6-常见错误码)

---

## 1. Projects API

### 1.1 获取活跃项目列表

```http
GET https://www.freelancer.com/api/projects/0.1/projects/active/
```

**查询参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `query` | string | 搜索关键词 |
| `jobs[]` | array | 技能 ID 列表 |
| `min_avg_price` | number | 最低平均预算 |
| `max_avg_price` | number | 最高平均预算 |
| `limit` | integer | 返回数量 |
| `offset` | integer | 分页偏移 |

**响应格式**:

```json
{
  "status": "success",
  "request_id": "string",
  "result": {
    "projects": [...],
    "users": {...}
  }
}
```

---

### 1.2 获取项目详情

```http
GET https://www.freelancer.com/api/projects/0.1/projects/{project_id}/
```

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `project_id` | integer | 项目 ID |

**查询参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `project_details[]` | array | 项目详情字段 |
| `user_details[]` | array | 用户详情字段 |

---

## 2. Bids API

### 2.1 创建投标

```http
POST https://www.freelancer.com/api/projects/0.1/bids/
```

**请求头**:

```http
Content-Type: application/json
Authorization: Bearer <OAUTH_TOKEN>
```

**请求体**:

```json
{
  "project_id": 123456,
  "bidder_id": 789012,
  "amount": 100.00,
  "period": 7,
  "milestone_percentage": 100,
  "description": "I can help you with..."
}
```

---

### 2.2 撤销投标

```http
DELETE https://www.freelancer.com/api/projects/0.1/bids/{bid_id}/
```

---

## 3. Milestones API

### 3.1 创建里程碑

```http
POST https://www.freelancer.com/api/milestones/0.1/milestones/
```

**请求体**:

```json
{
  "project_id": 123456,
  "bidder_id": 789012,
  "amount": 500.00,
  "description": "Phase 1 completion",
  "due_date": "2026-02-01"
}
```

---

### 3.2 接受里程碑

```http
POST https://www.freelancer.com/api/milestones/0.1/milestones/{milestone_id}/accept/
```

---

### 3.3 释放里程碑

```http
POST https://www.freelancer.com/api/milestones/0.1/milestones/{milestone_id}/release/
```

---

## 4. Messages API

### 4.1 发送消息

```http
POST https://www.freelancer.com/api/messages/0.1/messages/
```

**请求体**:

```json
{
  "thread_id": 12345,
  "message": "Hello, I have a question..."
}
```

---

### 4.2 获取消息列表

```http
GET https://www.freelancer.com/api/messages/0.1/messages/?thread_id=12345
```

---

### 4.3 获取线程列表

```http
GET https://www.freelancer.com/api/messages/0.1/###threads/
```

---

 4.4 上传附件

```http
POST https://www.freelancer.com/api/messages/0.1/attachments/
```

**Form Data**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `file` | File | 要上传的文件 |
| `thread_id` | integer | 目标线程 ID |

---

## 5. Users API

### 5.1 获取用户信息

```http
GET https://www.freelancer.com/api/users/0.1/users/{user_id}/
```

**响应字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 用户 ID |
| `username` | string | 用户名 |
| `display_name` | string | 显示名称 |
| `country` | object | 国家信息 |
| `payment_verified` | boolean | 支付验证状态 |
| `deposit_made` | boolean | 押金状态 |
| `rating` | number | 评分 |
| `jobs_posted` | integer | 发布的工作数 |
| `jobs_hired` | integer | 雇佣的工作数 |

---

### 5.2 获取用户评价

```http
GET https://www.freelancer.com/api/users/0.1/users/{user_id}/reviews/
```

---

## 6. 常见错误码

| 错误码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 403 | 禁止访问 |
| 404 | 资源不存在 |
| 429 | 速率限制 |
| 500 | 服务器错误 |

---

## 附录: SDK 方法映射

| SDK 方法 | 对应 API 端点 |
|----------|--------------|
| `search_projects()` | GET /projects/0.1/projects/active/ |
| `get_project_by_id()` | GET /projects/0.1/projects/{id}/ |
| `place_project_bid()` | POST /projects/0.1/bids/ |
| `retract_project_bid()` | DELETE /projects/0.1/bids/{id}/ |
| `create_milestone_payment()` | POST /milestones/0.1/milestones/ |
| `accept_milestone_request()` | POST /milestones/0.1/milestones/{id}/accept/ |
| `release_milestone_payment()` | POST /milestones/0.1/milestones/{id}/release/ |
| `post_message()` | POST /messages/0.1/messages/ |
| `post_attachment()` | POST /messages/0.1/attachments/ |
| `get_messages()` | GET /messages/0.1/messages/ |
| `get_threads()` | GET /messages/0.1/threads/ |
