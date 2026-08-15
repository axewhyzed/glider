from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional, cast
from urllib.parse import urlsplit

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - exercised by core-only installs
    async_playwright = None

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed
from fake_useragent import UserAgent

from engine.schemas import ScraperConfig, InteractionType
from engine.network import FetchResult, UrlPolicy, is_sensitive_header, origin
from engine.cookies import load_scoped_cookies

# Optional stealth — support both old module-style and new direct-function-style imports
stealth_async: Optional[Callable[[Any], Awaitable[None]]] = None
try:
    from playwright_stealth import stealth_async as _stealth_import  # type: ignore
    # Newer versions export the function directly; older versions wrapped it in a module object
    if callable(_stealth_import):
        stealth_async = cast(Callable[[Any], Awaitable[None]], _stealth_import)
    elif hasattr(_stealth_import, 'stealth_async') and callable(_stealth_import.stealth_async):
        stealth_async = cast(Callable[[Any], Awaitable[None]], _stealth_import.stealth_async)
except ImportError:
    pass

class BrowserManager:
    """
    Manages Playwright lifecycle: Browsers, Contexts, and Pages.
    Implements context rotation to prevent memory leaks in long-running jobs.
    """
    def __init__(self, config: ScraperConfig, url_policy: Optional[UrlPolicy] = None):
        self.config = config
        self.url_policy = url_policy or UrlPolicy(config.url_policy)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        
        self.ua_rotator = UserAgent()
        self.request_count = 0
        self.MAX_REQUESTS_PER_CONTEXT = config.browser.context_max_requests
        self._context_lock = asyncio.Lock()
        self._context_condition = asyncio.Condition(self._context_lock)
        self._active_requests = 0
        self._context_proxy: Optional[str] = None
        self._rotation_requested = False

    @property
    def current_proxy(self) -> Optional[str]:
        """Proxy actually attached to the shared browser context."""
        return self._context_proxy

    @property
    def context_rotation_due(self) -> bool:
        """Whether the next shared fetch will rotate the context."""
        return (
            self.config.browser.proxy_rotation == "per_context"
            and self._active_requests == 0
            and (
                self._rotation_requested
                or self.request_count >= self.MAX_REQUESTS_PER_CONTEXT
            )
        )

    def request_context_rotation(self) -> None:
        """Request a context swap at the next safe request boundary.

        Playwright binds a proxy to a context for its entire lifetime.  This
        flag lets the scraper defer a proxy change until all requests using
        the current context have finished.
        """
        if self.config.browser.proxy_rotation == "per_context":
            self._rotation_requested = True

    async def ensure_context_proxy(self, proxy: Optional[str]) -> Optional[str]:
        """Bind the next shared context to ``proxy`` and return actual identity.

        Proxy selection and context rotation are separate layers, so concurrent
        callers may select different candidates while one caller is rotating.
        This method serializes the binding and lets callers reconcile their
        health lease with the proxy that is actually attached.
        """
        if self.config.browser.proxy_rotation == "per_request":
            return proxy
        async with self._context_condition:
            while self._active_requests > 0 and (
                self._rotation_requested
                or self.request_count >= self.MAX_REQUESTS_PER_CONTEXT
                or proxy != self._context_proxy
            ):
                await self._context_condition.wait()
            if self._rotation_requested or proxy != self._context_proxy or (
                self._active_requests == 0
                and self.request_count >= self.MAX_REQUESTS_PER_CONTEXT
            ):
                replacement_proxy = (
                    proxy
                    if self._rotation_requested
                    else proxy or self._context_proxy
                )
                await self._create_context(replacement_proxy)
            return self._context_proxy
    
    async def start(self, proxy: Optional[str] = None):
        if self.playwright: return

        if async_playwright is None:
            raise RuntimeError(
                "Playwright support is not installed; install glider[browser] to enable browser scraping"
            )
        
        self.playwright = await async_playwright().start()
        
        # Explicitly type as Dict[str, Any] to satisfy Pylance
        launch_args: Dict[str, Any] = {"headless": True}
        self.browser = await self.playwright.chromium.launch(**launch_args)
        await self._create_context(proxy=proxy)
        logger.info("🎭 Playwright Browser Started")

    def _build_context_options(self, proxy: Optional[str] = None) -> Dict[str, Any]:
        """Context launch options (extracted for testability without a browser)."""
        options: Dict[str, Any] = {
            "user_agent": self.ua_rotator.random,
            "viewport": {"width": 1920, "height": 1080},
            "ignore_https_errors": self.config.browser.ignore_https_errors,
            # Routes do not intercept service-worker handled requests. Keep
            # the URL/SSRF policy authoritative for every browser request.
            "service_workers": "block",
        }
        if proxy:
            options["proxy"] = {"server": proxy}
        return options

    async def _install_request_guard(self, context) -> None:
        """Abort in-flight requests that resolve to private addresses (SSRF guard)."""
        from engine.network import _host_resolves_to_private, _host_is_private

        async def _guard(route) -> None:
            request_url = route.request.url
            host = urlsplit(request_url).hostname or ""
            resolved_private = _host_resolves_to_private(host) if host else False
            dns_failed = resolved_private is None
            if host and (
                _host_is_private(host)
                or resolved_private is True
                or (dns_failed and self.config.url_policy.dns_failure_policy == "deny")
            ):
                await route.abort()
                logger.warning(f"SSRF guard aborted {request_url}")
            else:
                await route.continue_()

        await context.route("**/*", _guard)

    def _cookie_scope_url(self) -> Optional[str]:
        return (
            str(self.config.base_url)
            if self.config.base_url
            else (str(self.config.start_urls[0]) if self.config.start_urls else None)
        )

    async def _new_context(self, proxy: Optional[str] = None):
        """Create and fully secure a context, closing it if setup fails."""
        if not self.browser:
            raise RuntimeError("Browser not initialized")

        context = await self.browser.new_context(**self._build_context_options(proxy))
        try:
            # Shared and per-request contexts must receive identical,
            # origin-scoped cookie injection. Do not silently continue without
            # cookies when setup fails; that changes authenticated semantics.
            if self.config.cookies_file:
                scoped = load_scoped_cookies(self.config.cookies_file, self._cookie_scope_url())
                if scoped.playwright:
                    # Playwright's stubs type this as a structural sequence;
                    # the loader returns validated cookie dictionaries that
                    # match the runtime API.
                    await context.add_cookies(cast(Any, scoped.playwright))
                    logger.info(f"🍪 Injected {len(scoped.playwright)} cookies into Playwright context")
            await self._install_request_guard(context)
        except BaseException:
            try:
                await context.close()
            except Exception as close_exc:
                logger.warning(f"Failed to close temporary browser context: {close_exc}")
            raise
        return context

    async def _create_context(self, proxy: Optional[str] = None):
        """Atomically replace the shared context after setup succeeds."""
        new_context = await self._new_context(proxy)
        old_context = self.context
        self.context = new_context
        if old_context:
            try:
                await old_context.close()
            except Exception as e:
                logger.warning(f"Failed to close old context: {e}")
        self.request_count = 0
        self._context_proxy = proxy
        self._rotation_requested = False

    async def close(self):
        if self.context:
            try:
                await self.context.close()
            except Exception as exc:
                logger.warning(f"Failed to close context: {exc}")
            self.context = None
        if self.browser:
            try:
                await self.browser.close()
            except Exception as exc:
                logger.warning(f"Failed to close browser: {exc}")
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
        self.playwright = None
        self.request_count = 0

    async def fetch_page_legacy(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Fetch a page content handling context rotation and interactions."""
        url = self._validate_navigation_url(url)
        if not self.context:
            raise RuntimeError("Browser context not started")

        # Rotate context if needed
        self.request_count += 1
        if self.request_count > self.MAX_REQUESTS_PER_CONTEXT:
            logger.debug("♻️ Rotating Browser Context")
            await self._create_context()

        page = await self.context.new_page()
        try:
            # Apply Headers (for Auth)
            if headers:
                await page.set_extra_http_headers(headers)

            if stealth_async:
                await stealth_async(page)
            
            # Navigate — use the configured request_timeout (converted from seconds to ms)
            nav_timeout_ms = self.config.request_timeout * 1000
            await page.goto(url, timeout=nav_timeout_ms, wait_until="domcontentloaded")
            
            # Handle Interactions
            if self.config.interactions:
                await self._handle_interactions(page)
            
            # Wait for selector if configured
            if self.config.wait_for_selector:
                try:
                    await page.wait_for_selector(self.config.wait_for_selector, timeout=5000)
                except Exception:
                    logger.warning(
                        f"⏳ wait_for_selector '{self.config.wait_for_selector}' "
                        f"timed out on {url} — scraping available content"
                    )

            return await page.content()
        except Exception as e:
            logger.warning(f"Browser Fetch Error ({url}): {e}")
            raise e
        finally:
            await page.close()

    async def fetch_page(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        proxy: Optional[str] = None,
        worker_id: int = 0,
        method: str = "GET",
        body: Any = None,
        body_type: str = "json",
    ) -> FetchResult:
        """Fetch a page while keeping context rotation safe under concurrency.

        ``per_request`` proxy rotation creates a throwaway context per call
        (Playwright cannot change a live context's proxy); ``per_context``
        (default) uses the shared context and rotates when the request cap is
        reached.
        """
        url = self._validate_navigation_url(url)
        if method.upper() != "GET":
            raise ValueError(
                "BrowserManager supports only GET navigation; use the HTTP transport for POST requests"
            )
        method = "GET"
        if self.config.browser.proxy_rotation == "per_request":
            return await self._fetch_page_single_context(url, headers, proxy, method, body, body_type)
        return await self._fetch_page_shared_context(url, headers, proxy, method, body, body_type)

    def _validate_navigation_url(self, url: str) -> str:
        """Validate direct browser entry points before creating a page."""
        validated = self.url_policy.validate(url)
        if urlsplit(validated).scheme not in {"http", "https"}:
            raise ValueError("Browser navigation only supports http and https URLs")
        return validated

    async def _fetch_page_single_context(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        proxy: Optional[str] = None,
        method: str = "GET",
        body: Any = None,
        body_type: str = "json",
    ) -> FetchResult:
        """per_request mode: one throwaway context per fetch."""
        if not self.browser:
            raise RuntimeError("Browser not started")
        context = await self._new_context(proxy)
        try:
            return await self._fetch_with_context(context, url, headers, method, body, body_type)
        finally:
            try:
                await context.close()
            except Exception as exc:
                logger.warning(f"Failed to close per-request context: {exc}")

    async def _fetch_page_shared_context(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        proxy: Optional[str] = None,
        method: str = "GET",
        body: Any = None,
        body_type: str = "json",
    ) -> FetchResult:
        """per_context mode: shared context with safe rotation."""
        if not self.context:
            raise RuntimeError("Browser context not started")

        # Rotation is decision-only here; the actual swap happens under the
        # lock at the top of the next fetch, never mid-request.
        async with self._context_condition:
            # A circuit-open proxy requests rotation.  Wait for any requests
            # already using the old context, then swap before admitting this
            # request so it cannot intentionally reuse the unhealthy proxy.
            while self._active_requests > 0 and (
                self._rotation_requested
                or self.request_count >= self.MAX_REQUESTS_PER_CONTEXT
                or proxy != self._context_proxy
            ):
                await self._context_condition.wait()
            if self._rotation_requested or proxy != self._context_proxy or (
                self._active_requests == 0
                and self.request_count >= self.MAX_REQUESTS_PER_CONTEXT
            ):
                # A health-triggered rotation may intentionally pass None to
                # escape an all-open proxy pool. Ordinary request-cap
                # rotation preserves the current proxy for direct callers
                # that do not provide a replacement.
                replacement_proxy = (
                    proxy
                    if self._rotation_requested
                    else proxy or self._context_proxy
                )
                await self._create_context(proxy=replacement_proxy)
            context = self.context
            self._active_requests += 1
            # Reserve the context slot at admission, not after navigation.
            # This prevents concurrent callers from exceeding the configured
            # per-context request cap.
            self.request_count += 1

        try:
            return await self._fetch_with_context(context, url, headers, method, body, body_type)
        finally:
            async with self._context_condition:
                self._active_requests -= 1
                self._context_condition.notify_all()

    async def _fetch_with_context(
        self,
        context,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        method: str = "GET",
        body: Any = None,
        body_type: str = "json",
    ) -> FetchResult:
        """Open a page in ``context``, navigate, and return a FetchResult."""
        page = await context.new_page()
        started = time.perf_counter()
        response = None
        try:
            request_origin = origin(url)

            async def _page_policy(route) -> None:
                request = route.request
                request_url = request.url
                request_scheme = urlsplit(request_url).scheme.lower()
                if request_scheme not in {"http", "https"}:
                    await route.abort()
                    logger.warning(f"Browser blocked non-network request ({request_url})")
                    return
                previous = request.redirected_from
                redirect_hops = 0
                while previous is not None:
                    redirect_hops += 1
                    previous = previous.redirected_from
                try:
                    parent_url = request.redirected_from.url if request.redirected_from else url
                    self.url_policy.validate(request_url, parent_url=parent_url)
                    if redirect_hops > self.config.url_policy.max_redirects:
                        raise ValueError("browser redirect limit exceeded")
                except Exception as exc:
                    logger.warning(f"Browser request blocked by policy ({request_url}): {exc}")
                    await route.abort()
                    return
                filtered = dict(request.headers)
                if headers:
                    filtered.update(headers)
                if origin(request_url) != request_origin:
                    filtered = {
                        key: value for key, value in filtered.items()
                        if not is_sensitive_header(key)
                    }
                await route.continue_(headers=filtered)

            if hasattr(page, "route"):
                await page.route("**/*", _page_policy)
            elif headers and hasattr(page, "set_extra_http_headers"):
                # Compatibility fallback for lightweight test doubles. Real
                # Playwright pages always use the origin-aware route above.
                await page.set_extra_http_headers(headers)
            if stealth_async:
                await stealth_async(page)

            nav_timeout_ms = self.config.request_timeout * 1000
            if method.upper() != "GET":
                raise ValueError(
                    "BrowserManager supports only GET navigation; use the HTTP transport for POST requests"
                )
            goto_options: Dict[str, Any] = {
                "timeout": nav_timeout_ms,
                "wait_until": "domcontentloaded",
            }
            response = await page.goto(url, **goto_options)
            if self.config.interactions:
                await self._handle_interactions(page)
            if self.config.wait_for_selector:
                try:
                    await page.wait_for_selector(self.config.wait_for_selector, timeout=5000)
                except Exception:
                    logger.warning(
                        f"wait_for_selector '{self.config.wait_for_selector}' timed out on {url}"
                    )

            response_headers: Dict[str, str] = {}
            status_code = 200
            if response is not None:
                status_code = response.status
                try:
                    response_headers = await response.all_headers()
                except Exception:
                    response_headers = dict(response.headers)
            if self.config.response_type == "json" and response is not None:
                try:
                    content = (await response.body()).decode("utf-8", errors="replace")
                except Exception:
                    content = await response.text()
            else:
                content = await page.content()
            return FetchResult(
                content=content,
                requested_url=url,
                final_url=page.url or url,
                status_code=status_code,
                headers=response_headers,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            logger.warning(f"Browser Fetch Error ({url}): {exc}")
            raise
        finally:
            try:
                await page.close()
            except Exception as exc:
                logger.warning(f"Failed to close page: {exc}")

    async def _handle_interactions(self, page: Page):
        interactions = self.config.interactions or []
        
        for action in interactions:
            try:
                await self._execute_interaction(page, action)
            except Exception as e:
                logger.warning(f"Interaction failed ({action.type}): {e}")
                if self.config.interaction_failure_policy == "fail":
                    from engine.errors import ErrorCategory, FetchError
                    raise FetchError(
                        ErrorCategory.INTERACTION,
                        page.url or "",
                        f"required interaction '{action.type.value}' failed: {e}",
                        cause=e,
                    ) from e

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
    async def _execute_interaction(self, page: Page, action):
        if action.type == InteractionType.WAIT:
            await page.wait_for_timeout(action.duration or 1000)
        elif action.type == InteractionType.SCROLL:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
        elif action.type == InteractionType.CLICK and action.selector:
            await page.click(action.selector, timeout=5000)
        elif action.type == InteractionType.FILL and action.selector:
            await page.fill(action.selector, action.value or "")
        elif action.type == InteractionType.PRESS and action.selector:
            await page.press(action.selector, action.value or "Enter")
        elif action.type == InteractionType.HOVER and action.selector:
            await page.hover(action.selector, timeout=5000)
        elif action.type == InteractionType.KEY_PRESS and action.value:
            await page.keyboard.press(action.value)
