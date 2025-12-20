from typing import List, Optional, Any
from enum import Enum
from pydantic import BaseModel, HttpUrl

class SelectorType(str, Enum):
    CSS = "css"
    XPATH = "xpath"

class TransformerType(str, Enum):
    STRIP = "strip"
    TO_FLOAT = "to_float"
    TO_INT = "to_int"
    REGEX = "regex"
    REPLACE = "replace"

class Transformer(BaseModel):
    name: TransformerType
    # args can now handle [decimal_separator, thousand_separator] for to_float
    args: Optional[List[Any]] = []

class Selector(BaseModel):
    type: SelectorType
    value: str

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
    use_playwright: bool = False
    wait_for_selector: Optional[str] = None
    
    # Anti-Ban & Performance Settings
    min_delay: int = 1
    max_delay: int = 3
    proxy: Optional[str] = None
    concurrency: int = 1  # NEW: For future parallel processing

    fields: List[DataField]
    pagination: Optional[Pagination] = None

DataField.model_rebuild()