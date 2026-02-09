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

6. 发送 Telegram 通知  
`python scripts/manual_pipeline/06_notify_telegram.py --threshold 7.0 --limit 10 --since-days 7 --allowed-statuses "open,active,open_for_bidding"`

## 兼容入口

`02_fetch_sync.py` 已转为兼容包装器，行为与 `02_fetch.py` 一致。
