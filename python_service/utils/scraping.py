"""
Web scraping utilities with anti-blocking strategies.
"""
import aiohttp
import asyncio
import random
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import re

logger = logging.getLogger(__name__)


# Common browser User-Agents to rotate
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
]


class ScrapingConfig:
    """Configuration for web scraping with anti-blocking measures."""

    def __init__(
        self,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        max_retries: int = 3,
        timeout: float = 10.0
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.timeout = timeout
        self.last_request_time = None

    async def wait_for_rate_limit(self):
        """Wait between requests to avoid rate limiting."""
        if self.last_request_time:
            elapsed = (datetime.now() - self.last_request_time).total_seconds()
            delay = random.uniform(self.min_delay, self.max_delay)

            if elapsed < delay:
                wait_time = delay - elapsed
                logger.info(f"Rate limiting: waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)

        self.last_request_time = datetime.now()


class ScrapingCache:
    """Simple in-memory cache for scraped content."""

    def __init__(self, ttl_hours: int = 24):
        self.cache: Dict[str, tuple[str, datetime]] = {}
        self.ttl = timedelta(hours=ttl_hours)

    def get(self, key: str) -> Optional[str]:
        """Get cached value if not expired."""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                logger.debug(f"Cache hit for {key}")
                return value
            else:
                # Expired, remove
                del self.cache[key]
        return None

    def set(self, key: str, value: str):
        """Set cache value with current timestamp."""
        self.cache[key] = (value, datetime.now())
        logger.debug(f"Cached {key}")

    def clear_expired(self):
        """Clear expired entries."""
        now = datetime.now()
        expired_keys = [k for k, (_, t) in self.cache.items() if now - t >= self.ttl]
        for k in expired_keys:
            del self.cache[k]
        if expired_keys:
            logger.debug(f"Cleared {len(expired_keys)} expired cache entries")


# Global cache instance
_description_cache = ScrapingCache(ttl_hours=24)


def get_random_user_agent() -> str:
    """Get a random User-Agent string."""
    return random.choice(USER_AGENTS)


def get_common_headers() -> Dict[str, str]:
    """Get headers that mimic a real browser."""
    return {
        'User-Agent': get_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }


async def fetch_project_description(
    project_id: int,
    config: Optional[ScrapingConfig] = None,
    use_cache: bool = True
) -> Optional[str]:
    """
    Fetch full project description from Freelancer web page with anti-blocking measures.

    Args:
        project_id: Freelancer project ID
        config: Scraping configuration
        use_cache: Whether to use cache

    Returns:
        Full description string or None if not found
    """
    if config is None:
        config = ScrapingConfig()

    cache_key = f"project_desc_{project_id}"

    # Check cache first
    if use_cache:
        cached = _description_cache.get(cache_key)
        if cached:
            return cached

    # Try multiple URLs in order
    urls = [
        f"https://www.freelancer.cn/api/projects/0.1/projects/{project_id}/",
        f"https://www.freelancer.com/api/projects/0.1/projects/{project_id}/",
    ]

    for attempt in range(config.max_retries):
        for url in urls:
            try:
                await config.wait_for_rate_limit()

                headers = get_common_headers()

                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config.timeout)) as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            html = await resp.text()

                            # Extract description from embedded JSON
                            pattern = r'"description":"([^"]+)"'
                            match = re.search(pattern, html)

                            if match:
                                # Clean up JSON escapes
                                desc = match.group(1)
                                desc = desc.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')

                                # Cache the result
                                if use_cache:
                                    _description_cache.set(cache_key, desc)

                                logger.info(f"Fetched description for project {project_id} ({len(desc)} chars)")
                                return desc

                            # Try alternative extraction
                            pattern2 = r'"description":"(.*?)(?="status")'
                            match2 = re.search(pattern2, html, re.DOTALL)
                            if match2:
                                desc = match2.group(1)
                                desc = desc.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
                                if use_cache:
                                    _description_cache.set(cache_key, desc)
                                logger.info(f"Fetched description for project {project_id} (alt method)")
                                return desc

                        elif resp.status == 429:
                            # Rate limited, wait longer
                            wait_time = (attempt + 1) * 10
                            logger.warning(f"Rate limited (429), waiting {wait_time}s")
                            await asyncio.sleep(wait_time)

            except asyncio.TimeoutError:
                logger.warning(f"Timeout fetching {url}, attempt {attempt + 1}/{config.max_retries}")
            except Exception as e:
                logger.debug(f"Failed to fetch {url}: {e}")

    logger.warning(f"Could not fetch full description for project {project_id} after {config.max_retries} attempts")
    return None


async def clear_expired_cache():
    """Clear expired cache entries."""
    _description_cache.clear_expired()
