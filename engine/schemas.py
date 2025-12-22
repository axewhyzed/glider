from typing import List, Optional, Any, Dict, Literal
from enum import Enum
from pydantic import BaseModel, HttpUrl, Field, field_validator
from dataclasses import dataclass

@dataclass
class StatsEvent:
    event_type: Literal["page_success", "page_error", "page_skipped", "blocked", "entries_added"]
    count: int = 1
    metadata: Optional[Dict[str, Any]] = None

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
    HOVER = "hover"
    KEY_PRESS = "key"

class Transformer(BaseModel):
    name: TransformerType
    args: Optional[List[Any]] = []

class Selector(BaseModel):
    type: SelectorType
    value: str

class Interaction(BaseModel):
    type: InteractionType
    selector: Optional[str] = None
    value: Optional[str] = None
    duration: Optional[int] = None

class DataField(BaseModel):
    name: str
    selectors: List[Selector]
    is_list: bool = False
    attribute: Optional[str] = None
    transformers: List[Transformer] = []
    children: Optional[List['DataField']] = None
    
    @field_validator('attribute')
    @classmethod
    def validate_attribute(cls, v):
        return v.strip().lower() if v and v.strip() else None

class Pagination(BaseModel):
    selector: Selector
    max_pages: int = 5
    @field_validator('max_pages')
    @classmethod
    def check_max_pages(cls, v):
        if v < 1: raise ValueError('max_pages must be at least 1')
        return v

class ScraperConfig(BaseModel):
    name: str
    base_url: Optional[HttpUrl] = None
    mode: ScrapeMode = ScrapeMode.PAGINATION
    start_urls: Optional[List[HttpUrl]] = []
    use_playwright: bool = False
    wait_for_selector: Optional[str] = None
    interactions: Optional[List[Interaction]] = []
    min_delay: int = 1
    max_delay: int = 3
    proxies: Optional[List[str]] = None
    concurrency: int = 2
    rate_limit: int = 5
    respect_robots_txt: bool = False
    use_checkpointing: bool = False
    fields: List[DataField]
    pagination: Optional[Pagination] = None
    
    @field_validator('concurrency', 'rate_limit')
    @classmethod
    def check_positive(cls, v):
        if v < 1: raise ValueError('Must be positive integer')
        return v

DataField.model_rebuild()