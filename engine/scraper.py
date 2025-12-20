import time
from typing import Dict, Any
from curl_cffi import requests
from engine.schemas import ScraperConfig
from engine.resolver import HtmlResolver

class ScraperEngine:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.session = requests.Session()
    
    def run(self) -> Dict[str, Any]:
        """
        The main execution flow:
        1. Fetch HTML (Stealth Mode)
        2. Parse HTML
        3. Extract Data
        """
        print(f"🚀 Starting scrape for: {self.config.name}")
        
        # 1. Fetch
        html_content = self._fetch_page(str(self.config.base_url))
        if not html_content:
            return {"error": "Failed to retrieve page"}

        # 2. Parse
        resolver = HtmlResolver(html_content)
        
        # 3. Extract
        extracted_data = {}
        for field in self.config.fields:
            # We skip 'nested' logic for this MVP and just grab root level fields
            data = resolver.resolve_field(field)
            extracted_data[field.name] = data
            
        return extracted_data

    def _fetch_page(self, url: str) -> str:
        """
        Uses curl_cffi to impersonate a real Chrome browser (JA3 Spoofing).
        """
        try:
            # 'impersonate="chrome"' is the magic switch that fools firewalls
            response = self.session.get(url, impersonate="chrome110", timeout=15)
            if response.status_code == 200:
                return response.text
            else:
                print(f"❌ Error: Status Code {response.status_code}")
                return ""
        except Exception as e:
            print(f"❌ Network Error: {e}")
            return ""