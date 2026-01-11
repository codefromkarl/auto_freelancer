"""
用途：调试脚本，检查 API 返回的预算数据结构，辅助开发预算解析逻辑。
状态：活跃/工具。
"""
import asyncio
from services.freelancer_client import get_freelancer_client
import json


async def main():
    client = get_freelancer_client()

    # Get project data
    project_id = 40122137
    project_data = await client.get_project(project_id)

    print('=== Raw API Data ===')
    print(json.dumps(project_data, indent=2, default=str))

    print('\n=== Budget Section ===')
    budget = project_data.get('budget', {})
    print(f'budget object type: {type(budget)}')
    print(f'budget keys: {list(budget.keys())}')
    print(f'budget minimum: {budget.get("minimum")} ({type(budget.get("minimum"))})')
    print(f'budget maximum: {budget.get("maximum")} ({type(budget.get("maximum"))})')


if __name__ == '__main__':
    asyncio.run(main())