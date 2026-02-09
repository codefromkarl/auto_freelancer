#!/usr/bin/env python3
"""查询评分前10的项目"""
import sys
sys.path.insert(0, '/home/yuanzhi/Develop/automation/freelancer_automation/python_service')
from database.connection import get_db_session
from database.models import Project
from sqlalchemy import desc
import json

with get_db_session() as db:
    # 查询所有已评分的项目，按评分降序
    projects = db.query(Project).filter(
        Project.ai_score.isnot(None)
    ).order_by(desc(Project.ai_score)).limit(10).all()

    print(f'找到 {len(projects)} 个已评分项目\n')
    print('评分前10名：')
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
        print('-'*120)
