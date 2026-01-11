#!/usr/bin/env python3
"""
生成高分项目的投标内容报告
"""
import json
import sys
from pathlib import Path

# 添加路径
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project
from utils.currency_converter import get_currency_converter


def main():
    """生成投标内容报告"""
    print("=" * 60)
    print("📋 高分项目投标内容生成")
    print("=" * 60)

    with common.get_db_context() as db:
        converter = get_currency_converter()
        # 获取评分 >= 7.0 的项目
        high_score_projects = (
            db.query(Project)
            .filter(Project.ai_score >= 7.0)
            .order_by(Project.ai_score.desc())
            .all()
        )

        if not high_score_projects:
            print("❌ 没有找到高分项目")
            return 1

        print(f"✅ 找到 {len(high_score_projects)} 个高分项目 (>= 7.0)\n")

        # 生成报告
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("📋 高分项目投标内容报告")
        report_lines.append("=" * 80)
        report_lines.append("")

        for idx, project in enumerate(high_score_projects, 1):
            budget_min = float(project.budget_minimum) if project.budget_minimum else 0.0
            budget_max = float(project.budget_maximum) if project.budget_maximum else 0.0
            currency_code = project.currency_code or "USD"
            rate = converter.get_rate_sync(currency_code) or 1.0
            budget_min_usd = budget_min * rate
            budget_max_usd = budget_max * rate
            avg_budget = (budget_min_usd + budget_max_usd) / 2
            suggested_bid = float(project.suggested_bid) if project.suggested_bid else avg_budget * 0.7

            # 解析 bid_stats
            bid_count = 0
            if project.bid_stats:
                try:
                    bid_data = json.loads(project.bid_stats)
                    bid_count = bid_data.get("bid_count", 0)
                except (json.JSONDecodeError, AttributeError):
                    pass

            report_lines.append(f"{'─' * 80}")
            report_lines.append(f"项目 #{idx}: {project.title}")
            report_lines.append(f"{'─' * 80}")
            report_lines.append(f"📌 项目 ID:       {project.freelancer_id}")
            report_lines.append(f"📊 AI 评分:       {project.ai_score:.1f} / 10")
            report_lines.append(f"💰 预算范围:     ${budget_min_usd:.0f} - ${budget_max_usd:.0f} USD")
            report_lines.append(f"💵 建议报价:     ${suggested_bid:.0f} USD")
            report_lines.append(f"📝 投标数量:       {bid_count}")
            report_lines.append(f"👤 客户名称:       {project.owner_info and json.loads(project.owner_info).get('username', 'N/A') or 'N/A'}")
            report_lines.append(f"📅 截止日期:       {project.deadline or 'N/A'}")
            report_lines.append("")
            report_lines.append("📝 项目描述:")
            report_lines.append(f"   {project.description}")
            report_lines.append("")
            report_lines.append("💡 AI 分析:")
            report_lines.append(f"   {project.ai_reason}")
            report_lines.append("")
            report_lines.append("✍️ 投标方案 (AI 生成的提案草案):")
            report_lines.append("─" * 50)
            report_lines.append(project.ai_proposal_draft)
            report_lines.append("─" * 50)
            report_lines.append("")

        # 生成文件
        report_path = Path.cwd() / "bid_content_report.md"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")

        print(f"📄 报告已生成: {report_path}")

        # 统计信息
        report_lines.append("")
        report_lines.append("=" * 80)
        report_lines.append("📈 统计摘要")
        report_lines.append("=" * 80)

        total_budget_min = sum(
            float(p.budget_minimum) * (converter.get_rate_sync(p.currency_code or "USD") or 1.0)
            for p in high_score_projects
            if p.budget_minimum
        )
        total_budget_max = sum(
            float(p.budget_maximum) * (converter.get_rate_sync(p.currency_code or "USD") or 1.0)
            for p in high_score_projects
            if p.budget_maximum
        )
        avg_score = sum(p.ai_score for p in high_score_projects) / len(high_score_projects)

        report_lines.append(f"项目数量:         {len(high_score_projects)}")
        report_lines.append(f"平均评分:         {avg_score:.1f}")
        report_lines.append(f"预算范围总和:   ${total_budget_min:.0f} - ${total_budget_max:.0f}")
        report_lines.append(f"平均建议报价:     ${sum(p.suggested_bid for p in high_score_projects if p.suggested_bid) / len([p for p in high_score_projects if p.suggested_bid]):.0f}")

        # 更新文件
        report_path.write_text("\n".join(report_lines), encoding="utf-8")

        print(f"📊 统计:")
        print(f"  项目数量:    {len(high_score_projects)}")
        print(f"  平均评分:    {avg_score:.1f}")
        print(f"  预算总额:    ${total_budget_min:.0f} - ${total_budget_max:.0f}")

        return 0


if __name__ == "__main__":
    sys.exit(main())
