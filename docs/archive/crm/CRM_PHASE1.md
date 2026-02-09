# Freelancer CRM - Phase 1 实现文档

## 概述

实现了 Freelancer 平台的全生命周期 CRM 功能，包括消息监听、AI 辅助回复、Telegram 推送与回调处理。

---

## 架构图

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Freelancer    │     │   Python API    │     │      n8n        │
│     API         │────▶│    Service      │────▶│    Workflow     │
│ (0.1/messages) │     │  (FastAPI)      │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
                                                   ┌──────────────┐
                                                   │ Telegram Bot │
                                                   │ (推送到用户)  │
                                                   └──────┬───────┘
                                                          │
                                                          ▼
                                                   ┌──────────────┐
                                                   │   n8n Webhook│
                                                   │  (用户点击按钮)│
                                                   └──────┬───────┘
                                                          │
                                                          ▼
                                                   ┌──────────────┐
                                                   │ Python API   │
                                                   │ (发送回复)    │
                                                   └──────────────┘
```

---

## 新增文件清单

### Codex 实现

| 文件 | 功能 |
|------|------|
| `python_service/utils/redaction.py` | 敏感信息脱敏（邮箱/电话/URL/信用卡号 → `<REDACTED>`） |
| `python_service/services/llm_client.py` | OpenAI LLM 客户端封装（gpt-4o-mini） |
| `python_service/api/ai_replies.py` | AI 回复生成端点 `POST /api/v1/ai/replies` |
| `python_service/tests/test_ai_replies_endpoint.py` | 单元测试（脱敏验证） |
| `python_service/tests/test_redaction.py` | 脱敏工具单元测试 |

### Gemini 实现

| 文件 | 功能 |
|------|------|
| `python_service/services/freelancer_client.py` (增强) | 新增 `get_threads()` 方法 |
| `python_service/api/messages.py` (增强) | 新增 sync/unread/telegram/callback 端点 |
| `python_service/database/models.py` (增强) | 新增 `AIReplyOption` 模型 |
| `workflows/message_crm_polling.json` | 消息监控 workflow (Cron 5分钟) |
| `workflows/callback_handler_workflow.json` | Telegram 回调处理 workflow |

---

## API 端点说明

### 消息同步

#### POST `/api/v1/messages/sync`

同步 Freelancer 最新消息到本地数据库。

**请求头：**
- `X-API-Key`: API 密钥

**响应体：**
```json
{
  "status": "success",
  "data": {
    "new_messages_count": 5,
    "updated_threads_count": 2
  }
}
```

**去重逻辑：**
- 基于 `(thread_id, message_content_hash)` 组合去重
- 仅插入新消息到 DB
- 更新 `message_threads` 表的 `last_message_time` 和 `unread_count`

---

### 获取未读消息

#### GET `/api/v1/messages/unread`

获取所有未读线程及其最新上下文。

**查询参数：**
- `limit`: 返回数量 (1-100, 默认: 20)

**响应体：**
```json
{
  "status": "success",
  "data": {
    "threads": [
      {
        "thread_id": 12345,
        "project_id": 67890,
        "unread_count": 2,
        "last_message_time": "2024-01-07 10:30:00",
        "messages": [...]
      }
    ],
    "total": 5
  }
}
```

---

### AI 回复生成

#### POST `/api/v1/ai/replies`

生成 3 种语气的 AI 回复候选项。

**请求头：**
- `X-API-Key`: API 密钥

**请求体：**
```json
{
  "thread_id": 12345,
  "context_messages": [
    {"role": "client", "message": "Hello, email me at test@example.com"},
    {"role": "me", "message": "Sure, my phone is +86 138 0013 8000"}
  ]
}
```

**响应体：**
```json
{
  "status": "success",
  "thread_id": 12345,
  "replies": [
    {
      "id": 1,
      "tone": "professional",
      "text": "Thank you for reaching out. I'd be happy to discuss..."
    },
    {
      "id": 2,
      "tone": "enthusiastic",
      "text": "Thanks for your message! I'm excited to help..."
    },
    {
      "id": 3,
      "tone": "concise",
      "text": "Thanks! Let's discuss the details..."
    }
  ]
}
```

**数据脱敏：**
- 调用 LLM 前对 `context_messages` 全量递归脱敏
- 支持脱敏：邮箱、电话、URL、信用卡号
- 脱敏后信息写入 `audit_logs` 表

---

### Telegram 回调处理

#### POST `/api/v1/messages/telegram/callback`

处理来自 Telegram 的按钮回调。

**请求头：**
- `X-API-Key`: API 密钥

**请求体：**
```json
{
  "callback_data": "send:12345:1"  // 或 "ignore:12345"
}
```

**Callback Data 格式：**
- `send:{thread_id}:{reply_id}` → 发送对应语气的回复
- `ignore:{thread_id}` → 标记已读，忽略

**响应体：**
```json
{
  "status": "success",
  "data": {
    "message": "Reply sent successfully"
  }
}
```

---

## 数据库变更

### 新增表：`ai_reply_options`

```sql
CREATE TABLE ai_reply_options (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL,
    tone VARCHAR(20) NOT NULL,  -- professional / enthusiastic / concise
    text TEXT NOT NULL,
    provider VARCHAR(50),  -- openai, anthropic, etc.
    model VARCHAR(100),  -- gpt-4o-mini, claude-3-5-sonnet, etc.
    context_messages_masked TEXT,  -- 脱敏后的上下文快照
    created_at DATETIME
);

ALTER TABLE ai_reply_options ADD FOREIGN KEY (thread_id) REFERENCES message_threads(freelancer_thread_id);
```

---

## 环境变量配置

在 `.env` 文件中新增以下配置：

```bash
# LLM 配置
LLM_PROVIDER=openai
LLM_API_KEY=your-openai-api-key
LLM_MODEL=gpt-4o-mini

