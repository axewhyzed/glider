import asyncio
import random
import hashlib
import json
import urllib.robotparser
from typing import Dict, Any, Optional, List, Callable, Awaitable
from urllib.parse import urljoin, urlparse
from itertools import cycle
from collections import deque

from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright, Page
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed, retry_if_exception_type
from aiolimiter import AsyncLimiter
from fake_useragent import UserAgent

from engine.bloom import BloomFilter  # Pure Python implementation
from engine.checkpoint import CheckpointManager
from engine.schemas import ScraperConfig, ScrapeMode, InteractionType
from engine.resolver import HtmlResolver

# Import StatsEvent from main
try:
    from main import StatsEvent
except ImportError:
    # Fallback for testing without main.py
    from dataclasses import dataclass
    from typing import Literal
    
    @dataclass
    class StatsEvent:
        event_type: Literal["page_success", "page_error", "page_skipped", "blocked", "entries_added"]
        count: int = 1
        metadata: Optional[Dict[str, Any]] = None

# --- ROBUST STEALTH IMPORT (v1.0.6 Compatible) ---
stealth_async: Optional[Callable[[Page], Awaitable[None]]] = None

try:
    # Standard import for playwright-stealth < 2.0.0
    from playwright_stealth import stealth_async # type: ignore
except ImportError as e:
    # Don't warn here - will warn later if actually needed
    pass

# Final check to ensure we have a callable function
if stealth_async and not callable(stealth_async):
    # Fallback for weird module resolution issues
    if hasattr(stealth_async, 'stealth_async'):
        stealth_async = stealth_async # type: ignore
    else:
        stealth_async = None
# -----------------------------

