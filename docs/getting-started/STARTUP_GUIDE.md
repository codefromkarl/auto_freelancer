# 快速启动指南 (Startup Guide)

本指南将帮助你从零开始配置 Freelancer Automation 系统的运行环境。

---

## 1. 核心账号配置

系统核心依赖 **Freelancer API** 进行数据抓取和投标，以及 **LLM** 进行评分和内容生成。请务必先获取以下凭证。

### 1.1 获取 Freelancer API 凭证

我们需要 `FREELANCER_OAUTH_TOKEN` 和 `FREELANCER_USER_ID`。

**步骤 A: 获取 API Token**
1. 登录 [Freelancer Developer Portal](https://www.freelancer.com/api-projects)。
2. 点击 **Create New Project** (如果已有可跳过)。
3. 在项目列表中点击你的项目名称。
4. 在左侧菜单或页面下方找到 **Advanced Options**。
5. 点击 **Create Access Token**。
6. 选择所有权限（Scopes），尤其是 `bidding`, `projects`, `messaging`, `users` 相关权限。
7. 生成后，复制 Token 字符串，填入 `.env` 文件的 `FREELANCER_OAUTH_TOKEN`。

**步骤 B: 获取 User ID**
1. 登录 Freelancer 网站。
2. 点击右上角头像，进入 **View Profile**。
3. 观察浏览器地址栏，URL 格式通常为 `https://www.freelancer.com/u/yourusername`。
4. 如果 URL 中没有数字 ID，可以按 `F12` 打开开发者工具，刷新页面，在 `Network` 标签页过滤 `api` 请求，通常在响应中能找到你的 `id`。
5. **最简单的方法**：运行我们的环境检查脚本，它会尝试自动查询你的 ID：
   ```bash
   # 配置好 TOKEN 后运行
   python scripts/manual_pipeline/01_check_env.py
   ```
6. 将 ID 填入 `.env` 文件的 `FREELANCER_USER_ID`。

### 1.2 配置 LLM (DeepSeek / OpenAI / Anthropic)

系统默认推荐使用 **DeepSeek** (性价比高) 或 **Claude 3.5 Sonnet** (生成质量最好)。

在 `.env` 中修改：
```bash
# 推荐配置 (DeepSeek)
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxxxxxxxxx  # 你的 DeepSeek API Key
LLM_MODEL=deepseek-chat

# 备选配置 (Anthropic)
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
# ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

### 1.3 配置 Telegram 通知 (可选)

如果你希望手机接收高分项目通知：

1. 在 Telegram 中搜索 `@BotFather`。
2. 发送 `/newbot` 创建机器人，获取 **Token**。
3. 搜索 `@userinfobot` 获取你自己的 **Chat ID**。
4. 在 `.env` 中填入：
   ```bash
   TELEGRAM_BOT_TOKEN=123456789:ABCDefGhiJklMnoPqrStuVwxYz
   TELEGRAM_CHAT_ID=987654321
   ```

---

## 2. 环境安装

### 2.1 Python 后端环境
建议使用 Conda 或 venv。

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装核心依赖
pip install -r python_service/requirements.txt
```

### 2.2 TypeScript 前端环境 (可选)
如果你想使用可视化界面：

```bash
cd typescript
npm install
# 启动开发服务器
npm run dev
```

---

## 3. 验证安装

运行检查脚本，它会测试数据库连接、API 连通性和 LLM 可用性。

```bash
python scripts/manual_pipeline/01_check_env.py
```

如果看到 `✅ Environment check passed!`，说明配置成功。

---

## 4. 下一步

前往 [手动流水线执行指南](../workflows/MANUAL_WORKFLOW.md) 查看如何运行自动化任务。