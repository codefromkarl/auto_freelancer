"""
评分结果缓存模块。

提供评分结果的内存和持久化缓存，
减少重复评分，节省 LLM API 调用。

功能：
1. 内存缓存（LRU）
2. 持久化缓存（SQLite/JSON）
3. 缓存键生成
4. 缓存过期管理
5. 缓存统计
"""

import hashlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict
from threading import RLock

logger = logging.getLogger(__name__)


# =============================================================================
# 缓存配置
# =============================================================================


@dataclass
class CacheConfig:
    """
    缓存配置。

    Attributes:
        enabled: 是否启用缓存
        ttl: 缓存生存时间（秒）
        max_size: 最大缓存条目数（内存）
        persistent: 是否持久化
        persist_path: 持久化文件路径
        namespace: 缓存命名空间
    """

    enabled: bool = True
    ttl: int = 3600  # 1小时
    max_size: int = 1000
    persistent: bool = True
    persist_path: str = "data/scoring_cache.json"
    namespace: str = "default"


# =============================================================================
# 缓存存储接口
# =============================================================================


class CacheBackend(ABC):
    """缓存后端抽象接口"""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int) -> None:
        """设置缓存值"""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """删除缓存值"""
        pass

    @abstractmethod
    def clear(self) -> None:
        """清空缓存"""
        pass

    @abstractmethod
    def stats(self) -> Dict[str, int]:
        """获取缓存统计"""
        pass


# =============================================================================
# 内存缓存实现
# =============================================================================


class MemoryCacheBackend(CacheBackend):
    """
    内存缓存实现。

    使用 LRU（最近最少使用）策略管理缓存。
    """

    def __init__(self, max_size: int = 1000):
        """
        初始化内存缓存。

        Args:
            max_size: 最大缓存条目数
        """
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._lock = RLock()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            value, expiry = self._cache[key]
            # 检查是否过期
            if time.time() > expiry:
                del self._cache[key]
                self._misses += 1
                return None

            # 移到末尾（LRU）
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        """设置缓存值"""
        with self._lock:
            expiry = time.time() + ttl

            # 如果键已存在，更新值
            if key in self._cache:
                self._cache[key] = (value, expiry)
                self._cache.move_to_end(key)
                return

            # 添加新值
            self._cache[key] = (value, expiry)

            # LRU 淘汰
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def delete(self, key: str) -> bool:
        """删除缓存值"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, int]:
        """获取缓存统计"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._cache),
                "max_size": self._max_size,
                "hit_rate": f"{hit_rate:.2f}%",
            }


# =============================================================================
# 持久化缓存实现
# =============================================================================


