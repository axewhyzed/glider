from typing import List, Optional, Any, Dict, Literal
from enum import Enum
from pydantic import BaseModel, HttpUrl, Field, field_validator, model_validator
from dataclasses import dataclass

@dataclass
class StatsEvent:
    event_type: Literal["page_success", "page_error", "page_skipped", "blocked", "entries_added"]
    count: int = 1
    metadata: Optional[Dict[str, Any]] = None

class SelectorType(str, Enum):
    CSS = "css"
    XPATH = "xpath"
    JSON = "json"  # <--- NEW

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

    @model_validator(mode='before')
    @classmethod
    def parse_shorthand(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"name": data, "args": []}
        return data

class Selector(BaseModel):
    type: SelectorType
    value: str

    @model_validator(mode='before')
    @classmethod
    def parse_shorthand(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"type": "css", "value": data}
        return data

class Interaction(BaseModel):
    type: InteractionType
    selector: Optional[str] = None
    value: Optional[str] = None
    duration: Optional[int] = None

class DataField(BaseModel):
    name: str
    selector: Optional[Any] = Field(default=None, exclude=True) 
    selectors: List[Selector] = Field(default=[])
    is_list: bool = False
    attribute: Optional[str] = None
    transformers: List[Transformer] = []
    children: Optional[List['DataField']] = None
    
    @model_validator(mode='before')
    @classmethod
    def normalize_selectors(cls, data: Any) -> Any:
        if isinstance(data, dict):
            single = data.get('selector')
            existing = data.get('selectors', [])
            if single:
                if isinstance(single, list):
                    existing = single + existing
                else:
                    existing.insert(0, single)
                data['selector'] = None
            data['selectors'] = existing
        return data

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

# --- NEW AUTH CONFIG ---
class AuthConfig(BaseModel):
    type: Literal["oauth_password", "bearer"] = "oauth_password"
    token_url: Optional[HttpUrl] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    scope: Optional[str] = "*"

class ScraperConfig(BaseModel):
    name: str
    base_url: Optional[HttpUrl] = None
    mode: ScrapeMode = ScrapeMode.PAGINATION
    start_urls: Optional[List[HttpUrl]] = []
    
    # Engine Settings
    response_type: Literal["html", "json"] = "html"  # <--- NEW
    use_playwright: bool = False
    debug_mode: bool = False
    concurrency: int = 2
    rate_limit: int = 5
    min_delay: int = 1
    max_delay: int = 3
    
    wait_for_selector: Optional[str] = None
    interactions: Optional[List[Interaction]] = []
    proxies: Optional[List[str]] = None
    
    # New Header & Auth Fields
    headers: Optional[Dict[str, str]] = None
    authentication: Optional[AuthConfig] = None
    
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