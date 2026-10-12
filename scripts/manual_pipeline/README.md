# Manual Pipeline

本目录为当前唯一的执行路径（无 n8n 依赖）。

## 核心准则（强制）

- 宁可禁止提交，也不要提交不合格的数据（Fail-Closed）。
- 任何“中间草稿/回退模板”默认不得真实提交。
- 具体准则见：`docs/CORE_PRINCIPLES.md`

## 一键执行（到 bid 前）

`python scripts/manual_pipeline/run_until_bid.py --since-days 7 --allowed-statuses "open,active,open_for_bidding" --threshold 6.0 --output review_report.txt`

默认会执行：
- `01_check_env.py`
- `02_fetch.py`
- `02b_fetch_bids.py`
- `03_score_concurrent.py`
- `04_review.py`

说明：
- 默认会临时移除代理环境变量（`HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`），避免评分阶段 socks 代理兼容问题。
- 如果你希望保留代理，增加参数：`--keep-proxy`。
- 默认只筛选一次性固定总价（fixed）项目；如需包含按小时项目，增加参数：`--include-hourly`。

## 分步命令

1. 环境检查  
`python scripts/manual_pipeline/01_check_env.py`

2. 抓取项目（写入本地数据库）  
`python scripts/manual_pipeline/02_fetch.py --keywords "python automation,fastapi,web scraping,api integration" --limit 20 --since-days 7 --allowed-statuses "open,active,open_for_bidding"`

3. AI 并发评分  
`python scripts/manual_pipeline/03_score_concurrent.py --limit 50 --since-days 7 --allowed-statuses "open,active,open_for_bidding"`

4. 生成高分复核报告  
`python scripts/manual_pipeline/04_review.py --threshold 7.0 --output review_report.txt --since-days 7 --allowed-statuses "open,active,open_for_bidding"`

5. 手动确认并投标（可先 dry-run）  
`python scripts/manual_pipeline/05_bid.py --project-id <PROJECT_ID> --dry-run --allowed-statuses "open,active,open_for_bidding"`

6. 发送 QQ Bot 候选通知
`python scripts/manual_pipeline/06_notify_qqbot.py --limit 5`

## 兼容入口

`02_fetch_sync.py` 已转为兼容包装器，行为与 `02_fetch.py` 一致。

## 调度器

```bash
# 默认预览，仅禁止真实投标；仍会抓取项目、调用评分模型并写本地数据
python scripts/manual_pipeline/scheduler.py --once

# 显式开启真实投标，要求 QQ Bot 人工确认
python scripts/manual_pipeline/scheduler.py --submit --confirm
```

基础间隔默认 3 分钟，白天实际约 3–6 分钟，夜间约 8–12 分钟。`--confirm` 在夜间同样生效；配置缺失、确认失败或超时均阻断提交。预览数量记录为 `bids_previewed`，不会算入 `bids_submitted`。

`start_scheduler.sh` 按自身目录启动，默认使用项目 `.venv/bin/python`，支持 `PYTHON_BIN` 和额外参数。启动脚本默认也是预览模式。

`05_bid.py --amount` 表示本币金额；未传金额时，美元建议价会明确换算到本币。预览模式不询问是否提交，真实模式仍需输入 `y`，之后服务重新检查远端状态。

## 最终内容批准

先准备快照并通知 QQ，接收器使用 `run_qqbot.py` 独立运行。QQ 中发送 `候选` 查看完整内容，发送消息给出的 `批准风险 ID 版本` 或 `拒绝 ID 版本` 做决定。未配置对象、审批者、签名失败、过期或内容变化都不能提交。

`--submit` 还需要 `.env` 中的 `BID_SUBMISSION_ENABLED=true`；默认保持 false。审批记录本身不开启真实投标。每日默认最多一次提交尝试、20 项评分，金额/净时薪/工时上限可配置。

CLI 先用 `05_bid.py --project-id ID --amount 本币金额 --period 天数 --dry-run` 准备完整快照。已批准后才可使用 `05_bid.py --approval-id ID --submit`；不再通过本地输入 y 绕过 QQ 批准。

## 评分新鲜度与候选选择

Web、`03_score_concurrent.py` 和调度器共用结构化模型评分。默认仅调用一个配置模型，不在评分时自动生成提案。旧版/手动/规则分、竞争或客户发生变化的分数，以及超过 `SCORING_TTL_HOURS`（默认 6 小时）的分数都需重评；CLI `--limit` 在类型和评分有效性判断之后执行。

受控候选先检查真实净时薪、工时上限和客户明确阻断，再按分数取前 N 项。准备失败会跳过该次评分并补位，单轮最多 `BID_MAX_CANDIDATE_PREPARATIONS_PER_CYCLE`（默认 10）次。审批开关、未知资料人工风险复核、每日提交额度和未知结果防重规则保持有效。

新增 `score_metadata` / `scored_at` 兼容迁移只在本轮隔离库验证；业务库启用与真实模型重评需要在后续运行阶段完成。

## 竞争标书与评估

`02b_fetch_bids.py` 保存竞标快照；`04_review.py` 显示其时效和已保存的最终稿评估。`05_bid.py`、调度器和 API 候选准备共用竞标上下文与评估器：生成前读公开报价及代表稿，生成后检查差距和复制风险。QQ 展示完整文案及比较摘要，高价、资料不足或交付差距需要人工核对，不自动降价。

独立评估入口为 `POST /api/v1/proposals/evaluate`，使用现有 API Key。新文案/金额、竞标变化或过期需重新准备审批；旧版无评估快照不能提交。规则及验收见 [链路计划](../../docs/plans/2026-10-12-competitor-proposal-pipeline.md)。

## 候选队列与待澄清

前端“候选处理”页（`/workflow`）可以读取近期队列和统计；“检查已有项目与审批状态”只同步本地资料，不抓取平台或发消息。暂缓/拒绝需填写原因，可指定未来再次检查时间；没有指定时间的人工决定须明确恢复。未回答的问题必须完整录入，保存后回到待判断并使旧工时、报价及评分失效。

调度现在先评分和判断澄清，再对前排可行项目读取完整竞标资料。待澄清、待审批、人工暂缓/拒绝、已投标和未知结果不会重复评分。每轮返回 `run_id` 和分阶段耗时；发生异常也保存失败阶段。统计只覆盖新版本记录，不能从旧样本推算历史漏斗或模型费用。

新增 `candidate_workflows/workflow_events/workflow_runs` 三张表需要在正式运行阶段通过已有初始化流程创建，本轮仅在隔离库验收。评分契约已更新为 v3，旧候选须重评；现有人工审批、真实投标开关、每日额度与未知结果防重继续有效。
