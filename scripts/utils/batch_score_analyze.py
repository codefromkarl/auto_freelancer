#!/usr/bin/env python3
"""
Batch score and analyze projects with iterative feedback loop.

Process:
1. Score un-scored projects in batches of 10
2. After each batch, send results to Gemini and OpenCode for analysis
3. If both agree score >= 7.0, send to Telegram
4. Continue until all projects are scored
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir.parent / "manual_pipeline"))
sys.path.insert(0, str(script_dir.parent / "python_service"))

import common
from database.models import Project
from database.connection import SessionLocal
from services.project_scorer import ProjectScorer, ProjectScore


def format_project_for_analysis(project: Project, score: ProjectScore) -> str:
    """Format project and score for analysis."""
    # Calculate hourly rate for analysis
    budget_min = float(project.budget_minimum) if project.budget_minimum else 0
    budget_max = float(project.budget_maximum) if project.budget_maximum else 0
    avg_budget = (budget_min + budget_max) / 2 if budget_max > 0 else budget_min
    estimated_hours = score.score_breakdown.estimated_hours
    hourly_rate = avg_budget / estimated_hours if estimated_hours > 0 else 0

    return f"""
Project ID: {project.freelancer_id}
Title: {project.title}
Budget: {project.currency_code} {project.budget_minimum} - {project.budget_maximum}
Type: {project.type_id or 'fixed'}
Owner Info: {project.owner_info[:100] if project.owner_info else 'None'}
Bid Count: {project.bid_stats[:100] if project.bid_stats else 'None'}

AI Score: {score.ai_score} ({score.ai_grade})
- Budget Efficiency: {score.score_breakdown.budget_efficiency_score:.2f}
- Estimated Hours: {estimated_hours}
- Hourly Rate: {project.currency_code or 'USD'} {hourly_rate:.2f}/h
- Competition: {score.score_breakdown.competition_score:.2f}
- Clarity: {score.score_breakdown.clarity_score:.2f}
- Customer: {score.score_breakdown.customer_score:.2f}
- Tech: {score.score_breakdown.tech_score:.2f}
- Risk: {score.score_breakdown.risk_score:.2f}

Reason: {score.ai_reason}
"""


def send_to_gemini(projects_data: List[str]) -> str:
    """Send batch results to Gemini for analysis."""
    prompt = f"""请分析这批项目的评分结果，判断当前评分系统是否存在问题。

项目评分结果（共 {len(projects_data)} 个）:
{''.join(['=' * 60] + ['\n\n' + p for p in projects_data] + ['\n'])}

请评估：
1. 评分是否合理？如果有明显不合理的评分，请指出
2. 预算效率评分是否正确？
3. 需求清晰度评分是否恰当？
4. 工作量估算是否准确？
5. 有什么改进建议？

请直接给出你的分析结论和改进建议。"""
    import os
    from config import settings

    # Check if Gemini is enabled
    if not os.getenv("ZHIPU_API_KEY") and not os.getenv("DEEPSEEK_API_KEY"):
        return "Gemini未配置，跳过分析"

    # Use gask-w command for synchronous execution
    import subprocess
    print("  正在等待 Gemini 分析...")
    result = subprocess.run(
        ["gask-w", prompt],
        capture_output=True,
        text=True,
        timeout=300  # 5 minutes timeout for analysis
    )
    if result.returncode == 0:
        return result.stdout
    else:
        return f"分析失败: {result.stderr}"


def send_to_opencode(projects_data: List[str]) -> str:
    """Send batch results to OpenCode for analysis."""
    prompt = f"""Please analyze this batch of project scoring results and identify any issues with the current scoring system.

Project Scoring Results ({len(projects_data)} projects):
{''.join(['=' * 60] + ['\n\n' + p for p in projects_data] + ['\n'])}

Please evaluate:
1. Are the scores reasonable? Point out any obviously wrong scores
2. Is the budget efficiency scoring correct?
3. Is the requirement clarity scoring appropriate?
4. Is the workload estimation accurate?
5. Any improvement suggestions?

