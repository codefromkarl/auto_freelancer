#!/usr/bin/env python3
"""为评分前三的项目生成投标内容"""
import sys
import asyncio
sys.path.insert(0, '/home/yuanzhi/Develop/automation/freelancer_automation/python_service')

from database.connection import get_db_session
from database.models import Project
from services.proposal_service import get_proposal_service

async def generate_proposals_for_top3():
    """为评分前三的项目生成投标内容"""
    project_ids = [40135964, 40207719, 40207552]

    with get_db_session() as db:
        proposal_service = get_proposal_service()

        for i, project_id in enumerate(project_ids, 1):
            project = db.query(Project).filter(
                Project.freelancer_id == project_id
            ).first()

            if not project:
                print(f"\n❌ 项目 {project_id} 未找到")
                continue

            print(f"\n\n{'#'*120}")
            print(f"# 第 {i} 名项目")
            print(f"{'#'*120}")
            print(f"\n项目 ID: {project_id}")
            print(f"标题: {project.title}")
            print(f"预算: {project.budget_minimum}-{project.budget_maximum} {project.currency_code}")
            print(f"评分: {project.ai_score:.1f}/10")
            print(f"投标数: {project.bid_stats}")

            try:
                result = await proposal_service.generate_proposal(project, db=db)

                if result.get('success') and result.get('validation_passed'):
                    proposal = result.get('proposal', '')
                    print(f"\n✅ 投标内容生成成功！")
                    print(f"\n{'='*120}")
                    print(proposal)
                    print(f"{'='*120}")
                    print(f"\n字数: {len(proposal.split())} 词")
                else:
                    print(f"\n❌ 生成失败")
                    print(f"错误: {result.get('error')}")
                    print(f"验证问题: {result.get('validation_issues')}")

            except Exception as e:
                print(f"\n❌ 生成失败: {e}")

if __name__ == "__main__":
    asyncio.run(generate_proposals_for_top3())
