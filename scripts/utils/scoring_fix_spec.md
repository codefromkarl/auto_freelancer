# 评分系统修复方案

## 问题总结

### 问题 1: 货币识别与汇率转换失效

**问题现象**：
- 数据库中有 35 个 INR（印度卢比）项目
- config.py 中 `INR` 汇率是 0.012（几乎为 0）
- 项目如 `40119010` (INR 1500-12500) 被错误评分

**根本原因**：
1. `score_budget_efficiency()` 方法直接使用 `project.get('currency', {}).get('code', 'USD')`
2. 没有调用已有的 `_normalize_currency_code()` 方法
3. `_normalize_currency_code()` 返回 3 位代码（如 IND），但评分逻辑没有使用

### 问题 2: 工时估算不准确

**问题现象**：
- 小项目（$10-50）被估算为 33h
- 导致 $0.3-1.5/h 的极低时薪仍获得部分评分

**根本原因**：
- 工时估算逻辑对所有项目都加了基础工时
- 小任务被过度估算

### 问题 3: 需求清晰度评分方向错误

**问题现象**：
- 有模糊需求关键词的项目得分反而更高
- 因为模糊需求只是小幅扣分

---

## 修复方案

### 修复 1: 正确处理货币代码

**文件**: `python_service/services/project_scorer.py`

**修改位置**: `score_budget_efficiency()` 方法（第 258-323 行）

**修改内容**:
```python
def score_budget_efficiency(
    self, project: Dict[str, Any], estimated_hours: int
) -> float:
    # ... existing code ...

    # Fix: Use normalized currency code
    raw_currency = project.get("currency", {}).get("code", "USD")
    currency_code = self._normalize_currency_code(raw_currency)

    # Fix: Check if rate is available
    rate = settings.CURRENCY_RATES.get(currency_code, 1.0)
    if rate <= 0:
        # Fallback to 1.0 if rate not available
        rate = 1.0
        logger.warning(f"Currency {currency_code} rate not available, using fallback 1.0")

    avg_budget_usd = ((budget_min + budget_max) / 2) * rate

    # ... rest of method ...
```

---

### 修复 2: 优化工时估算

**文件**: `python_service/services/project_scorer.py`

**修改位置**: `estimate_project_hours()` 方法（第 145-256 行）

**修改内容**:
```python
def estimate_project_hours(self, project: Dict[str, Any]) -> int:
    title = project.get("title", "").lower()
    description = (project.get("full_description") or "").lower()
    combined_text = f"{title} {description}"

    hours = 0

    # Platform base hours
    if "web" in title or "website" in title:
        hours += 40
    elif "web" in combined_text:
        hours += 20  # Lower base for minor web tasks

    if "ios" in title or "iphone" in title or "ipad" in title:
        hours += 80
    elif "android" in title:
        hours += 80

    if "api" in title or "backend" in title or "database" in description:
        hours += 30

    # AI/ML complexity
    ai_keywords = [
        "machine learning",
        "ml ",
        "deep learning",
        "neural network",
        "nlp",
        "natural language",
        "computer vision",
        "predictive",
        "ai ",
        "artificial intelligence",
        "llm",
        "large language",
    ]
    ai_count = sum(1 for kw in ai_keywords if kw in combined_text)

    if ai_count > 0:
        hours += 40 + (ai_count - 1) * 20  # Base 40h + 20h per extra AI feature

    # Mobile app complexity (cross-platform)
    if ("ios" in title or "android" in title) and (
        "web" in title or "website" in title
    ):
        hours += 40  # Additional integration work for multi-platform

    # Integration complexity
    integration_keywords = [
        "payment gateway",
        "stripe",
        "paypal",
        "auth0",
        "firebase",
        "aws",
        "azure",
        "google cloud",
        "webhook",
        "third-party",
        "rest api",
        "graphql",
        "oauth",
        "social login",
    ]
    integration_count = sum(1 for kw in integration_keywords if kw in combined_text)
    if integration_count >= 2:
        hours += 30
    elif integration_count >= 1:
        hours += 15

    # Admin dashboard
    if "admin" in title or "dashboard" in title or "cms" in combined_text:
        hours += 25

    # User authentication
    if (
        "login" in combined_text
        or "authentication" in combined_text
        or "signup" in combined_text
    ):
        hours += 15

    # Security requirements
    if (
        "security" in combined_text
        or "encryption" in combined_text
        or "ssl" in combined_text
    ):
        hours += 10

    # Testing and QA
    if (
        "test" in combined_text
        or "qa" in combined_text
        or "unit test" in combined_text
    ):
        hours += 15

    # Project management overhead (10% of estimated hours)
    pm_overhead = int(hours * 0.1)
    hours += pm_overhead

    # Minimum 10 hours, maximum 500 hours
    estimated = max(10, min(hours, 500))
    logger.debug(f"Estimated {estimated} hours for project {project.get('id')}")
    return estimated
```