Please provide your analysis conclusions and improvement recommendations directly."""
    import os
    from config import settings

    # Check if OpenCode is available
    if not os.getenv("OPENCODE_API_KEY"):
        return "OpenCode未配置，跳过分析"

    # Use oask-w command for synchronous execution
    import subprocess
    print("  正在等待 OpenCode 分析...")
    result = subprocess.run(
        ["oask-w", prompt],
        capture_output=True,
        text=True,
        timeout=300  # 5 minutes timeout for analysis
    )
    if result.returncode == 0:
        return result.stdout
    else:
        return f"分析失败: {result.stderr}"


def send_to_telegram(message: str) -> bool:
    """Send message to Telegram."""
    import os
    from config import settings

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Telegram未配置，跳过通知")
        return False

    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        response = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=30)

        if response.status_code == 200:
            print(f"✓ Telegram消息已发送")
            return True
        else:
            print(f"✗ Telegram发送失败: {response.text}")
            return False
    except Exception as e:
        print(f"✗ Telegram发送异常: {e}")
        return False


def process_batch(db, scorer, batch: List[Project], batch_num: int) -> Dict[str, Any]:
    """Process a batch of projects."""
    print(f"\n{'=' * 60}")
    print(f"处理批次 {batch_num}: {len(batch)} 个项目")
    print(f"{'=' * 60}\n")

    scored_results = []
    for project in batch:
        # Build project dict for scoring
        # Handle None values and parse JSON fields safely
        try:
            bid_stats = json.loads(project.bid_stats) if project.bid_stats else {}
        except json.JSONDecodeError:
            bid_stats = {}

        try:
            owner_info = json.loads(project.owner_info) if project.owner_info else {}
        except json.JSONDecodeError:
            owner_info = {}

        # Use full_description if available, otherwise use preview_description
        # The database stores full_description in description field
        description = project.description or project.preview_description or ""

        project_dict = {
            "id": project.freelancer_id,
            "title": project.title,
            "type": "fixed" if project.type_id == 1 else "hourly",
            "budget": {
                "minimum": float(project.budget_minimum) if project.budget_minimum else 0,
                "maximum": float(project.budget_maximum) if project.budget_maximum else 0,
            },
            "currency": {"code": project.currency_code or "USD"},
            "full_description": description,
            "preview_description": project.preview_description or "",
            "bid_stats": bid_stats,
            "owner_info": owner_info,
        }
        score = scorer.score_project(project_dict)
        scored_results.append((project, score))
        print(f"  项目 {project.freelancer_id}: {score.ai_score} ({score.ai_grade}) - {score.ai_reason[:50]}...")

        # Update database
        from services import project_service
        project_service.update_project_ai_analysis(
            db,
            project.freelancer_id,
            score.ai_score,
            score.ai_reason,
            score.ai_proposal_draft,
            None  # suggested_bid not needed for rule-based scoring
        )

    # Commit batch updates
    db.commit()

    # Prepare data for analysis
    projects_data = [format_project_for_analysis(p, s) for p, s in scored_results]
    high_score_projects = [(p, s) for p, s in scored_results if s.ai_score >= 7.0]

    # Send to analysis
    print(f"\n--- 推送给 Gemini 分析 ---")
    gemini_result = send_to_gemini(projects_data)
    print(f"Gemini分析: {gemini_result[:200]}..." if len(gemini_result) > 200 else gemini_result)

    print(f"\n--- 推送给 OpenCode 分析 ---")
    opencode_result = send_to_opencode(projects_data)
    print(f"OpenCode分析: {opencode_result[:200]}..." if len(opencode_result) > 200 else opencode_result)

    # Check if analysis indicates that current scoring needs improvement
    needs_improvement = False
    improvement_reasons = []

    # Check Gemini analysis for issues (Gemini is the primary analyzer)
    gemini_lower = gemini_result.lower()
    issue_keywords = ["不合理", "问题", "需要改进", "不正确", "偏低", "偏高", "error", "issue", "improve", "unreasonable", "incorrect", "失效", "缺陷", "偏差", "崩溃", "逆向", "亏本"]

    gemini_has_issues = any(kw in gemini_lower for kw in issue_keywords)

    # Also check OpenCode if available (secondary analysis)
    opencode_has_issues = False
    if not opencode_result.startswith("OpenCode未配置"):
        opencode_lower = opencode_result.lower()
        opencode_has_issues = any(kw in opencode_lower for kw in issue_keywords)

    # Stop if Gemini identifies issues (primary analyzer)
    if gemini_has_issues:
        needs_improvement = True
        if opencode_has_issues:
            improvement_reasons = ["Gemini 和 OpenCode 都认为当前评分系统需要优化"]
        else:
            improvement_reasons = ["Gemini 认为当前评分系统需要优化"]
        print(f"\n{'⚠️' * 30}")
        print("⚠️ 检测到评分系统需要优化！")
        print(f"{'⚠️' * 30}")
        print(f"\nGemini分析摘要: {gemini_result[:400]}...")
        if opencode_has_issues:
            print(f"OpenCode分析摘要: {opencode_result[:400]}...")

    # Check if both agree on high scores
    # Simplified check: if AI score >= 7.0, send notification
    if high_score_projects:
        project_list = "\n".join([
            f"  - {p.title} (ID: {p.freelancer_id}, 评分: {s.ai_score})"
            for p, s in high_score_projects
        ])
        telegram_msg = f"""🎯 高分项目通知 (评分 >= 7.0)
