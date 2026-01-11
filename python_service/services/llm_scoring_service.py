"""
Concurrent LLM scoring service with multiple API providers support.

Design Principles:
- Dependency Injection: No global singletons for better testability
- Factory Pattern: Easy service creation with custom configurations
- Provider Abstraction: Unified interface for multiple LLM providers
- Caching: Reduce redundant LLM API calls with intelligent caching

IMPORTANT: This module supports both dependency injection and singleton access.
For convenience, use `get_scoring_service()` which maintains a singleton internally.
For testing, use `create_scoring_service()` to create fresh instances
or `reset_singleton()` to clear cached state.
"""

from typing import List, Dict, Any, Optional, Tuple, Callable
import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from decimal import Decimal

from config import settings
from database.models import Project
from sqlalchemy.orm import Session
from utils.currency_converter import get_currency_converter
from services.project_scorer import get_project_scorer

logger = logging.getLogger(__name__)


@dataclass
class LLMProviderConfig:
    """
    LLM Provider 配置（依赖注入友好）。

    Attributes:
        name: Provider 标识符 (openai, anthropic, zhipu, deepseek)
        api_key: API 密钥
        base_url: API 基础 URL
        model: 模型名称
        enabled: 是否启用
        priority: 优先级（数值越小优先级越高）
        max_retries: 最大重试次数
        timeout: 超时时间（秒）
    """

    name: str
    api_key: str
    base_url: Optional[str] = None
    model: str = "gpt-4o-mini"
    enabled: bool = True
    priority: int = 0
    max_retries: int = 2
    timeout: float = 30.0


@dataclass
class LLMScoringConfig:
    """
    LLM 评分服务配置。

    Attributes:
        providers: Provider 配置列表
        batch_size: 批量处理大小
        default_system_prompt: 默认系统提示词
        rate_limit_delay: 批次间延迟（秒）
        cache_ttl: 缓存 TTL（秒），0 表示禁用缓存
        cache_enabled: 是否启用缓存
        on_score_complete: 评分完成回调
    """

    providers: List[LLMProviderConfig] = field(default_factory=list)
    batch_size: int = 5
    default_system_prompt: Optional[str] = None
    rate_limit_delay: float = 0.5
    cache_ttl: int = 3600  # 1小时缓存
    cache_enabled: bool = True
    on_score_complete: Optional[Callable[[Dict[str, Any]], None]] = None

    @classmethod
    def from_settings(cls) -> "LLMScoringConfig":
        """从应用配置创建默认配置"""
        settings_providers = settings.get_enabled_llm_providers()
        providers = [
            LLMProviderConfig(
                name=p["name"],
                api_key=p["api_key"],
                base_url=p.get("base_url"),
                model=p.get("model", "gpt-4o-mini"),
                enabled=True,
                priority=i,
            )
            for i, p in enumerate(settings_providers)
        ]

        return cls(
            providers=providers,
            batch_size=5,
            default_system_prompt=_get_default_system_prompt(),
            rate_limit_delay=0.5,
            cache_ttl=3600,
            cache_enabled=True,
        )


