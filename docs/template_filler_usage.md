# Template Filler Service 使用指南

## 概述

`TemplateFillerService` 是一个智能模板填充服务,可以根据项目信息自动生成个性化的投标文本,避免手动填写模板的重复劳动。

## 核心功能

### 1. 自动提取项目需求
从项目标题和描述中识别核心需求:
- 动词+对象模式 (如 "build API", "scrape data")
- 技术关键词识别
- 智能回退机制

### 2. 匹配专业领域
根据技能标签和项目描述匹配相关领域:
- Python backend development
- FastAPI microservices
- Workflow automation
- AI application development
- 等20+领域

### 3. 选择相关案例
从简历中自动选择最匹配的项目经验:
- AI dialogue platform (100+ concurrent requests)
- RESTful backend (19 endpoints)
- Media generation workflow (15-26% efficiency)
- Data extraction system (10K+ pages daily)

### 4. 生成技术方案
针对项目需求自动组装解决方案:
- Scraping: Playwright/Selenium + proxy rotation
- API: FastAPI async endpoints + documentation
- Automation: Scheduled tasks + error retry
- AI: LLM integration + context management

### 5. 量化收益估算
根据项目类型预估价值提升:
- Automation: 60-80% time savings
- API: 10x traffic capacity
- Optimization: 30-50% speed improvement
- AI: 70% cost reduction

## 快速开始

### 基础用法

```python
from services.template_filler_service import fill_proposal_template

# 项目信息
project = {
    "title": "Build Python Web Scraping Tool",
    "description": "Need to scrape product data from e-commerce sites",
    "skills": ["python", "web scraping", "selenium"]
}

# 填充模板
proposal = fill_proposal_template(
    project=project,
    portfolio_link="https://github.com/yourusername"
)

print(proposal)
```

### 输出示例

```
Hi,

I noticed your project requires scraping development. With 8+ years specializing in Python backend development and data scraping and extraction, I've helped clients like Data extraction system processing 10K+ pages daily achieve proven delivery track record across multiple production systems.

**Why I'm a great fit:**
- ✅ Implement dynamic page scraping with Playwright/Selenium, including proxy rotation and anti-bot strategies for stability
- ✅ 8 years Python development experience, proficient in FastAPI/Django for high-concurrency backend systems
- 📊 Portfolio: https://github.com/yourusername

I focus on building long-term partnerships through consistent quality. My clients typically see Automated data collection can replace 90% manual gathering work.

**Next steps:**
Available for a quick call this week to discuss your specific requirements.

Best regards,
Yuanzhi
```

## 高级用法

### 自定义模板

```python
from services.template_filler_service import TemplateFillerService

# 自定义模板
custom_template = """
Hello,

Your project "[具体需求]" aligns perfectly with my expertise in [相关领域].

I've previously worked on [类似案例], achieving [具体成果].

My approach:
- [针对需求1的解决方案]
- [针对需求2的技术优势]

Expected outcome: [量化收益]

Portfolio: [链接]

Best,
Yuanzhi
"""

# 使用自定义模板
service = TemplateFillerService(portfolio_link="https://github.com/yourusername")
proposal = service.fill_template(custom_template, project)
```

### 集成到现有系统

```python
from services.proposal_service import ProposalService
from services.template_filler_service import fill_proposal_template

# 在 ProposalService 中使用
class EnhancedProposalService(ProposalService):
    def generate_quick_proposal(self, project):
        """快速生成模板化提案(无LLM调用)"""
        return fill_proposal_template(
            project=self._project_to_dict(project),
            portfolio_link="https://github.com/yourusername"
        )
```

## 占位符说明

