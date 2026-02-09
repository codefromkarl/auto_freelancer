# BidMaster 架构设计（Manual Pipeline）

## 架构概述

BidMaster 采用 **Python FastAPI + SQLite + 手动流水线脚本** 的执行模式：

- `python_service/` 提供 API、业务服务、数据模型
- `scripts/manual_pipeline/` 提供抓取、评分、复核、投标 CLI 流程
- `python_service/data/freelancer.db` 作为本地状态与投标记录存储

## 分层

1. API 层：`python_service/api/*`
2. 服务层：`python_service/services/*`
3. 数据层：`python_service/database/*`
4. 执行层：`scripts/manual_pipeline/*`

## 核心数据流

1. `02_fetch.py` 抓取项目并入库
2. `03_score_concurrent.py` 打分并写回项目
3. `04_review.py` 输出候选项目报告
4. `05_bid.py` 执行远端状态校验、生成提案、提交投标
5. `bids` 表记录提交结果，`projects.status` 标记本地状态（如 `bid_submitted` / `skills_blocked`）

## 运行方式

- 直接本地运行脚本
- 或通过 `docker-compose` 运行 `python_service` 容器

## 设计原则

- Fail-Closed：任何关键校验失败必须阻断提交
- 防重提交：本地 `bids` 记录与项目状态共同防止重复投标
- 远端优先：投标前强制远端状态校验，避免本地陈旧状态误投