class ScraperEngine:
    """
    Core scraping engine handling resource management, concurrency, and parsing strategies.
    Enhanced with micro-batched writes, bloom filter deduplication, and crash recovery.
    
    Version: 2.7 - Critical Fixes Applied
    - C1: Bloom filter false positive tracking
    - C3: Race condition fix in batch flush
    - C4: Incomplete URL deduplication
    - H1: O(1) LRU cache with deque
    - H3: User-Agent rotation for curl_cffi
    - H5: Graceful shutdown handling
    """
    def __init__(
        self, 
        config: ScraperConfig, 
        output_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        stats_callback: Optional[Callable[[StatsEvent], None]] = None
    ):
        self.config = config
        self.aggregated_data: Dict[str, Any] = {}
        self.failed_urls: List[str] = []
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
        
        # Memory-efficient deduplication with Bloom filter (PURE PYTHON)
        self.seen_hashes = BloomFilter(capacity=100000, error_rate=0.001)
        
        # H1 FIX: Use deque for O(1) LRU operations instead of list
        self.recent_hashes = deque(maxlen=1000)  # Auto-evicts oldest when full
        
        # C1 FIX: Track suspected false positives
        self.false_positive_count = 0
        
        self.rate_limiter = AsyncLimiter(self.config.rate_limit, 1) 
        self.ua_rotator = UserAgent()
        
        # Proxy Rotation
        self.proxy_pool = cycle(config.proxies) if config.proxies else None
        
        # Batching configuration
        self.batch_size = 10  # Write every 10 items
        self.pending_batch: List[Dict[str, Any]] = []  # C3 FIX: Shared batch buffer
        
        # H5 FIX: Shutdown flag for graceful termination
        self.shutdown_requested = False

    async def run(self) -> Dict[str, Any]:
        """Main entry point."""
        logger.info(f"🚀 Starting ASYNC scrape for: {self.config.name} (Mode: {self.config.mode.value})")
        
        await self._setup_resources()
        
        if self.config.respect_robots_txt and self.config.base_url:
            await self._init_robots_txt()
        
        # C4 FIX: Check for incomplete URLs and filter out already-done ones
        incomplete_urls = self.checkpoint.get_incomplete()
        if incomplete_urls:
            # Remove URLs that are both incomplete AND done
            incomplete_urls = [u for u in incomplete_urls if not self.checkpoint.is_done(u)]
            if incomplete_urls:
                logger.warning(f"⚠️ Re-queueing {len(incomplete_urls)} incomplete URLs from previous session")

        try:
            if self.config.mode == ScrapeMode.LIST:
                await self._run_list_mode(incomplete_urls)
            else:
                await self._run_pagination_mode()
        except asyncio.CancelledError:
            # H5 FIX: Graceful shutdown - flush remaining batches
            logger.warning("⚠️ Shutdown requested - flushing remaining data...")
            await self._flush_remaining_batches()
            raise
        finally:
            await self._cleanup_resources()
            self.checkpoint.close()

        total_items = sum(len(v) if isinstance(v, list) else 1 for v in self.aggregated_data.values())
        
        # Report False Positives
        if self.false_positive_count > 0:
            logger.warning(
                f"⚠️ Bloom filter detected {self.false_positive_count} suspected false positives "
                f"({(self.false_positive_count/total_items*100):.2f}% of data) - items were preserved"
            )
        
        # Report Failures
        if self.failed_urls:
             logger.error(f"❌ {len(self.failed_urls)} URLs failed completely after retries.")
             for url in self.failed_urls[:5]:
                 logger.debug(f"Failed: {url}")

        logger.success(f"✅ Finished! Extracted {total_items} total unique items.")
        return self.aggregated_data

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
            
            # L1 FIX: Add timeout for robots.txt fetch
            await asyncio.wait_for(
                loop.run_in_executor(None, self.robots_parser.read),
                timeout=10.0
            )
            
            logger.info(f"✅ Robots.txt parsed from {robots_url}")
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Robots.txt fetch timed out. Defaulting to ALLOW all.")
            self.robots_parser = None
        except Exception as e:
            logger.warning(f"⚠️ Failed to parse robots.txt: {e}. Defaulting to ALLOW all.")
            self.robots_parser = None

    def _is_allowed(self, url: str) -> bool:
        if not self.config.respect_robots_txt or not self.robots_parser:
            return True
        return self.robots_parser.can_fetch("*", url)

    async def _run_pagination_mode(self):
        if not self.config.base_url:
             logger.error("Base URL is required for pagination mode.")
             return

        current_url = str(self.config.base_url)
        pages_scraped = 0
        max_pages = self.config.pagination.max_pages if self.config.pagination else 1

        while pages_scraped < max_pages and current_url and not self.shutdown_requested:
            if not self._is_allowed(current_url):
                logger.warning(f"⛔ URL blocked by robots.txt: {current_url}")
                if self.stats_callback: 
                    self.stats_callback(StatsEvent("blocked"))
                break

            logger.info(f"📄 Scraping Page {pages_scraped + 1}: {current_url}")
            
            # Mark as in-progress before processing
            self.checkpoint.mark_in_progress(current_url)
            
            try:
                html_content = await self._fetch_page(current_url)
                if not html_content:
                    raise Exception("Empty content")
                
                await self._process_content(html_content)
                
                # Mark as done after successful processing
                self.checkpoint.mark_done(current_url)
                if self.stats_callback: 
                    self.stats_callback(StatsEvent("page_success"))
                
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

            except Exception as e:
                logger.error(f"❌ Failed to scrape {current_url}: {e}")
                self.failed_urls.append(current_url)
                if self.stats_callback: 
                    self.stats_callback(StatsEvent("page_error"))
                break

    async def _run_list_mode(self, incomplete_urls: List[str] = []):
        raw_urls = self.config.start_urls or []
        urls = [str(u) for u in raw_urls]
        
        # Add incomplete URLs from previous crash
        if incomplete_urls:
            urls = list(set(urls + incomplete_urls))
        
        if self.config.use_checkpointing:
            original_count = len(urls)
            urls = [u for u in urls if not self.checkpoint.is_done(u)]
            skipped = original_count - len(urls)
            if skipped > 0:
                logger.info(f"⏭️ Skipping {skipped} URLs (already in checkpoint).")
                if self.stats_callback: 
                    self.stats_callback(StatsEvent("page_skipped", count=skipped))

        if not urls:
            logger.warning("⚠️ No URLs to process.")
            return

        sem = asyncio.Semaphore(self.config.concurrency)
        logger.info(f"⚡ Processing {len(urls)} URLs with Concurrency={self.config.concurrency}")

        async def _worker(url):
            if self.shutdown_requested:
                return
                
            if not self._is_allowed(url):
                logger.warning(f"⛔ URL blocked by robots.txt: {url}")
                if self.stats_callback: 
                    self.stats_callback(StatsEvent("blocked"))
                return

            async with sem:
                async with self.rate_limiter:
                    # Mark as in-progress
                    self.checkpoint.mark_in_progress(url)
                    
                    try:
                        logger.info(f"▶️ Fetching: {url}")
                        html = await self._fetch_page(url)
                        if html:
                            await self._process_content(html)
                            self.checkpoint.mark_done(url)
                            if self.stats_callback: 
                                self.stats_callback(StatsEvent("page_success"))
                        else:
                            raise Exception("Empty HTML returned")
                    except asyncio.CancelledError:
                        raise  # Propagate cancellation
                    except Exception as e:
                        logger.error(f"Failed to fetch {url}: {e}")
                        self.failed_urls.append(url)
                        if self.stats_callback: 
                            self.stats_callback(StatsEvent("page_error"))
                    
                    delay = random.uniform(0.5, 1.5)
                    await asyncio.sleep(delay)

        tasks = [asyncio.create_task(_worker(url)) for url in urls]
        
        try:
            # H5 FIX: Proper cancellation handling
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            # Cancel all pending tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Wait for cancellation to complete
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    
    async def _process_content(self, html: str):
        try:
            resolver = HtmlResolver(html)
            data = self._extract_data(resolver)
            await self._merge_data(data)
        except Exception as e:
            logger.error(f"⚠️ Parsing/Extraction Error: {e}")
            raise e

    async def _setup_resources(self):
        if self.config.use_playwright:
            # Only warn about stealth if Playwright is enabled and stealth is missing
            if not stealth_async:
                logger.warning("⚠️ playwright-stealth not available. Install for better anti-detection.")
            
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
            browser_choice: Any = random.choice(["chrome110", "chrome120", "chrome100", "opera78", "safari17_0", "safari15_5"])
            logger.info(f"🕵️ Impersonating: {browser_choice}")
            self.session = AsyncSession(impersonate=browser_choice)

    async def _cleanup_resources(self):
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
        if self.session: await self.session.close()

    async def _handle_interactions(self, page):
        """
        Execute browser interactions with structured logging and retry logic.
        Non-critical failures are logged but don't halt execution.
        """
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
                logger.warning(
                    f"  ⚠️  [{idx}/{total}] Interaction failed ({action.type}): {e}"
                )
                # Continue with next interaction instead of crashing
                continue
        
        logger.info(f"✅ Interactions complete: {successful} succeeded, {failed} failed")

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1), reraise=True)
    async def _execute_interaction(self, page, action, idx: int, total: int):
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
            if not self.context: return ""
            page = None 
            try:
                page = await self.context.new_page()
                
                # Apply Stealth (if available)
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
        else:
            if not self.session: return ""
            try:
                proxies: Any = None
                if current_proxy:
                    proxies = {"http": current_proxy, "https": current_proxy}

                # H3 FIX: Rotate User-Agent per request for curl_cffi
                headers = {"User-Agent": self.ua_rotator.random}
                
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

    def _extract_data(self, resolver: HtmlResolver) -> Dict[str, Any]:
        data = {}
        for field in self.config.fields:
            data[field.name] = resolver.resolve_field(field)
        return data

    async def _merge_data(self, page_data: Dict[str, Any]):
        """
        Merge extracted data with atomic per-item streaming.
        Uses micro-batching to reduce I/O overhead.
        
        FIXES APPLIED:
        - C1: Track and log Bloom filter false positives
        - C3: Race condition fix - flush outside lock
        - H1: Use deque for O(1) operations
        """
        entries_added = 0
        batch_to_flush: Optional[List[Dict[str, Any]]] = None
        
        async with self.data_lock:
            for key, value in page_data.items():
                if key not in self.aggregated_data:
                    self.aggregated_data[key] = value if not isinstance(value, list) else []
                
                target = self.aggregated_data[key]
                
                if isinstance(target, list) and isinstance(value, list):
                    for item in value:
                        item_hash = hashlib.md5(
                            json.dumps(item, sort_keys=True).encode()
                        ).hexdigest()
                        
                        # Bloom filter check (probabilistic)
                        if item_hash not in self.seen_hashes:
                            # Definitely new - add it
                            target.append(item)
                            self.seen_hashes.add(item_hash)
                            self.recent_hashes.append(item_hash)  # H1: O(1) with deque
                            entries_added += 1
                            
                            # Add to batch
                            self.pending_batch.append({key: [item]})
                            
                        else:
                            # Might be false positive - check exact match
                            if item_hash in self.recent_hashes:
                                # Definitely duplicate
                                continue
                            else:
                                # C1 FIX: Suspected false positive - add anyway
                                self.false_positive_count += 1
                                logger.debug(f"⚠️ Bloom false positive suspected - preserving item")
                                target.append(item)
                                self.recent_hashes.append(item_hash)
                                entries_added += 1
                                self.pending_batch.append({key: [item]})
                        
                        # C3 FIX: Check batch size and prepare flush INSIDE lock
                        if len(self.pending_batch) >= self.batch_size:
                            batch_to_flush = self.pending_batch.copy()
                            self.pending_batch = []
                            # Don't flush here - will flush outside lock
                else:
                    # Non-list fields - add to batch immediately
                    self.pending_batch.append({key: value})
        
        # C3 FIX: Flush OUTSIDE the lock to prevent race conditions
        if batch_to_flush:
            await self._flush_batch(batch_to_flush)
        
        # Update stats with precise entry count
        if self.stats_callback and entries_added > 0:
            self.stats_callback(StatsEvent("entries_added", count=entries_added))

    async def _flush_batch(self, batch: List[Dict[str, Any]]):
        """Write batched items in a single I/O operation."""
        if not self.output_callback or not batch:
            return
        
        # Combine all items into single payload
        combined = {}
        for item in batch:
            for k, v in item.items():
                if k not in combined:
                    combined[k] = []
                if isinstance(v, list):
                    combined[k].extend(v)
                else:
                    combined[k].append(v)
        
        await self.output_callback(combined)
    
    async def _flush_remaining_batches(self):
        """H5 FIX: Flush any remaining batches on shutdown."""
        async with self.data_lock:
            if self.pending_batch:
                logger.info(f"Flushing {len(self.pending_batch)} remaining items...")
                batch_to_flush = self.pending_batch.copy()
                self.pending_batch = []
        
        if batch_to_flush:
            await self._flush_batch(batch_to_flush)
