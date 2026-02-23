# Template Filler 集成指南

## 集成方案

将 `TemplateFillerService` 集成到现有投标系统,提供快速模板化投标和LLM增强投标两种模式。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    Bidding Pipeline                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │  Project Evaluation   │
                │   (Score Service)     │
                └───────────────────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │   Proposal Strategy   │
                │   Selection           │
                └───────────────────────┘
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
    ┌──────────────────┐    ┌──────────────────┐
    │  Quick Template  │    │  LLM Enhanced    │
    │  (Fast, Cheap)   │    │  (Slow, Quality) │
    └──────────────────┘    └──────────────────┘
                │                       │
                │                       ▼
                │           ┌──────────────────┐
                │           │ ProposalService  │
                │           │ (LLM Generation) │
                │           └──────────────────┘
                │                       │
                └───────────┬───────────┘
                            ▼
                ┌───────────────────────┐
                │  Validation & Submit  │
                └───────────────────────┘
```

## 集成步骤

### 步骤1: 扩展 ProposalService

在 `proposal_service.py` 中添加快速模板生成方法:

```python
# python_service/services/proposal_service.py

from services.template_filler_service import fill_proposal_template

class ProposalService:
    # ... 现有代码 ...

    def generate_quick_proposal(
        self,
        project: Project,
        portfolio_link: str = "https://github.com/yourusername",
    ) -> str:
        """
        快速生成模板化提案(无LLM调用,秒级响应)

        适用场景:
        - 低价值项目(<$200)
        - 高竞争项目(>50 bids)
        - LLM服务不可用时的回退方案

        Args:
            project: 项目对象
            portfolio_link: 作品集链接

        Returns:
            模板化提案文本
        """
        project_dict = self._project_to_dict(project)
        return fill_proposal_template(
            project=project_dict,
            portfolio_link=portfolio_link,
        )

    async def generate_proposal_with_strategy(
        self,
        project: Project,
        score_data: Optional[Dict[str, Any]] = None,
        strategy: str = "auto",
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        根据策略生成提案

        Args:
            project: 项目对象
            score_data: 评分数据
            strategy: 生成策略
                - "auto": 自动选择(根据项目评分和预算)
                - "quick": 强制使用快速模板
                - "llm": 强制使用LLM生成
            db: 数据库会话

        Returns:
            提案结果字典
        """
        # 自动策略选择
        if strategy == "auto":
            strategy = self._select_strategy(project, score_data)

        if strategy == "quick":
            # 快速模板生成
            proposal = self.generate_quick_proposal(project)
            return {
                "success": True,
                "proposal": proposal,
                "attempts": 1,
                "validation_passed": True,
                "validation_issues": [],
                "model_used": "template",
                "latency_ms": 0,
                "error": None,
                "strategy": "quick_template",
            }
        else:
            # LLM增强生成
            result = await self.generate_proposal(project, score_data, db=db)
            result["strategy"] = "llm_enhanced"
            return result

    def _select_strategy(
        self,
        project: Project,
        score_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        自动选择生成策略

        策略规则:
        1. 低价值项目(<$200) → quick
        2. 高竞争项目(>50 bids) → quick
        3. 低评分项目(<6.0) → quick
        4. 其他 → llm

        Args:
            project: 项目对象
            score_data: 评分数据

        Returns:
            策略名称 ("quick" 或 "llm")
        """
        # 规则1: 低价值项目
        budget_max = float(project.budget_maximum or 0)
        if budget_max > 0 and budget_max < 200:
            logger.info(f"Project {project.freelancer_id}: Using quick template (low budget: ${budget_max})")
            return "quick"

        # 规则2: 高竞争项目
        bid_stats = project.bid_stats
        if isinstance(bid_stats, str):
            try:
                bid_stats = json.loads(bid_stats)
            except:
                bid_stats = {}
        bid_count = bid_stats.get("bid_count", 0) if isinstance(bid_stats, dict) else 0
        if bid_count > 50:
            logger.info(f"Project {project.freelancer_id}: Using quick template (high competition: {bid_count} bids)")
            return "quick"

        # 规则3: 低评分项目
        if score_data and score_data.get("score", 10) < 6.0:
            logger.info(f"Project {project.freelancer_id}: Using quick template (low score: {score_data.get('score')})")
            return "quick"

        # 默认: LLM增强
        logger.info(f"Project {project.freelancer_id}: Using LLM enhanced generation")
        return "llm"
```

### 步骤2: 更新 API 端点

在 `api/proposals.py` 中添加策略选择参数:

```python
# python_service/api/proposals.py

@router.post("/generate")
async def generate_proposal(
    request: ProposalRequest,
    strategy: str = Query("auto", description="Generation strategy: auto, quick, llm"),
    db: Session = Depends(get_db),
):
    """
    生成投标提案

    Args:
        request: 提案请求
        strategy: 生成策略
            - auto: 自动选择(默认)
            - quick: 快速模板
            - llm: LLM增强
    """
    try:
        # 获取项目
        project = db.query(Project).filter(
            Project.freelancer_id == request.project_id
        ).first()

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # 生成提案
        service = get_proposal_service()
        result = await service.generate_proposal_with_strategy(
            project=project,
            score_data=request.score_data,
            strategy=strategy,
            db=db,
        )

        return result

    except Exception as e:
        logger.error(f"Proposal generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### 步骤3: 配置环境变量

在 `.env` 中添加配置:

```bash
# Template Filler 配置
PORTFOLIO_LINK=https://github.com/yourusername
QUICK_TEMPLATE_ENABLED=true
AUTO_STRATEGY_ENABLED=true

# 策略阈值
QUICK_TEMPLATE_BUDGET_THRESHOLD=200
QUICK_TEMPLATE_BID_COUNT_THRESHOLD=50
QUICK_TEMPLATE_SCORE_THRESHOLD=6.0
```

### 步骤4: 更新配置文件

在 `config.py` 中添加配置项:

```python
# python_service/config.py

class Settings(BaseSettings):
    # ... 现有配置 ...

    # Template Filler 配置
    PORTFOLIO_LINK: str = "https://github.com/yourusername"
    QUICK_TEMPLATE_ENABLED: bool = True
    AUTO_STRATEGY_ENABLED: bool = True

    # 策略阈值
    QUICK_TEMPLATE_BUDGET_THRESHOLD: float = 200.0
    QUICK_TEMPLATE_BID_COUNT_THRESHOLD: int = 50
    QUICK_TEMPLATE_SCORE_THRESHOLD: float = 6.0
```

## 使用示例

### 示例1: 自动策略选择

```python
# 自动选择最佳策略
result = await service.generate_proposal_with_strategy(
    project=project,
    score_data=score_data,
    strategy="auto",  # 自动选择
)

print(f"Strategy used: {result['strategy']}")
print(f"Proposal: {result['proposal']}")
```

### 示例2: 强制使用快速模板

```python
# 强制使用快速模板(适合批量投标)
result = await service.generate_proposal_with_strategy(
    project=project,
    strategy="quick",  # 强制快速模板
)

# 秒级响应,无LLM成本
print(f"Latency: {result['latency_ms']}ms")
```

### 示例3: 强制使用LLM

```python
# 强制使用LLM(适合高价值项目)
result = await service.generate_proposal_with_strategy(
    project=project,
    score_data=score_data,
    strategy="llm",  # 强制LLM
)

# 高质量输出,但有延迟和成本
print(f"Model: {result['model_used']}")
print(f"Validation: {result['validation_passed']}")
```

## 性能对比

| 指标 | Quick Template | LLM Enhanced |
|------|----------------|--------------|
| 响应时间 | <100ms | 2-5s |
| API成本 | $0 | $0.001-0.01 |
| 质量评分 | 6-7/10 | 8-9/10 |
| 个性化程度 | 中等 | 高 |
| 适用场景 | 批量投标 | 重点项目 |

## 监控指标

### 添加策略使用统计

```python
# python_service/services/proposal_metrics.py

class ProposalMetrics:
    def __init__(self):
        self.strategy_usage = {
            "quick": 0,
            "llm": 0,
        }
        self.strategy_success_rate = {
            "quick": [],
            "llm": [],
        }

    def record_strategy_usage(self, strategy: str, success: bool):
        """记录策略使用情况"""
        self.strategy_usage[strategy] += 1
        self.strategy_success_rate[strategy].append(1 if success else 0)

    def get_strategy_stats(self) -> Dict[str, Any]:
        """获取策略统计"""
        return {
            "usage": self.strategy_usage,
            "success_rate": {
                strategy: sum(results) / len(results) if results else 0
                for strategy, results in self.strategy_success_rate.items()
            },
        }
```

## 测试

### 单元测试

```python
# python_service/tests/test_proposal_integration.py

async def test_quick_template_generation():
    """测试快速模板生成"""
    service = ProposalService()
    project = create_test_project(budget_maximum=150)

    result = await service.generate_proposal_with_strategy(
        project=project,
        strategy="quick",
    )

    assert result["success"]
    assert result["strategy"] == "quick_template"
    assert result["latency_ms"] < 100
    assert len(result["proposal"]) > 200

async def test_auto_strategy_selection():
    """测试自动策略选择"""
    service = ProposalService()

    # 低价值项目 → quick
    low_budget_project = create_test_project(budget_maximum=150)
    result = await service.generate_proposal_with_strategy(
        project=low_budget_project,
        strategy="auto",
    )
    assert result["strategy"] == "quick_template"

    # 高价值项目 → llm
    high_budget_project = create_test_project(budget_maximum=1000)
    result = await service.generate_proposal_with_strategy(
        project=high_budget_project,
        strategy="auto",
    )
    assert result["strategy"] == "llm_enhanced"
```

### 集成测试

```bash
# 测试快速模板API
curl -X POST "http://localhost:8000/api/proposals/generate?strategy=quick" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "12345",
    "score_data": {"score": 7.5}
  }'

# 测试自动策略API
curl -X POST "http://localhost:8000/api/proposals/generate?strategy=auto" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "12345",
    "score_data": {"score": 7.5}
  }'
```

## 部署建议

### 1. 灰度发布

```python
# 10%流量使用快速模板
import random

def should_use_quick_template() -> bool:
    return random.random() < 0.1  # 10%概率

if should_use_quick_template():
    strategy = "quick"
else:
    strategy = "llm"
```

### 2. A/B测试

```python
# 记录策略和中标率
def track_bid_result(project_id: str, strategy: str, won: bool):
    """跟踪投标结果"""
    metrics.record_bid_result(
        project_id=project_id,
        strategy=strategy,
        won=won,
    )

# 分析哪种策略中标率更高
stats = metrics.get_strategy_performance()
print(f"Quick template win rate: {stats['quick']['win_rate']}")
print(f"LLM enhanced win rate: {stats['llm']['win_rate']}")
```

### 3. 成本优化

```python
# 根据预算动态调整策略
def optimize_strategy(project_budget: float, daily_llm_cost: float) -> str:
    """成本优化策略选择"""
    MAX_DAILY_LLM_COST = 10.0  # $10/天

    if daily_llm_cost >= MAX_DAILY_LLM_COST:
        return "quick"  # 超出预算,使用免费模板

    if project_budget < 200:
        return "quick"  # 低价值项目不值得LLM成本

    return "llm"  # 高价值项目使用LLM
```

## 故障排查

### 问题1: 快速模板质量不足

**症状**: 使用快速模板后中标率下降

**解决方案**:
1. 更新 `SKILL_TO_DOMAIN_MAP` 增加技能覆盖
2. 丰富 `case_studies` 案例库
3. 调整 `QUICK_TEMPLATE_BUDGET_THRESHOLD` 阈值
4. 考虑混合策略(模板+LLM润色)

### 问题2: 策略选择不合理

**症状**: 高价值项目使用了快速模板

**解决方案**:
1. 检查 `_select_strategy` 逻辑
2. 调整阈值配置
3. 添加更多策略规则(如客户评级、项目类型)

### 问题3: 模板输出格式问题

**症状**: 生成的文本包含未填充占位符

**解决方案**:
1. 检查项目数据完整性
2. 添加更多回退逻辑
3. 使用 `validation` 检查输出质量

## 下一步优化

1. **混合策略**: 模板生成 + LLM润色(兼顾速度和质量)
2. **动态模板**: 根据项目类型选择不同模板
3. **学习优化**: 根据中标率自动调整模板内容
4. **多语言支持**: 支持中文/英文/其他语言项目
5. **个性化**: 根据客户历史偏好调整模板风格

## 相关文档

- [TemplateFillerService 使用指南](./template_filler_usage.md)
- [ProposalService 文档](../python_service/services/proposal_service.py)
- [API 文档](../python_service/api/proposals.py)
