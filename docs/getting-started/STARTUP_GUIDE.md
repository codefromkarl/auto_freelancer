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

### 1.3 配置 QQ Bot 通知与审批

AppID/AppSecret 放在项目 `.env.qqbot`（Git 忽略、权限 0600），不要放进代码。运行 `.venv/bin/python scripts/manual_pipeline/run_qqbot.py --once-ready` 验证鉴权与 Gateway。

正常运行接收器后，在机器人私聊或群中发送 `身份`。将返回的接收对象和审批者 OpenID 写入本地配置：

```dotenv
QQ_BOT_TARGET_TYPE=c2c
QQ_BOT_TARGET_ID=接收对象OpenID
QQ_BOT_APPROVER_OPENIDS=审批者OpenID
```

机器人不会把第一位发消息的人自动授权为审批者。详细配置与签名回调见 [QQ Bot 接入指南](QQBOT_GUIDE.md)。

---

## 2. 环境安装

### 2.1 Python 后端环境
建议使用 Conda 或 venv。
当前固定依赖建议使用 Python 3.12；不要直接使用系统 Python 3.14 安装旧版 Pydantic。

```bash
# 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装核心依赖
pip install -r python_service/requirements.txt
```

### 2.2 TypeScript 前端环境 (可选)
如果你想使用可视化界面：

```bash
cd typescript
npm ci --ignore-scripts
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
