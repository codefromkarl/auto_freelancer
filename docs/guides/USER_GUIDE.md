# 用户指南（简版）

## 日常执行顺序

1. 抓取：`02_fetch.py`
2. 评分：`03_score_concurrent.py`
3. 复核：`04_review.py`
4. 投标：`05_bid.py`

## 高频命令

```bash
python scripts/manual_pipeline/run_until_bid.py --since-days 7 --threshold 6.0 --output review_report.txt
python scripts/manual_pipeline/05_bid.py --project-id <ID> --dry-run
python scripts/manual_pipeline/05_bid.py --project-id <ID> --amount <AMOUNT> --period <DAYS>
```

## 常见问题

- 为什么项目被拦截：通常是远端状态不可投、文案校验失败或内容风控命中。
- 为什么不能重复投标：系统会检查本地 `bids` 记录与项目状态，防止重复提交。
- 为什么有项目被标记 `skills_blocked`：平台返回技能门槛错误，系统会自动标记避免再次尝试。
