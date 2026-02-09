#!/bin/bash
# Launcher script: clears proxy env vars before starting scheduler

# 1. 尝试从现有代理变量中提取并固定 Telegram 专用代理
if [ -z "${TELEGRAM_PROXY:-}" ]; then
  # 优先级：TELEGRAM_HTTPS_PROXY > HTTPS_PROXY > ALL_PROXY > TELEGRAM_HTTP_PROXY > HTTP_PROXY
  TELEGRAM_PROXY_CANDIDATE="${TELEGRAM_HTTPS_PROXY:-${HTTPS_PROXY:-${https_proxy:-${ALL_PROXY:-${all_proxy:-${TELEGRAM_HTTP_PROXY:-${HTTP_PROXY:-${http_proxy:-}}}}}}}}"
  if [ -n "${TELEGRAM_PROXY_CANDIDATE}" ]; then
    # 确保有协议头
    if [[ ! "$TELEGRAM_PROXY_CANDIDATE" =~ :// ]]; then
      TELEGRAM_PROXY_CANDIDATE="http://$TELEGRAM_PROXY_CANDIDATE"
    fi
    export TELEGRAM_PROXY="${TELEGRAM_PROXY_CANDIDATE}"
    echo "[Launcher] Preserved Telegram proxy: $TELEGRAM_PROXY"
  fi
fi

# 2. 清理全局代理环境变量，防止干扰主爬虫进程（主进程通常应走直连或自理代理）
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

cd /home/yuanzhi/Develop/automation/freelancer_automation/scripts/manual_pipeline

exec python scheduler.py \
  --interval 5 \
  --since-days 3 \
  --bid-threshold 6.0 \
  --max-bids-per-cycle 2 \
  --limit 20 \
  --keywords "python automation,fastapi,web scraping,api integration"