def _get_default_system_prompt() -> str:
    """获取默认系统提示词（仅用于评分，不包含提案生成逻辑）"""
    return """
You are an expert Freelancer project evaluator. Your goal is to identify
projects with HIGH WIN RATE and COMPLETION RATE for a senior developer.

PRIMARY GOAL: Maximize win rate and successful project completion, not just profit.

EVALUATION WORKFLOW:
1. Estimate Workload:
   - Simple scripts/automation: 5-15h (small task multiplier 0.1-0.3)
   - Bug fixes/updates: 10-20h
   - API integration/Scraping: 15-30h
   - Mobile apps (iOS/Android): 60-120h+
   - Web Platform: 40-80h+
   - AI/LLM integration: +20h extra complexity

2. Calculate Hourly Rate: (budget_max) / (estimated_hours)
   - $20-60/hour: OPTIMAL for win rate (Score 8-10)
   - $60-80/hour: GOOD but competitive (Score 6-8)
   - $80+/hour: HIGH RISK - hard to win (Score 4-6)
   - $15-20/hour: FAIR (Score 6-8)
   - <$15/hour: LOW VALUE (Score < 5)

3. Assess Competition:
   - 0-4 bids: SUSPICIOUS - likely low quality (Score 2)
   - 5-20 bids: OPTIMAL for win rate (Score 10)
   - 21-40 bids: MODERATE competition (Score 6)
   - >40 bids: HIGH competition - hard to win (Score 2)
   - New projects (<24h old): BONUS - slightly higher score

4. Identify Risks & Clarity:
   - Clarity: Does it name specific deliverables, acceptance criteria, tools?
   - Vague keywords (e.g., "optimize", "insights", "improve") reduce clarity score
   - Long descriptions without technical details are LOW QUALITY signals

SCORING CRITERIA (0-10) - WIN RATE OPTIMIZED:
- Budget Efficiency (15%): $20-60/h is optimal. High rates ($80+) hurt win rate.
- Competition (25%): 5-20 bids is optimal. Too few = bad project, too many = hard to win.
- Requirement Clarity (25%): Specific deliverables and acceptance criteria required.
- Client Trust (20%): Payment verification and hire rate are CRITICAL for completion.
- Technical Match (10%): Must fit standard stacks (Python, API, automation).
- Risk Assessment (5%): Overall project risk evaluation.

SCORING RULES (WIN RATE FOCUS):
- Hourly rate $20-60 MUST result in Budget score >= 8.0.
- Hourly rate $80+ MUST result in Budget score <= 6.0 (hard to win).
- Payment NOT verified MUST result in Client score <= 5.0.
- New client (0 projects) MUST result in Client score <= 5.0.
- Bid count 5-20 MUST result in Competition score >= 8.0.
- Bid count 0-4 MUST result in Competition score <= 3.0 (suspicious).

Return strict JSON only:
{
    "score": 7.5,
    "reason": "Clear explanation (2-3 sentences)",
    "suggested_bid": 500,
    "estimated_hours": 40,
    "hourly_rate": 25.0,
    "risk_keywords": ["insights"]
}
"""


class LLMProvider(ABC):
    """LLM Provider 抽象接口"""

    @abstractmethod
    def get_client(self):
        """获取异步客户端实例"""
        pass

    @abstractmethod
    async def score(
        self, client, model: str, payload: Dict[str, Any], system_prompt: str
    ) -> Optional[Dict[str, Any]]:
        """使用此 provider 进行评分"""
        pass

    @abstractmethod
    async def close(self, client):
        """关闭客户端连接"""
        pass

    def _parse_response(self, content: str, model: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 响应 (REF-005)"""
        import re

        parsed = None

        # 1. 尝试从 Markdown 代码块提取
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Failed to parse JSON from markdown block in {model} response: {e}"
                )

        # 2. 纯 JSON 回退
        if not parsed:
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # 3. 提取第一个 { 和最后一个 }
                start_idx = content.find("{")
                end_idx = content.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    try:
                        parsed = json.loads(content[start_idx : end_idx + 1])
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"Failed to parse JSON from extracted substring in {model} response: {e}"
                        )

        if not parsed:
            logger.error(
                f"Could not extract valid JSON from {model} response. Content snippet: {content[:200]}"
            )
            return None

        try:
            score = float(parsed.get("score", 0.0))
            return {
                "score": max(0.0, min(10.0, score)),
                "reason": str(parsed.get("reason", "")).strip()
                or "No reason provided.",
                "suggested_bid": self._parse_float(parsed.get("suggested_bid")),
                "estimated_hours": self._parse_int(parsed.get("estimated_hours")),
                "hourly_rate": self._parse_float(parsed.get("hourly_rate")),
                "provider_model": model,
            }
        except Exception as e:
            logger.error(f"Error processing parsed LLM fields from {model}: {e}")
            return None

    def _parse_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_int(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 Provider"""

    def get_client(self, api_key: str, base_url: Optional[str]):
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def score(
        self, client, model: str, payload: Dict[str, Any], system_prompt: str
    ) -> Optional[Dict[str, Any]]:
        """Score project using OpenAI-compatible API."""
        try:
            result = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                temperature=0.2,
            )
            content = (result.choices[0].message.content or "").strip()
            return self._parse_response(content, model)
        except Exception as exc:
            logger.error(f"OpenAI scoring failed: {exc}")
            return None

    async def close(self, client):
        if hasattr(client, "close"):
            await client.close()


class AnthropicProvider(LLMProvider):
    """Anthropic Claude Provider"""

    def get_client(self, api_key: str, base_url: Optional[str] = None):
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=api_key)

    async def score(
        self, client, model: str, payload: Dict[str, Any], system_prompt: str
    ) -> Optional[Dict[str, Any]]:
        """Score project using Anthropic API."""
        try:
            result = await client.messages.create(
                model=model,
                max_tokens=1000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": json.dumps(payload)},
                ],
            )
            content = result.content[0].text
            return self._parse_response(content, model)
        except Exception as exc:
            logger.error(f"Anthropic scoring failed: {exc}")
            return None

    async def close(self, client):
        if hasattr(client, "close"):
            await client.close()


