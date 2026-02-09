# 手动流水线执行指南

本指南描述当前生产路径：纯 Python 手动流水线。

## 流程概览

1. `01_check_env.py`：校验配置与连通性
2. `02_fetch.py`：抓取项目并入库（默认 fixed-only）
3. `03_score_concurrent.py`：并发评分
4. `04_review.py`：生成候选报告
5. `05_bid.py`：预览/提交投标
6. `06_notify_telegram.py`：发送通知（可选）

## 一键执行（到投标前）

```bash
python scripts/manual_pipeline/run_until_bid.py \
  --since-days 7 \
  --allowed-statuses "open,active,open_for_bidding" \
  --threshold 6.0 \
  --output review_report.txt
```

## 关键参数

- `--include-hourly`：默认关闭；打开后包含按小时项目
- `--keep-proxy`：默认关闭；打开后保留代理环境变量

## 投标执行建议

先 `--dry-run` 生成预览，确认金额、工期、方案与里程碑后再提交。

```bash
python scripts/manual_pipeline/05_bid.py --project-id <ID> --dry-run
python scripts/manual_pipeline/05_bid.py --project-id <ID> --amount <AMOUNT> --period <DAYS>
```