| 占位符 | 说明 | 示例 |
|--------|------|------|
| `[具体需求]` | 项目核心需求 | "web scraping development" |
| `[相关领域]` | 匹配的专业领域 | "Python backend development and data scraping" |
| `[类似案例]` | 相关项目经验 | "Data extraction system processing 10K+ pages daily" |
| `[具体成果]` | 量化成果 | "proven delivery track record" |
| `[针对需求1的解决方案]` | 技术方案1 | "Implement dynamic page scraping with Playwright" |
| `[针对需求2的技术优势]` | 技术优势 | "8 years Python development experience" |
| `[量化收益]` | 预估收益 | "90% manual work replacement" |
| `[链接]` | 作品集链接 | "https://github.com/yourusername" |

## 配置扩展

### 添加新的技能映射

编辑 `template_filler_service.py`:

```python
SKILL_TO_DOMAIN_MAP = {
    # 添加新技能
    "react": "React frontend development",
    "vue": "Vue.js SPA development",
    # ...
}
```

### 添加新的解决方案模板

```python
REQUIREMENT_TO_SOLUTION_MAP = {
    # 添加新需求类型
    "mobile": "Develop cross-platform mobile app with React Native",
    "blockchain": "Implement smart contracts with Solidity and Web3.js",
    # ...
}
```

### 添加新的案例库

```python
# 在 _select_case_study 方法中添加
case_studies = {
    "blockchain": "DeFi platform with 1M+ daily transactions",
    "mobile": "E-commerce app with 50K+ active users",
    # ...
}
```

## 最佳实践

### 1. 保持模板简洁
- 目标长度: 800-1400字符
- 3段式结构: 需求理解 → 能力证明 → 行动召唤

### 2. 避免过度模板化
- 不要在所有项目中使用相同的模板
- 根据项目类型调整风格(简单任务用简洁模板,大型项目用详细模板)

### 3. 定期更新案例库
- 每完成一个项目,更新 `case_studies` 字典
- 添加最新的量化成果数据

### 4. A/B测试不同模板
```python
# 测试不同版本
templates = {
    "concise": "...",  # 简洁版
    "detailed": "...", # 详细版
    "technical": "..." # 技术版
}

# 根据项目类型选择
if project_budget < 500:
    template = templates["concise"]
else:
    template = templates["detailed"]
```

## 性能优化

### 缓存技能映射
```python
class CachedTemplateFillerService(TemplateFillerService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._domain_cache = {}

    def _match_domain(self, skills, project_text):
        cache_key = f"{','.join(skills)}:{project_text[:50]}"
        if cache_key not in self._domain_cache:
            self._domain_cache[cache_key] = super()._match_domain(skills, project_text)
        return self._domain_cache[cache_key]
```

## 故障排查

### 问题: 输出包含未填充的占位符
**原因**: 项目信息不完整或匹配失败
**解决**: 检查项目数据,确保至少有 `title` 或 `description`

### 问题: 生成的文本过于通用
**原因**: 技能标签为空或不匹配
**解决**:
1. 检查 `SKILL_TO_DOMAIN_MAP` 是否包含项目技能
2. 添加更多技能映射
3. 使用自定义模板

### 问题: 案例选择不相关
**原因**: 案例库关键词匹配失败
**解决**: 在 `_select_case_study` 中添加更多关键词匹配规则

## 测试

运行单元测试:
```bash
cd python_service
python -m pytest tests/test_template_filler.py -v
```

测试覆盖:
- ✅ 需求提取
- ✅ 领域匹配
- ✅ 案例选择
- ✅ 方案生成
- ✅ 完整模板填充
- ✅ 边界情况处理

## 未来改进

1. **机器学习优化**: 根据中标率自动调整模板策略
2. **多语言支持**: 支持中文/英文/其他语言模板
3. **动态案例库**: 从数据库加载历史项目案例
4. **A/B测试框架**: 自动测试不同模板的效果
5. **情感分析**: 根据客户描述调整语气风格

## 相关文档

- [ProposalService 文档](../python_service/services/proposal_service.py)
- [ProposalPromptBuilder 文档](../python_service/services/proposal_prompt_builder.py)
- [测试用例](../python_service/tests/test_template_filler.py)