**改进说明**:
1. Web 平台判断更精确：检查 title vs combined_text
2. 移动端只在明确提到时才加分
3. 添加最小工时 10h，防止过低估算

---

### 修复 3: 优化需求清晰度评分

**文件**: `python_service/services/project_scorer.py`

**修改位置**: `score_requirement_quality()` 方法

**修改内容**:
```python
def score_requirement_quality(self, project: Dict[str, Any]) -> float:
    """
    Score requirement quality with risk keyword penalty (0-2.0 points).

    Weight: 25%

    Scoring rules:
    - Description length > 500: +0.5
    - Has clear deliverables: +0.5
    - Has acceptance criteria: +0.3
    - Has vague requirement keywords: -1.0 per category (NEW: higher penalty)
    - Maximum score: 2.0

    Args:
        project: Project data dictionary

    Returns:
        Quality score (0.0 to 2.0)
    """
    description = (
        project.get("full_description")
        or project.get("description")
        or project.get("preview_description", "")
    )

    if not description:
        return 0.0

    score = 0.0

    # Description length scoring
    if len(description) > 500:
        score += 0.5
    elif len(description) > 200:
        score += 0.3

    # Check for clear deliverables
    deliverable_keywords = [
        "deliverable",
        "deliverable is",
        "must deliver",
        "will deliver",
        "final deliverable",
        "project deliverable",
        "expected output",
    ]
    if any(keyword in description.lower() for keyword in deliverable_keywords):
        score += 0.5

    # Check for acceptance criteria
    acceptance_keywords = [
        "acceptance",
        "acceptance criteria",
        "验收标准",
        "验收 criterion",
        "approved if",
        "will be approved",
        "pass if",
        "success criteria",
    ]
    if any(keyword in description.lower() for keyword in acceptance_keywords):
        score += 0.3

    # Apply risk keyword penalty - HIGHER PENALTY
    risk_keywords = self.detect_risk_keywords(project)
    risk_categories_count = len(risk_keywords)

    # Each vague requirement category reduces score by 1.0
    # Maximum reduction of 2.0
    risk_penalty = min(risk_categories_count * 1.0, 2.0)
    score -= risk_penalty

    final_score = max(0.0, min(score, 2.0))
    logger.debug(
        f"Requirement quality score: {final_score} "
        f"(base: {score + risk_penalty}, risk_categories: {risk_categories_count}, "
        f"penalty: {risk_penalty})"
    )
    return final_score
```

---

### 修复 4: 添加 INR 汇率到 config.py

**文件**: `python_service/config.py`

**修改位置**: `CURRENCY_RATES` 字典（第 97-112 行）

**修改内容**:
```python
CURRENCY_RATES: Dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.1,
    "GBP": 1.3,
    "INR": 0.012,  # FIX: Add INR rate (1 INR ≈ 0.012 USD)
    "CAD": 0.75,
    "AUD": 0.65,
    "SGD": 0.74,
    "NZD": 0.60,
    "HKD": 0.13,
    "JPY": 0.0067,
    "CNY": 0.14,
    "MYR": 0.22,
    "PHP": 0.018,  # Used for Freelancer PHP payments
    "THB": 0.028,
}
```

---

## 验证方案

### 测试用例 1: INR 项目
```python
project = {
    'id': 40119010,
    'title': 'Telegram Automation',
    'type': 'fixed',
    'budget': {'minimum': 1500, 'maximum': 12500},
    'currency': {'code': 'INR'},  # Should be normalized to IND
    'currency_code': 'INR',
    ...
}
```

**预期结果**:
- 货币代码被规范化为 IND
- 汇率使用 0.012
- 预算 USD: (1500 + 12500) / 2 * 0.012 = 84 USD
- 时薪: 84 / estimated_hours
- 评分应反映极低时薪（预算效率得分应为 0.0）

### 测试用例 2: 小预算项目
```python
project = {
    'id': 40127977,
    'title': 'FastAPI Enhancement',
    'type': 'fixed',
    'budget': {'minimum': 10, 'maximum': 50},
    'currency': {'code': 'USD'},
    ...
}
```

**预期结果**:
- 工时估算应更准确（可能 5-10h）
- 时薪: $1-5/h
- 预算效率得分应为 0.0（极低）

---

## 任务拆分

| 任务 | 负责方 | 优先级 |
|------|--------|--------|
| 修复 1: 货币识别与汇率转换 | OpenCode | P0 |
| 修复 2: 优化工时估算 | Gemini | P0 |
| 修复 3: 优化需求清晰度评分 | Gemini | P1 |
| 修复 4: 添加 INR 汇率 | OpenCode | P1 |
| 验证修复效果 | 双方 | P2 |
