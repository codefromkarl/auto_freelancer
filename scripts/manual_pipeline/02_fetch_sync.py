#!/usr/bin/env python3
"""
同步方式抓取 Freelancer 项目（绕过 SSL 问题）
通过调用统一的 project_service 确保初筛和详情获取逻辑一致。
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path

# 添加路径
script_dir = Path(__file__).resolve().parent
repo_root = script_dir.parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "python_service"))

# 加载环境变量
env_file = repo_root / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

from database.connection import SessionLocal
from services import project_service

# 关键词列表
KEYWORDS = [
    "Python automation",
    "n8n",
    "FastAPI",
    "web scraping",
    "API integration",
    "data automation",
    "workflow automation",
    "Python script",
    "backend development",
    "database",
]

# OAuth Token
OAUTH_TOKEN = os.environ.get("FREELANCER_OAUTH_TOKEN", "")

def main():
    """主函数：抓取项目"""
    print("=" * 60)
    print("📊 项目抓取工具 (Service 模式)")
    print("=" * 60)

    if not OAUTH_TOKEN:
        print("❌ 错误: FREELANCER_OAUTH_TOKEN 未设置")
        return 1

    print(f"📝 搜索关键词: {len(KEYWORDS)} 个")
    print(f"🎯 目标数量: 50 个项目\n")

    # 获取数据库会话
    db = SessionLocal()

    try:
        all_new_projects = []
        
        for keyword in KEYWORDS:
            if len(all_new_projects) >= 50:
                break

            print(f"🔍 正在处理关键词: '{keyword}'...")

            try:
                # 调用统一的 search_projects (包含初筛和详情获取)
                new_projects = asyncio.run(
                    project_service.search_projects(
                        db=db,
                        query=keyword,
                        limit=10,
                        enable_pre_filter=True  # 强制开启初筛
                    )
                )
                
                all_new_projects.extend(new_projects)
                print(f"  ✓ 本次新增 {len(new_projects)} 个符合要求的项目")

            except Exception as e:
                print(f"  ✗ 处理失败: {e}")

        print(f"\n📊 流程完成，共入库 {len(all_new_projects)} 个新项目")
        
        if all_new_projects:
            output_file = repo_root / "fetched_projects_raw.json"
            with open(output_file, "w") as f:
                json.dump(all_new_projects, f, indent=2, ensure_ascii=False)
            print(f"📄 原始数据备份已更新: {output_file}")

        return 0

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())