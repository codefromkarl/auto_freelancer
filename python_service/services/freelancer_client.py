"""
Freelancer SDK client wrapper with authentication and error handling.
"""
from __future__ import annotations

from freelancersdk.session import Session
from freelancersdk.resources.projects.projects import (
    search_projects,
    get_project_by_id as get_project_details,
    place_project_bid as place_bid,
    retract_project_bid as retract_bid,
    create_milestone_payment as create_milestone,
    accept_milestone_request as accept_milestone,
    release_milestone_payment
)
from freelancersdk.resources.messages.messages import (
    post_message,
    post_attachment as upload_attachment,
    get_messages,
    get_threads
)
from collections import deque
from typing import Optional, Dict, List, Any, Callable, Awaitable, Tuple
from datetime import datetime
import logging
import re
import aiohttp
import asyncio
import time

from config import settings

logger = logging.getLogger(__name__)


class FreelancerAPIError(Exception):
    """Custom exception for Freelancer API errors."""
    def __init__(self, message: str, status_code: int = None, retry_after: int = None):
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(self.message)


class _AsyncRateLimiter:
    """
    简易异步限流器（按“每分钟最多 N 次”）。

    设计目标：
    - 方向四的客户风控会显著增加 getUser/评价等 API 调用
    - 这里用“滑动窗口 + sleep”等待的方式做保守限流，避免 429
    """

    def __init__(self, max_per_minute: int):
        self._max = max(1, int(max_per_minute))
        self._lock = asyncio.Lock()
        self._events: deque[float] = deque()

    async def acquire(self) -> None:
        """获取一次调用配额；若超限则等待到下一窗口。"""
        while True:
            async with self._lock:
                now = time.monotonic()
                # 清理 60 秒窗口外的请求时间戳
                while self._events and now - self._events[0] >= 60:
                    self._events.popleft()

                if len(self._events) < self._max:
                    self._events.append(now)
                    return

                # 超限：计算需要等待多久
                wait_seconds = 60 - (now - self._events[0])
                wait_seconds = max(0.05, wait_seconds)

            await asyncio.sleep(wait_seconds)


