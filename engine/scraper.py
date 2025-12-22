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
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from aiolimiter import AsyncLimiter
from fake_useragent import UserAgent

from engine.bloom import BloomFilter
from engine.checkpoint import CheckpointManager
from engine.schemas import ScraperConfig, ScrapeMode, StatsEvent
from engine.resolver import HtmlResolver
from engine.browser import BrowserManager

class ScraperEngine:
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
        
        # Managers
        self.checkpoint = CheckpointManager(config.name, config.use_checkpointing)
        self.browser_manager = BrowserManager(config) if config.use_playwright else None
        self.robots_parser: Optional[urllib.robotparser.RobotFileParser] = None
        self.session: Optional[AsyncSession] = None
        
        # State
        self.data_lock = asyncio.Lock() 
        self.bloom_path = Path("data") / f"{config.name.replace(' ', '_').lower()}.bloom"
        self.seen_hashes = BloomFilter(capacity=100000, error_rate=0.001)
        self.recent_hashes = deque(maxlen=1000)
        
        self.rate_limiter = AsyncLimiter(self.config.rate_limit, 1) 
        self.ua_rotator = UserAgent()
        self.proxy_pool = cycle(config.proxies) if config.proxies else None
        
        self.batch_size = 10
        self.pending_batch: List[Dict[str, Any]] = []
        self.shutdown_requested = False

    async def run(self):
        logger.info(f"🚀 Starting Engine for: {self.config.name}")
        
        await self._setup_resources()
        
        if self.config.respect_robots_txt and self.config.base_url:
            await self._init_robots_txt()
            
        incomplete_urls = await self.checkpoint.get_incomplete()
        if incomplete_urls:
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
        await self.checkpoint.initialize()
        self.seen_hashes.load(self.bloom_path)
        
        if self.browser_manager:
            proxy = self._get_next_proxy()
            await self.browser_manager.start(proxy)
        else:
            self._init_session()

    def _init_session(self):
        browser_choice = random.choice(["chrome110", "chrome120", "chrome100", "safari17_0"])
        self.session = AsyncSession(impersonate=cast(Any, browser_choice))

    async def _cleanup_resources(self):
        try: self.seen_hashes.save(self.bloom_path)
        except Exception: pass

        await self.checkpoint.close()
        if self.browser_manager: await self.browser_manager.close()
        if self.session: await self.session.close()

    def _get_next_proxy(self) -> Optional[str]:
        return next(self.proxy_pool) if self.proxy_pool else None

    async def _init_robots_txt(self):
        logger.info("🤖 Checking robots.txt...")
        try:
            parsed = urlparse(str(self.config.base_url))
            url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            self.robots_parser = urllib.robotparser.RobotFileParser()
            self.robots_parser.set_url(url)
            await asyncio.get_running_loop().run_in_executor(None, self.robots_parser.read)
        except Exception:
            self.robots_parser = None

    def _is_allowed(self, url: str) -> bool:
        if not self.config.respect_robots_txt or not self.robots_parser: return True
        return self.robots_parser.can_fetch("*", url)

    async def _run_list_mode(self, incomplete_urls: List[str] = []):
        raw_urls = self.config.start_urls or []
        all_urls = list(set([str(u) for u in raw_urls] + incomplete_urls))
        queue_urls = [u for u in all_urls if not self.checkpoint.is_done(u)]
        
        if not queue_urls: return

        queue = asyncio.Queue()
        for u in queue_urls: queue.put_nowait(u)

        logger.info(f"⚡ Processing {len(queue_urls)} URLs (Concurrency={self.config.concurrency})")
        workers = [asyncio.create_task(self._worker_loop(queue)) for _ in range(self.config.concurrency)]
        await queue.join()
        for w in workers: w.cancel()

    async def _worker_loop(self, queue: asyncio.Queue):
        while not self.shutdown_requested:
            try:
                url = await queue.get()
                try: await self._process_url(url)
                finally: queue.task_done()
            except asyncio.CancelledError: break
            except Exception: pass

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
        if not self.config.base_url: return
        current_url = str(self.config.base_url)
        pages = 0
        max_pages = self.config.pagination.max_pages if self.config.pagination else 1

        while pages < max_pages and current_url and not self.shutdown_requested:
            if not self._is_allowed(current_url): break
            
            logger.info(f"📄 Page {pages + 1}: {current_url}")
            await self.checkpoint.mark_in_progress(current_url)
            
            try:
                html = await self._fetch_page(current_url)
                if not html: raise Exception("Empty")
                
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
                        current_url = None
                else:
                    current_url = None
            except Exception as e:
                logger.error(f"Page failed: {e}")
                break

    async def _process_content(self, html: str) -> HtmlResolver:
        loop = asyncio.get_running_loop()
        data, resolver = await loop.run_in_executor(None, self._cpu_bound_extract, html)
        await self._merge_data(data)
        return resolver

    def _cpu_bound_extract(self, html: str):
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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(Exception))
    async def _fetch_page(self, url: str) -> str:
        current_proxy = self._get_next_proxy()
        
        if self.browser_manager:
            return await self.browser_manager.fetch_page(url)
        else:
            if not self.session: return ""
            try:
                proxies: Any = {"http": current_proxy, "https": current_proxy} if current_proxy else None
                self.session.cookies.clear()
                
                response = await self.session.get(url, timeout=15, proxies=proxies, headers={"User-Agent": self.ua_rotator.random})
                if response.status_code == 200:
                    return response.text
                elif response.status_code in [403, 429]:
                    raise Exception(f"Blocked: {response.status_code}")
                else:
                    return ""
            except Exception as e:
                logger.warning(f"Network Error: {e}")
                raise e