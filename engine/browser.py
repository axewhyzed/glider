import asyncio
from typing import Optional, Any, Callable, Awaitable, Dict, List
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed
from fake_useragent import UserAgent

from engine.schemas import ScraperConfig, InteractionType

# Optional stealth
stealth_async: Optional[Callable[[Page], Awaitable[None]]] = None
try:
    from playwright_stealth import stealth_async # type: ignore
except ImportError:
    pass
if stealth_async and hasattr(stealth_async, 'stealth_async'):
    stealth_async = stealth_async.stealth_async # type: ignore

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
            await self.context.close()
        
        if not self.browser:
             raise RuntimeError("Browser not initialized")

        self.context = await self.browser.new_context(
            user_agent=self.ua_rotator.random,
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True
        )
        self.request_count = 0

    async def close(self):
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
        self.playwright = None

    # [FIXED] Added headers support
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
            # 1. Apply Headers (for Auth)
            if headers:
                await page.set_extra_http_headers(headers)

            if stealth_async:
                await stealth_async(page)
            
            # Navigate
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            
            # Handle Interactions
            if self.config.interactions:
                await self._handle_interactions(page)
            
            # Wait for selector if configured
            if self.config.wait_for_selector:
                try:
                    await page.wait_for_selector(self.config.wait_for_selector, timeout=5000)
                except Exception:
                    pass

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