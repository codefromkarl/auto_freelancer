"""
Freelancer SDK client wrapper with authentication and error handling.

修复版本：修复 bidder_id 类型错误
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
        except Exception as e:
            logger.error(f"Failed to initialize Freelancer client: {e}")
            raise FreelancerAPIError(
                message="Authentication failed",
                status_code=401
            )

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        """
        获取客户（雇主）基本信息（用于风控/资格审查）。
        """
        if user_id <= 0:
            raise FreelancerAPIError(message="Invalid user_id", status_code=400)

        ttl = int(getattr(settings, "FREELANCER_USER_CACHE_TTL_SECONDS", 600))
        now = time.monotonic()
        async with self._cache_lock:
            cached = self._user_cache.get(int(user_id))
            if cached and cached[0] > now:
                return cached[1]

        await self._rate_limiter.acquire()
        try:
            fetcher = getattr(self, "_fetch_user_http")
            user = await fetcher(int(user_id))  # type: ignore[misc]
            normalized = self._normalize_user(user)

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

        Note: Uses direct requests API instead of SDK to fix bidder_id type issues
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


# Singleton instance
_client: Optional[FreelancerClient] = None


def get_freelancer_client() -> FreelancerClient:
    """Get or create singleton Freelancer client."""
    global _client
    if _client is None:
        _client = FreelancerClient()
    return _client


def create_freelancer_client() -> FreelancerClient:
    """Create a new Freelancer client instance."""
    return FreelancerClient()
