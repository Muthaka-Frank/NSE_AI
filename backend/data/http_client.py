"""
NSE AI Platform — Stealth HTTP Client & Anti-IP-Ban Protection Engine
Provides:
  1. Realistic desktop browser fingerprinting (User-Agents, Sec-CH-UA, headers).
  2. Centralized proxy support (HTTP, HTTPS, SOCKS5 via SCRAPER_PROXY).
  3. Global circuit breaker with automatic backoff on 403, 429, or network drop.
  4. Polite request throttling with randomized human-like jitter.
"""

import time
import random
import logging
from typing import Optional, Dict, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from core.config import settings

logger = logging.getLogger(__name__)

# Modern realistic desktop User-Agents
DESKTOP_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
]

# Circuit breaker state
_CIRCUIT_BREAKER_UNTIL = 0.0
_CIRCUIT_BREAKER_REASON = ""


def get_random_headers(referer: str = "https://www.google.com/") -> Dict[str, str]:
    """Generates authentic browser navigation headers with rotating User-Agent."""
    ua = random.choice(DESKTOP_USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site" if referer else "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def is_circuit_breaker_active() -> bool:
    """Returns True if the circuit breaker is currently cooling down."""
    return time.time() < _CIRCUIT_BREAKER_UNTIL


def get_circuit_breaker_remaining() -> int:
    """Returns remaining seconds on active circuit breaker cooldown."""
    return max(0, int(_CIRCUIT_BREAKER_UNTIL - time.time()))


def trip_circuit_breaker(reason: str, duration_secs: Optional[int] = None):
    """Activates the circuit breaker to cease all external requests and protect the IP."""
    global _CIRCUIT_BREAKER_UNTIL, _CIRCUIT_BREAKER_REASON
    duration = duration_secs or settings.SCRAPER_CIRCUIT_BREAKER_SECS
    _CIRCUIT_BREAKER_UNTIL = time.time() + duration
    _CIRCUIT_BREAKER_REASON = reason
    logger.warning(
        "🚨 Anti-IP-Ban Circuit Breaker tripped: '%s'. External requests paused for %d seconds (%d min).",
        reason, duration, duration // 60
    )


def reset_circuit_breaker():
    """Manually resets the circuit breaker."""
    global _CIRCUIT_BREAKER_UNTIL, _CIRCUIT_BREAKER_REASON
    _CIRCUIT_BREAKER_UNTIL = 0.0
    _CIRCUIT_BREAKER_REASON = ""
    logger.info("Anti-IP-Ban Circuit Breaker reset.")


def get_stealth_session() -> requests.Session:
    """
    Creates a configured requests.Session with:
      - Proxy routing (if SCRAPER_PROXY is configured)
      - Zero blind retries (prevents hammering servers during blocks)
      - Realistic timeout and keep-alive configuration
    """
    session = requests.Session()

    # Mount adapter with 0 blind retries to prevent triggering rate limits
    no_retry_strategy = Retry(
        total=0,
        connect=0,
        read=0,
        status=0,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=no_retry_strategy, pool_connections=5, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Route through proxy if set in .env
    proxy_url = getattr(settings, "SCRAPER_PROXY", "").strip()
    if proxy_url:
        session.proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        logger.debug("Using scraper proxy: %s", proxy_url)

    return session


def safe_scrape_get(
    url: str,
    timeout: tuple = (3.0, 6.0),
    referer: str = "https://www.google.com/"
) -> Optional[requests.Response]:
    """
    Executes a polite HTTP GET with full anti-bot protection.
    Returns Response if successful, or None if failed/circuit-broken.
    """
    if is_circuit_breaker_active():
        logger.warning(
            "Scrape request to %s skipped — circuit breaker active (%d seconds remaining).",
            url, get_circuit_breaker_remaining()
        )
        return None

    session = get_stealth_session()
    headers = get_random_headers(referer=referer)

    try:
        resp = session.get(url, headers=headers, timeout=timeout)
        
        # Check for rate limiting / WAF blocking
        if resp.status_code in (403, 429):
            trip_circuit_breaker(f"HTTP {resp.status_code} received from {url}")
            return None
        
        if resp.status_code >= 500:
            logger.warning("Remote server returned HTTP %d for %s", resp.status_code, url)
            return None

        return resp

    except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as e:
        logger.warning("Timeout connecting to %s: %s", url, e)
        # Timeout on port 443 can indicate firewall silent drop; trip a short cooldown
        trip_circuit_breaker("Connection timed out (possible firewall block)", duration_secs=300)
        return None

    except requests.exceptions.ConnectionError as e:
        err_msg = str(e)
        if "Network is unreachable" in err_msg or "Errno 101" in err_msg:
            logger.warning("Local network is unreachable. Skipping external request to %s.", url)
            # Short 60s cooldown for local network recovery
            trip_circuit_breaker("Local network unreachable", duration_secs=60)
        else:
            logger.warning("Connection error connecting to %s: %s", url, e)
            trip_circuit_breaker(f"Connection failed ({type(e).__name__})", duration_secs=300)
        return None

    except Exception as e:
        logger.error("Unexpected error fetching %s: %s", url, e)
        return None


def polite_delay(min_sec: float = 3.0, max_sec: float = 6.0):
    """Sleeps with randomized human-like jitter to prevent burst traffic."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)
