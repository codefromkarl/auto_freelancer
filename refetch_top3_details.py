#!/usr/bin/env python3
"""重新拉取指定项目的详细信息"""
import sys
import asyncio
sys.path.insert(0, '/home/yuanzhi/Develop/automation/freelancer_automation/python_service')

from database.connection import get_db_session
from database.models import Project
from services.freelancer_client import get_freelancer_client
import json

async def fetch_project_details(project_ids):
    """拉取项目详细信息"""
    client = get_freelancer_client()

    for project_id in project_ids:
        try:
            print(f"\n{'='*100}")
            print(f"正在拉取项目 {project_id} 的详细信息...")
            print('='*100)

            # 获取项目详情
            project_data = await client.get_project(project_id)

            if project_data:
                print(f"\n✅ 项目 ID: {project_id}")
                print(f"标题: {project_data.get('title', 'N/A')}")
                print(f"状态: {project_data.get('status', 'N/A')}")

                # 投标统计
                bid_stats = project_data.get('bid_stats', {})
                print(f"\n【投标统计】")
                print(f"投标数量: {bid_stats.get('bid_count', 0)}")
                print(f"平均投标金额: {bid_stats.get('bid_avg', 'N/A')}")

                # 预算信息
                print(f"\n【预算信息】")
                print(f"最小预算: {project_data.get('budget', {}).get('minimum', 'N/A')}")
                print(f"最大预算: {project_data.get('budget', {}).get('maximum', 'N/A')}")
                print(f"货币: {project_data.get('currency', {}).get('code', 'N/A')}")

                # 客户信息
                owner = project_data.get('owner', {})
                print(f"\n【客户信息】")
                print(f"客户 ID: {owner.get('id', 'N/A')}")
                print(f"用户名: {owner.get('username', 'N/A')}")
                print(f"国家: {owner.get('location', {}).get('country', {}).get('name', 'N/A')}")

                # 更新数据库
                with get_db_session() as db:
                    project = db.query(Project).filter(
                        Project.freelancer_id == project_id
                    ).first()

                    if project:
                        # 更新 bid_stats
                        project.bid_stats = json.dumps(bid_stats)

                        # 更新 owner_info
                        project.owner_info = json.dumps(owner)

                        db.commit()
                        print(f"\n✅ 数据库已更新")
                    else:
                        print(f"\n⚠️ 数据库中未找到项目 {project_id}")
            else:
                print(f"❌ 无法获取项目 {project_id} 的详细信息")

        except Exception as e:
            print(f"❌ 拉取项目 {project_id} 失败: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    # 评分前三的项目 ID
    project_ids = [40135964, 40207719, 40207552]
    asyncio.run(fetch_project_details(project_ids))
