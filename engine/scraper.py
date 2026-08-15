import asyncio
import random
import hashlib
import json
import time
import aiofiles
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, Optional, List, Callable, Awaitable, cast, Tuple
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, urlunparse
from itertools import cycle

from curl_cffi.requests import AsyncSession
from loguru import logger
from aiolimiter import AsyncLimiter
from fake_useragent import UserAgent

from engine.bloom import BloomFilter
from engine.checkpoint import CheckpointManager
from engine.schemas import ScraperConfig, ScrapeMode, StatsEvent, DataField
from engine.resolver import HtmlResolver, JsonResolver
from engine.browser import BrowserManager
from engine.network import (
    FetchResult,
    HttpStatusError,
    RequestPurpose,
    UrlPolicy,
    UrlPolicyError,
    backoff_seconds,
    canonicalize_url,
    is_retryable_status,
    origin,
    resolve_url,
    retry_after_seconds,
)
from engine.errors import AuthError, ErrorCategory, FetchError, NON_RETRYABLE_CATEGORIES
from engine.redact import redact_text
from engine.robots import RobotsCache
from engine.run import RunContext
from engine.sitemap import discover_sitemap
from engine.limits import DomainRateLimitPolicy, DomainRateLimiter
from engine.proxies import ProxyCircuitBreaker, ProxyHealthPolicy, ProxyLease

if TYPE_CHECKING:
    from engine.writer import JsonlStreamWriter


class FailureCounter:
    """Mutable integer-like failure count retained for API compatibility."""

    def __init__(self) -> None:
        self.value = 0

    def increment(self) -> None:
        self.value += 1

    def __len__(self) -> int:
        return self.value

    def __int__(self) -> int:
        return self.value

    def __repr__(self) -> str:
        return str(self.value)


