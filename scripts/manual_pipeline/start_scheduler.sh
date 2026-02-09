#!/bin/bash
# Launcher script: clears proxy env vars before starting scheduler
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

cd /home/yuanzhi/Develop/automation/freelancer_automation/scripts/manual_pipeline

exec python scheduler.py \
  --interval 5 \
  --since-days 3 \
  --bid-threshold 6.0 \
  --max-bids-per-cycle 2 \
  --limit 20 \
  --keywords "python automation,fastapi,web scraping,api integration"
