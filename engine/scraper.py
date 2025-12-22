import asyncio
import random
import hashlib
import json
import urllib.robotparser
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Awaitable, cast
from urllib.parse import urljoin, urlparse
from itertools import cycle
from collections import deque

from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright, Page
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed, retry_if_exception_type
from aiolimiter import AsyncLimiter
from fake_useragent import UserAgent

from engine.bloom import BloomFilter
from engine.checkpoint import CheckpointManager
from engine.schemas import ScraperConfig, ScrapeMode, InteractionType, StatsEvent
from engine.resolver import HtmlResolver

# Stealth import
stealth_async: Optional[Callable[[Page], Awaitable[None]]] = None
try:
    from playwright_stealth import stealth_async # type: ignore
except ImportError:
    pass
if stealth_async and not callable(stealth_async) and hasattr(stealth_async, 'stealth_async'):
    stealth_async = stealth_async.stealth_async # type: ignore


class ScraperEngine:
    """
    Fixed Scraper Engine v2.7.
    - Blocking I/O removed (async checkpoint)
    - Memory leak fixed (no aggregated_data)
    - CPU blocking fixed (thread pool for parsing)
    - Persistence added (bloom filter)
    """
    def __init__(
        self, 
        config: ScraperConfig, 
        output_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        stats_callback: Optional[Callable[[StatsEvent], None]] = None
    ):
        self.config = config
        self.failed_urls: List[str] = []
        self.output_callback = output_callback
        self.stats_callback = stats_callback
        
        # Resources
        self.playwright = None
        self.browser = None
        self.context = None
        self.session: Optional[AsyncSession] = None
        self.robots_parser: Optional[urllib.robotparser.RobotFileParser] = None
        
        # Async Checkpoint
        self.checkpoint = CheckpointManager(config.name, config.use_checkpointing)
        
        self.data_lock = asyncio.Lock() 
        
        # Bloom Filter Persistence
        self.bloom_path = Path("data") / f"{config.name.replace(' ', '_').lower()}.bloom"
        self.seen_hashes = BloomFilter(capacity=100000, error_rate=0.001)
        self.recent_hashes = deque(maxlen=1000)
        self.false_positive_count = 0
        
        self.rate_limiter = AsyncLimiter(self.config.rate_limit, 1) 
        self.ua_rotator = UserAgent()
        self.proxy_pool = cycle(config.proxies) if config.proxies else None
        
        self.batch_size = 10
        self.pending_batch: List[Dict[str, Any]] = []
        self.shutdown_requested = False

    async def run(self):
        logger.info(f"🚀 Starting ASYNC scrape for: {self.config.name}")
        
        await self._setup_resources()
        
        if self.config.respect_robots_txt and self.config.base_url:
            await self._init_robots_txt()
            
        incomplete_urls = await self.checkpoint.get_incomplete()
        if incomplete_urls:
            # Filter against cache
            incomplete_urls = [u for u in incomplete_urls if not self.checkpoint.is_done(u)]

        try:
            if self.config.mode == ScrapeMode.LIST:
                await self._run_list_mode(incomplete_urls)
            else:
                await self._run_pagination_mode()
        except asyncio.CancelledError:
            logger.warning("⚠️ Shutdown requested - flushing data...")
            await self._flush_remaining_batches()
            raise
        finally:
            await self._cleanup_resources()
            logger.success("✅ Finished!")

    async def _setup_resources(self):
        # 1. Initialize Checkpoint DB
        await self.checkpoint.initialize()
        
        # 2. Load Bloom Filter
        self.seen_hashes.load(self.bloom_path)
        
        # 3. Setup Browser/Session
        if self.config.use_playwright:
            self.playwright = await async_playwright().start()
            # Explicitly type as Dict[str, Any] to silence Pylance "Dict[str, bool]" inference error
            launch_args: Dict[str, Any] = {"headless": True}
            
            proxy_url = self._get_next_proxy()
            if proxy_url:
                launch_args["proxy"] = {"server": proxy_url}
                
            self.browser = await self.playwright.chromium.launch(**launch_args)
            self.context = await self.browser.new_context(
                user_agent=self.ua_rotator.random,
                viewport={"width": 1920, "height": 1080}
            )
        else:
            self._init_session()

    def _init_session(self):
        """Helper to create fresh session."""
        browser_choice = random.choice(["chrome110", "chrome120", "chrome100", "safari17_0"])
        # Cast to Any to satisfy Literal checks if necessary
        self.session = AsyncSession(impersonate=cast(Any, browser_choice))

    async def _cleanup_resources(self):
        # Save Bloom Filter
        try:
            self.seen_hashes.save(self.bloom_path)
        except Exception as e:
            logger.error(f"Failed to save bloom filter: {e}")

        await self.checkpoint.close()
        
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
        if self.session: await self.session.close()

    def _get_next_proxy(self) -> Optional[str]:
        if self.proxy_pool:
            return next(self.proxy_pool)
        return None

    async def _init_robots_txt(self):
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

    async def _run_list_mode(self, incomplete_urls: List[str] = []):
        raw_urls = self.config.start_urls or []
        all_urls = list(set([str(u) for u in raw_urls] + incomplete_urls))
        
        # Filter done URLs
        queue_urls = [u for u in all_urls if not self.checkpoint.is_done(u)]
        
        if not queue_urls:
            return

        # Fix: Use Queue to prevent Task Explosion (Severity P2)
        queue = asyncio.Queue()
        for u in queue_urls:
            queue.put_nowait(u)

        logger.info(f"⚡ Processing {len(queue_urls)} URLs with Concurrency={self.config.concurrency}")
        
        workers = []
        for _ in range(self.config.concurrency):
            workers.append(asyncio.create_task(self._worker_loop(queue)))
        
        await queue.join()
        
        for w in workers:
            w.cancel()

    async def _worker_loop(self, queue: asyncio.Queue):
        while not self.shutdown_requested:
            try:
                url = await queue.get()
                try:
                    await self._process_url(url)
                finally:
                    queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker Error: {e}")

    async def _process_url(self, url: str):
        if not self._is_allowed(url):
            if self.stats_callback: self.stats_callback(StatsEvent("blocked"))
            return

        async with self.rate_limiter:
            await self.checkpoint.mark_in_progress(url)
            try:
                html = await self._fetch_page(url)
                if html:
                    await self._process_content(html)
                    await self.checkpoint.mark_done(url)
                    if self.stats_callback: self.stats_callback(StatsEvent("page_success"))
                else:
                    raise Exception("Empty HTML")
            except Exception as e:
                logger.error(f"Failed {url}: {e}")
                self.failed_urls.append(url)
                if self.stats_callback: self.stats_callback(StatsEvent("page_error"))

    async def _run_pagination_mode(self):
        if not self.config.base_url:
             logger.error("Base URL is required for pagination mode.")
             return

        current_url = str(self.config.base_url)
        pages = 0
        max_pages = self.config.pagination.max_pages if self.config.pagination else 1

        while pages < max_pages and current_url and not self.shutdown_requested:
            if not self._is_allowed(current_url):
                logger.warning(f"⛔ URL blocked by robots.txt: {current_url}")
                if self.stats_callback: self.stats_callback(StatsEvent("blocked"))
                break
            
            logger.info(f"📄 Page {pages + 1}: {current_url}")
            await self.checkpoint.mark_in_progress(current_url)
            
            try:
                html = await self._fetch_page(current_url)
                if not html: raise Exception("Empty")
                
                # Extract Data (CPU Offloaded)
                resolver = await self._process_content(html)
                
                await self.checkpoint.mark_done(current_url)
                if self.stats_callback: self.stats_callback(StatsEvent("page_success"))
                
                pages += 1
                if self.config.pagination and pages < max_pages:
                    next_link = resolver.get_attribute(self.config.pagination.selector, "href")
                    if next_link:
                        current_url = urljoin(current_url, next_link)
                        await asyncio.sleep(random.uniform(self.config.min_delay, self.config.max_delay))
                    else:
                        logger.warning("🛑 No 'Next' button found.")
                        current_url = None
                else:
                    current_url = None
            except Exception as e:
                logger.error(f"Failed page {current_url}: {e}")
                if self.stats_callback: self.stats_callback(StatsEvent("page_error"))
                break

    async def _process_content(self, html: str) -> HtmlResolver:
        """Process content with CPU offloading."""
        loop = asyncio.get_running_loop()
        
        # Fix: Run CPU-bound parsing in thread pool (Severity P1)
        data, resolver = await loop.run_in_executor(None, self._cpu_bound_extract, html)
        
        await self._merge_data(data)
        return resolver

    def _cpu_bound_extract(self, html: str):
        """Synchronous extraction logic running in thread."""
        resolver = HtmlResolver(html)
        data = {}
        for field in self.config.fields:
            data[field.name] = resolver.resolve_field(field)
        return data, resolver

    async def _merge_data(self, page_data: Dict[str, Any]):
        batch_to_flush = None
        entries = 0
        
        async with self.data_lock:
            for key, value in page_data.items():
                if isinstance(value, list):
                    for item in value:
                        item_hash = hashlib.md5(json.dumps(item, sort_keys=True).encode()).hexdigest()
                        
                        if item_hash not in self.seen_hashes:
                            self.seen_hashes.add(item_hash)
                            self.recent_hashes.append(item_hash)
                            self.pending_batch.append({key: [item]})
                            entries += 1
                        elif item_hash not in self.recent_hashes:
                             # False positive mitigation
                            self.false_positive_count += 1
                            self.pending_batch.append({key: [item]})
                            self.recent_hashes.append(item_hash)
                            entries += 1
                else:
                    self.pending_batch.append({key: value})
            
            if len(self.pending_batch) >= self.batch_size:
                batch_to_flush = self.pending_batch.copy()
                self.pending_batch = []
        
        if batch_to_flush:
            await self._flush_batch(batch_to_flush)
            
        if self.stats_callback and entries > 0:
            self.stats_callback(StatsEvent("entries_added", count=entries))

    async def _flush_batch(self, batch: List[Dict]):
        if self.output_callback and batch:
            combined = {}
            for item in batch:
                for k, v in item.items():
                    if k not in combined: combined[k] = []
                    if isinstance(v, list): combined[k].extend(v)
                    else: combined[k].append(v)
            await self.output_callback(combined)

    async def _flush_remaining_batches(self):
        async with self.data_lock:
            batch = self.pending_batch.copy()
            self.pending_batch = []
        if batch: await self._flush_batch(batch)

    async def _handle_interactions(self, page):
        """Execute browser interactions with structured logging and retry logic."""
        if not self.config.interactions:
            return

        total = len(self.config.interactions)
        logger.info(f"🎮 Starting {total} browser interaction(s)...")
        
        successful = 0
        failed = 0
        
        for idx, action in enumerate(self.config.interactions, 1):
            try:
                await self._execute_interaction(page, action, idx, total)
                successful += 1
            except Exception as e:
                failed += 1
                logger.warning(f"  ⚠️  [{idx}/{total}] Interaction failed ({action.type}): {e}")
                continue
        
        logger.info(f"✅ Interactions complete: {successful} succeeded, {failed} failed")

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1), reraise=True)
    async def _execute_interaction(self, page: Page, action, idx: int, total: int):
        """Execute single interaction with retry logic."""
        if action.type == InteractionType.WAIT:
            duration_ms = action.duration or 1000
            logger.debug(f"  [{idx}/{total}] ⏳ Waiting {duration_ms}ms...")
            await page.wait_for_timeout(duration_ms)
            
        elif action.type == InteractionType.SCROLL:
            logger.debug(f"  [{idx}/{total}] 📜 Scrolling to bottom...")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
            
        elif action.type == InteractionType.CLICK and action.selector:
            logger.debug(f"  [{idx}/{total}] 👆 Clicking: {action.selector}")
            await page.click(action.selector, timeout=5000)
            
        elif action.type == InteractionType.FILL and action.selector and action.value:
            logger.debug(f"  [{idx}/{total}] ✍️  Filling '{action.selector}' with '{action.value}'")
            await page.fill(action.selector, action.value, timeout=5000)
            
        elif action.type == InteractionType.PRESS and action.selector and action.value:
            logger.debug(f"  [{idx}/{total}] ⌨️  Pressing '{action.value}' on {action.selector}")
            await page.press(action.selector, action.value, timeout=5000)
            
        elif action.type == InteractionType.HOVER and action.selector:
            logger.debug(f"  [{idx}/{total}] 🖱️  Hovering: {action.selector}")
            await page.hover(action.selector, timeout=5000)
            
        elif action.type == InteractionType.KEY_PRESS and action.value:
            logger.debug(f"  [{idx}/{total}] ⌨️  Global key press: {action.value}")
            await page.keyboard.press(action.value)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(Exception))
    async def _fetch_page(self, url: str) -> str:
        current_proxy = self._get_next_proxy()
        
        if self.config.use_playwright:
             return await self._fetch_playwright(url, current_proxy)
        else:
            if not self.session: return ""
            try:
                # FIX: Use Any to satisfy strict Pylance check against ProxySpec
                proxies: Any = {"http": current_proxy, "https": current_proxy} if current_proxy else None
                headers = {"User-Agent": self.ua_rotator.random}
                
                # Fix: Clear cookies to prevent session tracking
                self.session.cookies.clear()
                
                response = await self.session.get(url, timeout=15, proxies=proxies, headers=headers)
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

    async def _fetch_playwright(self, url: str, proxy: Optional[str]) -> str:
        if not self.context: return ""
        page = None 
        try:
            page = await self.context.new_page()
            
            if stealth_async:
                await stealth_async(page)
            
            await page.goto(url, timeout=30000)
            await self._handle_interactions(page)
            
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