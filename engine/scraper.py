import asyncio
import random
import hashlib
import json
import urllib.robotparser
import aiofiles
from datetime import datetime, timedelta
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
from engine.schemas import ScraperConfig, ScrapeMode, StatsEvent, DataField
from engine.resolver import HtmlResolver, JsonResolver
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
        
        self.checkpoint = CheckpointManager(config.name, config.use_checkpointing)
        self.browser_manager = BrowserManager(config) if config.use_playwright else None
        self.robots_parser: Optional[urllib.robotparser.RobotFileParser] = None
        self.session: Optional[AsyncSession] = None
        
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

        # Authentication State
        self.auth_token: Optional[str] = None
        self.token_expires_at: datetime = datetime.min

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
                content = await self._fetch_page(url)
                if content:
                    await self._process_content(content, url)
                    await self.checkpoint.mark_done(url)
                    if self.stats_callback: self.stats_callback(StatsEvent("page_success"))
                else:
                    raise Exception("Empty Content")
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
                content = await self._fetch_page(current_url)
                if not content: raise Exception("Empty")
                
                resolver = await self._process_content(content, current_url)
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

    # [UPDATED] Recursive Content Processing
    async def _process_content(self, content: str, url: str = "", fields: Optional[List[DataField]] = None) -> Any:
        current_fields = fields or self.config.fields
        
        # 1. Initialize Resolver
        if self.config.response_type == "json" and not self.config.use_playwright:
             # Logic fix: If fetching nested HTML link inside JSON mode, we might need HTML resolver
             # But usually response_type is global. For Reddit, we append .json to links.
             resolver = JsonResolver(content)
        else:
             # Playwright always returns HTML, even if source was JSON-like
             resolver = HtmlResolver(content) # type: ignore

        # 2. Extract Data
        data = {}
        for field in current_fields:
            # A. Standard Extraction
            extracted_value = resolver.resolve_field(field)
            
            # B. Link Following (Deep Scrape)
            if field.follow_url and extracted_value and field.nested_fields:
                urls_to_follow = extracted_value if isinstance(extracted_value, list) else [extracted_value]
                nested_results = []
                
                logger.info(f"    ↳ Following {len(urls_to_follow)} nested links...")
                
                for i, relative_url in enumerate(urls_to_follow):
                    if i >= 5: break # Safety: limit to 5 children per page
                    
                    full_child_url = urljoin(url, str(relative_url))
                    
                    # Reddit Specific Hack: Ensure child URL is JSON if mode is JSON
                    if self.config.response_type == "json" and not full_child_url.endswith(".json"):
                        # remove query params first
                        parsed = urlparse(full_child_url)
                        path = parsed.path.rstrip('/')
                        full_child_url = f"{parsed.scheme}://{parsed.netloc}{path}.json"

                    try:
                        # Rate Limit applies to child requests too
                        async with self.rate_limiter:
                            child_content = await self._fetch_page(full_child_url)
                            if child_content:
                                # Recursively process with nested_fields
                                child_data = await self._process_content(
                                    child_content, 
                                    full_child_url, 
                                    fields=field.nested_fields
                                )
                                # Merge nested data into a flat dict or keep structure?
                                # _process_content returns resolver usually, but here we want data.
                                # Wait, _process_content in original returned 'resolver'.
                                # We need to separate extraction from processing.
                                
                                # FIX: The recursive call returns the resolver, but we want the DATA that was merged.
                                # Since _merge_data is async and decoupled, we can't easily get the return value here.
                                # Solution: We can't return the data easily because _merge_data pushes to a batch.
                                # Alternative: We just let the recursive call push data to the main batch!
                                pass 
                    except Exception as e:
                        logger.warning(f"Failed to follow {full_child_url}: {e}")

                # For the parent object, we might just store the URL, 
                # or we can't store the child data because it's already flushed.
                data[field.name] = extracted_value
            else:
                data[field.name] = extracted_value

        # 3. Save Data (Only if we are at the top level, or if we want to save child entries as separate rows)
        # Current logic: Scraper flushes rows. 
        # If we are in a nested call, 'data' contains the fields extracted from the child.
        # We should merge them.
        
        # NOTE: To support "give me as many as you find", we treat every nested hit as a new entry.
        await self._merge_data(data)
        
        return resolver

    async def _save_debug_snapshot(self, html: str, url: str):
        try:
            debug_dir = Path("debug")
            debug_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = debug_dir / f"fail_{timestamp}_{safe_name}.html"
            async with aiofiles.open(filename, "w", encoding="utf-8") as f:
                await f.write(f"\n")
                await f.write(html)
            logger.warning(f"📸 Snapshot saved: {filename}")
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")

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
            # Flatten logic: If a field is a list, we often want to explode it.
            # But for simple extraction, let's just push what we found.
            
            # Simple check: If the dict is empty or all None, skip
            if not any(page_data.values()): return

            self.pending_batch.append(page_data)
            if len(self.pending_batch) >= self.batch_size:
                batch_to_flush = self.pending_batch.copy()
                self.pending_batch = []
        
        if batch_to_flush:
            await self._flush_batch(batch_to_flush)
            if self.stats_callback:
                self.stats_callback(StatsEvent("entries_added", count=len(batch_to_flush)))

    async def _flush_batch(self, batch: List[Dict]):
        if self.output_callback and batch:
            # For JSON output, we want a list of objects. 
            # The current logic attempts to combine keys, which is good for columnar data,
            # but for a stream of "Discord Links", a list of dicts is better.
            await self.output_callback({"items": batch}) 

    async def _flush_remaining_batches(self):
        async with self.data_lock:
            batch = self.pending_batch.copy()
            self.pending_batch = []
        if batch: await self._flush_batch(batch)

    # --- AUTH LOGIC (UNCHANGED BUT INCLUDED FOR COMPLETENESS) ---
    async def ensure_active_token(self):
        if not self.config.authentication:
            return
        if self.auth_token and datetime.now() < (self.token_expires_at - timedelta(seconds=60)):
            return
        logger.info(f"🔄 Refreshing OAuth Token for {self.config.authentication.type}...")
        auth_config = self.config.authentication
        if not self.session: self._init_session()
        if not self.session: raise RuntimeError("Failed to initialize session")
        try:
            if auth_config.type == "oauth_password":
                client_id = auth_config.client_id or ""
                client_secret = auth_config.client_secret or ""
                payload = {
                    "grant_type": "password",
                    "username": auth_config.username or "",
                    "password": auth_config.password or "",
                    "scope": auth_config.scope or "*"
                }
                response = await self.session.post(str(auth_config.token_url), auth=(client_id, client_secret), data=payload)
                if response.status_code == 200:
                    data = response.json()
                    self.auth_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                    logger.success(f"✅ Token Refreshed! Expires in {expires_in}s")
                else:
                    logger.error(f"❌ Auth Failed: {response.status_code} - {response.text}")
                    raise Exception("Authentication Failed")
        except Exception as e:
            logger.error(f"Auth Error: {e}")
            raise e

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(Exception))
    async def _fetch_page(self, url: str) -> str:
        if self.config.authentication: await self.ensure_active_token()
        headers = self.config.headers.copy() if self.config.headers else {}
        headers["User-Agent"] = self.ua_rotator.random
        if self.auth_token: headers["Authorization"] = f"Bearer {self.auth_token}"
        current_proxy = self._get_next_proxy()
        
        if self.browser_manager:
            return await self.browser_manager.fetch_page(url)
        else:
            if not self.session: return ""
            try:
                proxies: Any = {"http": current_proxy, "https": current_proxy} if current_proxy else None
                response = await self.session.get(url, timeout=15, proxies=proxies, headers=headers)
                if response.status_code == 200: return response.text
                elif response.status_code in [403, 429, 401]: raise Exception(f"Blocked/Auth Error: {response.status_code}")
                else: return ""
            except Exception as e:
                logger.warning(f"Network Error: {e}")
                raise e