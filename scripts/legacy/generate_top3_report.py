#!/usr/bin/env python3
"""生成评分前三项目的投标报告"""
import sys
sys.path.insert(0, '/home/yuanzhi/Develop/automation/freelancer_automation/python_service')
from database.connection import get_db_session
from database.models import Project
from sqlalchemy import desc, func
import json

def format_project_details(project):
    """格式化项目详情"""
    # 解析 bid_stats
    bid_count = 0
    if project.bid_stats:
        try:
            stats = json.loads(project.bid_stats)
            bid_count = stats.get('bid_count', 0)
        except:
            pass

    # 解析 owner_info
    owner_info = {}
    if project.owner_info:
        try:
            owner_info = json.loads(project.owner_info)
        except:
            pass

    print(f"\n{'='*120}")
    print(f"项目 ID: {project.freelancer_id}")
    print(f"评分: {project.ai_score:.1f}/10")
    print(f"标题: {project.title}")
    print(f"{'='*120}")
    print(f"\n【项目详情】")
    print(f"预算: {project.budget_minimum}-{project.budget_maximum} {project.currency_code}")
    print(f"状态: {project.status}")
    print(f"投标数: {bid_count}")
    if project.hourly_rate:
        print(f"时薪: ${project.hourly_rate:.1f}/h")
    if project.estimated_hours:
        print(f"预估工时: {project.estimated_hours} 小时")
    if project.suggested_bid:
        print(f"建议投标金额: ${project.suggested_bid} USD")
    print(f"创建时间: {project.created_at}")

    print(f"\n【项目描述】")
    print(project.description[:500] if project.description else "无描述")
    if project.description and len(project.description) > 500:
        print(f"... (共 {len(project.description)} 字符)")

    print(f"\n【AI 评分理由】")
    print(project.ai_reason if project.ai_reason else "无评分理由")

    print(f"\n【AI 生成的投标草稿】")
    if project.ai_proposal_draft:
        print(project.ai_proposal_draft[:800])
        if len(project.ai_proposal_draft) > 800:
            print(f"... (共 {len(project.ai_proposal_draft)} 字符)")
    else:
        print("未生成投标草稿")

    print(f"\n【客户信息】")
    if owner_info:
        print(f"客户 ID: {owner_info.get('id', 'N/A')}")
        print(f"在线状态: {owner_info.get('status', {}).get('online_status', 'N/A')}")
        print(f"发布项目数: {owner_info.get('jobs', {}).get('posted', 'N/A')}")
        print(f"评分: {owner_info.get('reputation', {}).get('entire_history', {}).get('overall', 'N/A')}")
    else:
        print("无客户信息")

with get_db_session() as db:
    # 查询可投标的已评分项目，按评分降序
    allowed_statuses = ['open', 'active', 'open_for_bidding']
    projects = db.query(Project).filter(
        Project.ai_score.isnot(None),
        func.lower(Project.status).in_(allowed_statuses)
    ).order_by(desc(Project.ai_score)).limit(3).all()

    print(f"\n\n{'#'*120}")
    print(f"# 评分前三的可投标项目详细报告")
    print(f"# 生成时间: {__import__('datetime').datetime.now()}")
    print(f"{'#'*120}")

    for i, project in enumerate(projects, 1):
        print(f"\n\n## 第 {i} 名")
        format_project_details(project)

    print(f"\n\n{'#'*120}")
    print(f"# 报告结束")
    print(f"{'#'*120}\n")
