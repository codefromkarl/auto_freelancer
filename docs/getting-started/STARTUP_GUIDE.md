# 启动指南（Manual Pipeline）

## 1. 环境准备

```bash
cd python_service
pip install -r requirements.txt
cd ..
```

确保 `.env` 配置了以下关键项：

- `FREELANCER_OAUTH_TOKEN`
- `FREELANCER_USER_ID`
- `PYTHON_API_KEY`
- `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL`

## 2. 启动 Python API（可选）

```bash
docker-compose up -d python_service
```

## 3. 手动流水线

```bash
python scripts/manual_pipeline/01_check_env.py
python scripts/manual_pipeline/02_fetch.py --limit 20
python scripts/manual_pipeline/03_score_concurrent.py --limit 50
python scripts/manual_pipeline/04_review.py --threshold 6.0 --output review_report.txt
```

## 4. 投标预览与提交

```bash
python scripts/manual_pipeline/05_bid.py --project-id <PROJECT_ID> --dry-run
python scripts/manual_pipeline/05_bid.py --project-id <PROJECT_ID> --amount <AMOUNT> --period <DAYS>
```

## 5. 默认筛选策略

- 默认只处理 fixed 项目
- 若需包含 hourly：为 `02_fetch.py` / `03_score_concurrent.py` / `04_review.py` 增加 `--include-hourly`
