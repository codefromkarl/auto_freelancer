# 手动流水线与自动化调度指南

本系统已从复杂的 n8n 工作流迁移至纯 Python 的执行架构。主要支持两种运行模式：**单次执行** (One-off) 和 **定时调度** (Scheduler)。

---

## 模式一：单次执行 (Run Until Bid)

适合手动触发、调试或每天定点执行一次。该脚本会串行执行：抓取 -> 评分 -> 生成报告。

**命令：**
```bash
python scripts/manual_pipeline/run_until_bid.py [参数]
```

**常用参数：**
- `--since-days N`: 抓取最近 N 天的项目（默认 3 天）。
- `--threshold N`: 评分阈值（0-10，默认 6.0）。
- `--output FILE`: 报告输出路径（默认 `review_report.txt`）。
- `--include-hourly`: **重要**。默认只抓取固定价格 (Fixed) 项目。加上此参数会包含按小时计费的项目。

**示例：**
```bash
# 抓取最近 1 天的 Fixed 项目，筛选 7 分以上的，并保存报告
python scripts/manual_pipeline/run_until_bid.py --since-days 1 --threshold 7.0
```

---

## 模式二：定时调度 (Scheduler)

适合长期后台运行。调度器会进入死循环，每隔指定时间（默认 30 分钟）执行一次完整的流程。

**功能特点：**
- 自动维护一个 `pipeline.lock` 文件，防止重复运行。
- 集成了 Telegram 通知，发现高分项目直接推送到手机。
- 自动跳过已处理的项目。

**命令：**
```bash
python scripts/manual_pipeline/scheduler.py
```

**配置建议：**
建议使用 `nohup` 或 `screen` 在后台运行：

```bash
# 后台运行，日志写入 scheduler.log
nohup python scripts/manual_pipeline/scheduler.py > logs/scheduler.log 2>&1 &
```

---

## 模式三：分步执行 (Debug)

如果你需要调试某个环节，可以直接运行子脚本：

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 1. 环境检查 | `01_check_env.py` | 验证 API Token 和 LLM 连接 |
| 2. 数据抓取 | `02_fetch.py` | 从 Freelancer API 拉取项目存入 SQLite |
| 3. AI 评分 | `03_score_concurrent.py` | 使用 LLM 并发评分 |
| 4. 人工复核 | `04_review.py` | 生成文本报告，列出 Top 项目 |
| 5. 投标执行 | `05_bid.py` | **慎用**。生成投标内容或实际提交 |

**投标脚本用法：**
```bash
# 仅生成投标内容预览（不提交）
python scripts/manual_pipeline/05_bid.py --project-id 12345678 --dry-run

# 实际提交投标（需要指定金额和工期）
python scripts/manual_pipeline/05_bid.py --project-id 12345678 --amount 50 --period 3
```

---

## 可视化界面 (Next.js)

虽然核心逻辑是 Python 脚本，但你可以启动 Next.js 前端来查看数据。

1. 确保 SQLite 数据库文件存在 (`python_service/data/freelancer.db`)。
2. 启动前端：
   ```bash
   cd typescript
   npm run dev
   ```
3. 访问 `http://localhost:3000/projects` 查看已抓取和评分的项目。

---

## 常见问题

**Q: 为什么抓不到项目？**
A: 检查 `.env` 中的 `USER_SKILLS` 配置。Freelancer API 是根据你的技能标签来搜索项目的。如果技能列表为空或不匹配，可能抓不到相关项目。

**Q: 评分很慢？**
A: `03_score_concurrent.py` 默认并发度为 5。受限于 LLM API 的速率限制（Rate Limit）。如果是 DeepSeek，速度通常较快；如果是 Zhipu 或 OpenAI，可能需要调整并发数。