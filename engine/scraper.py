import time
import random
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from curl_cffi import requests
from playwright.sync_api import sync_playwright
from loguru import logger  # NEW IMPORT
from engine.schemas import ScraperConfig
from engine.resolver import HtmlResolver

class ScraperEngine:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.session = requests.Session()
        self.aggregated_data: Dict[str, Any] = {}
        self.playwright = None
        self.browser = None

    def run(self) -> Dict[str, Any]:
        logger.info(f"🚀 Starting scrape execution for: {self.config.name}")
        
        if self.config.use_playwright:
            logger.info("🎭 Activating Playwright (Headless Browser)...")
            self.playwright = sync_playwright().start()
            
            launch_args: Dict[str, Any] = {"headless": True}
            
            if self.config.proxy:
                logger.info(f"🛡️  Using Proxy: {self.config.proxy}")
                launch_args["proxy"] = {"server": self.config.proxy}
            
            self.browser = self.playwright.chromium.launch(**launch_args)

        try:
            current_url = str(self.config.base_url)
            pages_scraped = 0
            max_pages = self.config.pagination.max_pages if self.config.pagination else 1

            while pages_scraped < max_pages and current_url:
                logger.info(f"📄 Scraping Page {pages_scraped + 1}: {current_url}")
                
                html_content = self._fetch_page(current_url)
                if not html_content:
                    logger.error("Empty content received. Aborting this page.")
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
                        logger.debug(f"💤 Sleeping for {delay:.2f} seconds...")
                        time.sleep(delay)
                    else:
                        logger.warning("🛑 No 'Next' button found. Stopping pagination.")
                        current_url = None
                else:
                    current_url = None
                    
        finally:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()

        logger.success(f"✅ Finished! Scraped {pages_scraped} pages.")
        return self.aggregated_data

    def _fetch_page(self, url: str) -> str:
        # METHOD A: Playwright
        if self.config.use_playwright:
            if not self.browser: return ""
            try:
                page = self.browser.new_page()
                page.goto(url, timeout=30000)
                
                if self.config.wait_for_selector:
                    try:
                        page.wait_for_selector(self.config.wait_for_selector, timeout=10000)
                    except Exception:
                        logger.warning(f"Timeout waiting for selector: {self.config.wait_for_selector}")

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1) 
                
                content = page.content()
                page.close()
                return content
            except Exception as e:
                logger.error(f"Browser Error: {e}")
                return ""

        # METHOD B: Curl_Cffi
        else:
            try:
                proxies: Any = None
                if self.config.proxy:
                    proxies = {"http": self.config.proxy, "https": self.config.proxy}

                response = self.session.get(
                    url, 
                    impersonate="chrome110", 
                    timeout=15,
                    proxies=proxies 
                )
                if response.status_code == 200:
                    return response.text
                else:
                    logger.error(f"Status Code {response.status_code} at {url}")
                    return ""
            except Exception as e:
                logger.error(f"Network Error: {e}")
                return ""

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