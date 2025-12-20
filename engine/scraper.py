import asyncio
import random
import hashlib
import json
import urllib.robotparser
from typing import Dict, Any, Optional, List, Callable, Awaitable
from urllib.parse import urljoin, urlparse
from itertools import cycle

from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright, Page
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from aiolimiter import AsyncLimiter
from fake_useragent import UserAgent

from engine.checkpoint import CheckpointManager

# --- ROBUST STEALTH IMPORT ---
stealth_async: Optional[Callable[[Page], Awaitable[None]]] = None

try:
    # 1. Try importing the async function directly (Standard)
    from playwright_stealth import stealth_async # type: ignore
except ImportError:
    try:
        # 2. Try importing from the submodule (Some versions/forks)
        from playwright_stealth.stealth import stealth_async # type: ignore
    except ImportError:
        logger.warning("⚠️ Could not import 'playwright-stealth'. Bot evasion will be disabled.")

# Final check to ensure we have a callable function
if stealth_async and not callable(stealth_async):
    logger.warning("⚠️ 'stealth_async' is not callable (likely a module). Disabling stealth.")
    stealth_async = None
# -----------------------------

from engine.schemas import ScraperConfig, ScrapeMode, InteractionType
from engine.resolver import HtmlResolver

class ScraperEngine:
    """
    Core scraping engine handling resource management, concurrency, and parsing strategies.
    """
    def __init__(
        self, 
        config: ScraperConfig, 
        output_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        stats_callback: Optional[Callable[[str], None]] = None
    ):
        self.config = config
        self.aggregated_data: Dict[str, Any] = {}
        self.output_callback = output_callback
        self.stats_callback = stats_callback
        
        # Resources
        self.playwright = None
        self.browser = None
        self.context = None
        self.session: Optional[AsyncSession] = None
        self.robots_parser: Optional[urllib.robotparser.RobotFileParser] = None
        
        # State Management
        self.checkpoint = CheckpointManager(config.name, config.use_checkpointing)
        
        # Concurrency & Safety
        self.data_lock = asyncio.Lock() 
        self.seen_hashes = set() 
        self.rate_limiter = AsyncLimiter(self.config.rate_limit, 1) 
        self.ua_rotator = UserAgent()
        
        # Proxy Rotation
        self.proxy_pool = cycle(config.proxies) if config.proxies else None

    async def run(self) -> Dict[str, Any]:
        """Main entry point. Initializes resources and dispatches the appropriate scrape mode."""
        logger.info(f"🚀 Starting ASYNC scrape for: {self.config.name} (Mode: {self.config.mode.value})")
        
        await self._setup_resources()
        
        if self.config.respect_robots_txt:
            await self._init_robots_txt()

        try:
            if self.config.mode == ScrapeMode.LIST:
                await self._run_list_mode()
            else:
                await self._run_pagination_mode()
        finally:
            await self._cleanup_resources()
            self.checkpoint.close()

        total_items = sum(len(v) if isinstance(v, list) else 1 for v in self.aggregated_data.values())
        logger.success(f"✅ Finished! Extracted {total_items} total unique items.")
        return self.aggregated_data

    def _get_next_proxy(self) -> Optional[str]:
        if self.proxy_pool:
            return next(self.proxy_pool)
        return None

    async def _init_robots_txt(self):
        """Fetches and parses robots.txt for the base URL in a non-blocking thread."""
        logger.info("🤖 Checking robots.txt policies...")
        try:
            parsed_url = urlparse(str(self.config.base_url))
            robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
            
            self.robots_parser = urllib.robotparser.RobotFileParser()
            self.robots_parser.set_url(robots_url)
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.robots_parser.read)
            
            logger.info(f"✅ Robots.txt parsed from {robots_url}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to parse robots.txt: {e}. Defaulting to ALLOW all.")
            self.robots_parser = None

    def _is_allowed(self, url: str) -> bool:
        if not self.config.respect_robots_txt or not self.robots_parser:
            return True
        return self.robots_parser.can_fetch("*", url)

    async def _run_pagination_mode(self):
        """Executes depth-first pagination crawling."""
        current_url = str(self.config.base_url)
        pages_scraped = 0
        max_pages = self.config.pagination.max_pages if self.config.pagination else 1

        while pages_scraped < max_pages and current_url:
            if not self._is_allowed(current_url):
                logger.warning(f"⛔ URL blocked by robots.txt: {current_url}")
                if self.stats_callback: self.stats_callback("blocked")
                break

            logger.info(f"📄 Scraping Page {pages_scraped + 1}: {current_url}")
            
            html_content = await self._fetch_page(current_url)
            if not html_content:
                logger.error("❌ Failed to retrieve content. Stopping chain.")
                if self.stats_callback: self.stats_callback("error")
                break

            await self._process_content(html_content)
            self.checkpoint.mark_done(current_url)
            if self.stats_callback: self.stats_callback("success")
            
            pages_scraped += 1
            if self.config.pagination and pages_scraped < max_pages:
                resolver = HtmlResolver(html_content)
                next_link = resolver.get_attribute(self.config.pagination.selector, "href")
                if next_link:
                    current_url = urljoin(current_url, next_link)
                    delay = random.uniform(self.config.min_delay, self.config.max_delay)
                    await asyncio.sleep(delay)
                else:
                    logger.warning("🛑 No 'Next' button found.")
                    current_url = None
            else:
                current_url = None

    async def _run_list_mode(self):
        """Executes breadth-first parallel crawling."""
        raw_urls = self.config.start_urls or []
        urls = [str(u) for u in raw_urls]
        
        if self.config.use_checkpointing:
            original_count = len(urls)
            urls = [u for u in urls if not self.checkpoint.is_done(u)]
            skipped = original_count - len(urls)
            if skipped > 0:
                logger.info(f"⏭️ Skipping {skipped} URLs (already in checkpoint).")
                if self.stats_callback: 
                    for _ in range(skipped): self.stats_callback("skipped")

        if not urls:
            logger.warning("⚠️ No URLs to process.")
            return

        sem = asyncio.Semaphore(self.config.concurrency)
        logger.info(f"⚡ Processing {len(urls)} URLs with Concurrency={self.config.concurrency}")

        async def _worker(url):
            if not self._is_allowed(url):
                logger.warning(f"⛔ URL blocked by robots.txt: {url}")
                if self.stats_callback: self.stats_callback("blocked")
                return

            async with sem:
                async with self.rate_limiter:
                    logger.info(f"▶️ Fetching: {url}")
                    html = await self._fetch_page(url)
                    if html:
                        await self._process_content(html)
                        self.checkpoint.mark_done(url)
                        if self.stats_callback: self.stats_callback("success")
                        delay = random.uniform(0.5, 1.5)
                        await asyncio.sleep(delay)
                    else:
                        if self.stats_callback: self.stats_callback("error")

        tasks = [_worker(url) for url in urls]
        await asyncio.gather(*tasks)
    
    async def _process_content(self, html: str):
        try:
            resolver = HtmlResolver(html)
            data = self._extract_data(resolver)
            await self._merge_data(data)
        except Exception as e:
            logger.error(f"⚠️ Parsing/Extraction Error: {e}")
            if self.stats_callback: self.stats_callback("error")

    async def _setup_resources(self):
        if self.config.use_playwright:
            logger.info("🎭 Launching Playwright...")
            self.playwright = await async_playwright().start()
            
            launch_args: Dict[str, Any] = {"headless": True}
            
            proxy_url = self._get_next_proxy()
            if proxy_url:
                logger.info(f"🛡️ Using Proxy: {proxy_url}")
                launch_args["proxy"] = {"server": proxy_url}
                
            self.browser = await self.playwright.chromium.launch(**launch_args)
            
            dynamic_ua = self.ua_rotator.random
            logger.info(f"🕵️  Playwright User-Agent: {dynamic_ua}")
            
            self.context = await self.browser.new_context(
                user_agent=dynamic_ua,
                viewport={"width": 1920, "height": 1080}
            )
        else:
            # Using stable browser fingerprints supported by curl_cffi
            browser_choice: Any = random.choice(["chrome110", "chrome120", "chrome100", "opera78", "safari17_0"])
            logger.info(f"🕵️ Impersonating: {browser_choice}")
            self.session = AsyncSession(impersonate=browser_choice)

    async def _cleanup_resources(self):
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
        if self.session: await self.session.close()

    async def _handle_interactions(self, page):
        """Executes defined browser interactions (click, scroll, fill)."""
        if not self.config.interactions:
            return

        for action in self.config.interactions:
            try:
                if action.type == InteractionType.WAIT:
                    await page.wait_for_timeout(action.duration or 1000)
                
                elif action.type == InteractionType.SCROLL:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1) # Settle
                
                elif action.type == InteractionType.CLICK and action.selector:
                    await page.click(action.selector)
                
                elif action.type == InteractionType.FILL and action.selector and action.value:
                    await page.fill(action.selector, action.value)
                
                elif action.type == InteractionType.PRESS and action.selector and action.value:
                    await page.press(action.selector, action.value)
                    
            except Exception as e:
                logger.warning(f"⚠️ Interaction failed ({action.type}): {e}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(Exception))
    async def _fetch_page(self, url: str) -> str:
        current_proxy = self._get_next_proxy()
        
        if self.config.use_playwright:
            if not self.context: return ""
            page = None 
            try:
                page = await self.context.new_page()
                
                # Robust Stealth Call
                if stealth_async:
                    await stealth_async(page)
                
                await page.goto(url, timeout=30000)
                
                # Interactions
                await self._handle_interactions(page)
                
                # Standard Wait
                if self.config.wait_for_selector:
                    try:
                        await page.wait_for_selector(self.config.wait_for_selector, timeout=10000)
                    except Exception:
                        pass
                
                content = await page.content()
                return content
            except Exception as e:
                logger.warning(f"Browser Error: {e}")
                raise e
            finally:
                if page:
                    await page.close()
        else:
            if not self.session: return ""
            try:
                proxies: Any = None
                if current_proxy:
                    proxies = {"http": current_proxy, "https": current_proxy}

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

    async def _merge_data(self, page_data: Dict[str, Any]):
        async with self.data_lock: 
            for key, value in page_data.items():
                if key not in self.aggregated_data:
                    self.aggregated_data[key] = value
                else:
                    target = self.aggregated_data[key]
                    if isinstance(target, list) and isinstance(value, list):
                        for item in value:
                            item_hash = hashlib.md5(json.dumps(item, sort_keys=True).encode()).hexdigest()
                            if item_hash not in self.seen_hashes:
                                target.append(item)
                                self.seen_hashes.add(item_hash)
            
            if self.output_callback:
                await self.output_callback(page_data)