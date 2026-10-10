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
5. 在外部提交前，`bid_submissions` 表提交唯一项目预留记录。确认成功后与 `bids` 记录一起更新；异常保留预留记录并标记 `outcome_unknown`。
6. `projects.status` 标记本地状态（如 `bid_submitted` / `skills_blocked`），调度器同时排除有提交预留记录的项目。

## 运行方式

- 直接本地运行脚本
- 或通过 `docker-compose` 运行 `python_service` 容器

## 设计原则

- Fail-Closed：任何关键校验失败必须阻断提交
- 防重提交：`bid_submissions.project_freelancer_id` 唯一约束覆盖并发 API/CLI 请求；`submitting`、`outcome_unknown` 和 `submitted` 均阻断再次提交，不能因超时或缺少 ID 自动重试。旧版缺 ID 的成功审计记录同样阻断。
- 远端优先：投标前强制远端状态校验，避免本地陈旧状态误投

## 提交契约

- 所有业务 API 在主应用注册时统一验证 `X-API-Key`，`BYPASS_AUTH` 不再生效。`/health`、根入口和 API 文档保留公开访问。
- `create_bid` 不提供跳过内容检查或远端状态检查的参数。默认生成经过校验的最终文案，不自动提交来源不明的缓存草稿；显式文案同样经过服务校验。
- 文案长度使用 `PROPOSAL_MIN_LENGTH` / `PROPOSAL_MAX_LENGTH`，并校验与提交报价的关系。修改投标文案也需校验。
- `amount` 默认表示项目本币金额；美元建议价必须显式传入 `amount_currency="USD"`。不通过数字是否恰好等于建议价推断币种；不再自动美化金额。
- 提交超时、响应缺少有效 ID 或本地落库失败返回错误，不宣称成功。预留记录持续阻断提交，直到人工核对远端结果。当前不提供自动重发或自动解锁功能。
- 新增表由现有 `init_db()` 建表机制创建。本轮只在隔离测试库验证，业务库变更属于后续授权的部署/迁移步骤。

## 本地验证

本轮验收与证据见 [可靠性优化清单](../plans/2026-10-10-reliability.md)。测试使用虚拟凭证和临时数据库，外部 HTTP 调用被拦截。

项目详情 API 默认读取缓存，显式 `refresh=true` 或缓存缺失才访问远端；该读取策略不影响真实投标前的远端门禁。消息数据在数据库会话内转换为响应数据，避免提交后属性过期。前端所有写操作均不自动重试，未知结果需要人工确认。