class FreelancerClient:
    """Wrapper for Freelancer SDK with enhanced error handling."""

    def __init__(self):
        """Initialize Freelancer client with OAuth token."""
        try:
            self.session = Session(
                oauth_token=settings.FREELANCER_OAUTH_TOKEN,
                url=settings.FLN_URL
            )
            self.user_id = int(settings.FREELANCER_USER_ID)
            logger.info(f"Freelancer client initialized for user {self.user_id}")

            # -----------------------------
            # 方向四：客户风控所需的缓存/限流
            # -----------------------------
            self._rate_limiter = _AsyncRateLimiter(settings.RATE_LIMIT_PER_MINUTE)

            # in-memory 缓存（避免在一个服务周期内重复 getUser / getReviews）
            # 结构：user_id -> (expires_at, payload)
            self._user_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}
            self._reviews_cache: Dict[int, Tuple[float, List[Dict[str, Any]]]] = {}
            self._cache_lock = asyncio.Lock()

        except Exception as e:
            logger.error(f"Failed to initialize Freelancer client: {e}")
            raise FreelancerAPIError(
                message="Authentication failed",
                status_code=401
            )

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        """
        获取客户（雇主）基本信息（用于风控/资格审查）。

        说明：
        - 优先命中缓存（降低 API 调用成本与 429 风险）
        - 对外输出尽量“字段归一化”的 dict（上层 hard_rules/assessment 会容错）
        """
        if user_id <= 0:
            raise FreelancerAPIError(message="Invalid user_id", status_code=400)

        # 1) 读取缓存
        ttl = int(getattr(settings, "FREELANCER_USER_CACHE_TTL_SECONDS", 600))
        now = time.monotonic()
        async with self._cache_lock:
            cached = self._user_cache.get(int(user_id))
            if cached and cached[0] > now:
                return cached[1]

        # 2) 限流 + 拉取
        await self._rate_limiter.acquire()

        try:
            # 允许测试注入自定义 fetcher：直接给实例赋值 `client._fetch_user_http = fake`
            fetcher = getattr(self, "_fetch_user_http")
            user = await fetcher(int(user_id))  # type: ignore[misc]
            normalized = self._normalize_user(user)

            # 3) 写入缓存
            async with self._cache_lock:
                self._user_cache[int(user_id)] = (time.monotonic() + ttl, normalized)

            return normalized
        except FreelancerAPIError:
            raise
        except Exception as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            raise FreelancerAPIError(message=f"Failed to get user: {e}", status_code=500)

    async def get_user_reviews(self, user_id: int) -> List[Dict[str, Any]]:
        """
        获取客户历史评价（如果 API 支持）。

        注意：
        - Freelancer SDK 对“评价/评论”接口支持不稳定，因此这里采用“尽力而为”的策略：
          1) 尝试调用公开 Web API
          2) 失败则返回空数组（由上层做降级）
        - 同样提供缓存与限流
        """
        if user_id <= 0:
            raise FreelancerAPIError(message="Invalid user_id", status_code=400)

        ttl = int(getattr(settings, "FREELANCER_REVIEWS_CACHE_TTL_SECONDS", 600))
        now = time.monotonic()
        async with self._cache_lock:
            cached = self._reviews_cache.get(int(user_id))
            if cached and cached[0] > now:
                return cached[1]

        await self._rate_limiter.acquire()

        try:
            fetcher = getattr(self, "_fetch_user_reviews_http")
            reviews = await fetcher(int(user_id))  # type: ignore[misc]
            if not isinstance(reviews, list):
                reviews = []

            async with self._cache_lock:
                self._reviews_cache[int(user_id)] = (time.monotonic() + ttl, reviews)

            return reviews
        except FreelancerAPIError:
            raise
        except Exception as e:
            logger.warning(f"Failed to get user reviews {user_id}: {e}")
            return []

    async def _fetch_user_http(self, user_id: int) -> Dict[str, Any]:
        """
        通过 Freelancer Web API 获取用户信息（JSON）。

        说明：
        - 这里尽量不依赖 SDK 的 users 模块（不同版本差异较大）
        - 采用 aiohttp 调用公开 API；如果命中 429，会在日志中提示
        """
        urls = [
            f"https://www.freelancer.com/api/users/0.1/users/{user_id}/",
            f"https://www.freelancer.cn/api/users/0.1/users/{user_id}/",
        ]

        data = await self._fetch_json_from_urls(urls)
        return self._unwrap_user_payload(data) or {"id": user_id}

    async def _fetch_user_reviews_http(self, user_id: int) -> List[Dict[str, Any]]:
        """
        尝试获取用户评价（Best-effort）。

        备注：该接口在不同地区/版本可能不可用，因此失败时直接返回 []。
        """
        urls = [
            f"https://www.freelancer.com/api/users/0.1/users/{user_id}/reviews/",
            f"https://www.freelancer.cn/api/users/0.1/users/{user_id}/reviews/",
        ]

        try:
            data = await self._fetch_json_from_urls(urls)
        except FreelancerAPIError:
            return []

        # 常见返回结构兼容：{"result": {"reviews": [...]}} 或 {"reviews": [...]}
        if isinstance(data, dict):
            if isinstance(data.get("reviews"), list):
                return data["reviews"]  # type: ignore[return-value]
            result = data.get("result")
            if isinstance(result, dict) and isinstance(result.get("reviews"), list):
                return result["reviews"]  # type: ignore[return-value]
        return []

    async def _fetch_json_from_urls(self, urls: List[str]) -> Dict[str, Any]:
        """
        从多个候选 URL 拉取 JSON（依次尝试，成功即返回）。

        处理：
        - 200：返回 json
        - 429：抛出带 retry_after 的异常（上层可选择等待/降级）
        - 其它：继续尝试下一个 URL
        """
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            last_error: Optional[str] = None
            for url in urls:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            return await resp.json(content_type=None)
                        if resp.status == 429:
                            retry_after = int(resp.headers.get("Retry-After", "0") or "0")
                            raise FreelancerAPIError(message="Rate limited", status_code=429, retry_after=retry_after)
                        last_error = f"{url} -> HTTP {resp.status}"
                except FreelancerAPIError:
                    raise
                except Exception as e:
                    last_error = f"{url} -> {e}"

            raise FreelancerAPIError(message=f"Failed to fetch JSON: {last_error}", status_code=502)

    def _unwrap_user_payload(self, data: Any) -> Optional[Dict[str, Any]]:
        """
        兼容不同 API 返回结构，尽量提取“用户对象 dict”。
        """
        if not isinstance(data, dict):
            return None

        # 结构 1：{"result": {"users": [ {...} ]}}
        result = data.get("result")
        if isinstance(result, dict):
            users = result.get("users")
            if isinstance(users, list) and users and isinstance(users[0], dict):
                return users[0]
            user = result.get("user")
            if isinstance(user, dict):
                return user

        # 结构 2：{"user": {...}}
        user2 = data.get("user")
        if isinstance(user2, dict):
            return user2

        # 结构 3：数据本身就是 user
        if "id" in data:
            return data  # type: ignore[return-value]

        return None

    def _normalize_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        对用户字段进行轻量归一化，确保上层能稳定读取关键字段。

        目标字段：
        - payment_verified / deposit_made / country / jobs_posted / review_count / hire_rate / rating
        """
        normalized: Dict[str, Any] = dict(user or {})

        # 统一 country 字段：尽量输出 ISO2
        country = normalized.get("country")
        if isinstance(country, dict):
            # 有些 API 会返回 {"code":"US","name":"United States"}
            normalized["country"] = str(country.get("code") or "").upper() or None
            normalized["country_name"] = country.get("name")
        elif isinstance(country, str):
            normalized["country"] = country.upper()

        # hire_rate：如果缺失，则尝试推导
        if normalized.get("hire_rate") is None:
            try:
                jobs_posted = int(normalized.get("jobs_posted") or 0)
                jobs_hired = int(normalized.get("jobs_hired") or 0)
                if jobs_posted > 0:
                    normalized["hire_rate"] = jobs_hired / jobs_posted
            except Exception:
                pass

        return normalized

    async def search_projects(
        self,
        query: Optional[str] = None,
        skills: Optional[List[int]] = None,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Search projects with advanced filters.
        """
        try:
            search_filter = {}

            if skills:
                search_filter['jobs'] = skills
            if budget_min is not None:
                search_filter['min_avg_price'] = budget_min
            if budget_max is not None:
                search_filter['max_avg_price'] = budget_max
            if status == 'active':
                active_only = True
            else:
                active_only = None

            logger.info(f"Searching projects: query='{query}', filter={search_filter}")

            loop = asyncio.get_running_loop()
            
            # Run blocking SDK call in executor
            result = await loop.run_in_executor(
                None,
                lambda: search_projects(
                    self.session,
                    query=query,
                    search_filter=search_filter,
                    limit=limit,
                    offset=offset,
                    active_only=active_only
                )
            )

            # result is usually a dictionary with 'projects', 'users', etc.
            if isinstance(result, dict):
                return result.get('projects', [])
            return []

        except Exception as e:
            logger.error(f"Failed to search projects: {e}")
            raise FreelancerAPIError(
                message=f"Failed to search projects: {str(e)}",
                status_code=500
            )

    async def get_project(
        self,
        project_id: int,
        project_details: Optional[Dict[str, Any]] = None,
        user_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get detailed information for a specific project.

        Args:
            project_id: Freelancer project ID
            project_details: Dict from create_get_projects_project_details_object (e.g., full_description=True)
            user_details: Dict from create_get_projects_user_details_object (e.g., reputation=True)

        Returns:
            Project details dictionary
        """
        try:
            logger.info(f"Getting project details for ID: {project_id}")

            loop = asyncio.get_running_loop()

            # Run blocking SDK call in executor with query params
            # SDK expects named parameters project_details and user_details
            project = await loop.run_in_executor(
                None,
                lambda: get_project_details(
                    self.session,
                    project_id,
                    project_details=project_details,
                    user_details=user_details
                )
            )

            return project
        except Exception as e:
            logger.error(f"Failed to get project {project_id}: {e}")
            raise FreelancerAPIError(
                message=f"Project not found: {str(e)}",
                status_code=404
            )

    async def _fetch_full_description(self, project_id: int) -> Optional[str]:
        """
        Fetch full project description from Freelancer API.

        Args:
            project_id: Freelancer project ID

        Returns:
            Full description string or None if not found
        """
        try:
            # Try both domains in parallel
            urls = [
                f"https://www.freelancer.cn/api/projects/0.1/projects/{project_id}/",
                f"https://www.freelancer.com/api/projects/0.1/projects/{project_id}/",
            ]

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            }

            async def fetch_json(session, url):
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            content_type = resp.headers.get('Content-Type', '')
                            if 'application/json' in content_type:
                                return await resp.json()
                            else:
                                # Fallback to text parsing
                                text = await resp.text()
                                # Try to parse as JSON
                                import json
                                try:
                                    return json.loads(text)
                                except:
                                    return None
                        elif resp.status == 429:
                            logger.warning(f"Rate limited by {url}")
                except Exception as e:
                    logger.debug(f"Failed to fetch from {url}: {e}")
                return None

            async with aiohttp.ClientSession(headers=headers) as session:
                tasks = [fetch_json(session, url) for url in urls]
                results = await asyncio.gather(*tasks)

                for data in results:
                    if data:
                        # Extract description from JSON response
                        # Handle multiple possible response structures
                        desc = None

                        # Structure 1: {"result": {"project": {...}}}
                        if isinstance(data, dict):
                            result = data.get('result')
                            if isinstance(result, dict):
                                project_data = result.get('project')
                                if isinstance(project_data, dict):
                                    desc = project_data.get('description')
                                else:
                                    desc = result.get('description')
                            # Structure 2: {"project": {...}}
                            elif not desc:
                                project_data = data.get('project')
                                if isinstance(project_data, dict):
                                    desc = project_data.get('description')
                            # Structure 3: {"description": "..."} direct
                            elif not desc:
                                desc = data.get('description')

                        if desc and isinstance(desc, str):
                            logger.info(f"Fetched full description for project {project_id} ({len(desc)} chars)")
                            return desc

            logger.warning(f"Could not fetch full description for project {project_id}")
            return None

        except Exception as e:
            logger.error(f"Error fetching full description: {e}")
            return None

    async def create_bid(
        self,
        project_id: int,
        amount: float,
        period: int = 7,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new bid for a project.

        Args:
            project_id: Target project ID
            amount: Bid amount
            period: Duration in days
            description: Bid proposal text

        Returns:
            Bid creation result

        Note: Uses direct requests API instead of SDK to fix bidder_id type issues (REF-007)
        """
        try:
            logger.info(f"Creating bid for project {project_id}, amount: {amount}, period: {period}, user_id: {self.user_id}")

            # 直接使用 requests 库绕过 SDK 类型问题
            import requests as req_module

            # 构建投标 URL - 使用当前域名配置
            bid_url = f"{settings.FLN_URL}/api/projects/0.1/bids/"

            # 确保所有数值都是整数类型
            bid_data = {
                'project_id': int(project_id),
                'bidder_id': int(self.user_id),
                'amount': int(amount),
                'period': int(period),
                'description': description or "",
                'milestone_percentage': 100
            }

            logger.info(f"Sending bid data: project_id={bid_data['project_id']}, amount={bid_data['amount']}")

            # 使用同步请求
            response = req_module.post(
                bid_url,
                json=bid_data,
                headers={
                    'Freelancer-OAuth-V1': settings.FREELANCER_OAUTH_TOKEN,
                    'Content-Type': 'application/json',
                    'User-Agent': 'Mozilla/5.0'
                },
                timeout=30,
                verify=True
            )

            logger.info(f"Response status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Successfully created bid: {result}")
                return result
            else:
                error_msg = response.text[:500] if response.text else "Unknown error"
                raise FreelancerAPIError(
                    message=f"Failed to create bid (HTTP {response.status_code}): {error_msg}",
                    status_code=response.status_code
                )

        except Exception as e:
            logger.error(f"Failed to create bid: {e}")
            raise FreelancerAPIError(
                message=f"Failed to create bid: {str(e)}",
                status_code=500
            )

    async def update_bid(
        self,
        bid_id: int,
        amount: Optional[float] = None,
        period: Optional[int] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update an existing bid.

        Args:
            bid_id: Bid ID to update
            amount: New bid amount
            period: New duration in days
            description: New proposal text

        Returns:
            Update result
        """
        try:
            logger.info(f"Updating bid {bid_id}")

            update_data = {}

            if amount is not None:
                update_data['amount'] = amount
            if period is not None:
                update_data['period'] = period
            if description:
                update_data['description'] = description

            # update_bid is not supported in this version of the SDK
            logger.error("update_bid is not supported in freelancersdk 0.1.20")
            raise FreelancerAPIError(
                message="Updating bids is not supported by the current SDK version",
                status_code=501
            )

        except Exception as e:
            logger.error(f"Failed to update bid {bid_id}: {e}")
            raise FreelancerAPIError(
                message=f"Failed to update bid: {str(e)}",
                status_code=500
            )

    async def retract_bid(self, bid_id: int) -> Dict[str, Any]:
        """
        Retract (withdraw) an existing bid.

        Args:
            bid_id: Bid ID to retract

        Returns:
            Retract result
        """
        try:
            logger.info(f"Retracting bid {bid_id}")
            
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: retract_bid(self.session, bid_id)
            )

            logger.info(f"Successfully retracted bid {bid_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to retract bid {bid_id}: {e}")
            raise FreelancerAPIError(
                message=f"Failed to retract bid: {str(e)}",
                status_code=500
            )

    async def create_milestone(
        self,
        project_id: int,
        bidder_id: int,
        amount: float,
        description: str,
        due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a milestone payment for a project.

        Args:
            project_id: Project ID
            bidder_id: ID of the freelancer (bidder)
            amount: Milestone amount
            description: Milestone description
            due_date: Due date (ISO format)

        Returns:
            Milestone creation result
        """
        try:
            logger.info(f"Creating milestone for project {project_id}, bidder {bidder_id}, amount: {amount}")

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: create_milestone(
                    self.session,
                    project_id=project_id,
                    bidder_id=bidder_id,
                    amount=amount,
                    reason="PARTIAL_PAYMENT",
                    description=description
                )
            )

            logger.info(f"Successfully created milestone: {result}")
            return result

        except Exception as e:
            logger.error(f"Failed to create milestone: {e}")
            raise FreelancerAPIError(
                message=f"Failed to create milestone: {str(e)}",
                status_code=500
            )

    async def accept_milestone(self, milestone_id: int) -> Dict[str, Any]:
        """
        Accept a milestone payment request.

        Args:
            milestone_id: Milestone ID

        Returns:
            Accept result
        """
        try:
            logger.info(f"Accepting milestone {milestone_id}")
            
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: accept_milestone(self.session, milestone_id)
            )

            logger.info(f"Successfully accepted milestone {milestone_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to accept milestone {milestone_id}: {e}")
            raise FreelancerAPIError(
                message=f"Failed to accept milestone: {str(e)}",
                status_code=500
            )

    async def release_milestone(self, milestone_id: int) -> Dict[str, Any]:
        """
        Release payment for a completed milestone.

        Args:
            milestone_id: Milestone ID

        Returns:
            Release result
        """
        try:
            logger.info(f"Releasing milestone {milestone_id}")
            
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: release_milestone_payment(self.session, milestone_id)
            )

            logger.info(f"Successfully released milestone {milestone_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to release milestone {milestone_id}: {e}")
            raise FreelancerAPIError(
                message=f"Failed to release milestone: {str(e)}",
                status_code=500
            )

    async def send_message(
        self,
        thread_id: Optional[int] = None,
        to_user_id: Optional[int] = None,
        message: str = None
    ) -> Dict[str, Any]:
        """
        Send a message to a thread or user.

        Args:
            thread_id: Message thread ID
            to_user_id: Recipient user ID
            message: Message content

        Returns:
            Message sending result
        """
        try:
            logger.info(f"Sending message (thread: {thread_id}, user: {to_user_id})")

            message_data = {}

            if thread_id:
                message_data['thread_id'] = thread_id
            elif to_user_id:
                message_data['to_user_id'] = to_user_id
            else:
                raise ValueError("Either thread_id or to_user_id must be provided")

            if message:
                message_data['message'] = message

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: post_message(self.session, **message_data)
            )

            logger.info(f"Successfully sent message")
            return result

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise FreelancerAPIError(
                message=f"Failed to send message: {str(e)}",
                status_code=500
            )

    async def upload_attachment(
        self,
        file_path: str,
        thread_id: int
    ) -> Dict[str, Any]:
        """
        Upload an attachment to a message thread.

        Args:
            file_path: Path to the file
            thread_id: Target thread ID

        Returns:
            Upload result with attachment URL
        """
        try:
            logger.info(f"Uploading attachment to thread {thread_id}")

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: upload_attachment(
                    self.session,
                    file_path=file_path,
                    thread_id=thread_id
                )
            )

            logger.info(f"Successfully uploaded attachment: {result}")
            return result

        except Exception as e:
            logger.error(f"Failed to upload attachment: {e}")
            raise FreelancerAPIError(
                message=f"Failed to upload attachment: {str(e)}",
                status_code=500
            )

    async def get_messages(
        self,
        thread_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get messages from a thread.

        Args:
            thread_id: Message thread ID
            limit: Number of messages to return
            offset: Pagination offset

        Returns:
            List of messages
        """
        try:
            logger.info(f"Getting messages for thread {thread_id}")

            loop = asyncio.get_running_loop()
            messages = await loop.run_in_executor(
                None,
                lambda: get_messages(
                    self.session,
                    thread_id=thread_id,
                    limit=limit,
                    offset=offset
                )
            )

            return messages

        except Exception as e:
            logger.error(f"Failed to get messages: {e}")
            raise FreelancerAPIError(
                message=f"Failed to get messages: {str(e)}",
                status_code=500
            )


    async def get_threads(
        self,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get message threads.

        Args:
            limit: Number of threads to return
            offset: Pagination offset
            unread_only: Filter by unread threads

        Returns:
            List of threads
        """
        try:
            logger.info(f"Getting threads (unread_only={unread_only})")

            # Determine endpoint arguments based on SDK capabilities
            # Using basic arguments for now as per common SDK patterns
            
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: get_threads(
                    self.session,
                    limit=limit,
                    offset=offset
                )
            )

            # result is typically {'threads': [...], 'users': {...}}
            # We might want to enrich thread data with user info here if needed
            # For now, just return the threads list
            if isinstance(result, dict):
                return result.get('threads', [])
            return []

        except Exception as e:
            logger.error(f"Failed to get threads: {e}")
            raise FreelancerAPIError(
                message=f"Failed to get threads: {str(e)}",
                status_code=500
            )


# Singleton client instance
_client: Optional[FreelancerClient] = None


def get_freelancer_client() -> FreelancerClient:
    """Get or create singleton Freelancer client."""
    global _client
    if _client is None:
        _client = FreelancerClient()
    return _client
