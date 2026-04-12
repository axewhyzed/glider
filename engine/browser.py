import asyncio
import json
from typing import Optional, Any, Callable, Awaitable, Dict, List
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed
from fake_useragent import UserAgent

from engine.schemas import ScraperConfig, InteractionType

# Optional stealth — support both old module-style and new direct-function-style imports
stealth_async: Optional[Callable[[Page], Awaitable[None]]] = None
try:
    from playwright_stealth import stealth_async as _stealth_import  # type: ignore
    # Newer versions export the function directly; older versions wrapped it in a module object
    if callable(_stealth_import):
        stealth_async = _stealth_import
    elif hasattr(_stealth_import, 'stealth_async') and callable(_stealth_import.stealth_async):
        stealth_async = _stealth_import.stealth_async  # type: ignore
except ImportError:
    pass

class BrowserManager:
    """
    Manages Playwright lifecycle: Browsers, Contexts, and Pages.
    Implements context rotation to prevent memory leaks in long-running jobs.
    """
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        
        self.ua_rotator = UserAgent()
        self.request_count = 0
        self.MAX_REQUESTS_PER_CONTEXT = 50 # Rotate context every N requests
    
    async def start(self, proxy: Optional[str] = None):
        if self.playwright: return
        
        self.playwright = await async_playwright().start()
        
        # Explicitly type as Dict[str, Any] to satisfy Pylance
        launch_args: Dict[str, Any] = {"headless": True}
        
        if proxy:
            launch_args["proxy"] = {"server": proxy}
            
        self.browser = await self.playwright.chromium.launch(**launch_args)
        await self._create_context()
        logger.info("🎭 Playwright Browser Started")

    async def _create_context(self):
        if self.context:
            try:
                await self.context.close()
            except Exception as e:
                logger.warning(f"Failed to close old context: {e}")
        
        if not self.browser:
             raise RuntimeError("Browser not initialized")

        context_options: Dict[str, Any] = {
            "user_agent": self.ua_rotator.random,
            "viewport": {"width": 1920, "height": 1080},
            "ignore_https_errors": True,
        }

        # Inject cookies from cookie file into the Playwright context
        if self.config.cookies_file:
            try:
                with open(self.config.cookies_file, 'r') as f:
                    raw_cookies = json.load(f)
                if isinstance(raw_cookies, dict):
                    # Convert simple key/value dict to Playwright cookie format.
                    # Playwright requires either `url` or `domain`+`path`; use base_url
                    # when available.  If base_url is not set, omit `url` and let
                    # Playwright infer domain from the first navigation.
                    base_url_str = str(self.config.base_url) if self.config.base_url else None
                    pw_cookies = []
                    for k, v in raw_cookies.items():
                        if v is None or not isinstance(v, (str, int, float, bool)):
                            continue
                        entry: Dict[str, Any] = {"name": str(k), "value": str(v)}
                        if base_url_str:
                            entry["url"] = base_url_str
                        pw_cookies.append(entry)
                elif isinstance(raw_cookies, list):
                    pw_cookies = raw_cookies  # Already in Playwright format
                else:
                    pw_cookies = []

                self.context = await self.browser.new_context(**context_options)
                if pw_cookies:
                    await self.context.add_cookies(pw_cookies)
                    logger.info(f"🍪 Injected {len(pw_cookies)} cookies into Playwright context")
            except Exception as e:
                logger.error(f"❌ Failed to inject cookies into browser context: {e}")
                self.context = await self.browser.new_context(**context_options)
        else:
            self.context = await self.browser.new_context(**context_options)

        self.request_count = 0

    async def close(self):
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
        self.playwright = None

    async def fetch_page(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Fetch a page content handling context rotation and interactions."""
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
            nav_timeout_ms = (self.config.request_timeout or 30) * 1000
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

    async def _handle_interactions(self, page: Page):
        interactions = self.config.interactions or []
        
        for action in interactions:
            try:
                await self._execute_interaction(page, action)
            except Exception as e:
                logger.warning(f"Interaction failed ({action.type}): {e}")

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