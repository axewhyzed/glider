from typing import List, Optional, Any, Dict, Literal
from enum import Enum
from pydantic import BaseModel, HttpUrl, Field, field_validator, model_validator
from dataclasses import dataclass

@dataclass
class StatsEvent:
    event_type: str
    count: int = 1
    metadata: Optional[Dict[str, Any]] = None

class SelectorType(str, Enum):
    CSS = "css"
    XPATH = "xpath"
    JSON = "json"
    REGEX = "regex"

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
    args: Optional[List[Any]] = Field(default_factory=list)
    
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
    duration: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_action_requirements(self) -> "Interaction":
        if self.type in {
            InteractionType.CLICK,
            InteractionType.FILL,
            InteractionType.PRESS,
            InteractionType.HOVER,
        } and not self.selector:
            raise ValueError(f"{self.type.value} interaction requires a selector")
        if self.type == InteractionType.KEY_PRESS and not self.value:
            raise ValueError("key interaction requires a value")
        return self

class DataField(BaseModel):
    name: str
    selector: Optional[Any] = Field(default=None, exclude=True) 
    selectors: List[Selector] = Field(default_factory=list)
    is_list: bool = False
    attribute: Optional[str] = None
    transformers: List[Transformer] = Field(default_factory=list)
    children: Optional[List['DataField']] = None
    
    # Nested Scraping Logic
    follow_url: bool = False
    nested_fields: Optional[List['DataField']] = None 
    
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
    query_param: str = "after"
    @field_validator('max_pages')
    @classmethod
    def check_max_pages(cls, v):
        if v < 1: raise ValueError('max_pages must be at least 1')
        return v

class AuthConfig(BaseModel):
    type: Literal["oauth_password", "bearer"] = "oauth_password"
    token_url: Optional[HttpUrl] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    scope: Optional[str] = "*"


class UrlPolicyConfig(BaseModel):
    """Outbound URL and SSRF policy."""

    allowed_domains: List[str] = Field(default_factory=list)
    allow_subdomains: bool = False
    allow_external_urls: bool = False
    allowed_schemes: List[str] = Field(default_factory=lambda: ["http", "https"])
    block_private_networks: bool = True
    resolve_dns: bool = True
    dns_failure_policy: Literal["allow", "deny"] = "deny"
    max_redirects: int = Field(default=5, ge=0, le=20)

    @field_validator("allowed_schemes")
    @classmethod
    def validate_schemes(cls, values: List[str]) -> List[str]:
        normalized = [value.lower() for value in values]
        if not normalized or any(value not in {"http", "https"} for value in normalized):
            raise ValueError("allowed_schemes may only contain http and https")
        return list(dict.fromkeys(normalized))

    @field_validator("allowed_domains")
    @classmethod
    def validate_domains(cls, values: List[str]) -> List[str]:
        """Normalize domains; allow leading '*.' wildcards only (no regex)."""
        normalized = []
        for value in values:
            domain = value.strip().lower().rstrip(".")
            if not domain:
                raise ValueError("allowed_domains entries may not be empty")
            wildcard = domain.startswith("*.")
            body = domain[2:] if wildcard else domain
            if not body or any(char in body for char in "/?#:") or "*" in body:
                raise ValueError(f"Invalid allowed domain: {value}")
            normalized.append(domain)
        return normalized


class RetryConfig(BaseModel):
    """Status-aware retry policy for transient network failures."""

    max_attempts: int = Field(default=3, ge=1, le=20)
    base_delay_seconds: float = Field(default=1.0, ge=0, le=300)
    max_delay_seconds: float = Field(default=30.0, ge=0, le=3600)
    retry_statuses: List[int] = Field(
        default_factory=lambda: [408, 425, 429, 500, 502, 503, 504]
    )
    retry_after_cap_seconds: float = Field(default=300.0, ge=0, le=86400)


class BrowserConfig(BaseModel):
    """Playwright safety and context lifecycle settings."""

    ignore_https_errors: bool = False
    context_max_requests: int = Field(default=50, ge=1, le=10000)
    proxy_rotation: Literal["per_context", "per_request"] = "per_context"


class DedupMode(str, Enum):
    NONE = "none"
    URL = "url"
    FIELDS = "fields"
    EXACT_HASH = "exact_hash"


class DedupConfig(BaseModel):
    """Deduplication policy (P7.1/P7.2)."""

    mode: DedupMode = DedupMode.EXACT_HASH
    capacity: int = Field(default=100_000, ge=1000, le=10_000_000)
    error_rate: float = Field(default=0.001, gt=0, lt=1)
    fields: List[str] = Field(default_factory=list)  # top-level fields for FIELDS mode
    exact_capacity: int = Field(default=100_000, ge=1000, le=10_000_000)

    @model_validator(mode="after")
    def validate_fields_mode(self) -> "DedupConfig":
        if self.mode == DedupMode.FIELDS and not self.fields:
            raise ValueError("dedup.fields must contain at least one field when mode is 'fields'")
        return self


class ExtractionValidation(BaseModel):
    """Post-extraction validation (P6.2)."""

    min_records_per_page: int = Field(default=0, ge=0)
    required_fields: List[str] = Field(default_factory=list)
    fail_on_empty: bool = False


class DebugSnapshotConfig(BaseModel):
    """Bounded debug snapshot policy (P7.5)."""

    # Failed bodies can contain credentials or personal data.  Operators must
    # explicitly opt in before persisting them to disk.
    enabled: bool = False
    max_files: int = Field(default=100, ge=0)
    max_bytes_per_file: int = Field(default=1_000_000, ge=0)
    max_total_bytes: int = Field(default=100_000_000, ge=0)


