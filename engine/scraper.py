import time
from typing import Dict, Any, List
from urllib.parse import urljoin
from curl_cffi import requests
from engine.schemas import ScraperConfig
from engine.resolver import HtmlResolver

class ScraperEngine:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.session = requests.Session()
        self.aggregated_data = {} 

    def run(self) -> Dict[str, Any]:
        """
        Main execution loop with Pagination support.
        """
        print(f"🚀 Starting scrape for: {self.config.name}")
        
        current_url = str(self.config.base_url)
        pages_scraped = 0
        max_pages = self.config.pagination.max_pages if self.config.pagination else 1

        while pages_scraped < max_pages and current_url:
            print(f"📄 Scraping Page {pages_scraped + 1}: {current_url}")
            
            # 1. Fetch
            html_content = self._fetch_page(current_url)
            if not html_content:
                break # Stop if network error

            # 2. Parse
            resolver = HtmlResolver(html_content)
            
            # 3. Extract & Merge Data
            page_data = self._extract_data(resolver)
            self._merge_data(page_data)
            
            # 4. Handle Pagination
            pages_scraped += 1
            if self.config.pagination and pages_scraped < max_pages:
                next_link = resolver.get_attribute(self.config.pagination.selector, "href")
                if next_link:
                    # Handle relative URLs (e.g., "catalogue/page-2.html")
                    current_url = urljoin(current_url, next_link)
                    time.sleep(1) # Be polite
                else:
                    print("🛑 No 'Next' button found. Stopping.")
                    current_url = None
            else:
                current_url = None

        print(f"✅ Finished! Scraped {pages_scraped} pages.")
        return self.aggregated_data

    def _extract_data(self, resolver: HtmlResolver) -> Dict[str, Any]:
        """Extracts fields for a single page."""
        data = {}
        for field in self.config.fields:
            data[field.name] = resolver.resolve_field(field)
        return data

    def _merge_data(self, page_data: Dict[str, Any]):
        """
        Smart Merge: 
        - If field is a LIST, append new items.
        - If field is a SINGLE value, keep the first one (or overwrite, depending on pref).
        """
        for key, value in page_data.items():
            if key not in self.aggregated_data:
                # First time seeing this key, just add it
                self.aggregated_data[key] = value
            else:
                # If both are lists, extend them (e.g. adding more products)
                if isinstance(self.aggregated_data[key], list) and isinstance(value, list):
                    self.aggregated_data[key].extend(value)
                # If scalar, we usually ignore subsequent pages (e.g. site title is same on every page)

    def _fetch_page(self, url: str) -> str:
        try:
            # Chrome110 impersonation prevents blocking
            response = self.session.get(url, impersonate="chrome110", timeout=15)
            if response.status_code == 200:
                return response.text
            else:
                print(f"❌ Status Code {response.status_code} at {url}")
                return ""
        except Exception as e:
            print(f"❌ Network Error: {e}")
            return ""