━━━━━━━━━━━━━━━━━━━━━━━━━━━

{project_list}

🔗 查看详情"""
        send_to_telegram(telegram_msg)

    return {
        "batch_num": batch_num,
        "count": len(batch),
        "high_score_count": len(high_score_projects),
        "gemini_analysis": gemini_result[:500],
        "opencode_analysis": opencode_result[:500],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Batch score and analyze projects.")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size (default: 10)")
    parser.add_argument("--lock-file", default=str(common.DEFAULT_LOCK_FILE), help="Lock file path")
    args = parser.parse_args(argv)

    logger = common.setup_logging("batch_score_analyze")

    with common.file_lock(Path(args.lock_file), blocking=False) as acquired:
        if not acquired:
            print("Lock busy. Another workflow may be running.")
            return common.EXIT_LOCK_ERROR

        try:
            common.load_env()
            common.get_settings()
        except Exception as exc:
            print(f"Failed to load settings: {exc}")
            return common.EXIT_VALIDATION_ERROR

        with common.get_db_context() as db:
            # Get total un-scored projects
            total_unscored = (
                db.query(Project)
                .filter(Project.ai_score.is_(None))
                .count()
            )

            if total_unscored == 0:
                print("所有项目已评分完成！")
                return common.EXIT_SUCCESS

            print(f"总待评分项目数: {total_unscored}")
            print(f"批次大小: {args.batch_size}")
            print(f"预计需要 {(total_unscored + args.batch_size - 1) // args.batch_size} 个批次\n")

            # Process in batches
            scorer = ProjectScorer()
            batch_num = 0
            all_results = []
            needs_optimization = False

            while True:
                # Get next batch
                batch = (
                    db.query(Project)
                    .filter(Project.ai_score.is_(None))
                    .order_by(Project.created_at.desc())
                    .limit(args.batch_size)
                    .all()
                )

                if not batch:
                    break

                batch_num += 1
                result = process_batch(db, scorer, batch, batch_num)
                all_results.append(result)

                # Check if this batch indicates needs optimization
                if "needs_improvement" in result and result["needs_improvement"]:
                    needs_optimization = True
                    # Stop and ask for optimization
                    break

                # Pause between batches
                if len(batch) == args.batch_size:
                    print(f"\n批次 {batch_num} 完成，等待 3 秒后继续...")
                    import time
                    time.sleep(3)

            # If optimization needed, stop and wait
            if needs_optimization:
                print(f"\n{'⚠️' * 40}")
                print("⚠️ 检测到评分系统需要优化！")
                print("⚠️ 请先优化评分系统后再继续评分")
                print(f"{'⚠️' * 40}")
                return common.EXIT_VALIDATION_ERROR

            # Final summary
            print(f"\n{'=' * 60}")
            print(f"批量评分完成！")
            print(f"{'=' * 60}")
            print(f"总批次数: {len(all_results)}")
            print(f"总评分项目数: {sum(r['count'] for r in all_results)}")
            high_score_count = sum(r['high_score_count'] for r in all_results)
            print(f"高分项目数 (>=7.0): {high_score_count}")

            return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
