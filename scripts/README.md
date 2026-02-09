# Scripts Directory

此目录包含了项目相关的各类 Python 脚本，按功能划分为以下子目录：

> 当前默认执行路径为 `manual_pipeline/`（手动流水线）。系统已移除 n8n 自动编排依赖，统一使用 Python 脚本执行抓取、评分、复核与投标流程。

## 目录结构

### 1. `legacy/` (归档脚本)
包含了项目早期开发阶段使用的抓取和评分脚本。这些脚本目前已被 `python_service` 与 `manual_pipeline/` 取代。
- `fetch_and_score_projects.py`: 基础抓取与评分。
- `fetch_projects_simple.py`: 简化版抓取。
- `fetch_projects_step1/2/3.py`: 分步抓取流程。

### 2. `utils/` (工具脚本)
包含用于日常维护、调试和数据处理的实用工具。
- `debug_budget.py`: 调试 API 预算数据。

### 3. `tests/` (测试脚本)
包含用于验证第三方服务（如 Telegram, Freelancer API）连通性和功能的小型测试脚本。
- `test_telegram.py`: 测试机器人基础连通性。
- `test_telegram_link.py`: 测试富文本消息和内联按钮。
- `test_freelancer_detail.py`: 测试 SDK 获取项目详情。

## 注意事项
- 所有 `legacy/` 目录下的脚本建议仅作为参考，不再建议在生产环境直接运行。
- 运行脚本前，请确保项目根目录下的 `.env` 文件已正确配置。