class PersistentCacheBackend(CacheBackend):
    """
    持久化缓存实现。

    使用 JSON 文件存储缓存，支持跨进程共享。
    """

    def __init__(
        self,
        file_path: str = "data/scoring_cache.json",
        ttl: int = 3600,
        max_entries: int = 10000,
    ):
        """
        初始化持久化缓存。

        Args:
            file_path: 缓存文件路径
            ttl: 默认 TTL（秒）
            max_entries: 最大缓存条目数
        """
        self._file_path = file_path
        self._ttl = ttl
        self._max_entries = max_entries
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()

        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # 加载缓存
        self._load()

    def _load(self) -> None:
        """从文件加载缓存"""
        if not os.path.exists(self._file_path):
            return

        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 过滤过期条目
                now = time.time()
                self._cache = {
                    k: v for k, v in data.items() if v.get("expiry", 0) > now
                }
            logger.info(f"Loaded {len(self._cache)} cached entries")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            self._cache = {}

    def _save(self) -> None:
        """保存缓存到文件"""
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key not in self._cache:
                return None

            entry = self._cache[key]
            if time.time() > entry.get("expiry", 0):
                del self._cache[key]
                return None

            return entry.get("value")

    def set(self, key: str, value: Any, ttl: int) -> None:
        """设置缓存值"""
        with self._lock:
            entry = {
                "value": value,
                "expiry": time.time() + ttl,
                "created": time.time(),
            }

            # 如果缓存已满，删除最旧的条目
            if len(self._cache) >= self._max_entries:
                oldest_key = min(
                    self._cache.keys(), key=lambda k: self._cache[k].get("created", 0)
                )
                del self._cache[oldest_key]

            self._cache[key] = entry

            # 异步保存
            self._save()

    def delete(self, key: str) -> bool:
        """删除缓存值"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._save()
                return True
            return False

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._save()

    def stats(self) -> Dict[str, int]:
        """获取缓存统计"""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_entries,
                "file_path": self._file_path,
            }


# =============================================================================
# 评分结果缓存
# =============================================================================


class ScoringCache:
    """
    评分结果缓存管理器。

    提供统一的缓存接口，支持：
    1. 基于项目特征的缓存键生成
    2. 多级缓存（内存 + 持久化）
    3. 缓存命中/未命中处理
    """

    # 缓存键前缀
    SCORE_PREFIX = "score"
    LLM_PREFIX = "llm"

    def __init__(self, config: Optional[CacheConfig] = None):
        """
        初始化评分缓存。

        Args:
            config: 缓存配置
        """
        self.config = config or CacheConfig()
        self._memory_cache: Optional[MemoryCacheBackend] = None
        self._persistent_cache: Optional[PersistentCacheBackend] = None

    @property
    def memory_cache(self) -> MemoryCacheBackend:
        """获取内存缓存"""
        if self._memory_cache is None:
            self._memory_cache = MemoryCacheBackend(
                max_size=self.config.max_size if self.config.enabled else 0
            )
        return self._memory_cache

    @property
    def persistent_cache(self) -> PersistentCacheBackend:
        """获取持久化缓存"""
        if self._persistent_cache is None and self.config.persistent:
            self._persistent_cache = PersistentCacheBackend(
                file_path=self.config.persist_path,
                ttl=self.config.ttl,
                max_entries=self.config.max_size,
            )
        return self._persistent_cache

    def _generate_key(
        self,
        prefix: str,
        project_data: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None,
    ) -> str:
        """
        生成缓存键。

        Args:
            prefix: 键前缀
            project_data: 项目数据
            weights: 使用的权重配置

        Returns:
            缓存键
        """
        # 提取关键特征
        key_features = {
            "id": project_data.get("id"),
            "title": project_data.get("title", "")[:100],  # 截断长标题
            "budget_min": project_data.get("budget_minimum"),
            "budget_max": project_data.get("budget_maximum"),
            "currency": project_data.get("currency_code"),
        }

        if weights:
            key_features["weights"] = weights

        # 生成哈希
        features_str = json.dumps(key_features, sort_keys=True)
        key_hash = hashlib.md5(features_str.encode()).hexdigest()[:16]

        return f"{prefix}:{key_hash}"

    def get_rule_score(
        self,
        project_data: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        获取规则评分缓存。

        Args:
            project_data: 项目数据
            weights: 使用的权重配置

        Returns:
            缓存的评分结果，未命中返回 None
        """
        if not self.config.enabled:
            return None

        key = self._generate_key(self.SCORE_PREFIX, project_data, weights)

        # 先查内存缓存
        result = self.memory_cache.get(key)
        if result is not None:
            logger.debug(f"Cache hit (memory): {key}")
            return result

        # 再查持久化缓存
        if self.persistent_cache:
            result = self.persistent_cache.get(key)
            if result is not None:
                logger.debug(f"Cache hit (persistent): {key}")
                # 回填内存缓存
                self.memory_cache.set(key, result, self.config.ttl)
                return result

        logger.debug(f"Cache miss: {key}")
        return None

    def set_rule_score(
        self,
        project_data: Dict[str, Any],
        result: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        缓存规则评分结果。

        Args:
            project_data: 项目数据
            result: 评分结果
            weights: 使用的权重配置
        """
        if not self.config.enabled:
            return

        key = self._generate_key(self.SCORE_PREFIX, project_data, weights)

        # 同时写入内存和持久化缓存
        self.memory_cache.set(key, result, self.config.ttl)

        if self.persistent_cache:
            self.persistent_cache.set(key, result, self.config.ttl)

        logger.debug(f"Cached rule score: {key}")

    def get_llm_score(
        self,
        project_data: Dict[str, Any],
        prompt_hash: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        获取 LLM 评分缓存。

        Args:
            project_data: 项目数据
            prompt_hash: 提示词哈希

        Returns:
            缓存的评分结果，未命中返回 None
        """
        if not self.config.enabled:
            return None

        # 生成 LLM 专用键
        key = self._generate_key(
            f"{self.LLM_PREFIX}:{prompt_hash}",
            project_data,
        )

        result = self.memory_cache.get(key)
        if result is not None:
            logger.debug(f"LLM cache hit (memory): {key}")
            return result

        if self.persistent_cache:
            result = self.persistent_cache.get(key)
            if result is not None:
                logger.debug(f"LLM cache hit (persistent): {key}")
                self.memory_cache.set(key, result, self.config.ttl)
                return result

        logger.debug(f"LLM cache miss: {key}")
        return None

    def set_llm_score(
        self,
        project_data: Dict[str, Any],
        result: Dict[str, Any],
        prompt_hash: str = "",
    ) -> None:
        """
        缓存 LLM 评分结果。

        Args:
            project_data: 项目数据
            result: 评分结果
            prompt_hash: 提示词哈希
        """
        if not self.config.enabled:
            return

        key = self._generate_key(
            f"{self.LLM_PREFIX}:{prompt_hash}",
            project_data,
        )

        self.memory_cache.set(key, result, self.config.ttl)

        if self.persistent_cache:
            self.persistent_cache.set(key, result, self.config.ttl)

        logger.debug(f"Cached LLM score: {key}")

    def invalidate(self, project_id: int) -> int:
        """
        使⽤指定项目的缓存失效。

        Args:
            project_id: 项目 ID

        Returns:
            删除的缓存条目数
        """
        # 由于使用哈希键，无法直接按项目 ID 删除
        # 这里实现简化的清理逻辑
        deleted = 0

        # 清除所有缓存（实际使用中应该更精细）
        self.memory_cache.clear()
        if self.persistent_cache:
            self.persistent_cache.clear()
            deleted = 1

        return deleted

    def clear(self) -> None:
        """清空所有缓存"""
        self.memory_cache.clear()
        if self.persistent_cache:
            self.persistent_cache.clear()
        logger.info("Scoring cache cleared")

    def stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        stats = {
            "memory": self.memory_cache.stats(),
        }
        if self.persistent_cache:
            stats["persistent"] = self.persistent_cache.stats()
        return stats


# =============================================================================
# 全局缓存实例
# =============================================================================

_cache: Optional[ScoringCache] = None


def get_scoring_cache() -> ScoringCache:
    """获取全局缓存实例"""
    global _cache
    if _cache is None:
        _cache = ScoringCache()
    return _cache


def reset_cache() -> None:
    """重置缓存"""
    global _cache
    _cache = None


# =============================================================================
# 便捷函数
# =============================================================================


def cache_rule_score(
    project_data: Dict[str, Any],
    result: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> None:
    """缓存规则评分结果（便捷函数）"""
    cache = get_scoring_cache()
    cache.set_rule_score(project_data, result, weights)


def get_cached_rule_score(
    project_data: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> Optional[Dict[str, Any]]:
    """获取规则评分缓存（便捷函数）"""
    cache = get_scoring_cache()
    return cache.get_rule_score(project_data, weights)


def cache_llm_score(
    project_data: Dict[str, Any],
    result: Dict[str, Any],
    prompt_hash: str = "",
) -> None:
    """缓存 LLM 评分结果（便捷函数）"""
    cache = get_scoring_cache()
    cache.set_llm_score(project_data, result, prompt_hash)


def get_cached_llm_score(
    project_data: Dict[str, Any],
    prompt_hash: str = "",
) -> Optional[Dict[str, Any]]:
    """获取 LLM 评分缓存（便捷函数）"""
    cache = get_scoring_cache()
    return cache.get_llm_score(project_data, prompt_hash)