# Telegram 配置（n8n workflow 使用）
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
```

---

## 依赖更新

在 `python_service/requirements.txt` 中新增：

```txt
openai>=1.0.0
```

---

## n8n Workflow 配置

### 1. 导入 Workflows

1. 登录 n8n: `http://localhost:5678`
2. 点击 "Import from File"
3. 分别导入以下文件：
   - `workflows/message_crm_polling.json`
   - `workflows/callback_handler_workflow.json`

### 2. Workflow: `message_crm_polling`

**功能：** 每 5 分钟轮询未读消息，生成 AI 回复并推送到 Telegram

**节点流程：**
```
Cron Trigger (5分钟)
  → Sync API (/api/v1/messages/sync)
  → Get Unread API (/api/v1/messages/unread)
  → Split Threads
  → Generate AI Replies (/api/v1/ai/replies)
  → Send Telegram (Inline Buttons)
```

**Telegram 按钮结构：**
```
┌─────────────────────────────────────┐
│  👔 专业   |   🔥 热情   │
├─────────────────────────────────────┤
│  ⚡ 简洁   |   🔕 忽略   │
└─────────────────────────────────────┘
```

**Callback Data 格式：**
- `send:{thread_id}:{reply_id}` → 发送对应回复
- `ignore:{thread_id}` → 标记已读

### 3. Workflow: `callback_handler_workflow`

**功能：** 接收 Telegram 按钮回调，调用 Python API 执行操作

**节点流程：**
```
Telegram Webhook
  → Call Callback API (/api/v1/messages/telegram/callback)
  → Update Telegram Message (处理成功提示)
```

---

## 单元测试

### 运行测试

```bash
cd /home/yuanzhi/Develop/automation/freelancer_automation
PYTHONPATH=python_service python -m unittest tests.test_ai_replies_endpoint
PYTHONPATH=python_service python -m unittest tests.test_redaction
```

### 测试结果

```
OK
----------------------------------------------------------------------
Ran 4 tests in 0.003s
```

**测试覆盖：**
- ✅ 邮箱脱敏
- ✅ 电话脱敏
- ✅ URL 脱敏
- ✅ 信用卡号脱敏（Luhn 校验）
- ✅ AI 回复生成与脱敏验证

---

## 部署步骤

### 1. 更新配置

```bash
# 在项目根目录的 .env 文件中添加
echo "LLM_PROVIDER=openai" >> .env
echo "LLM_API_KEY=your-key-here" >> .env
echo "LLM_MODEL=gpt-4o-mini" >> .env
```

### 2. 安装依赖

```bash
cd python_service
pip install -r requirements.txt
```

### 3. 重建并启动服务

```bash
docker-compose down
docker-compose up -d --build
```

### 4. 导入 n8n Workflows

1. 登录 n8n: `http://localhost:5678`
2. 导入 `workflows/message_crm_polling.json`
3. 导入 `workflows/callback_handler_workflow.json`
4. 激活两个 workflow

### 5. 配置 Telegram Webhook（可选）

如需 Telegram Bot 自动接收回调，需要配置：
1. 在 n8n 中设置 Telegram 节点的 Webhook URL
2. 或使用 Telegram Bot API 设置 webhook

---

## 数据流说明

### 同步阶段
```
Freelancer API
  → Python Service (/api/v1/messages/sync)
  → 去重逻辑
  → messages 表
  → message_threads 表 (更新 unread_count)
```

### 提醒阶段
```
Python Service (/api/v1/messages/unread)
  → n8n Workflow
  → AI Replies (/api/v1/ai/replies)
  → 脱敏处理
  → OpenAI LLM
  → Telegram Bot (推送 4 个按钮)
```

### 响应阶段
```
用户点击 Telegram 按钮
  → n8n Webhook (callback_handler_workflow)
  → Python Service (/api/v1/messages/telegram/callback)
  → 查询 ai_reply_options 表
  → Freelancer API (发送消息)
  → 更新 Telegram 消息状态
```

---

## 安全与隐私

### 数据脱敏

| 敏感类型 | 脱敏规则 |
|----------|----------|
| 邮箱 | `a@b.com` → `<REDACTED>` |
| 电话 | `+86 138 0013 8000` → `<REDACTED>` (8-15 位) |
| URL | `https://example.com` → `<REDACTED>` |
| 信用卡号 | `4111 1111 1111 1111` → `<REDACTED>` (Luhn 校验) |

### 审计日志

所有 AI 回复生成操作都会记录到 `audit_logs` 表：
- 请求：脱敏后的 `context_messages`
- 响应：生成的回复选项
- 状态：`success` 或 `error`
- 错误信息（如有）

---

## 故障排查

### 常见问题

1. **测试失败（ModuleNotFoundError: No module named 'freelancersdk'）**
   - 原因：本地测试环境未安装依赖
   - 解决：在 Docker 容器内运行测试，或安装依赖

2. **LLM 调用失败（500 错误）**
   - 检查 `LLM_API_KEY` 是否正确
   - 检查 `LLM_MODEL` 是否可用
   - 查看 `audit_logs` 表的错误信息

3. **Telegram 按钮无响应**
   - 检查 n8n workflow 是否激活
   - 检查 Webhook URL 配置
   - 查看 n8n workflow 执行日志

---

## 下一步

1. **生产环境测试**：使用真实 Freelancer API Token 和 OpenAI Key 进行完整测试
2. **性能优化**：根据实际使用情况调整轮询间隔
3. **功能扩展**：
   - 支持更多 LLM 提供商
   - 添加回复模板管理
   - 实现客户分级与 SLA 统计
