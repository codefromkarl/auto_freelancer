# 标书生成重构方案 - 评审总结

## 评审结果汇总

### Gemini 评审 (通过 ✅)

| 评审维度 | 评分 | 核心意见 |
|---------|------|---------|
| 职责分离合理性 | High | 评分与撰写解耦，互不影响迭代 |
| Persona Controller 设计 | High | 动态切换身份，关注点专业 |
| 三段式结构可行性 | Medium-High | 需要强指令约束，Validator 兜底必要 |
| 配置化方案实用性 | High | 非开发人员可直接调整话术 |

**Gemini 建议**:
1. 确保 `ProposalService` 能获取 `estimated_hours` 和 `hourly_rate`
2. 在 Prompt 中增加 One-Shot Example 提高结构遵循度

---

### OpenCode 评审 (通过 ✅)

| 评审维度 | 评分 | 核心意见 |
|---------|------|---------|
| 架构可扩展性 | ⭐⭐⭐⭐ | 基础良好，建议增强插件化 |
| 验证规则完整性 | ⭐⭐⭐ | 基础规则够用，缺少技术验证 |
| 模块化程度 | ⭐⭐⭐⭐ | 分层清晰，建议完全配置化 |
| 代码兼容性 | ⭐⭐⭐ | 需要分阶段迁移，保留兼容层 |

**OpenCode 建议**:

#### 必须改进项（实施前）
1. **验证规则补充**
   - 添加技术准确性验证
   - 添加重复内容检测
   - 添加规则严重级别（CRITICAL/WARNING）

2. **配置文件完整性**
   - 添加版本校验
   - 完全移除硬编码提示词
   - 添加配置 Schema 验证

3. **配置加载器**
   ```python
   class ProposalConfigLoader:
       SUPPORTED_VERSIONS = ["2.0"]

       def load(self, config_path: str) -> dict:
           # 验证版本
           # Schema 验证
   ```

#### 建议改进项（后续迭代）
1. **插件化扩展** - 支持动态添加新项目类型
2. **策略模式** - 三段式结构可扩展
3. **A/B 测试框架** - 提示词版本对比
4. **模板引擎** - 变量转义处理

#### 兼容性处理
1. 保留兼容层（标记为 deprecated）
2. 统一返回格式
3. 提供配置迁移脚本

---

## 整合后的优化方案

### 1. 新增模块

| 模块 | 负责人 | 优先级 |
|------|--------|--------|
| `ProposalConfigLoader` | Gemini | P0 (必须) |
| `ProposalValidator` | Gemini | P0 (必须) |
| `BidPersonaController` | Gemini | P0 (必须) |
| `ProposalPromptBuilder` | OpenCode | P0 (必须) |
| `ProposalService` | OpenCode | P0 (必须) |
| `TechnicalAccuracyValidator` | Gemini | P1 (实施前) |
| `DuplicateContentValidator` | Gemini | P1 (实施前) |

### 2. 更新的验证规则

```python
class ValidationResult:
    SEVERITY_CRITICAL = "critical"  # 直接拒绝
    SEVERITY_WARNING = "warning"    # 记录但通过

    issues: List[Tuple[str, str, str]]  # (message, pattern, severity)

class ProposalValidator:
    REQUIRED_CHECKS = {
        "word_count": TechnicalAccuracyValidator,      # 80-200 words
        "has_question": StructureValidator,             # 必须有问号
        "no_markdown_headers": StructureValidator,      # 无 Markdown 标题
        "no_forbidden_phrases": ForbiddenPhraseValidator,  # 禁用词
        "tech_accuracy": TechnicalAccuracyValidator,   # 技术栈匹配 (新增)
        "no_duplicates": DuplicateContentValidator,    # 重复检测 (新增)
    }
```

### 3. 配置文件结构更新

