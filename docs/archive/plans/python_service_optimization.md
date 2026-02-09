# Python API 服务优化计划

> 创建日期: 2026-01-11  
> 版本: v1.0  
> 状态: 待执行

---

## 目录

- [执行摘要](#执行摘要)
- [代码质量优化](#代码质量优化)
- [性能优化](#性能优化)
- [安全加固](#安全加固)
- [可维护性改进](#可维护性改进)
- [实施路线图](#实施路线图)
- [验收标准](#验收标准)

---

## 执行摘要

基于对 `python_service` 的综合代码分析（47个Python文件，12,333行代码），本计划提出了分级优化建议。

### 整体评估

| 维度 | 当前状态 | 目标状态 | 优先级 |
|------|----------|----------|--------|
| 代码结构 | ⭐⭐⭐⭐ 良好 | ⭐⭐⭐⭐⭐ 优秀 | 中 |
| 错误处理 | ⭐⭐⭐ 一般 | ⭐⭐⭐⭐ 良好 | 高 |
| 性能设计 | ⭐⭐⭐ 良好 | ⭐⭐⭐⭐ 良好 | 高 |
| 安全性 | ⭐⭐ 需加强 | ⭐⭐⭐⭐ 安全 | 高 |
| 可测试性 | ⭐⭐⭐⭐ 优秀 | ⭐⭐⭐⭐⭐ 卓越 | 低 |

### 优化工作量预估

- **紧急修复**: 2-3天
- **核心优化**: 1-2周
- **架构升级**: 2-4周

---

## 代码质量优化

### 1. 异常处理规范化

#### 问题描述

多处使用裸 `except Exception` 或仅 `pass` 的异常处理，吞掉了重要错误信息。

#### 问题位置

| 文件 | 行号 | 问题 |
|------|------|------|
| `services/freelancer_client.py` | 314 | `except Exception: pass` |
| `services/client_risk/llm_analysis.py` | - | 裸 except |
| `services/client_risk/hard_rules.py` | - | 裸 except |
| `services/client_risk/assessment.py` | 91-97 | 裸 except 转换类型 |

#### 解决方案

**优先级**: 高

```python
# ❌ 当前代码 (freelancer_client.py:307-314)
if normalized.get("hire_rate") is None:
    try:
        jobs_posted = int(normalized.get("jobs_posted") or 0)
        jobs_hired = int(normalized.get("jobs_hired") or 0)
        if jobs_posted > 0:
            normalized["hire_rate"] = jobs_hired / jobs_posted
    except Exception:
        pass

# ✅ 优化后
if normalized.get("hire_rate") is None:
    try:
        jobs_posted = int(normalized.get("jobs_posted") or 0)
        jobs_hired = int(normalized.get("jobs_hired") or 0)
        if jobs_posted > 0:
            normalized["hire_rate"] = jobs_hired / jobs_posted
    except (TypeError, ValueError, ZeroDivisionError) as e:
        logger.warning(f"Failed to calculate hire_rate: {e}")
        normalized["hire_rate"] = None
```

**新增工具函数** (`utils/exceptions.py`):

```python
"""
异常处理工具模块
"""
import logging
from functools import wraps
from typing import Type, Callable, Any

logger = logging.getLogger(__name__)


def safe_convert(
    value: Any,
    target_type: Type,
    default: Any = None,
    error_msg: str = "Conversion failed"
) -> Any:
    """
    安全类型转换工具函数

    Args:
        value: 要转换的值
        target_type: 目标类型
        default: 转换失败时的默认值
        error_msg: 错误日志消息

    Returns:
        转换后的值或默认值
    """
    try:
        return target_type(value)
    except (TypeError, ValueError) as e:
        logger.warning(f"{error_msg}: {e} (value={value})")
        return default


class APIError(Exception):
    """API 调用错误基类"""

    def __init__(self, message: str, status_code: int = 500, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    重试装饰器

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟（秒）
        backoff: 延迟递增倍数
        exceptions: 需要重试的异常类型
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            f"Function {func.__name__} failed after {max_retries} retries: {e}"
                        )
                        raise
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. Retrying in {current_delay}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

            raise last_exception
        return wrapper
    return decorator
```

#### 验收标准

- [ ] 所有 `except Exception` 替换为具体异常类型
- [ ] 关键异常被记录到日志
- [ ] 保留原有功能逻辑

---

### 2. 日志配置优化

#### 问题描述

`main.py` 使用 `logging.basicConfig()`，可能在某些情况下重复初始化日志。

#### 解决方案

**优先级**: 中

**新增配置文件** (`config/logging_config.py`):

```python
"""
日志配置模块
"""
import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
) -> None:
    """
    配置日志系统

    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径，为 None 时只输出到控制台
        log_format: 日志格式
    """
    # 防止重复配置
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    # 创建格式器
    formatter = logging.Formatter(log_format)

    # 配置根日志器
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器（如果指定）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 禁用第三方库的冗余日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class LoggingContext:
    """日志上下文管理器，用于临时调整日志级别"""

    def __init__(self, logger_name: str, level: int):
        self.logger_name = logger_name
        self.target_level = level
        self.original_level = None

    def __enter__(self):
        logger = logging.getLogger(self.logger_name)
        self.original_level = logger.level
        logger.setLevel(self.target_level)
        return logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger = logging.getLogger(self.logger_name)
        logger.setLevel(self.original_level)
```

**更新 main.py**:

```python
# main.py
from config.logging_config import setup_logging

# 在应用启动时配置日志
setup_logging(
    log_level=settings.LOG_LEVEL,
    log_file=settings.LOG_FILE
)
```

#### 验收标准

- [ ] 日志不重复初始化
- [ ] 日志格式统一
- [ ] 第三方库日志不过于冗余

---

### 3. API Response 标准化

#### 问题描述

当前 API 返回格式不一致，有的直接返回数据，有的包装在 `APIResponse` 中。

#### 解决方案

**优先级**: 低

**新增统一响应模块** (`api/responses.py`):

```python
"""
统一 API 响应模块
"""
from typing import Generic, TypeVar, Optional, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime


class ApiResponse(BaseModel):
    """标准 API 响应"""
    status: str = Field(..., description="响应状态: success | error | warning")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[Any] = Field(None, description="响应数据")
    meta: Optional[Dict[str, Any]] = Field(None, description="元信息（如分页）")

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "status": "success",
                    "message": "操作成功",
                    "data": {...},
                    "meta": {"page": 1, "per_page": 20}
                }
            ]
        }


class PaginationMeta(BaseModel):
    """分页元信息"""
    page: int = Field(..., description="当前页码")
    per_page: int = Field(..., description="每页数量")
    total: int = Field(..., description="总数量")
    total_pages: int = Field(..., description="总页数")


def success_response(
    data: Any = None,
    message: str = "success",
    meta: Dict[str, Any] = None
) -> ApiResponse:
    """创建成功响应"""
    return ApiResponse(
        status="success",
        message=message,
        data=data,
        meta=meta
    )


def error_response(
    message: str,
    error_type: str = "unknown_error",
    details: Any = None
) -> ApiResponse:
    """创建错误响应"""
    return ApiResponse(
        status="error",
        message=message,
        data={"error_type": error_type, "details": details}
    )


class PaginationParams:
    """分页参数工具类"""

    def __init__(
        self,
        page: int = 1,
        per_page: int = 20,
        max_per_page: int = 100
    ):
        self.page = max(1, page)
        self.per_page = min(max(1, per_page), max_per_page)
        self.offset = (self.page - 1) * self.per_page

    @classmethod
    def from_request(
        cls,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        max_per_page: int = 100
    ) -> "PaginationParams":
        return cls(
            page=page or 1,
            per_page=per_page or 20,
            max_per_page=max_per_page
        )

    def get_meta(self, total: int) -> PaginationMeta:
        """获取分页元信息"""
        total_pages = (total + self.per_page - 1) // self.per_page
        return PaginationMeta(
            page=self.page,
            per_page=self.per_page,
            total=total,
            total_pages=total_pages
        )
```

#### 验收标准

- [ ] 所有 API 端点返回格式一致
- [ ] 包含适当的分页信息
- [ ] 错误响应包含 error_type

---

## 性能优化

### 1. 数据库升级

#### 问题描述

当前使用 SQLite + StaticPool，不适合生产环境的高并发场景。

#### 解决方案

**优先级**: 高

**分阶段实施**:

##### 阶段1: 添加 PostgreSQL 支持

**更新配置文件** (`config/database_config.py`):

```python
"""
数据库配置模块
"""
from typing import Optional
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base


class DatabaseConfig(BaseSettings):
    """数据库配置"""

    # SQLite 配置（开发环境）
    DATABASE_TYPE: str = "sqlite"
    DATABASE_PATH: str = "/app/data/freelancer.db"

    # PostgreSQL 配置（生产环境）
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "freelancer"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "freelancer_db"

    # 连接池配置
    POOL_SIZE: int = 10
    MAX_OVERFLOW: int = 20
    POOL_TIMEOUT: int = 30
    POOL_RECYCLE: int = 1800

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.DATABASE_PATH}"

    @property
    def async_postgres_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_postgres_url(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


class Database:
    """数据库连接管理器"""

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._sync_engine = None
        self._async_engine = None
        self._sync_session_factory = None
        self._async_session_factory = None

    def _create_sync_engine(self):
        """创建同步引擎"""
        if self.config.DATABASE_TYPE == "postgresql":
            url = self.config.sync_postgres_url
        else:
            url = self.config.sqlite_url

        return create_engine(
            url,
            pool_size=self.config.POOL_SIZE,
            max_overflow=self.config.MAX_OVERFLOW,
            pool_timeout=self.config.POOL_TIMEOUT,
            pool_recycle=self.config.POOL_RECYCLE,
            echo=settings.DEBUG  # 仅调试时输出 SQL
        )

    def get_sync_session(self):
        """获取同步数据库会话"""
        if self._sync_engine is None:
            self._sync_engine = self._create_sync_engine()

        if self._sync_session_factory is None:
            self._sync_session_factory = sessionmaker(
                bind=self._sync_engine,
                autocommit=False,
                autoflush=False
            )

        return self._sync_session_factory()

    async def get_async_session(self) -> AsyncSession:
        """获取异步数据库会话"""
        if self._async_engine is None:
            self._async_engine = create_async_engine(
                self.config.async_postgres_url,
                pool_size=self.config.POOL_SIZE,
                max_overflow=self.config.MAX_OVERFLOW,
                pool_timeout=self.config.POOL_TIMEOUT,
            )

        if self._async_session_factory is None:
            self._async_session_factory = sessionmaker(
                bind=self._async_engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

        async with self._async_session_factory() as session:
            yield session

    def close(self):
        """关闭所有连接"""
        if self._sync_engine:
            self._sync_engine.dispose()
        if self._async_engine:
            asyncio.run(self._async_engine.dispose())
```

##### 阶段2: 更新模型支持 JSONB

```python
# database/models.py
from sqlalchemy.dialects.postgresql import JSONB

class Project(Base):
    # ...
    bid_stats = Column(JSONB)  # 替换 Text
    owner_info = Column(JSONB)  # 替换 Text
```

##### 阶段3: 添加数据库中间件

```python
# middleware/database.py
from starlette.middleware.base import BaseHTTPMiddleware
import time


class DatabaseQueryMetricsMiddleware(BaseHTTPMiddleware):
    """数据库查询指标中间件"""

    async def dispatch(self, request, call_next):
        start_time = time.time()

        response = await call_next(request)

        duration = time.time() - start_time

        # 可以发送到 Prometheus
        # metrics.db_query_duration.observe(duration)

        return response
```

#### 验收标准

- [ ] 支持 SQLite/PostgreSQL 切换
- [ ] 连接池合理配置
- [ ] 有数据库性能监控

---

### 2. 缓存优化

#### 问题描述

当前内存缓存没有容量限制，存在内存泄漏风险。

#### 解决方案

**优先级**: 高

**更新 freelancer_client.py**:

```python
# services/freelancer_client.py
from cachetools import TTLCache, LRUCache
from typing import Dict, Tuple, Any, List, Optional
import time

class FreelancerClient:
    def __init__(self):
        # ... 现有初始化代码

        # 使用 TTLCache 替代 dict（自动过期 + 最大容量）
        self._user_cache: TTLCache[int, Dict[str, Any]] = TTLCache(
            maxsize=1000,  # 最多缓存 1000 个用户
            ttl=settings.FREELANCER_USER_CACHE_TTL_SECONDS  # 默认 600 秒
        )

        self._reviews_cache: TTLCache[int, List[Dict[str, Any]]] = TTLCache(
            maxsize=500,
            ttl=settings.FREELANCER_REVIEWS_CACHE_TTL_SECONDS
        )

        # LLM 响应缓存（更长时间）
        self._llm_response_cache: LRUCache[str, Any] = LRUCache(
            maxsize=100  # LRU 策略，最多 100 条
        )

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        # 检查缓存（TTLCache 自动处理过期）
        if user_id in self._user_cache:
            logger.debug(f"User {user_id} cache hit")
            return self._user_cache[user_id]

        # ... 原有逻辑
        # 写入缓存
        self._user_cache[user_id] = normalized
        return normalized

    def invalidate_user_cache(self, user_id: int) -> None:
        """手动失效用户缓存"""
        self._user_cache.pop(user_id, None)
        self._reviews_cache.pop(user_id, None)

    def clear_all_caches(self) -> None:
        """清空所有缓存"""
        self._user_cache.clear()
        self._reviews_cache.clear()
        self._llm_response_cache.clear()
```

**添加缓存监控**:

```python
# services/cache_metrics.py
"""缓存指标收集"""
from prometheus_client import Counter, Gauge, Histogram

cache_hits = Counter(
    'freelancer_cache_hits_total',
    'Total number of cache hits',
    ['cache_type']
)

cache_misses = Counter(
    'freelancer_cache_misses_total',
    'Total number of cache misses',
    ['cache_type']
)

cache_size = Gauge(
    'freelancer_cache_size',
    'Current cache size',
    ['cache_type']
)

cache_operations = Histogram(
    'freelancer_cache_operation_duration_seconds',
    'Cache operation duration',
    ['cache_type', 'operation'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)
```

#### 验收标准

- [ ] 缓存有最大容量限制
- [ ] 缓存自动过期
- [ ] 缓存操作有监控指标

---

### 3. API 限流

#### 问题描述

当前 API 没有请求限流，容易受到 DDoS 攻击。

#### 解决方案

**优先级**: 高

**添加限流中间件**:

```python
# middleware/rate_limit.py
"""
限流中间件
"""
from fastapi import Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional
import time
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
import asyncio


@dataclass
class RateLimitConfig:
    """限流配置"""
    requests: int = 60  # 允许的请求数
    window: int = 60  # 时间窗口（秒）


class RateLimiter:
    """滑动窗口限流器"""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._windows: dict = defaultdict(list)  # key -> [timestamps]

    async def check_rate_limit(self, key: str) -> tuple[bool, int]:
        """
        检查是否超过限流

        Returns:
            (is_allowed, remaining_seconds)
        """
        now = time.time()
        window_start = now - self.config.window

        # 清理过期时间戳
        self._windows[key] = [
            ts for ts in self._windows[key]
            if ts > window_start
        ]

        # 检查是否超限
        if len(self._windows[key]) >= self.config.requests:
            oldest = self._windows[key][0]
            wait_seconds = int(oldest + self.config.window - now) + 1
            return False, wait_seconds

        # 记录请求
        self._windows[key].append(now)
        return True, 0

    def get_remaining(self, key: str) -> int:
        """获取剩余请求数"""
        now = time.time()
        window_start = now - self.config.window
        current = len([ts for ts in self._windows[key] if ts > window_start])
        return max(0, self.config.requests - current)


# 全局限流器实例
_default_limiter = RateLimiter(RateLimitConfig())


class RateLimitMiddleware(BaseHTTPMiddleware):
    """限流中间件"""

    def __init__(self, app, limiter: RateLimiter = None):
        super().__init__(app)
        self.limiter = limiter or _default_limiter

    async def dispatch(self, request: Request, call_next):
        # 生成限流 key（基于 IP）
        client_ip = request.client.host if request.client else "unknown"
        # 也可考虑包含 API Key
        api_key = request.headers.get("X-API-Key")
        if api_key:
            key = f"apikey:{hashlib.md5(api_key.encode()).hexdigest()}"
        else:
            key = f"ip:{client_ip}"

        # 检查限流
        allowed, wait_seconds = await self.limiter.check_rate_limit(key)

        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "status": "error",
                    "error_type": "rate_limit_exceeded",
                    "message": f"Too many requests. Please wait {wait_seconds} seconds.",
                    "retry_after": wait_seconds
                },
                headers={"Retry-After": str(wait_seconds)}
            )

        response = await call_next(request)

        # 添加 Rate Limit 响应头
        remaining = self.limiter.get_remaining(key)
        response.headers["X-RateLimit-Limit"] = str(self.limiter.config.requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response


# 依赖注入方式
async def get_rate_limiter():
    return _default_limiter


async def verify_api_key_with_rate_limit(
    request: Request,
    api_key: str = Depends(verify_api_key),
    limiter: RateLimiter = Depends(get_rate_limiter)
):
    """带限流验证的 API Key 依赖"""
    key = f"apikey:{hashlib.md5(api_key.encode()).hexdigest()}"
    allowed, wait_seconds = await limiter.check_rate_limit(key)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Wait {wait_seconds} seconds."
        )

    return api_key
```

**注册中间件** (`main.py`):

```python
from middleware.rate_limit import RateLimitMiddleware

app.add_middleware(RateLimitMiddleware)
```

#### 验收标准

- [ ] API 有请求限流
- [ ] 返回 429 状态码和 Retry-After 头
- [ ] 可配置限流参数

---

## 安全加固

### 1. CORS 严格配置

#### 问题描述

```python
# main.py
allow_origins=["*"]  # 生产环境不安全
```

#### 解决方案

**优先级**: 高

```python
# main.py
from fastapi.middleware.cors import CORSMiddleware

# 从环境变量读取允许的域名
allowed_origins = [
    "https://yourdomain.com",
    "http://localhost:3000",  # 开发环境
]

# 生产环境只允许特定域名
if settings.ENVIRONMENT == "production":
    allowed_origins = [settings.PRODUCTION_FRONTEND_URL]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)
```

#### 验收标准

- [ ] CORS 只允许特定域名
- [ ] HTTP 方法限制为必要的方法
- [ ] 环境变量控制允许列表

---

### 2. API Key 安全增强

#### 问题描述

当前 API Key 验证简单，没有失败次数限制。

#### 解决方案

**优先级**: 高

```python
# middleware/auth_security.py
"""
认证安全增强模块
"""
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from typing import Optional
import time
import hashlib
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class AuthConfig:
    """认证配置"""
    max_failed_attempts: int = 5  # 最大失败次数
    lockout_duration: int = 300  # 锁定时间（秒）


class APIKeyValidator:
    """API Key 验证器（带失败计数）"""

    def __init__(self, config: AuthConfig = None):
        self.config = config or AuthConfig()
        self._failed_attempts: dict = defaultdict(list)  # key -> [timestamps]

    async def validate(
        self,
        api_key: str,
        expected_key: str,
        key_type: str = "api_key"
    ) -> tuple[bool, Optional[str]]:
        """
        验证 API Key

        Returns:
            (is_valid, error_message)
        """
        # 检查是否被锁定
        key_hash = hashlib.md5(api_key.encode()).hexdigest()
        now = time.time()

        # 清理过期记录
        self._failed_attempts[key_hash] = [
            ts for ts in self._failed_attempts[key_hash]
            if now - ts < self.config.lockout_duration
        ]

        # 检查失败次数
        recent_failures = len(self._failed_attempts[key_hash])
        if recent_failures >= self.config.max_failed_attempts:
            oldest = self._failed_attempts[key_hash][0]
            wait_seconds = int(oldest + self.config.lockout_duration - now) + 1
            return False, f"Account locked. Try again in {wait_seconds} seconds."

        # 验证 Key
        if api_key != expected_key:
            self._failed_attempts[key_hash].append(now)
            return False, "Invalid API key"

        # 验证成功，清空失败记录
        self._failed_attempts[key_hash] = []
        return True, None


# 全局验证器
api_key_validator = APIKeyValidator()


async def verify_api_key_secure(request: Request) -> str:
    """安全的 API Key 验证"""
    api_key = request.headers.get("X-API-Key")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key"
        )

    is_valid, error = await api_key_validator.validate(
        api_key,
        settings.PYTHON_API_KEY
    )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error
        )

    return api_key
```

#### 验收标准

- [ ] API Key 验证有失败次数限制
- [ ] 账户锁定功能
- [ ] 错误消息不泄露敏感信息

---

### 3. 敏感信息脱敏

#### 解决方案

**优先级**: 中

```python
# utils/redaction.py
"""
敏感信息脱敏工具
"""
import re
from typing import Any, Dict, List, Optional


class SensitiveDataRedactor:
    """敏感数据脱敏器"""

    # 脱敏规则
    PATTERNS = {
        "email": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
        "phone": re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
        "credit_card": re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
        "api_key": re.compile(r'(api[_-]?key|token|secret|password)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9\-_]{16,})["\']?', re.IGNORECASE),
        "ip_address": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    }

    # 需要脱敏的字段名
    SENSITIVE_FIELDS = {
        "password", "token", "secret", "api_key", "apikey",
        "oauth_token", "access_token", "refresh_token",
        "credit_card", "cvv", "ssn", "account_number"
    }

    @classmethod
    def redact_text(cls, text: str, mask: str = "***") -> str:
        """脱敏文本中的敏感信息"""
        if not text:
            return text

        result = text

        # 脱敏邮箱
        result = cls.PATTERNS["email"].sub(
            lambda m: m.group(0)[0] + "***" + m.group(0).split("@")[-1],
            result
        )

        # 脱敏手机号
        result = cls.PATTERNS["phone"].sub(
            lambda m: "***-***-" + m.group(0)[-4:],
            result
        )

        # 脱敏 API Key
        result = cls.PATTERNS["api_key"].sub(
            lambda m: m.group(1) + ": " + mask,
            result
        )

        return result

    @classmethod
    def redact_dict(cls, data: Dict[str, Any], recursive: bool = True) -> Dict[str, Any]:
        """脱敏字典中的敏感字段"""
        if not isinstance(data, dict):
            return data

        result = {}
        for key, value in data.items():
            key_lower = key.lower()

            if key_lower in cls.SENSITIVE_FIELDS:
                result[key] = "***REDACTED***"
            elif isinstance(value, str):
                result[key] = cls.redact_text(value)
            elif recursive and isinstance(value, dict):
                result[key] = cls.redact_dict(value, recursive)
            elif recursive and isinstance(value, list):
                result[key] = [
                    cls.redact_dict(item, recursive) if isinstance(item, dict)
                    else cls.redact_text(str(item)) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                result[key] = value

        return result

    @classmethod
    def redact_for_logging(cls, data: Any) -> Any:
        """为日志准备脱敏数据"""
        if isinstance(data, dict):
            return cls.redact_dict(data)
        elif isinstance(data, str):
            return cls.redact_text(data)
        return data
```

**日志过滤器**:

```python
# config/log_filters.py
"""
日志过滤配置
"""
import logging
from utils.redaction import SensitiveDataRedactor


class SensitiveDataFilter(logging.Filter):
    """敏感数据日志过滤器"""

    def filter(self, record: logging.LogRecord) -> bool:
        # 脱敏日志消息
        if record.msg:
            record.msg = SensitiveDataRedactor.redact_text(record.msg)

        # 脱敏 args（如果包含敏感信息）
        if record.args:
            record.args = tuple(
                SensitiveDataRedactor.redact_for_logging(arg)
                for arg in record.args
            )

        return True


# 配置日志过滤器
sensitive_filter = SensitiveDataFilter()

# 添加到日志处理器
logging.getLogger().handlers[0].addFilter(sensitive_filter)
```

#### 验收标准

- [ ] 日志中不包含敏感信息
- [ ] 敏感字段自动脱敏
- [ ] 错误消息不泄露敏感信息

---

## 可维护性改进

### 1. 统一 JSON 工具

#### 解决方案

**优先级**: 中

```python
# utils/json_tools.py
"""
JSON 工具模块
"""
import json
from typing import Any, Type, TypeVar
from datetime import datetime
from decimal import Decimal

T = TypeVar('T')


class DateTimeEncoder(json.JSONEncoder):
    """DateTime JSON 编码器"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def dumps(obj: Any, **kwargs) -> str:
    """安全的 JSON 序列化"""
    kwargs.setdefault('cls', DateTimeEncoder)
    kwargs.setdefault('ensure_ascii', False)
    return json.dumps(obj, **kwargs)


def loads(s: str) -> Any:
    """安全的 JSON 反序列化"""
    return json.loads(s)


def to_json(obj: Any) -> str:
    """对象转 JSON 字符串"""
    return dumps(obj)


def from_json(s: str, target_type: Type[T]) -> T:
    """JSON 字符串转目标类型"""
    data = loads(s)
    if isinstance(data, target_type):
        return data
    if isinstance(target_type, type) and issubclass(target_type, dict):
        return target_type(data)
    return data


class JsonField:
    """JSON 字段类型（用于 Pydantic）"""

    @staticmethod
    def __get_validators__():
        yield cls._validate

    @classmethod
    def _validate(cls, v):
        if isinstance(v, str):
            return loads(v)
        if isinstance(v, dict):
            return v
        raise ValueError("Must be str or dict")
```

#### 验收标准

- [ ] 所有 JSON 序列化使用统一工具
- [ ] DateTime 自动处理
- [ ] 代码中不再直接调用 `json.dumps/loads`

---

### 2. 类型注解补充

#### 解决方案

**优先级**: 低（长期工作）

对缺少类型注解的关键函数进行补充：

```python
# services/freelancer_client.py

class FreelancerClient:
    async def get_user(self, user_id: int) -> Dict[str, Any]: ...

    async def get_user_reviews(self, user_id: int) -> List[Dict[str, Any]]: ...

    async def search_projects(
        self,
        query: Optional[str] = None,
        skills: Optional[List[int]] = None,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]: ...
```

#### 验收标准

- [ ] 公共 API 有类型注解
- [ ] IDE 能正确推断类型
- [ ] mypy 检查通过

---

## 实施路线图

### Phase 1: 紧急修复（Week 1）

| 任务 | 预计时间 | 负责人 | 优先级 |
|------|----------|--------|--------|
| 异常处理规范化 | 2h | - | 高 |
| CORS 严格配置 | 1h | - | 高 |
| API Key 安全增强 | 4h | - | 高 |
| API 限流中间件 | 4h | - | 高 |

**目标**: 修复高危安全漏洞和错误处理问题

### Phase 2: 核心优化（Week 2-3）

| 任务 | 预计时间 | 负责人 | 优先级 |
|------|----------|--------|--------|
| 缓存优化 | 4h | - | 高 |
| 日志配置优化 | 2h | - | 中 |
| JSON 工具统一 | 4h | - | 中 |
| PostgreSQL 支持 | 2d | - | 高 |

**目标**: 提升性能和可维护性

### Phase 3: 架构升级（Week 4-6）

| 任务 | 预计时间 | 负责人 | 优先级 |
|------|----------|--------|--------|
| 类型注解补充 | 1w | - | 低 |
| API Response 标准化 | 4h | - | 低 |
| 监控指标集成 | 2d | - | 中 |
| 文档完善 | 1d | - | 低 |

**目标**: 提升代码质量和可维护性

---

## 验收标准

### 通用标准

- [ ] 所有代码通过 `ruff check`
- [ ] 所有测试通过 `pytest`
- [ ] 文档已更新

### 性能标准

- [ ] API 响应时间 P95 < 500ms
- [ ] 数据库查询 P95 < 100ms
- [ ] 缓存命中率 > 80%

### 安全标准

- [ ] 通过安全扫描（无高危漏洞）
- [ ] CORS 配置严格
- [ ] API 限流生效
- [ ] 敏感信息不泄露

### 代码质量标准

- [ ] 类型注解覆盖率 > 80%
- [ ] 单元测试覆盖率 > 70%
- [ ] 圈复杂度 < 15

---

## 风险与依赖

### 已知风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| PostgreSQL 迁移数据丢失 | 高 | 迁移前备份，脚本可重复执行 |
| 限流影响正常用户 | 中 | 初始限流阈值宽松，逐步收紧 |
| 安全改动引入 bug | 中 | 充分测试，保留回滚能力 |

### 外部依赖

- PostgreSQL 数据库服务
- Redis（可选，用于分布式缓存）
- 监控服务（Prometheus/Grafana）

---

## 附录

### A. 相关文档链接

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
- [Pydantic 文档](https://docs.pydantic.dev/)

### B. 监控指标定义

```python
# metrics.py
from prometheus_client import Counter, Histogram, Gauge

# HTTP 指标
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

# 数据库指标
db_query_duration = Histogram(
    'db_query_duration_seconds',
    'Database query duration',
    ['query_type'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

# 缓存指标
cache_hit_total = Counter(
    'cache_hit_total',
    'Cache hit total',
    ['cache_type']
)
```

---

> 文档版本: v1.0  
> 最后更新: 2026-01-11
