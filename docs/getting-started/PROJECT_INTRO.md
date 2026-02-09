# 项目介绍（2026 更新）

BidMaster 是一个面向 Freelancer 的投标自动化助手，当前以 **Python 手动流水线** 为主：抓取项目、AI 评分、人工复核、投标预览与提交。

## 当前能力

- 项目抓取与本地落库
- 多模型并发评分
- 固定总价（fixed）优先筛选
- 投标文案英文生成与校验
- 投标前远端状态校验与本地防重

## 目录入口

- 执行脚本：`scripts/manual_pipeline/`
- 后端服务：`python_service/`
- 数据库：`python_service/data/freelancer.db`
- 核心准则：`docs/CORE_PRINCIPLES.md`

## 推荐起步命令

```bash
python scripts/manual_pipeline/run_until_bid.py \
  --since-days 7 \
  --allowed-statuses "open,active,open_for_bidding" \
  --threshold 6.0 \
  --output review_report.txt
```