```yaml
# python_service/config/bid_prompts.yaml
version: "2.0"  # 必须字段，启动时验证

personas:
  frontend:
    id_hint: "..."
    experience_anchor: "..."
    question_types: [...]

styles:
  narrative:
    description: "..."
    directives: [...]

structures:
  three_step:
    class: "proposal_structures.ThreeStepStructure"
    steps: [...]

validation:
  rules:
    - name: "word_count"
      severity: "critical"
      min: 80
      max: 200
    - name: "tech_accuracy"
      severity: "warning"
      enabled: true
    - name: "duplicate_detection"
      severity: "warning"
      enabled: true
      history_limit: 5
      similarity_threshold: 0.8
```

---

## 更新后的实施任务拆分

### Phase 1: 基础设施 (Gemini 负责核心，OpenCode 支持配置)

#### Gemini 任务
| ID | 任务 | 文件 | 依赖 |
|----|------|------|------|
| G1 | `ProposalConfigLoader` | `proposal_config_loader.py` | - |
| G2 | `BidPersonaController` | `bid_persona_controller.py` | G1 |
| G3 | `ProposalValidator` | `proposal_validator.py` | G1 |
| G4 | `TechnicalAccuracyValidator` | `proposal_validator.py` | G1 |
| G5 | `DuplicateContentValidator` | `proposal_validator.py` | G1 |
| G6 | `bid_prompts.yaml` | `config/bid_prompts.yaml` | - |
| G7 | 单元测试 | `tests/test_*.py` | G2-G5 |

#### OpenCode 任务
| ID | 任务 | 文件 | 依赖 |
|----|------|------|------|
| O1 | `ProposalPromptBuilder` | `proposal_prompt_builder.py` | G1, G6 |
| O2 | `ProposalService` | `proposal_service.py` | O1, G3 |

### Phase 2: 核心集成 (OpenCode 负责)

| ID | 任务 | 文件 | 依赖 |
|----|------|------|------|
| O3 | 修改 LLM Scoring Service | `llm_scoring_service.py` | O2 |
| O4 | 修改 Project Scorer | `project_scorer.py` | O2 |
| O5 | 修改 Bid Service | `bid_service.py` | O2 |

### Phase 3: 测试与优化 (协作)

| ID | 任务 | 负责 | 依赖 |
|----|------|------|------|
| T1 | 集成测试 | Gemini | O3-O5 |
| T2 | 提案质量对比 | Gemini | O3-O5 |
| T3 | 性能测试 | OpenCode | O3-O5 |

---

## 关键接口契约

### Gemini → OpenCode 接口

```python
# ProposalConfigLoader
config = loader.load("config/bid_prompts.yaml")  # dict with version, personas, etc.

# BidPersonaController
project_type = persona_controller.detect_project_type(title, description)
hint = persona_controller.get_persona_hint(project_type)
anchor = persona_controller.get_experience_anchor(project_type)

# ProposalValidator
result = validator.validate(proposal, project_context={...})
# result.is_valid: bool
# result.issues: List[Tuple[str, str, str]]  # (msg, rule_name, severity)
```

### OpenCode → Gemini 接口

```python
# ProposalService
proposal = await proposal_service.generate_proposal(
    project=project_dict,
    score_data=score_dict,
    max_retries=2
)
```

---

## 实施检查清单

### 开始实施前 (P0)
- [ ] G1: `ProposalConfigLoader` 实现版本校验
- [ ] G3: `ProposalValidator` 包含技术准确性验证
- [ ] G3: `ProposalValidator` 包含重复内容检测
- [ ] G6: `bid_prompts.yaml` 完整配置

### 实施中 (P1)
- [ ] G2-G5: 所有模块通过单元测试
- [ ] O1-O2: OpenCode 模块通过单元测试
- [ ] 接口契约验证通过

### 实施后 (P2)
- [ ] T1: 集成测试全部通过
- [ ] T2: 新提案符合三段式结构
- [ ] T2: 新提案无明显 AI 痕迹
