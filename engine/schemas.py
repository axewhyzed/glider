from typing import List, Optional, Any
from enum import Enum
from pydantic import BaseModel, HttpUrl

# 1. Enums (Keep as is)
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
    args: Optional[List[Any]] = []

class Selector(BaseModel):
    type: SelectorType
    value: str

# 2. Updated DataField (Added 'children')
class DataField(BaseModel):
    name: str
    selectors: List[Selector]
    is_list: bool = False
    transformers: List[Transformer] = []
    # NEW: Allows us to scrape data INSIDE this element
    children: Optional[List['DataField']] = None 

# 3. Pagination & Config (Keep as is)
class Pagination(BaseModel):
    selector: Selector
    max_pages: int = 5

class ScraperConfig(BaseModel):
    name: str
    base_url: HttpUrl
    use_playwright: bool = False
    wait_for_selector: Optional[str] = None
    fields: List[DataField]
    pagination: Optional[Pagination] = None

# Essential for recursive Pydantic models
DataField.model_rebuild()