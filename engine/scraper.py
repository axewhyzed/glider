import asyncio
import random
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin

# Async Imports
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
# NEW: Anti-Bot Stealth (Added type: ignore to silence Pylance error)
from playwright_stealth import stealth_async  # type: ignore
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from engine.schemas import ScraperConfig, ScrapeMode
from engine.resolver import HtmlResolver

class ScraperEngine:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.aggregated_data: Dict[str, Any] = {}
        # Resources
        self.playwright = None
        self.browser = None
        self.context = None
        self.session: Optional[AsyncSession] = None

    async def run(self) -> Dict[str, Any]:
        """
        Main Entry Point: Dispatches to Pagination or List mode.
        """
        logger.info(f"🚀 Starting ASYNC scrape for: {self.config.name} (Mode: {self.config.mode.value})")
        
        await self._setup_resources()

        try:
            if self.config.mode == ScrapeMode.LIST:
                await self._run_list_mode()
            else:
                await self._run_pagination_mode()
        finally:
            await self._cleanup_resources()

        # Count total items for logging
        total_items = sum(len(v) if isinstance(v, list) else 1 for v in self.aggregated_data.values())
        logger.success(f"✅ Finished! Extracted {total_items} total items.")
        return self.aggregated_data

    async def _run_pagination_mode(self):
        """
        Standard Mode: Fetches Page 1 -> Finds Next Link -> Fetches Page 2...
        """
        current_url = str(self.config.base_url)
        pages_scraped = 0
        max_pages = self.config.pagination.max_pages if self.config.pagination else 1

        while pages_scraped < max_pages and current_url:
            logger.info(f"📄 Scraping Page {pages_scraped + 1}: {current_url}")
            
            html_content = await self._fetch_page(current_url)
            if not html_content:
                logger.error("❌ Failed to retrieve content. Stopping chain.")
                break

            resolver = HtmlResolver(html_content)
            page_data = self._extract_data(resolver)
            self._merge_data(page_data)
            
            pages_scraped += 1
            if self.config.pagination and pages_scraped < max_pages:
                next_link = resolver.get_attribute(self.config.pagination.selector, "href")
                if next_link:
                    current_url = urljoin(current_url, next_link)
                    
                    delay = random.uniform(self.config.min_delay, self.config.max_delay)
                    logger.debug(f"💤 Sleeping for {delay:.2f}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.warning("🛑 No 'Next' button found.")
                    current_url = None
            else:
                current_url = None

    async def _run_list_mode(self):
        """
        List Mode: Fetches a list of URLs in PARALLEL.
        """
        raw_urls = self.config.start_urls or []
        urls = [str(u) for u in raw_urls]
        
        if not urls:
            logger.warning("⚠️ No start_urls provided for List Mode.")
            return

        sem = asyncio.Semaphore(self.config.concurrency)
        logger.info(f"⚡ Processing {len(urls)} URLs with Concurrency={self.config.concurrency}")

        async def _worker(url):
            async with sem:
                logger.info(f"▶️ Fetching: {url}")
                html = await self._fetch_page(url)
                if html:
                    resolver = HtmlResolver(html)
                    data = self._extract_data(resolver)
                    self._merge_data(data)
                    delay = random.uniform(0.5, 1.5)
                    await asyncio.sleep(delay)

        tasks = [_worker(url) for url in urls]
        await asyncio.gather(*tasks)

    # --- Resources & Networking ---

    async def _setup_resources(self):
        if self.config.use_playwright:
            logger.info("🎭 Launching Playwright...")
            self.playwright = await async_playwright().start()
            
            launch_args: Dict[str, Any] = {"headless": True}
            
            if self.config.proxy:
                logger.info(f"🛡️ Using Proxy: {self.config.proxy}")
                launch_args["proxy"] = {"server": self.config.proxy}
                
            self.browser = await self.playwright.chromium.launch(**launch_args)
            
            # Setup Context with better user-agent simulation
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )
        else:
            self.session = AsyncSession(impersonate="chrome110")

    async def _cleanup_resources(self):
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
        if self.session: await self.session.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(Exception))
    async def _fetch_page(self, url: str) -> str:
        if self.config.use_playwright:
            if not self.context: return ""
            try:
                page = await self.context.new_page()
                
                # APPLY STEALTH
                await stealth_async(page)
                
                await page.goto(url, timeout=30000)
                if self.config.wait_for_selector:
                    try:
                        await page.wait_for_selector(self.config.wait_for_selector, timeout=10000)
                    except Exception:
                        pass
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                content = await page.content()
                await page.close()
                return content
            except Exception as e:
                logger.warning(f"Browser Error: {e}")
                raise e
        else:
            if not self.session: return ""
            try:
                proxies: Any = None
                if self.config.proxy:
                    proxies = {"http": self.config.proxy, "https": self.config.proxy}
                response = await self.session.get(url, timeout=15, proxies=proxies)
                if response.status_code == 200:
                    return response.text
                elif response.status_code in [403, 429, 500, 502, 503, 504]:
                    raise Exception(f"Status: {response.status_code}")
                else:
                    logger.error(f"Hard Failure: {response.status_code}")
                    return ""
            except Exception as e:
                logger.warning(f"Network Error: {e}")
                raise e

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