class ScraperConfig(BaseModel):
    name: str
    base_url: Optional[HttpUrl] = None
    mode: ScrapeMode = ScrapeMode.PAGINATION
    start_urls: Optional[List[HttpUrl]] = Field(default_factory=list)
    
    response_type: Literal["html", "json"] = "html"
    request_method: Literal["GET", "POST"] = "GET"
    request_body: Optional[Any] = None
    request_body_type: Literal["json", "form"] = "json"
    use_playwright: bool = False
    debug_mode: bool = False
    concurrency: int = 2
    rate_limit: int = 5
    request_timeout: int = Field(default=15, ge=1, le=3600)
    min_delay: float = 1
    max_delay: float = 3
    
    # Nested Scraping Limits
    max_nested_urls: int = Field(default=5, ge=1, le=100)
    max_depth: int = Field(default=2, ge=0, le=100)
    
    wait_for_selector: Optional[str] = None
    interactions: Optional[List[Interaction]] = Field(default_factory=list)
    interaction_failure_policy: Literal["warn", "fail"] = "warn"
    proxies: Optional[List[str]] = None
    headers: Optional[Dict[str, str]] = None
    cookies_file: Optional[str] = None 
    authentication: Optional[AuthConfig] = None
    
    respect_robots_txt: bool = False
    use_checkpointing: bool = False
    # How long a per-origin robots.txt parse is cached before re-fetching.
    robots_ttl_seconds: float = Field(default=3600.0, ge=0, le=86400)
    robots_failure_policy: Literal["allow", "deny"] = "allow"
    robots_max_origins: int = Field(default=1000, ge=1, le=100000)
    # Bounded in-memory failure ring (P7.4); failures are also streamed to disk.
    max_failed_entries: int = Field(default=1000, ge=1, le=100000)
    # Explicit record cardinality for pages containing multiple list fields.
    record_field: Optional[str] = None
    # Optional sitemap discovery roots for list-mode crawls.
    sitemap_urls: List[HttpUrl] = Field(default_factory=list)
    sitemap_max_urls: int = Field(default=10000, ge=1, le=1_000_000)
    sitemap_max_depth: int = Field(default=3, ge=0, le=20)
    sitemap_max_documents: int = Field(default=10000, ge=1, le=1_000_000)
    sitemap_max_queue: int = Field(default=10000, ge=1, le=1_000_000)
    sitemap_max_bytes: int = Field(default=10_000_000, ge=1024, le=100_000_000)
    per_domain_rate_limit: Optional[int] = Field(default=None, ge=1, le=100000)
    proxy_failure_threshold: int = Field(default=3, ge=1, le=100)
    proxy_cooldown_seconds: float = Field(default=60.0, ge=0, le=86400)

    # When response_type is "json" and follow_url is used, set this to True to
    # automatically append ".json" to child URLs that don't already end with it.
    # This is a Reddit-specific convention (e.g. /r/python/comments/xyz/ → .json).
    # Leave False for all other JSON APIs to avoid mangling URLs.
    append_json_suffix: bool = False
    fail_parent_on_nested_error: bool = True

    url_policy: UrlPolicyConfig = Field(default_factory=UrlPolicyConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    validation: ExtractionValidation = Field(default_factory=ExtractionValidation)
    debug_snapshots: DebugSnapshotConfig = Field(default_factory=DebugSnapshotConfig)

    fields: List[DataField]
    pagination: Optional[Pagination] = None
    
    @field_validator('concurrency', 'rate_limit')
    @classmethod
    def check_positive(cls, v):
        if v < 1: raise ValueError('Must be positive integer')
        return v

    @model_validator(mode='after')
    def check_delays(self) -> 'ScraperConfig':
        if self.min_delay > self.max_delay:
            raise ValueError("min_delay must be less than or equal to max_delay")
        return self

    @model_validator(mode='after')
    def check_mode_requirements(self) -> 'ScraperConfig':
        if self.mode == ScrapeMode.PAGINATION and not self.base_url:
            raise ValueError("'base_url' is required when mode is 'pagination'")
        if self.mode == ScrapeMode.LIST and not self.start_urls:
            if not self.sitemap_urls:
                raise ValueError("'start_urls' or 'sitemap_urls' must be non-empty when mode is 'list'")

        top_level_lists = [field.name for field in self.fields if field.is_list]
        if self.record_field and self.record_field not in {field.name for field in self.fields}:
            raise ValueError(f"record_field '{self.record_field}' is not a configured top-level field")
        if len(top_level_lists) > 1 and not self.record_field:
            # Keep legacy configurations valid while making the cardinality
            # choice explicit in validation output for new configurations.
            pass

        def validate_nested_fields(fields: List[DataField]) -> None:
            for field in fields:
                if field.follow_url and not field.nested_fields:
                    raise ValueError(
                        f"field '{field.name}' uses follow_url but has no nested_fields"
                    )
                validate_nested_fields(field.children or [])
                validate_nested_fields(field.nested_fields or [])

        validate_nested_fields(self.fields)
        return self

    @model_validator(mode="after")
    def check_browser_method(self) -> "ScraperConfig":
        if self.use_playwright and self.request_method != "GET":
            raise ValueError(
                "use_playwright supports only GET requests; use_playwright=false for POST requests"
            )
        return self

DataField.model_rebuild()
