from typing import List, Optional, Any
from enum import Enum
from pydantic import BaseModel, HttpUrl, Field

class SelectorType(str, Enum):
    CSS = "css"
    XPATH = "xpath"

class TransformerType(str, Enum):
    STRIP = "strip"
    TO_FLOAT = "to_float"
    TO_INT = "to_int"
    REGEX = "regex"
    REPLACE = "replace"

class ScrapeMode(str, Enum):
    PAGINATION = "pagination"
    LIST = "list"

class InteractionType(str, Enum):
    CLICK = "click"
    WAIT = "wait"
    SCROLL = "scroll"
    FILL = "fill"
    PRESS = "press"

class Transformer(BaseModel):
    name: TransformerType
    args: Optional[List[Any]] = []

class Selector(BaseModel):
    type: SelectorType
    value: str

class Interaction(BaseModel):
    """Defines an action to perform on the page before extraction."""
    type: InteractionType
    selector: Optional[str] = None
    value: Optional[str] = None  # Text to fill or key to press
    duration: Optional[int] = None # Duration for wait (ms)

class DataField(BaseModel):
    name: str
    selectors: List[Selector]
    is_list: bool = False
    transformers: List[Transformer] = []
    children: Optional[List['DataField']] = None 

class Pagination(BaseModel):
    selector: Selector
    max_pages: int = 5

class ScraperConfig(BaseModel):
    name: str
    base_url: HttpUrl
    mode: ScrapeMode = ScrapeMode.PAGINATION
    
    start_urls: Optional[List[HttpUrl]] = []

    use_playwright: bool = False
    wait_for_selector: Optional[str] = None
    
    # NEW: Browser Interactions (e.g., clicks, inputs)
    interactions: Optional[List[Interaction]] = Field(default=[], description="Actions to perform before scraping")
    
    # Anti-Ban & Performance
    min_delay: int = 1
    max_delay: int = 3
    
    proxies: Optional[List[str]] = Field(default=None, description="List of proxy URLs to rotate")
    
    concurrency: int = 2
    rate_limit: int = 5
    
    # Ethical & Reliability
    respect_robots_txt: bool = False
    use_checkpointing: bool = False

    fields: List[DataField]
    pagination: Optional[Pagination] = None

DataField.model_rebuild()