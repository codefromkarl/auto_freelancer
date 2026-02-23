#!/usr/bin/env python3
"""
Template Filler Demo - 模板填充服务演示脚本

展示如何使用 TemplateFillerService 自动生成投标文本
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_service"))

from services.template_filler_service import (
    fill_proposal_template,
    TemplateFillerService,
    DEFAULT_PROPOSAL_TEMPLATE,
)


def demo_basic_usage():
    """演示基础用法"""
    print("=" * 80)
    print("Demo 1: 基础用法 - Web Scraping 项目")
    print("=" * 80)

    project = {
        "title": "Build Python Web Scraping Tool for E-commerce",
        "description": "Need to scrape product data from multiple e-commerce sites. "
        "Should handle dynamic content, pagination, and export to CSV. "
        "Must include error handling and logging.",
        "skills": ["python", "web scraping", "selenium", "beautifulsoup"],
    }

    proposal = fill_proposal_template(
        project=project, portfolio_link="https://github.com/yuanzhi"
    )

    print(proposal)
    print("\n")


def demo_api_project():
    """演示API项目"""
    print("=" * 80)
    print("Demo 2: API 开发项目")
    print("=" * 80)

    project = {
        "title": "RESTful API Development with FastAPI",
        "description": "Build a RESTful API for user management system. "
        "Need authentication, CRUD operations, and database integration. "
        "Must include API documentation and unit tests.",
        "skills": ["python", "fastapi", "postgresql", "jwt", "api"],
    }

    proposal = fill_proposal_template(
        project=project, portfolio_link="https://github.com/yuanzhi"
    )

    print(proposal)
    print("\n")


def demo_ai_project():
    """演示AI项目"""
    print("=" * 80)
    print("Demo 3: AI Chatbot 项目")
    print("=" * 80)

    project = {
        "title": "AI Chatbot with GPT Integration",
        "description": "Develop an intelligent chatbot using OpenAI GPT API. "
        "Should support context management, multi-turn conversations, "
        "and integrate with existing customer service system.",
        "skills": ["python", "ai", "llm", "chatbot", "openai"],
    }

    proposal = fill_proposal_template(
        project=project, portfolio_link="https://github.com/yuanzhi"
    )

    print(proposal)
    print("\n")


def demo_custom_template():
    """演示自定义模板"""
    print("=" * 80)
    print("Demo 4: 自定义模板")
    print("=" * 80)

    custom_template = """Hello,

I see you need [具体需求]. This is exactly what I specialize in - [相关领域].

In my recent work, I've delivered [类似案例], achieving [具体成果].

My technical approach:
• [针对需求1的解决方案]
• [针对需求2的技术优势]

You can expect [量化收益] from this implementation.

Check out my work: [链接]

Let's discuss your specific requirements.

Yuanzhi"""

    project = {
        "title": "Automation Workflow Development",
        "description": "Automate data entry and reporting workflow",
        "skills": ["python", "automation"],
    }

    service = TemplateFillerService(portfolio_link="https://github.com/yuanzhi")
    proposal = service.fill_template(custom_template, project)

    print(proposal)
    print("\n")


def demo_minimal_project():
    """演示最小项目信息"""
    print("=" * 80)
    print("Demo 5: 最小项目信息(测试回退机制)")
    print("=" * 80)

    project = {
        "title": "Simple Task",
        "description": "Do something",
        "skills": [],
    }

    proposal = fill_proposal_template(
        project=project, portfolio_link="https://github.com/yuanzhi"
    )

    print(proposal)
    print("\n")


def demo_comparison():
    """演示不同项目类型的对比"""
    print("=" * 80)
    print("Demo 6: 项目类型对比")
    print("=" * 80)

    projects = [
        {
            "name": "简单脚本",
            "data": {
                "title": "Python Script for Data Processing",
                "skills": ["python"],
            },
        },
        {
            "name": "复杂系统",
            "data": {
                "title": "Enterprise Microservice Platform",
                "description": "Build scalable microservice architecture",
                "skills": ["python", "microservices", "docker", "api"],
            },
        },
        {
            "name": "AI项目",
            "data": {
                "title": "LLM Integration Project",
                "description": "Integrate multiple LLM providers",
                "skills": ["python", "ai", "llm"],
            },
        },
    ]

    for proj in projects:
        print(f"\n--- {proj['name']} ---")
        proposal = fill_proposal_template(
            project=proj["data"], portfolio_link="https://github.com/yuanzhi"
        )
        print(f"Length: {len(proposal)} chars")
        print(f"Preview: {proposal[:200]}...")
        print()


def main():
    """运行所有演示"""
    demos = [
        ("基础用法", demo_basic_usage),
        ("API项目", demo_api_project),
        ("AI项目", demo_ai_project),
        ("自定义模板", demo_custom_template),
        ("最小信息", demo_minimal_project),
        ("类型对比", demo_comparison),
    ]

    print("\n" + "=" * 80)
    print("Template Filler Service 演示")
    print("=" * 80)
    print("\n可用演示:")
    for i, (name, _) in enumerate(demos, 1):
        print(f"{i}. {name}")
    print("0. 运行所有演示")

    try:
        choice = input("\n请选择演示编号 (0-6): ").strip()

        if choice == "0":
            for _, demo_func in demos:
                demo_func()
        elif choice.isdigit() and 1 <= int(choice) <= len(demos):
            demos[int(choice) - 1][1]()
        else:
            print("无效选择")
    except KeyboardInterrupt:
        print("\n\n演示已取消")
    except Exception as e:
        print(f"\n错误: {e}")


if __name__ == "__main__":
    main()
