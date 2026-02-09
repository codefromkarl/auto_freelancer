#!/usr/bin/env python3
"""查询可投标的高分项目"""
import sys
sys.path.insert(0, '/home/yuanzhi/Develop/automation/freelancer_automation/python_service')
from database.connection import get_db_session
from database.models import Project
from sqlalchemy import desc, func
import json

with get_db_session() as db:
    # 查询可投标的已评分项目，按评分降序
    allowed_statuses = ['open', 'active', 'open_for_bidding']
    projects = db.query(Project).filter(
        Project.ai_score.isnot(None),
        func.lower(Project.status).in_(allowed_statuses)
    ).order_by(desc(Project.ai_score)).limit(10).all()

    print(f'找到 {len(projects)} 个可投标的已评分项目\n')
    print('评分前10名（可投标）：')
    print('='*120)
    for i, p in enumerate(projects, 1):
        # 解析 bid_stats
        bid_count = 0
        if p.bid_stats:
            try:
                stats = json.loads(p.bid_stats)
                bid_count = stats.get('bid_count', 0)
            except:
                pass

        print(f'{i}. [Freelancer ID: {p.freelancer_id}] 评分: {p.ai_score:.1f}')
        print(f'   标题: {p.title[:90]}')
        print(f'   预算: {p.budget_minimum}-{p.budget_maximum} {p.currency_code}')
        if p.hourly_rate:
            print(f'   状态: {p.status} | 投标数: {bid_count} | 时薪: ${p.hourly_rate:.1f}/h')
        else:
            print(f'   状态: {p.status} | 投标数: {bid_count}')
        print(f'   创建时间: {p.created_at}')
        if p.ai_proposal_draft:
            print(f'   已有投标草稿: 是')
        print('-'*120)