class LLMScoringService:
    """
    Service for scoring projects using multiple LLM providers in parallel.

    This class supports both configuration-based initialization and
    dependency injection for flexible usage patterns.

    Attributes:
        config: Service configuration
        providers: List of enabled providers sorted by priority
    """

    # Provider 类映射
    PROVIDER_CLASSES = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "zhipu": OpenAIProvider,  # OpenAI compatible
        "deepseek": OpenAIProvider,  # OpenAI compatible
    }

    def __init__(self, config: Optional[LLMScoringConfig] = None):
        """
        Initialize scoring service with optional configuration.

        Args:
            config: Service configuration. If None, uses defaults from settings.
        """
        self.config = config or LLMScoringConfig.from_settings()

        # 按优先级排序 providers
        self.providers = sorted(
            [p for p in self.config.providers if p.enabled], key=lambda p: p.priority
        )

        # 初始化缓存
        self._cache = None
        if self.config.cache_enabled:
            from services.scoring_cache import ScoringCache, CacheConfig

            cache_config = CacheConfig(
                enabled=True,
                ttl=self.config.cache_ttl,
                max_size=1000,
                persistent=True,
                persist_path="data/llm_scoring_cache.json",
            )
            self._cache = ScoringCache(cache_config)

        logger.info(
            f"LLMScoringService initialized with {len(self.providers)} providers, "
            f"cache={'enabled' if self._cache else 'disabled'}"
        )

    def _create_provider_client(
        self, provider_config: LLMProviderConfig
    ) -> Tuple[LLMProvider, Any]:
        """创建指定 provider 的客户端"""
        provider_class = self.PROVIDER_CLASSES.get(provider_config.name)
        if not provider_class:
            raise ValueError(f"Unknown provider: {provider_config.name}")

        provider = provider_class()
        client = provider.get_client(provider_config.api_key, provider_config.base_url)
        return provider, client

    def _prepare_project_payload(self, project: Project) -> Dict[str, Any]:
        """Prepare project data for LLM scoring (Forces USD conversion)."""
        converter = get_currency_converter()
        currency_code = project.currency_code or "USD"

        # Convert budget to USD to prevent LLM hallucinations with high-value currencies (e.g. INR, IDR)
        # Properly handle Decimal type from database
        budget_min = (
            float(project.budget_minimum)
            if project.budget_minimum is not None and float(project.budget_minimum) > 0
            else 0.0
        )
        budget_max = (
            float(project.budget_maximum)
            if project.budget_maximum is not None and float(project.budget_maximum) > 0
            else 0.0
        )

        rate = converter.get_rate_sync(currency_code)
        budget_min_usd = (
            (budget_min * rate) if budget_min > 0 and rate is not None else None
        )
        budget_max_usd = (
            (budget_max * rate) if budget_max > 0 and rate is not None else None
        )

        return {
            "id": project.freelancer_id,
            "title": project.title,
            "description": project.description or project.preview_description or "",
            "budget_minimum": budget_min_usd,  # Sent as USD
            "budget_maximum": budget_max_usd,  # Sent as USD
            "currency_code": "USD",  # Explicitly tell LLM it's USD
            "original_currency": currency_code,
            "skills": project.skills,
            "bid_stats": json.loads(project.bid_stats) if project.bid_stats else None,
            "owner_info": json.loads(project.owner_info)
            if project.owner_info
            else None,
        }

    async def _score_with_providers(
        self,
        payload: Dict[str, Any],
        provider_clients: Optional[
            List[Tuple[LLMProvider, Any, LLMProviderConfig]]
        ] = None,
        system_prompt: Optional[str] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Score using multiple providers concurrently with race/ensemble modes."""
        effective_prompt = system_prompt or self.config.default_system_prompt
        mode = getattr(settings, "LLM_SCORING_MODE", "ensemble").lower()

        local_provider_clients = provider_clients
        if local_provider_clients is None:
            local_provider_clients = []
            for provider_config in self.providers:
                try:
                    provider, client = self._create_provider_client(provider_config)
                    local_provider_clients.append((provider, client, provider_config))
                except Exception as e:
                    logger.error(
                        f"Failed to create client for {provider_config.name}: {e}"
                    )

        if not local_provider_clients:
            return False, None

        async def _score_provider(
            provider: LLMProvider, client: Any, provider_config: LLMProviderConfig
        ) -> Optional[Dict[str, Any]]:
            try:
                return await provider.score(
                    client, provider_config.model, payload, effective_prompt
                )
            except Exception as e:
                logger.warning(
                    f"Provider {provider_config.name} failed for payload {payload.get('id')}: {e}"
                )
                return None

        tasks = [
            asyncio.create_task(_score_provider(provider, client, provider_config))
            for provider, client, provider_config in local_provider_clients
        ]

        if mode == "race":
            try:
                for task in asyncio.as_completed(tasks):
                    result = await task
                    if result:
                        for pending in tasks:
                            if not pending.done():
                                pending.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        return True, result
            finally:
                await asyncio.gather(*tasks, return_exceptions=True)
            return False, None

        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid_results = [r for r in results if isinstance(r, dict) and r is not None]
        if not valid_results:
            return False, None

        aggregated = self._aggregate_ensemble(valid_results)
        return True, aggregated

    def _aggregate_ensemble(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate multiple provider results into a single ensemble output."""
        best = max(results, key=lambda r: r.get("score", 0.0))
        numeric_fields = ["score", "suggested_bid", "estimated_hours", "hourly_rate"]
        aggregated: Dict[str, Any] = {
            "reason": best.get("reason"),
            "provider_model": "ensemble",
        }

        for field in numeric_fields:
            values = [r.get(field) for r in results if r.get(field) is not None]
            if values:
                avg_value = sum(values) / len(values)
                if field == "score":
                    avg_value = max(0.0, min(10.0, avg_value))
                aggregated[field] = avg_value
            else:
                aggregated[field] = None

        return aggregated

    async def score_projects_concurrent(
        self,
        projects: List[Project],
        db: Session,
        batch_size: Optional[int] = None,
        max_retries: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> Tuple[int, int, float, Optional[int]]:
        """
        Score multiple projects concurrently using multiple LLM providers.

        Args:
            projects: List of projects to score
            db: Database session for updating results
            batch_size: Number of concurrent requests (override config)
            max_retries: Retry attempts per project (override config)
            system_prompt: Custom system prompt (override config)

        Returns:
            (total_scored, errors, top_score, top_id)
        """
        if not self.providers:
            logger.error("No enabled LLM providers found")
            return 0, len(projects), 0.0, None

        effective_batch_size = batch_size or self.config.batch_size
        effective_max_retries = (
            max_retries or self.providers[0].max_retries if self.providers else 2
        )
        effective_prompt = system_prompt or self.config.default_system_prompt

        # 创建所有 provider 客户端
        provider_clients: List[Tuple[LLMProvider, Any, LLMProviderConfig]] = []
        for provider_config in self.providers:
            try:
                provider, client = self._create_provider_client(provider_config)
                provider_clients.append((provider, client, provider_config))
            except Exception as e:
                logger.error(f"Failed to create client for {provider_config.name}: {e}")

        if not provider_clients:
            logger.error("No provider clients could be created")
            return 0, len(projects), 0.0, None

        async def score_single_project(
            project: Project, retry_count: int = 0
        ) -> Tuple[bool, Optional[Dict[str, Any]]]:
            """Score a single project with retry logic and caching."""
            payload = self._prepare_project_payload(project)

            # 生成提示词哈希作为缓存键的一部分
            prompt_hash = hashlib.md5((effective_prompt or "").encode()).hexdigest()[:8]

            # 先检查缓存
            if self._cache:
                cached_result = self._cache.get_llm_score(payload, prompt_hash)
                if cached_result:
                    logger.debug(f"Cache hit for project {project.freelancer_id}")
                    return True, cached_result

            success, result = await self._score_with_providers(
                payload, provider_clients, effective_prompt
            )
            if success and result:
                if self._cache:
                    self._cache.set_llm_score(payload, result, prompt_hash)
                return True, result

            # 所有 provider 都失败，重试
            if retry_count < effective_max_retries:
                await asyncio.sleep(1 + retry_count)
                return await score_single_project(project, retry_count + 1)

            return False, None

        async def process_batch(batch: List[Project]) -> List[Dict[str, Any]]:
            """Process a batch of projects concurrently."""
            tasks = [score_single_project(p) for p in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            scored_results = []
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    logger.error(f"Batch processing error: {res}")
                    continue

                success, result = res
                if success and result:
                    scored_results.append(
                        {"project_id": batch[i].freelancer_id, **result}
                    )

            return scored_results

        # 处理所有项目
        total_scored = 0
        errors = 0
        top_score = 0.0
        top_id = None

        for start in range(0, len(projects), effective_batch_size):
            batch = projects[start : start + effective_batch_size]
            scored = await process_batch(batch)

            # Sanitization and Fallback Logic
            scorer = get_project_scorer()

            for item in scored:
                project_id = item["project_id"]
                score = item["score"]

                # Retrieve original project object from batch
                project_obj = next(
                    (p for p in batch if p.freelancer_id == project_id), None
                )
                if not project_obj:
                    continue

                # 1. Fallback for estimated_hours
                if not item.get("estimated_hours") or item.get("estimated_hours") == 0:
                    project_dict = project_obj.to_dict()
                    estimated = scorer.estimate_project_hours(project_dict)
                    item["estimated_hours"] = estimated
                    logger.info(
                        f"Project {project_id}: LLM failed to estimate hours, fallback to {estimated}h"
                    )

                # 2. Recalculate/Validate Hourly Rate (using USD budget)
                # LLM might have failed math or used wrong budget
                est_hours = item.get("estimated_hours")

                # Get USD budget again (safe recalculation)
                converter = get_currency_converter()
                curr_code = project_obj.currency_code or "USD"
                # Properly handle Decimal type from database
                b_min = (
                    float(project_obj.budget_minimum)
                    if project_obj.budget_minimum is not None
                    and float(project_obj.budget_minimum) > 0
                    else 0.0
                )
                b_max = (
                    float(project_obj.budget_maximum)
                    if project_obj.budget_maximum is not None
                    and float(project_obj.budget_maximum) > 0
                    else 0.0
                )

                rate = converter.get_rate_sync(curr_code)
                b_min_usd = (b_min * rate) if b_min > 0 and rate is not None else None
                b_max_usd = (b_max * rate) if b_max > 0 and rate is not None else None

                # Check project type (1=Fixed, 2=Hourly usually, but handle None type_id)
                # If Hourly (type_id=2), rate is the budget itself
                is_hourly = project_obj.type_id == 2

                if is_hourly:
                    # Hourly project: rate is the budget itself
                    calculated_rate = (
                        (b_min_usd + b_max_usd) / 2
                        if (b_min_usd and b_max_usd)
                        else (b_max_usd or b_min_usd)
                    )
                    # Use calculated rate if LLM deviates significantly (>50%)
                    llm_rate = item.get("hourly_rate")
                    if (
                        not llm_rate
                        or abs(llm_rate - calculated_rate) > calculated_rate * 0.5
                    ):
                        item["hourly_rate"] = round(calculated_rate, 2)
                else:
                    # Fixed price: Rate = Budget / Hours
                    avg_budget = (
                        (b_min_usd + b_max_usd) / 2
                        if (b_min_usd and b_max_usd)
                        else (b_max_usd or b_min_usd)
                    )
                    if avg_budget and est_hours and est_hours > 0:
                        calculated_rate = avg_budget / est_hours
                        # Sanity check: hourly rate should be reasonable ($15-$200/h)
                        if calculated_rate > 200:
                            logger.warning(
                                f"Project {project_id}: Calculated rate {calculated_rate} exceeds $200/h threshold"
                            )
                            item["hourly_rate"] = 200.0
                        elif calculated_rate < 10:
                            logger.warning(
                                f"Project {project_id}: Calculated rate {calculated_rate} below $10/h threshold"
                            )
                            item["hourly_rate"] = 10.0
                        else:
                            item["hourly_rate"] = round(calculated_rate, 2)
                    else:
                        logger.warning(
                            f"Project {project_id}: Cannot calculate hourly rate (no budget or hours)"
                        )
                        item["hourly_rate"] = 0.0

                # 3. Sanity check Suggested Bid
                # Should not exceed budget max (for fixed)
                s_bid = item.get("suggested_bid")
                if s_bid and b_max_usd and s_bid > b_max_usd * 1.2:  # Allow 20% over
                    logger.warning(
                        f"Project {project_id}: Suggested bid {s_bid} > budget max {b_max_usd}. Clamping."
                    )
                    item["suggested_bid"] = round(b_max_usd, 2)

                # 详细日志：记录LLM返回的所有字段
                logger.info(
                    f"[LLM DETAIL] Project {project_id}: score={score:.1f}, "
                    f"provider={item.get('provider_model', 'unknown')}, "
                    f"hours={item.get('estimated_hours')}, "
                    f"rate={item.get('hourly_rate')}, "
                    f"reason={item.get('reason', '')[:100]}"
                )

                # 更新数据库（提案生成已移至 ProposalService，此处仅更新评分相关字段）
                from services import project_service

                project_service.update_project_ai_analysis(
                    db,
                    project_id,
                    score,
                    item["reason"],
                    "",  # ai_proposal_draft - now generated by ProposalService
                    item.get("suggested_bid"),
                    estimated_hours=item.get("estimated_hours"),
                    hourly_rate=item.get("hourly_rate"),
                )

                total_scored += 1
                if score > top_score:
                    top_score = score
                    top_id = project_id

                # 回调
                if self.config.on_score_complete:
                    try:
                        self.config.on_score_complete(item)
                    except Exception as e:
                        logger.warning(f"on_score_complete callback failed: {e}")

            errors += len(batch) - len(scored)

            # 批次间延迟
            if start + effective_batch_size < len(projects):
                await asyncio.sleep(self.config.rate_limit_delay)

        # 关闭所有客户端
        for provider, client, _ in provider_clients:
            try:
                await provider.close(client)
            except Exception as e:
                logger.warning(f"Error closing client: {e}")

        return total_scored, errors, top_score, top_id

    async def score_single_project(
        self,
        project: Project,
        system_prompt: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Score a single project using the best available provider.

        Args:
            project: Project to score
            system_prompt: Optional custom system prompt

        Returns:
            Scoring result or None if failed
        """
        if not self.providers:
            logger.error("No enabled LLM providers found")
            return None

        effective_prompt = system_prompt or self.config.default_system_prompt

        # 创建客户端
        provider_clients = []
        for provider_config in self.providers:
            try:
                provider, client = self._create_provider_client(provider_config)
                provider_clients.append((provider, client, provider_config))
            except Exception as e:
                logger.error(f"Failed to create client for {provider_config.name}: {e}")

        if not provider_clients:
            return None

        payload = self._prepare_project_payload(project)

        success, result = await self._score_with_providers(
            payload, provider_clients, effective_prompt
        )

        for provider, client, _ in provider_clients:
            await provider.close(client)

        if success:
            return result
        return None


# ============================================================================
# 单例管理（保留便捷访问，但支持依赖注入）
# ============================================================================

_scoring_service: Optional["LLMScoringService"] = None
_scoring_config: Optional[LLMScoringConfig] = None


def reset_singleton() -> None:
    """
    重置单例状态（用于测试环境）。

    调用此方法会清除缓存的服务实例，
    下次调用 get_scoring_service() 时会创建新实例。

    Example:
        # 在单元测试的 setUp 中
        def setUp(self):
            reset_singleton()
    """
    global _scoring_service, _scoring_config
    _scoring_service = None
    _scoring_config = None
    logger.debug("LLMScoringService singleton reset")


def create_scoring_service(
    config: Optional[LLMScoringConfig] = None,
) -> "LLMScoringService":
    """
    创建新的 LLMScoringService 实例（依赖注入模式）。

    这是推荐创建服务的方式，特别是在：
    1. 单元测试中
    2. 需要不同配置的多实例场景
    3. 依赖注入框架集成

    Args:
        config: 服务配置，为 None 时使用默认配置

    Returns:
        新的 LLMScoringService 实例

    Example:
        # 测试中使用自定义配置
        config = LLMScoringConfig(
            batch_size=3,
            providers=[...],
            cache_ttl=0,  # 禁用缓存
        )
        service = create_scoring_service(config)
    """
    return LLMScoringService(config=config)


def get_scoring_service() -> "LLMScoringService":
    """
    获取或创建单例评分服务（便捷访问）。

    此方法保留是为了向后兼容和简化应用代码使用。

    注意：在单元测试中请使用 create_scoring_service()。

    Returns:
        单例 LLMScoringService 实例
    """
    global _scoring_service, _scoring_config
    if _scoring_service is None:
        config = _scoring_config
        _scoring_service = create_scoring_service(config)
    return _scoring_service


def configure_service(config: LLMScoringConfig) -> None:
    """
    配置单例评分服务（在应用启动时调用）。

    Args:
        config: 服务配置

    Example:
        # 应用启动时
        config = LLMScoringConfig.from_settings()
        config.batch_size = 10
        configure_service(config)
    """
    global _scoring_config
    _scoring_config = config
    _scoring_service = None  # 标记需要重建
    logger.info("LLMScoringService configured with custom settings")
