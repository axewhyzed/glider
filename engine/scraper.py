import asyncio
import random
from typing import Dict, Any, Optional
from urllib.parse import urljoin

# Async Imports
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from engine.schemas import ScraperConfig
from engine.resolver import HtmlResolver

class ScraperEngine:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.aggregated_data: Dict[str, Any] = {}
        # Resources
        self.playwright = None
        self.browser = None
        self.context = None  # Browser Context (Cookies/Session)
        self.session: Optional[AsyncSession] = None  # Explicit type hint

    async def run(self) -> Dict[str, Any]:
        """
        Async Execution Loop.
        """
        logger.info(f"🚀 Starting ASYNC scrape for: {self.config.name}")
        
        # 1. Setup Resources
        await self._setup_resources()

        try:
            current_url = str(self.config.base_url)
            pages_scraped = 0
            max_pages = self.config.pagination.max_pages if self.config.pagination else 1

            while pages_scraped < max_pages and current_url:
                logger.info(f"📄 Scraping Page {pages_scraped + 1}: {current_url}")
                
                # FETCH (Async & Retrying)
                html_content = await self._fetch_page(current_url)
                
                if not html_content:
                    logger.error("❌ Failed to retrieve content after retries. Stopping.")
                    break

                # PARSE (CPU Bound - technically blocks loop briefly, but fine for text)
                resolver = HtmlResolver(html_content)
                
                # EXTRACT
                page_data = self._extract_data(resolver)
                self._merge_data(page_data)
                
                # PAGINATE
                pages_scraped += 1
                if self.config.pagination and pages_scraped < max_pages:
                    next_link = resolver.get_attribute(self.config.pagination.selector, "href")
                    if next_link:
                        current_url = urljoin(current_url, next_link)
                        
                        # Async Sleep
                        delay = random.uniform(self.config.min_delay, self.config.max_delay)
                        logger.debug(f"💤 Sleeping for {delay:.2f}s...")
                        await asyncio.sleep(delay)
                    else:
                        logger.warning("🛑 No 'Next' button found.")
                        current_url = None
                else:
                    current_url = None
                    
        finally:
            await self._cleanup_resources()

        logger.success(f"✅ Finished! Scraped {pages_scraped} pages.")
        return self.aggregated_data

    async def _setup_resources(self):
        """Initializes AsyncSession or Playwright Browser"""
        if self.config.use_playwright:
            logger.info("🎭 Launching Playwright...")
            self.playwright = await async_playwright().start()
            
            launch_args: Dict[str, Any] = {"headless": True}
            if self.config.proxy:
                logger.info(f"🛡️ Using Proxy: {self.config.proxy}")
                launch_args["proxy"] = {"server": self.config.proxy}
            
            self.browser = await self.playwright.chromium.launch(**launch_args)
            # Create a persistent context for the entire session
            self.context = await self.browser.new_context()
        else:
            # Initialize Curl AsyncSession
            self.session = AsyncSession(impersonate="chrome110")

    async def _cleanup_resources(self):
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
        if self.session: await self.session.close()

    # RETRY DECORATOR: Retries 3 times, waiting 2^x seconds, on Exceptions
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(Exception))
    async def _fetch_page(self, url: str) -> str:
        """
        Robust Async Fetcher with Retries.
        """
        # METHOD A: Playwright
        if self.config.use_playwright:
            if not self.context: return ""
            try:
                page = await self.context.new_page()
                await page.goto(url, timeout=30000)
                
                if self.config.wait_for_selector:
                    try:
                        await page.wait_for_selector(self.config.wait_for_selector, timeout=10000)
                    except Exception:
                        logger.warning(f"Timeout waiting for selector: {self.config.wait_for_selector}")

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1) # Tiny wait for animations
                
                content = await page.content()
                await page.close()
                return content
            except Exception as e:
                logger.warning(f"Browser Error (Retrying): {e}")
                raise e # Trigger Tenacity Retry

        # METHOD B: Curl_Cffi (Async)
        else:
            # FIX: Explicit check ensures self.session is not None
            if not self.session:
                logger.error("Session not initialized.")
                return ""

            try:
                # Type Hinting workaround
                proxies: Any = None
                if self.config.proxy:
                    proxies = {"http": self.config.proxy, "https": self.config.proxy}

                response = await self.session.get(
                    url, 
                    timeout=15,
                    proxies=proxies
                )
                
                if response.status_code == 200:
                    return response.text
                elif response.status_code in [403, 429, 500, 502, 503, 504]:
                    # Raise exception for retryable codes
                    raise Exception(f"Bad Status Code: {response.status_code}")
                else:
                    logger.error(f"❌ Hard Failure Status: {response.status_code}")
                    return ""
            except Exception as e:
                logger.warning(f"Network Error (Retrying): {e}")
                raise e # Trigger Tenacity Retry

    def _extract_data(self, resolver: HtmlResolver) -> Dict[str, Any]:
        data = {}
        for field in self.config.fields:
            data[field.name] = resolver.resolve_field(field)
        return data

    def _merge_data(self, page_data: Dict[str, Any]):
        for key, value in page_data.items():
            if key not in self.aggregated_data:
                self.aggregated_data[key] = value
            else:
                if isinstance(self.aggregated_data[key], list) and isinstance(value, list):
                    self.aggregated_data[key].extend(value)