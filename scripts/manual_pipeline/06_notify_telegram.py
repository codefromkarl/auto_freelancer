#!/usr/bin/env python3
"""
Send project notifications to Telegram (Chinese display).
"""
import argparse
import sys
from pathlib import Path
import json

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Send project notifications to Telegram.")
    parser.add_argument("--threshold", type=float, default=7.0, help="Minimum score threshold")
    parser.add_argument("--limit", type=int, default=10, help="Max projects to send")
    parser.add_argument("--lock-file", default=str(common.DEFAULT_LOCK_FILE), help="Lock file path")
    args = parser.parse_args(argv)

    logger = common.setup_logging("manual_telegram_notify")

    # Load env to get Telegram credentials
    import os
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Error: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")
        return common.EXIT_VALIDATION_ERROR

    with common.file_lock(Path(args.lock_file), blocking=False) as acquired:
        if not acquired:
            print("Lock busy. Another workflow may be running.")
            return common.EXIT_LOCK_ERROR

        with common.get_db_context() as db:
            # Get high-scored projects
            projects = (
                db.query(Project)
                .filter(Project.ai_score >= args.threshold)
                .filter(Project.ai_score.isnot(None))
                .order_by(Project.ai_score.desc())
                .limit(args.limit)
                .all()
            )

            if not projects:
                print(f"No projects found with score >= {args.threshold}")
                return common.EXIT_SUCCESS

            # Build message in Chinese
            header = f"🎯 *Freelancer 高分项目 (评分 >= {args.threshold})*\n"
            header += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            project_messages = []
            for i, project in enumerate(projects, 1):
                budget_min = float(project.budget_minimum) if project.budget_minimum else 0
                budget_max = float(project.budget_maximum) if project.budget_maximum else 0
                budget = f"{budget_min:.0f}-{budget_max:.0f} {project.currency_code or 'USD'}"
                score = f"{project.ai_score:.1f}" if project.ai_score else "0.0"
                suggested_bid = f"{project.suggested_bid:.0f}" if project.suggested_bid else "N/A"
                reason = (project.ai_reason or "")[:80] if project.ai_reason else "N/A"
                proposal = (project.ai_proposal_draft or "")[:150] if project.ai_proposal_draft else "N/A"

                # Project link
                project_link = f"https://www.freelancer.com/projects/{project.freelancer_id}"

                msg = f"""
*{i}. {project.title[:50]}*
⭐ *评分*: {score}/10
💰 *预算*: {budget}
💵 *建议报价*: {suggested_bid}

📋 *评分理由*:
{reason}

✍️ *投标提案*:
{proposal}

🔗 [查看详情]({project_link})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
                project_messages.append(msg)

            full_message = header + "\n".join(project_messages)

            # Send to Telegram
            import requests

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

            # Check message length (Telegram limit is 4096 chars for captions)
            max_length = 4096
            if len(full_message) > max_length:
                logger.warning(f"Message too long ({len(full_message)} chars), truncating to {max_length}")
                full_message = full_message[:max_length]

            payload = {
                "chat_id": chat_id,
                "text": full_message,
                "parse_mode": "Markdown"
            }

            try:
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
                result = response.json()

                if result.get("ok"):
                    print(f"✅ 成功发送 {len(projects)} 个项目通知到 Telegram")
                    print(f"   Chat ID: {chat_id}")
                    print(f"   评分阈值: {args.threshold}")
                    return common.EXIT_SUCCESS
                else:
                    error = result.get("description", "Unknown error")
                    print(f"❌ Telegram API 错误: {error}")
                    return common.EXIT_API_ERROR

            except requests.exceptions.Timeout:
                print("❌ 请求 Telegram 超时")
                return common.EXIT_API_ERROR
            except requests.exceptions.RequestException as e:
                print(f"❌ 请求 Telegram 失败: {e}")
                return common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