class ScraperEngine:
    def __init__(
        self, 
        config: ScraperConfig, 
        output_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        stats_callback: Optional[Callable[[StatsEvent], None]] = None,
        run_context: Optional[RunContext] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        stream_writer: Optional["JsonlStreamWriter"] = None,
    ):
        self.config = config
        # Compatibility-shaped counter: it supports ``len(engine.failed_urls)``
        # for older integrations without retaining every failed URL in memory.
        self.failed_urls = FailureCounter()
        # Bounded in-memory failure ring (P7.4). Full failures stream to
        # run_context.failures_path; this ring powers stats + report previews.
        from collections import deque as _deque
        self.failures_ring: "Any" = _deque(maxlen=config.max_failed_entries)
        self.output_callback = output_callback
        self.stats_callback = stats_callback
        self.stream_writer = stream_writer
        
        self.run_context = run_context
        self.dry_run = dry_run
        checkpoint_path = run_context.checkpoint_path if run_context else None
        checkpoint_enabled = (config.use_checkpointing or run_context is not None) and not dry_run
        self.checkpoint = CheckpointManager(config.name, checkpoint_enabled, checkpoint_path)
        self.browser_manager = None
        self.robots_cache: Optional[RobotsCache] = None
        self.session: Optional[AsyncSession] = None
        
        self.data_lock = asyncio.Lock() 
        self.bloom_path = run_context.bloom_path if run_context else Path("data") / f"{config.name.replace(' ', '_').lower()}.bloom"
        self.seen_hashes = BloomFilter(capacity=config.dedup.capacity, error_rate=config.dedup.error_rate)
        # Exact dedup authority: bounded LRU (OrderedDict). Bloom is only a gate.
        from collections import OrderedDict
        self.exact_seen: OrderedDict[str, None] = OrderedDict()
        
        self.rate_limiter = AsyncLimiter(self.config.rate_limit, 1) 
        self.domain_limiter = (
            DomainRateLimiter(DomainRateLimitPolicy(
                rate_per_second=float(config.per_domain_rate_limit),
                burst=1.0,
            ))
            if config.per_domain_rate_limit else None
        )
        self.ua_rotator = UserAgent()
        
        if config.proxies and len(config.proxies) > 0:
            self.proxy_pool = cycle(config.proxies)
            self.proxy_values = list(config.proxies)
        else:
            self.proxy_pool = None
            self.proxy_values = []
        self.proxy_health = ProxyCircuitBreaker(ProxyHealthPolicy(
            failure_threshold=config.proxy_failure_threshold,
            cooldown_seconds=config.proxy_cooldown_seconds,
            max_proxies=max(1, len(self.proxy_values) or 1),
        )) if self.proxy_values else None
        
        self.batch_size = 10
        self.pending_batch: List[Dict[str, Any]] = []
        self.shutdown_requested = False
        self.limit = limit
        self.url_policy = UrlPolicy(config.url_policy)
        if config.use_playwright:
            self.browser_manager = BrowserManager(config, self.url_policy)

        self.auth_token: Optional[str] = None
        self.token_expires_at: datetime = datetime.min
        self._auth_lock = asyncio.Lock() 
        self.child_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._child_inflight: Dict[str, asyncio.Future] = {}
        self.depth_first_seen: Dict[str, int] = {}
        self._failure_tasks: set[asyncio.Task] = set()
        from engine.metrics import MetricsCollector
        self.metrics = MetricsCollector()
        self.preview_diagnostics = None

    async def run(self):
        logger.info(f"🚀 Starting Engine for: {self.config.name}")
        try:
            await self._setup_resources()

            # Warm the robots cache lazily (no fetch until first can_fetch).
            if self.config.respect_robots_txt and self.config.base_url:
                await self._init_robots_txt()

            resume_kind = "root" if self.config.mode == ScrapeMode.LIST else "pagination"
            incomplete_urls = await self.checkpoint.get_incomplete(kind=resume_kind)
            if incomplete_urls:
                incomplete_urls = [
                    u for u in incomplete_urls
                    if not self.checkpoint.is_done(u, kind=resume_kind)
                ]

            if self.config.mode == ScrapeMode.LIST:
                await self._run_list_mode(incomplete_urls)
            else:
                # Resume pagination from the last incomplete URL if checkpointing is on
                resume_url: Optional[str] = None
                if incomplete_urls:
                    resume_url = incomplete_urls[0]
                    logger.info(f"🔁 Resuming pagination from checkpoint: {resume_url}")
                await self._run_pagination_mode(resume_url=resume_url)
            
            await self._flush_remaining_batches()

        except asyncio.CancelledError:
            logger.warning("⚠️ Shutdown requested - flushing data...")
            self.shutdown_requested = True  # P9.5: honest manifest state
            await self._flush_remaining_batches()
            raise
        finally:
            await self._cleanup_resources()
            if self.run_context:
                self.run_context.update_manifest(
                    state="cancelled" if self.shutdown_requested else "completed",
                    finished_at=datetime.utcnow().isoformat() + "Z",
                    failed_urls=int(self.failed_urls),
                )
            logger.success("✅ Finished!")

    async def _setup_resources(self):
        # Establish the durable stream artifact before checkpoint/session setup
        # can be interrupted. This guarantees cancellation leaves a resumable
        # run with an explicit (possibly empty) JSONL stream.
        if self.stream_writer is not None and not self.dry_run:
            await self.stream_writer.open()
        await self.checkpoint.initialize()
        if not self.dry_run:
            self.seen_hashes.load(self.bloom_path)
            for key in await self.checkpoint.get_dedup_keys(self.config.dedup.exact_capacity):
                self.exact_seen[key] = None

        # Warn early if browser interactions are configured but Playwright is disabled
        if self.config.interactions and not self.config.use_playwright:
            logger.warning(
                "⚠️ 'interactions' are defined but 'use_playwright' is false — "
                "interactions will be ignored.  Set 'use_playwright': true to enable them."
            )

        if self.browser_manager:
            proxy = self._get_next_proxy()
            await self.browser_manager.start(proxy)
        else:
            self._init_session()

    def _init_session(self):
        browser_choice = random.choice(["chrome110", "chrome120", "chrome100", "safari17_0"])
        cookies = {} 
        
        if self.config.cookies_file:
            try:
                with open(self.config.cookies_file, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        for k, v in loaded.items():
                            if v is None: continue
                            if isinstance(v, (str, int, float, bool)):
                                cookies[str(k)] = str(v)
                            else:
                                logger.warning(f"Skipping invalid cookie {k}: {type(v)}")
                        logger.info(f"🍪 Loaded {len(cookies)} cookies")
                    else:
                        logger.error("❌ Invalid cookie format: Root must be a dictionary")
            except Exception as e:
                logger.error(f"❌ Failed to load cookies: {e}")

        self.session = AsyncSession(
            impersonate=cast(Any, browser_choice),
            cookies=cookies if cookies else None
        )

    async def _cleanup_resources(self):
        if self._failure_tasks:
            await asyncio.gather(*self._failure_tasks, return_exceptions=True)
        if not self.dry_run:
            try: self.seen_hashes.save(self.bloom_path)
            except Exception: pass
        await self.checkpoint.close()
        if self.browser_manager: await self.browser_manager.close()
        if self.session: await self.session.close()
        if self.stream_writer: await self.stream_writer.close()

    async def preview(self, url: Optional[str] = None) -> Tuple[FetchResult, Dict[str, Any]]:
        """Fetch and extract one page without creating durable crawl artifacts."""
        target = url
        if not target:
            target = str(self.config.base_url) if self.config.base_url else None
        if not target and self.config.start_urls:
            target = str(self.config.start_urls[0])
        if not target:
            raise ValueError("A preview URL is required for list configurations")
        await self._setup_resources()
        try:
            result = await self._fetch_page(target, purpose=RequestPurpose.ROOT)
            if result.error is not None:
                raise result.error
            data, resolver = await self._process_content(result.content, result.final_url)
            self.preview_diagnostics = self._build_preview_diagnostics(
                resolver, data, result.final_url
            )
            return result, data
        finally:
            await self._cleanup_resources()

    def _get_next_proxy(self) -> Optional[str]:
        return next(self.proxy_pool) if self.proxy_pool else None

    async def _get_healthy_proxy(self) -> Tuple[Optional[str], Optional[ProxyLease]]:
        if (
            self.browser_manager
            and self.config.browser.proxy_rotation == "per_context"
            and not self.browser_manager.context_rotation_due
            and self.browser_manager.current_proxy
        ):
            actual_proxy = self.browser_manager.current_proxy
            if self.proxy_health:
                # A shared context cannot change proxy mid-life. If its
                # circuit is currently open, use the existing context without
                # attributing the outcome to a different proxy; rotation will
                # select a healthy proxy at the next safe boundary.
                lease = await self.proxy_health.try_acquire(actual_proxy)
                if lease is not None:
                    return actual_proxy, lease
                logger.warning(
                    "Current browser context proxy is circuit-open; preserving context identity until rotation"
                )
            return actual_proxy, None
        if not self.proxy_health or not self.proxy_values:
            return self._get_next_proxy(), None
        for _ in range(len(self.proxy_values)):
            proxy = self._get_next_proxy()
            if not proxy:
                return None, None
            lease = await self.proxy_health.try_acquire(proxy)
            if lease is not None:
                return proxy, lease
        logger.warning("All configured proxies are currently circuit-open; using direct transport")
        return None, None

    async def _limited_request(self, target: str, operation: Callable[[], Awaitable[Any]]) -> Any:
        """Acquire global and optional per-domain permits for one attempt only."""
        async with self.rate_limiter:
            if self.domain_limiter:
                async with self.domain_limiter.limit(target):
                    return await operation()
            return await operation()

    async def _init_robots_txt(self):
        """Warm the per-origin robots cache for the base URL (lazy, no network yet)."""
        if not self.robots_cache:
            self.robots_cache = RobotsCache(
                self._fetch_page,
                ttl_seconds=self.config.robots_ttl_seconds,
                failure_policy=self.config.robots_failure_policy,
                max_origins=self.config.robots_max_origins,
            )
        if self.config.base_url:
            await self.robots_cache.can_fetch(str(self.config.base_url))

    async def _is_allowed(self, url: str, parent_url: Optional[str] = None) -> bool:
        try:
            canonical = self.url_policy.validate(url, parent_url=parent_url)
        except UrlPolicyError as exc:
            logger.warning(f"URL blocked by policy: {exc}")
            return False
        if not self.config.respect_robots_txt or not self.robots_cache:
            return True
        return await self.robots_cache.can_fetch(canonical, parent_url=parent_url)

    async def _run_list_mode(self, incomplete_urls: Optional[List[str]] = None):
        raw_urls = self.config.start_urls or []
        sitemap_urls = await self._discover_sitemap_urls()
        extra = incomplete_urls or []
        all_urls = list(dict.fromkeys([str(u) for u in raw_urls] + sitemap_urls + list(extra)))
        queue_urls = [u for u in all_urls if not self.checkpoint.is_done(u, kind="root")]
        if self.limit is not None:
            queue_urls = queue_urls[: self.limit]
        if not queue_urls: return

        queue = asyncio.Queue()
        for u in queue_urls: queue.put_nowait(u)

        logger.info(f"⚡ Processing {len(queue_urls)} URLs (Concurrency={self.config.concurrency})")
        workers = [asyncio.create_task(self._worker_loop(queue)) for _ in range(self.config.concurrency)]
        try:
            await queue.join()
        finally:
            # Always stop workers — on the happy path the queue is drained, on
            # cancellation we must not leave orphaned worker tasks draining the
            # queue while cleanup tears down shared resources.
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _worker_loop(self, queue: asyncio.Queue):
        while not self.shutdown_requested:
            try:
                url = await queue.get()
                try:
                    await self._process_url(url)
                except Exception as e:
                    # _process_url has its own broad try/except; if something truly
                    # unexpected bubbles up (e.g. lock error), log it but keep the
                    # worker alive so other URLs can still be processed.
                    logger.exception(f"Unexpected worker error on URL {url}: {e}")
                finally:
                    queue.task_done()
            except asyncio.CancelledError:
                break

    def _record_failure(self, url: str, error: BaseException) -> None:
        """Record a failure in the bounded ring and stream to failures.jsonl."""
        self.failed_urls.increment()
        from datetime import datetime as _dt
        entry = {
            "url": redact_text(url),
            "category": getattr(error, "category", ErrorCategory.INTERNAL).value,
            "message": redact_text(str(error))[:200],
            "timestamp": _dt.utcnow().isoformat() + "Z",
        }
        self.failures_ring.append(entry)
        if self.run_context:
            task = asyncio.create_task(self.run_context.append_failure(entry))
            self._failure_tasks.add(task)
            task.add_done_callback(self._failure_tasks.discard)

    def _build_preview_diagnostics(self, resolver: Any, data: Dict[str, Any], url: str):
        from engine.report import PreviewDiagnostics
        diagnostics = PreviewDiagnostics()
        for field in self.config.fields:
            try:
                value = resolver.resolve_field(field)
                if isinstance(value, list):
                    diagnostics.field_matches[field.name] = len(value)
                    diagnostics.samples[field.name] = value[:3]
                else:
                    diagnostics.field_matches[field.name] = 1 if value is not None else 0
                    diagnostics.samples[field.name] = [] if value is None else [value]
                if not field.selectors:
                    diagnostics.warnings.append(f"Field '{field.name}' has no selectors")
                elif diagnostics.field_matches[field.name] == 0:
                    diagnostics.warnings.append(f"Field '{field.name}' matched no values")
            except Exception as exc:
                diagnostics.field_matches[field.name] = 0
                diagnostics.warnings.append(f"Field '{field.name}' failed: {exc}")
        if self.config.pagination:
            try:
                match = resolver.get_attribute(self.config.pagination.selector, "href")
                diagnostics.pagination_match = match
                diagnostics.pagination_next = self._build_next_url(url, match) if match else None
            except Exception as exc:
                diagnostics.warnings.append(f"Pagination selector failed: {exc}")
        diagnostics.nested_fetched = self._count_nested_records(data)
        return diagnostics

    @staticmethod
    def _count_nested_records(value: Any) -> int:
        if isinstance(value, dict):
            total = 0
            for key, item in value.items():
                if key in {"_source_url", "_parent_url"}:
                    continue
                total += ScraperEngine._count_nested_records(item)
            return total
        if isinstance(value, list):
            return sum(ScraperEngine._count_nested_records(item) for item in value)
        return 0

    def _record_sample(
        self,
        origin: str,
        purpose: str,
        status_code: int,
        elapsed_ms: float,
        attempts: int,
        category: str,
        url: str = "",
    ) -> None:
        from engine.metrics import RequestSample
        self.metrics.record(RequestSample(
            origin=origin,
            purpose=purpose,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            attempts=attempts,
            category=category,
            url=url,
        ))

    def _validate_extraction(self, page_data: Dict[str, Any]) -> Optional[str]:
        """Extraction validation (P6.2). Returns a failure category or None.

        Enforces min_records_per_page / required_fields / fail_on_empty.
        """
        validation = self.config.validation
        if validation.min_records_per_page <= 0 and not validation.required_fields:
            return None
        issues = []
        if validation.min_records_per_page > 0:
            count = self._count_items(page_data)
            if count < validation.min_records_per_page:
                issues.append(f"page has {count} records, expected >= {validation.min_records_per_page}")
        for required in validation.required_fields:
            if page_data.get(required) is None:
                issues.append(f"required field '{required}' is missing")
        if not issues:
            return None
        if validation.fail_on_empty:
            return "validation_error"
        logger.warning(f"Extraction validation warning: {'; '.join(issues)}")
        return None

    async def _process_url(self, url: str):
        if not await self._is_allowed(url):
            if self.stats_callback: self.stats_callback(StatsEvent("blocked"))
            return

        await self.checkpoint.mark_in_progress(url, kind="root")
        content = ""
        try:
            result = await self._fetch_page(url, purpose=RequestPurpose.ROOT)
            content = result.content
            if result.error is not None:
                raise result.error
            if content or result.status_code == 204:
                data, _ = await self._process_content(content, result.final_url)
                validation_failure = self._validate_extraction(data)
                if validation_failure:
                    raise FetchError(ErrorCategory.VALIDATION, url, validation_failure)
                await self._merge_data(data, source_url=result.final_url)
                await self.checkpoint.mark_done(url, kind="root")
                self._record_sample(
                    origin(url), "root", result.status_code,
                    result.elapsed_ms, result.attempts, "success", url,
                )
                if self.stats_callback: self.stats_callback(StatsEvent("page_success"))
            else:
                raise Exception("Empty Content")
        except FetchError as e:
            logger.error(f"Failed {url}: {e}")
            await self.checkpoint.mark_failed(url, kind="root", error=e.category.value)
            self._record_failure(url, e)
            self._record_sample(
                origin(url), "root", getattr(e, "status_code", 0) or 0,
                getattr(e, "elapsed_ms", 0.0), getattr(e, "attempts", 1), e.category.value, url,
            )
            if self.stats_callback:
                self.stats_callback(StatsEvent(e.category.value))
        except Exception as e:
                logger.error(f"Failed {url}: {e}")
                if 'content' in locals() and content:
                    await self._save_debug_snapshot(content, url)
                await self.checkpoint.mark_failed(url, kind="root", error=ErrorCategory.INTERNAL.value)
                self._record_failure(url, e)
                self._record_sample(origin(url), "root", 0, 0.0, 1, "internal_error", url)
                if self.stats_callback: self.stats_callback(StatsEvent("page_error"))

    def _build_next_url(self, current_url: str, next_value: str) -> Optional[str]:
        """
        Compute the next page URL from the current URL and the next_value token.

        For HTML pagination the next_value is typically a relative href that should
        be resolved with urljoin.  For JSON API pagination it is often a cursor token
        that must be appended as a query parameter (configurable via
        ``pagination.query_param``, default ``"after"``).
        """
        if not next_value:
            return None

        is_json = self.config.response_type == "json"

        # If the value already looks like an absolute or relative URL, resolve it.
        if next_value.startswith("http") or next_value.startswith("/"):
            return urljoin(current_url, next_value)

        if is_json:
            # Treat as a query-parameter cursor token
            param_name = (
                self.config.pagination.query_param
                if self.config.pagination
                else "after"
            )
            parsed = urlparse(current_url)
            params = parse_qs(parsed.query, keep_blank_values=True)
            params[param_name] = [next_value]
            new_query = urlencode(params, doseq=True)
            return urlunparse(parsed._replace(query=new_query))

        # Fallback: standard relative URL resolution for HTML
        return urljoin(current_url, next_value)

    async def _discover_sitemap_urls(self) -> List[str]:
        if not self.config.sitemap_urls:
            return []

        async def fetch_sitemap(url: str) -> str:
            result = await self._fetch_page(url, purpose=RequestPurpose.SITEMAP)
            if result.error is not None:
                raise result.error
            return result.content

        return await discover_sitemap(
            [str(url) for url in self.config.sitemap_urls],
            fetch_sitemap,
            self._is_allowed,
            max_urls=self.config.sitemap_max_urls,
            max_depth=self.config.sitemap_max_depth,
        )

    async def _run_pagination_mode(self, resume_url: Optional[str] = None):
        if not self.config.base_url: return
        current_url = resume_url or str(self.config.base_url)
        pages = 0
        max_pages = self.config.pagination.max_pages if self.config.pagination else 1
        if self.limit is not None:
            max_pages = min(max_pages, self.limit)

        while pages < max_pages and current_url and not self.shutdown_requested:
            if not await self._is_allowed(current_url):
                if self.stats_callback: self.stats_callback(StatsEvent("blocked"))
                break
            logger.info(f"📄 Page {pages + 1}: {current_url}")
            await self.checkpoint.mark_in_progress(current_url, kind="pagination")
            content = ""
            
            try:
                result = await self._fetch_page(
                    current_url, purpose=RequestPurpose.PAGINATION
                )
                content = result.content
                
                if result.error is not None:
                    raise result.error
                if not content: raise Exception("Empty")
                
                data, resolver = await self._process_content(content, result.final_url)
                await self._merge_data(data, source_url=result.final_url)
                
                await self.checkpoint.mark_done(current_url, kind="pagination")
                self._record_sample(
                    origin(current_url), "pagination", result.status_code,
                    result.elapsed_ms, result.attempts, "success", current_url,
                )
                if self.stats_callback: self.stats_callback(StatsEvent("page_success"))
                
                pages += 1
                if self.config.pagination and pages < max_pages:
                    next_link = resolver.get_attribute(self.config.pagination.selector, "href")
                    if next_link:
                        next_url = self._build_next_url(current_url, next_link)
                        if next_url:
                            current_url = next_url
                            await asyncio.sleep(random.uniform(self.config.min_delay, self.config.max_delay))
                        else:
                            current_url = None
                    else:
                        current_url = None
                else:
                    current_url = None
            except FetchError as e:
                logger.error(f"Page failed: {e}")
                await self.checkpoint.mark_failed(current_url, kind="pagination", error=e.category.value)
                self._record_failure(current_url, e)
                self._record_sample(
                    origin(current_url), "pagination", getattr(e, "status_code", 0) or 0,
                    getattr(e, "elapsed_ms", 0.0), getattr(e, "attempts", 1), e.category.value, current_url,
                )
                if self.stats_callback: self.stats_callback(StatsEvent(e.category.value))
                break
            except Exception as e:
                logger.error(f"Page failed: {e}")
                if 'content' in locals() and content:
                    await self._save_debug_snapshot(content, current_url)
                await self.checkpoint.mark_failed(
                    current_url, kind="pagination", error=ErrorCategory.INTERNAL.value
                )
                self._record_failure(current_url, e)
                self._record_sample(origin(current_url), "pagination", 0, 0.0, 1, "internal_error", current_url)
                if self.stats_callback: self.stats_callback(StatsEvent("page_error"))
                break

    async def _process_content(
        self,
        content: str,
        url: str = "",
        fields: Optional[List[DataField]] = None,
        depth: int = 0,
    ) -> Tuple[Dict[str, Any], Any]:
        current_fields = fields or self.config.fields
        # Register this page's URL at its own depth so revisiting it deeper is
        # recognized as a cycle.
        if url:
            self.depth_first_seen.setdefault(url, depth)
        try:
            if self.config.response_type == "json":
                 resolver = JsonResolver(content)
            else:
                 resolver = HtmlResolver(content)
        except Exception as exc:
            # Unparseable bodies are page failures (PARSE) and are never retried.
            from engine.errors import classify_exception
            raise FetchError(
                classify_exception(exc),
                url,
                f"failed to parse response: {exc}",
                cause=exc,
            )

        data = {}
        for field in current_fields:
            extracted_value = resolver.resolve_field(field)
            if field.follow_url and extracted_value and field.nested_fields:
                if depth >= self.config.max_depth:
                    logger.warning(
                        f"Maximum nested depth {self.config.max_depth} reached at {url}"
                    )
                    if self.stats_callback: self.stats_callback(StatsEvent("depth_exhausted"))
                    data[field.name] = []
                    continue
                urls_to_follow = extracted_value if isinstance(extracted_value, list) else [extracted_value]
                nested_results_list = []
                nested_failures: List[str] = []
                max_urls = self.config.max_nested_urls
                urls_to_follow = urls_to_follow[:max_urls]
                
                if urls_to_follow:
                    logger.info(f"    ↳ Following {len(urls_to_follow)} nested links from {url}...")
                
                for relative_url in urls_to_follow:
                    try:
                        full_child_url = resolve_url(url, str(relative_url))
                    except UrlPolicyError as exc:
                        logger.warning(f"Skipping invalid child URL {relative_url}: {exc}")
                        continue
                    # Append .json only when explicitly requested (Reddit-style APIs).
                    # This is opt-in via config.append_json_suffix to avoid mangling
                    # URLs for generic JSON APIs.
                    if self.config.append_json_suffix and not full_child_url.endswith(".json"):
                        parsed = urlparse(full_child_url)
                        path = parsed.path.rstrip('/')
                        full_child_url = f"{parsed.scheme}://{parsed.netloc}{path}.json"

                    if not await self._is_allowed(full_child_url, parent_url=url):
                        continue

                    # Cycle detection: same canonical URL revisited at a STRICTLY
                    # greater depth than its first sighting is a cycle — stop the
                    # branch (attach cached result if present, else skip).
                    first_seen = self.depth_first_seen.get(full_child_url)
                    child_depth = depth + 1
                    if first_seen is not None and child_depth > first_seen:
                        logger.debug(f"Cycle detected at {full_child_url} (depth {child_depth})")
                        if self.stats_callback: self.stats_callback(StatsEvent("cycle_detected"))
                        continue
                    self.depth_first_seen.setdefault(full_child_url, child_depth)

                    try:
                        cache_key = (
                            full_child_url,
                            field.model_dump_json(exclude={"name"}, exclude_none=True),
                        )
                    except AttributeError:
                        cache_key = (full_child_url, field.name)
                    cached_child = self.child_cache.get(cache_key)
                    if cached_child is not None:
                        child_data = dict(cached_child)
                        child_data["_source_url"] = full_child_url
                        child_data["_parent_url"] = url
                        nested_results_list.append(child_data)
                        continue

                    # Fetch-level dedup: a child already done is never re-fetched.
                    if self.checkpoint.is_done(full_child_url, kind="nested"):
                        persisted = await self.checkpoint.get_child_results(full_child_url, cache_key[1])
                        if url in persisted:
                            try:
                                child_data = json.loads(persisted[url])
                            except Exception:
                                child_data = None
                            if child_data is not None:
                                child_data["_source_url"] = full_child_url
                                child_data["_parent_url"] = url
                                nested_results_list.append(child_data)
                                continue

                    # Inflight dedup: two workers hitting the same child await one fetch.
                    inflight = self._child_inflight.get(full_child_url)
                    if inflight is not None:
                        try:
                            child_data = await inflight
                        except Exception as exc:
                            logger.warning(f"Inflight child {full_child_url} failed: {exc}")
                            continue
                        if child_data is not None:
                            child_data = dict(child_data)
                            child_data["_source_url"] = full_child_url
                            child_data["_parent_url"] = url
                            nested_results_list.append(child_data)
                        continue

                    future = asyncio.get_running_loop().create_future()
                    self._child_inflight[full_child_url] = future
                    try:
                        await self.checkpoint.mark_in_progress(
                            full_child_url, kind="nested", parent_url=url, depth=child_depth
                        )
                        child_result = await self._fetch_page(
                            full_child_url,
                            purpose=RequestPurpose.NESTED,
                            parent_url=url,
                        )
                        child_content = child_result.content

                        if child_result.error is not None:
                            raise child_result.error
                        if child_content:
                            child_data, _ = await self._process_content(
                                child_content,
                                child_result.final_url,
                                fields=field.nested_fields,
                                depth=child_depth,
                            )
                            self.child_cache[cache_key] = dict(child_data)
                            await self.checkpoint.mark_child_result(
                                full_child_url, url, cache_key[1], json.dumps(child_data, default=str)
                            )
                            future.set_result(dict(child_data))
                            child_data["_source_url"] = full_child_url
                            child_data["_parent_url"] = url
                            nested_results_list.append(child_data)
                            await self.checkpoint.mark_done(full_child_url, kind="nested")
                            self._record_sample(
                                origin(full_child_url), "nested", child_result.status_code,
                                child_result.elapsed_ms, child_result.attempts, "success", full_child_url,
                            )
                            if self.stats_callback: self.stats_callback(StatsEvent("page_success"))
                            # Polite delay between child-page requests to avoid hammering the server
                            await asyncio.sleep(random.uniform(self.config.min_delay, self.config.max_delay))

                    except FetchError as e:
                        logger.warning(f"Failed to follow {full_child_url}: {e}")
                        await self.checkpoint.mark_failed(full_child_url, kind="nested", error=e.category.value)
                        nested_failures.append(full_child_url)
                        self._record_sample(
                            origin(full_child_url), "nested", getattr(e, "status_code", 0) or 0,
                            getattr(e, "elapsed_ms", 0.0), getattr(e, "attempts", 1), e.category.value, full_child_url,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to follow {full_child_url}: {e}")
                        nested_failures.append(full_child_url)
                        self._record_sample(origin(full_child_url), "nested", 0, 0.0, 1, "internal_error", full_child_url)
                    finally:
                        self._child_inflight.pop(full_child_url, None)
                        if not future.done():
                            future.set_result(None)

                data[field.name] = nested_results_list
                if nested_failures:
                    message = f"{len(nested_failures)} nested child request(s) failed"
                    if self.config.fail_parent_on_nested_error:
                        raise FetchError(ErrorCategory.NESTED, url, message)
                    logger.warning(f"{message}; emitting partial nested data for {url}")
                    self.metrics.record_event("nested_partial")
                    if self.stats_callback:
                        self.stats_callback(StatsEvent("nested_partial"))
            else:
                data[field.name] = extracted_value
        return data, resolver

    async def _save_debug_snapshot(self, html: str, url: str):
        """Save a bounded debug snapshot (P7.5): count/size/retention caps."""
        try:
            snap_config = self.config.debug_snapshots
            if not snap_config.enabled:
                return
            debug_dir = self.run_context.debug_directory if self.run_context else Path("debug")
            debug_dir.mkdir(parents=True, exist_ok=True)

            # Cap by file count (keep newest).
            existing = sorted(debug_dir.glob("fail_*.html"), key=lambda p: p.stat().st_mtime)
            while len(existing) >= snap_config.max_files:
                oldest = existing.pop(0)
                try:
                    oldest.unlink()
                except OSError:
                    pass

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = debug_dir / f"fail_{timestamp}_{safe_name}.html"

            # Truncate content to max_bytes_per_file.
            body = html
            if snap_config.max_bytes_per_file > 0 and len(body.encode("utf-8")) > snap_config.max_bytes_per_file:
                body = body[:snap_config.max_bytes_per_file] + "\n<!-- truncated -->\n"

            async with aiofiles.open(filename, "w", encoding="utf-8") as f:
                await f.write(f"<!-- Failed URL: {redact_text(url)} -->\n")
                await f.write(body)
            logger.warning(f"📸 Snapshot saved: {filename}")

            # Cap by total bytes (sweep oldest).
            if snap_config.max_total_bytes > 0:
                total = sum(p.stat().st_size for p in debug_dir.glob("fail_*.html"))
                for snapshot in sorted(debug_dir.glob("fail_*.html"), key=lambda p: p.stat().st_mtime):
                    if total <= snap_config.max_total_bytes:
                        break
                    total -= snapshot.stat().st_size
                    try:
                        snapshot.unlink()
                    except OSError:
                        pass
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")

    def _count_items(self, page_data: Dict[str, Any]) -> int:
        """Count the number of extracted items in a page_data dict.

        A configured ``record_field`` is authoritative. Without one, the
        largest list is used rather than summing parallel list-valued fields;
        scalar pages count as one record.
        This drives the 'entries_added' stats counter so the dashboard shows
        meaningful record counts rather than page counts.
        """
        if self.config.record_field:
            value = page_data.get(self.config.record_field)
            if isinstance(value, list):
                return len(value)
            return 1 if value is not None else 0
        lists = [len(v) for v in page_data.values() if isinstance(v, list)]
        return max(lists, default=1)

    def _dedup_key(self, page_data: Dict[str, Any], source_url: Optional[str] = None) -> Optional[str]:
        """Compute the dedup key per the configured DedupMode (P7.1).

        Returns None for mode ``none`` (no dedup) or when the key cannot be
        computed (in which case the record is emitted — never dropped).
        """
        mode = self.config.dedup.mode
        if mode == "none":
            return None
        try:
            if mode == "url":
                return source_url or ""
            if mode == "fields":
                subset = {k: page_data[k] for k in self.config.dedup.fields if k in page_data}
                return hashlib.md5(
                    json.dumps(subset, sort_keys=True, default=str).encode()
                ).hexdigest()
            # exact_hash (default) — current behaviour
            return hashlib.md5(
                json.dumps(page_data, sort_keys=True, default=str).encode()
            ).hexdigest()
        except Exception as e:
            logger.warning(f"Skipping un-hashable page data: {e}")
            return None

    async def _merge_data(self, page_data: Dict[str, Any], source_url: Optional[str] = None):
        if not page_data:
            return

        key = self._dedup_key(page_data, source_url)
        if key is None:
            # No dedup configured (or un-hashable) -> emit unconditionally.
            async with self.data_lock:
                self.pending_batch.append(page_data)
            await self._flush_remaining_batches()
            return

        # Exact set is the authority: a Bloom false positive must never drop data.
        if key in self.exact_seen:
            logger.debug(f"Skipped duplicate entry: {key[:8]}")
            self.metrics.record_duplicate()
            if self.stats_callback: self.stats_callback(StatsEvent("page_skipped"))
            return

        if key in self.seen_hashes:
            # Bloom says "maybe present" — confirm against the exact set.
            if key in self.exact_seen:
                self.metrics.record_duplicate()
                if self.stats_callback: self.stats_callback(StatsEvent("page_skipped"))
                return
            # Bloom false positive: emit (correctness wins over memory).

        self.seen_hashes.add(key)
        # Bounded LRU: evict oldest when at capacity (Bloom still gates dupes).
        self.exact_seen[key] = None
        if len(self.exact_seen) > self.config.dedup.exact_capacity:
            self.exact_seen.popitem(last=False)
        await self.checkpoint.mark_dedup_key(key, self.config.dedup.exact_capacity)

        batch_to_flush: List[Dict[str, Any]] = []
        async with self.data_lock:
            self.pending_batch.append(page_data)
            if len(self.pending_batch) >= self.batch_size:
                batch_to_flush = self.pending_batch.copy()
                self.pending_batch = []
        
        if batch_to_flush:
            await self._flush_batch(batch_to_flush)
            if self.stats_callback:
                item_count = sum(self._count_items(item) for item in batch_to_flush)
                self.stats_callback(StatsEvent("entries_added", count=item_count))

    async def _flush_batch(self, batch: List[Dict[str, Any]]):
        if not batch:
            return
        if self.stream_writer is not None:
            await self.stream_writer.write({"items": batch})
        elif self.output_callback:
            await self.output_callback({"items": batch})

    async def _flush_remaining_batches(self):
        async with self.data_lock:
            batch = self.pending_batch.copy()
            self.pending_batch = []
        if batch:
            await self._flush_batch(batch)
            if self.stats_callback:
                item_count = sum(self._count_items(item) for item in batch)
                self.stats_callback(StatsEvent("entries_added", count=item_count))

    async def ensure_active_token(self):
        if not self.config.authentication: return

        auth_config = self.config.authentication

        # Bearer type: static token supplied directly in config — no refresh needed
        if auth_config.type == "bearer":
            if not self.auth_token and auth_config.client_secret:
                self.auth_token = auth_config.client_secret
                # Treat as non-expiring
                self.token_expires_at = datetime.max
                logger.info("🔑 Bearer token loaded from config")
            return

        if self.auth_token and datetime.now() < (self.token_expires_at - timedelta(seconds=60)): return

        session_to_close = None

        async with self._auth_lock:
            if self.auth_token and datetime.now() < (self.token_expires_at - timedelta(seconds=60)):
                return

            token_url = str(auth_config.token_url) if auth_config.token_url else ""
            if not token_url:
                raise AuthError(token_url, "oauth_password requires a token_url")
            # Validate the token endpoint against the URL policy before the request.
            try:
                token_url = self.url_policy.validate(token_url)
            except Exception as exc:
                from engine.errors import classify_exception
                raise AuthError(token_url, f"token URL rejected by policy: {exc}", cause=exc)

            logger.info(f"🔄 Refreshing OAuth Token for {auth_config.type}...")

            if not self.session: self._init_session()
            if not self.session: raise AuthError(token_url, "Failed to initialize session")

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
                    current_proxy = self._get_next_proxy()
                    proxies = {"http": current_proxy, "https": current_proxy} if current_proxy else None

                    token_headers = self.url_policy.headers_for(
                        token_url,
                        parent_url=None,
                        configured={},
                    )
                    token_headers["User-Agent"] = self.ua_rotator.random
                    token_headers["Accept"] = "application/json"

                    async with self.rate_limiter:
                        response = await self.session.post(
                            token_url,
                            auth=(client_id, client_secret),
                            data=payload,
                            proxies=cast(Any, proxies),
                            headers=token_headers,
                        )

                    if response.status_code == 200:
                        data = response.json()
                        self.auth_token = data.get("access_token")
                        expires_in = data.get("expires_in", 3600)
                        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                        logger.success(f"✅ Token Refreshed! Expires in {expires_in}s")
                    else:
                        logger.error(f"❌ Auth Failed: {response.status_code} - {response.text}")
                        raise AuthError(token_url, f"token endpoint returned {response.status_code}")

            except AuthError:
                raise
            except Exception as e:
                logger.error(f"Auth Error: {e}")
                # Close session outside lock to prevent race conditions
                session_to_close = self.session
                self.session = None
                if session_to_close:
                    await session_to_close.close()
                raise AuthError(token_url, str(e), cause=e)

    async def _fetch_page(
        self,
        url: str,
        purpose: RequestPurpose = RequestPurpose.ROOT,
        parent_url: Optional[str] = None,
    ) -> FetchResult:
        """Fetch a URL with policy validation and status-aware retries.

        Returns a FetchResult; on final failure the result carries ``error``
        (a classified FetchError) instead of raising. Redirects are followed
        manually and each hop is policy-validated; a blocked hop aborts the
        chain with a POLICY error (never retried).
        """
        current_url = self.url_policy.validate(url, parent_url=parent_url)
        requested_url = current_url
        redirect_chain: List[str] = []
        started = time.perf_counter()
        retry_config = self.config.retry
        credential_origin = origin(requested_url)

        def _failed(error: FetchError) -> FetchResult:
            error.elapsed_ms = (time.perf_counter() - started) * 1000
            return FetchResult(
                content="",
                requested_url=requested_url,
                final_url=current_url,
                status_code=error.status_code or 0,
                attempts=error.attempts,
                redirect_chain=redirect_chain,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error=error,
            )

        for attempt in range(1, retry_config.max_attempts + 1):
            if self.config.authentication:
                try:
                    await self.ensure_active_token()
                except Exception as exc:
                    from engine.errors import classify_exception
                    category = classify_exception(exc)
                    return _failed(FetchError(
                        category,
                        current_url,
                        str(exc),
                        cause=exc,
                        attempts=attempt,
                    ))
            headers = self.url_policy.headers_for(
                current_url,
                parent_url=parent_url,
                configured=self.config.headers,
                bearer_token=self.auth_token,
                credential_origin=credential_origin,
            )
            headers["User-Agent"] = self.ua_rotator.random
            if self.config.request_method == "POST":
                headers.setdefault(
                    "Content-Type",
                    "application/json" if self.config.request_body_type == "json"
                    else "application/x-www-form-urlencoded",
                )
            current_proxy, proxy_lease = await self._get_healthy_proxy()

            try:
                if self.browser_manager:
                    browser_manager = self.browser_manager
                    result = await self._limited_request(current_url, lambda: browser_manager.fetch_page(
                            current_url,
                            headers=headers,
                            proxy=current_proxy,
                            worker_id=0,
                            method=self.config.request_method,
                            body=self.config.request_body,
                            body_type=self.config.request_body_type,
                        ))
                    result.requested_url = requested_url
                    result.redirect_chain = redirect_chain
                    result.attempts = attempt
                    try:
                        self.url_policy.validate(result.final_url, parent_url=requested_url)
                    except Exception as exc:
                        from engine.errors import classify_exception
                        return _failed(FetchError(
                            classify_exception(exc),
                            result.final_url,
                            "redirect target blocked",
                            cause=exc,
                            attempts=attempt,
                        ))
                    if 200 <= result.status_code < 300:
                        if proxy_lease:
                            await proxy_lease.succeed()
                        return result
                    retry_after = retry_after_seconds(
                        result.headers.get("retry-after"), retry_config.retry_after_cap_seconds
                    )
                    if not is_retryable_status(result.status_code, retry_config) or attempt >= retry_config.max_attempts:
                        if proxy_lease:
                            await proxy_lease.succeed()
                        category = ErrorCategory.RATE_LIMIT if result.status_code == 429 else ErrorCategory.HTTP
                        return _failed(FetchError(
                            category, current_url, f"HTTP status {result.status_code}",
                            status_code=result.status_code, retry_after=retry_after, attempts=attempt,
                        ))
                    await asyncio.sleep(retry_after if retry_after is not None else backoff_seconds(attempt, retry_config))
                    if proxy_lease:
                        await proxy_lease.fail()
                    continue

                if not self.session:
                    raise RuntimeError("Session not initialized")
                proxies: Any = (
                    {"http": current_proxy, "https": current_proxy}
                    if current_proxy
                    else None
                )
                session: Any = self.session
                request_kwargs = {
                    "timeout": self.config.request_timeout,
                    "proxies": proxies,
                    "headers": headers,
                    "allow_redirects": False,
                }
                if self.config.request_method == "POST":
                    if self.config.request_body_type == "json":
                        request_kwargs["json"] = self.config.request_body
                    else:
                        request_kwargs["data"] = self.config.request_body
                async def _send_initial() -> Any:
                    if self.config.request_method == "POST":
                        return await session.post(current_url, **request_kwargs)
                    return await session.get(current_url, **request_kwargs)
                response = await self._limited_request(current_url, _send_initial)
                status = int(response.status_code)
                response_headers = {str(k): str(v) for k, v in response.headers.items()}

                if status in {301, 302, 303, 307, 308}:
                    # Follow redirects within this attempt; each hop is
                    # policy-validated. A blocked hop aborts the chain.
                    while True:
                        location = response_headers.get("location")
                        if not location or len(redirect_chain) >= self.config.url_policy.max_redirects:
                            error = HttpStatusError(status, current_url, "Redirect limit or missing Location")
                            return _failed(error.to_fetch_error(attempts=attempt))
                        try:
                            next_url = resolve_url(current_url, location)
                            next_url = self.url_policy.validate(next_url, parent_url=current_url)
                        except Exception as exc:
                            # A redirect hop that violates policy aborts the whole
                            # chain — never follow, never retry.
                            from engine.errors import classify_exception
                            redirect_error = FetchError(
                                classify_exception(exc),
                                current_url,
                                f"redirect target blocked: {exc}",
                                cause=exc,
                                attempts=attempt,
                            )
                            return _failed(redirect_error)
                        redirect_chain.append(next_url)
                        current_url = next_url
                        # Re-fetch the redirect target within the same attempt.
                        hop_headers = self.url_policy.headers_for(
                            current_url,
                            parent_url=redirect_chain[-2] if len(redirect_chain) > 1 else requested_url,
                            configured=self.config.headers,
                            bearer_token=self.auth_token,
                            credential_origin=credential_origin,
                        )
                        hop_headers["User-Agent"] = self.ua_rotator.random
                        hop_kwargs = {
                            "timeout": self.config.request_timeout,
                            "proxies": proxies,
                            "headers": hop_headers,
                            "allow_redirects": False,
                        }
                        if self.config.request_method == "POST":
                            if self.config.request_body_type == "json":
                                hop_kwargs["json"] = self.config.request_body
                            else:
                                hop_kwargs["data"] = self.config.request_body
                        async def _send_hop() -> Any:
                            if self.config.request_method == "POST":
                                return await session.post(current_url, **hop_kwargs)
                            return await session.get(current_url, **hop_kwargs)
                        response = await self._limited_request(current_url, _send_hop)
                        status = int(response.status_code)
                        response_headers = {str(k): str(v) for k, v in response.headers.items()}
                        if status not in {301, 302, 303, 307, 308}:
                            break

                if 200 <= status < 300:
                    if redirect_chain and redirect_chain[-1] != current_url:
                        redirect_chain.append(current_url)
                    if proxy_lease:
                        await proxy_lease.succeed()
                    return FetchResult(
                        content=response.text,
                        requested_url=requested_url,
                        final_url=current_url,
                        status_code=status,
                        headers=response_headers,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                        attempts=attempt,
                        redirect_chain=redirect_chain,
                    )

                error = HttpStatusError(status, current_url)
                retry_after = retry_after_seconds(
                    response_headers.get("retry-after"),
                    retry_config.retry_after_cap_seconds,
                )
                if not is_retryable_status(status, retry_config) or attempt >= retry_config.max_attempts:
                    # 429 with a Retry-After we already honored at max attempts
                    # is a rate-limit failure; anything else non-retryable is HTTP.
                    category = ErrorCategory.RATE_LIMIT if status == 429 else ErrorCategory.HTTP
                    if proxy_lease:
                        await proxy_lease.succeed()
                    return _failed(FetchError(
                        category,
                        current_url,
                        str(error),
                        status_code=status,
                        retry_after=retry_after,
                        cause=error,
                        attempts=attempt,
                    ))
                await asyncio.sleep(retry_after if retry_after is not None else backoff_seconds(attempt, retry_config))
                if proxy_lease:
                    await proxy_lease.fail()
            except asyncio.CancelledError:
                raise
            except FetchError as exc:
                # Already classified (e.g. POLICY from a nested policy call).
                if not exc.retryable or attempt >= retry_config.max_attempts:
                    if proxy_lease:
                        await proxy_lease.fail()
                    return _failed(exc)
                if proxy_lease:
                    await proxy_lease.fail()
                await asyncio.sleep(backoff_seconds(attempt, retry_config))
            except Exception as exc:
                from engine.errors import classify_exception
                category = classify_exception(exc)
                if category in NON_RETRYABLE_CATEGORIES or attempt >= retry_config.max_attempts:
                    if proxy_lease:
                        await proxy_lease.fail()
                    return _failed(FetchError(
                        category,
                        current_url,
                        str(exc),
                        cause=exc,
                        attempts=attempt,
                    ))
                logger.warning(f"Network Error ({purpose.value}): {exc}")
                if proxy_lease:
                    await proxy_lease.fail()
                await asyncio.sleep(backoff_seconds(attempt, retry_config))

        raise RuntimeError(f"Unable to fetch {requested_url}")
