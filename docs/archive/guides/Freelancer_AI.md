# Freelancer AI 指南（已更新）

本项目已从早期自动编排方案切换到 **手动流水线执行模式**。

## 当前推荐入口

- `scripts/manual_pipeline/README.md`
- `docs/workflows/MANUAL_WORKFLOW.md`

## 关键变化

- 不再依赖 n8n 工作流触发抓取/评分/投标
- 统一使用 Python 脚本执行全流程
- 固定总价（fixed）项目作为默认筛选目标

## 快速开始

```bash
python scripts/manual_pipeline/run_until_bid.py --since-days 7 --threshold 6.0 --output review_report.txt
```
