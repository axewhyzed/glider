"""Structured configuration validation used by the CLI and tests."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonpath_ng import parse as parse_jsonpath
import lxml.etree as etree
from lxml.cssselect import CSSSelector
from pydantic import ValidationError

from engine.schemas import DataField, ScraperConfig, ScrapeMode, SelectorType
from engine.utils import load_config


@dataclass
class ValidationIssue:
    path: str
    message: str
    severity: str = "error"


@dataclass
class ValidationResult:
    config: Optional[ScraperConfig]
    raw_config: Optional[Dict[str, Any]]
    issues: List[ValidationIssue]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [asdict(issue) for issue in self.issues],
        }


def _validate_selector(selector_type: SelectorType, value: str, path: str, issues: List[ValidationIssue]) -> None:
    try:
        if selector_type == SelectorType.CSS:
            CSSSelector(value)
        elif selector_type == SelectorType.XPATH:
            etree.XPath(value)
        elif selector_type == SelectorType.JSON:
            parse_jsonpath(value)
        elif selector_type == SelectorType.REGEX:
            re.compile(value)
    except Exception as exc:
        issues.append(ValidationIssue(path, f"Invalid {selector_type.value} selector: {exc}"))


def _validate_fields(fields: List[DataField], prefix: str, issues: List[ValidationIssue]) -> None:
    for index, field in enumerate(fields):
        field_path = f"{prefix}[{index}]"
        for selector_index, selector in enumerate(field.selectors):
            _validate_selector(
                selector.type,
                selector.value,
                f"{field_path}.selectors[{selector_index}]",
                issues,
            )
        _validate_fields(field.children or [], f"{field_path}.children", issues)
        _validate_fields(field.nested_fields or [], f"{field_path}.nested_fields", issues)


def _validate_delay_pair(config: ScraperConfig, issues: List[ValidationIssue]) -> None:
    """min_delay <= max_delay (mirrors ScraperConfig.check_delays)."""
    if config.min_delay > config.max_delay:
        issues.append(
            ValidationIssue("min_delay", "min_delay must be less than or equal to max_delay")
        )


def _lenient_parse(raw_config: Dict[str, Any]) -> Optional[ScraperConfig]:
    """Build a ScraperConfig without running model validators.

    Used only to surface every cross-field issue at once; direct construction
    still enforces the rules via the model validators.
    """
    try:
        from engine.schemas import DataField, Pagination, Selector

        def lenient_field(data: Any) -> Any:
            if not isinstance(data, dict):
                return data
            field = DataField.model_construct(**{k: v for k, v in data.items() if k != "children"})
            if data.get("children"):
                field.children = [lenient_field(c) for c in data["children"]]
            if data.get("nested_fields"):
                field.nested_fields = [lenient_field(c) for c in data["nested_fields"]]
            return field

        raw = dict(raw_config)
        if isinstance(raw.get("fields"), list):
            raw["fields"] = [lenient_field(f) for f in raw["fields"]]
        if isinstance(raw.get("pagination"), dict):
            raw["pagination"] = Pagination.model_construct(**raw["pagination"])
        if isinstance(raw.get("selectors"), list):
            raw["selectors"] = [Selector.model_construct(**s) for s in raw["selectors"]]
        return ScraperConfig.model_construct(**raw)
    except Exception:
        return None


def _validate_mode_requirements(config: ScraperConfig, issues: List[ValidationIssue]) -> None:
    """Mode-required fields (mirrors ScraperConfig.check_mode_requirements)."""
    if config.mode == ScrapeMode.PAGINATION and not config.base_url:
        issues.append(
            ValidationIssue("base_url", "'base_url' is required when mode is 'pagination'")
        )
    if config.mode == ScrapeMode.LIST and not config.start_urls:
        issues.append(
            ValidationIssue(
                "start_urls", "'start_urls' must be a non-empty list when mode is 'list'"
            )
        )


def _validate_follow_url_fields(
    fields: List[DataField], prefix: str, issues: List[ValidationIssue]
) -> None:
    """follow_url requires nested_fields (mirrors schemas.check_mode_requirements)."""
    for index, field in enumerate(fields):
        path = f"{prefix}[{index}]"
        if field.follow_url and not field.nested_fields:
            issues.append(
                ValidationIssue(
                    f"{path}.nested_fields",
                    f"field '{field.name}' uses follow_url but has no nested_fields",
                )
            )
        _validate_follow_url_fields(field.children or [], f"{path}.children", issues)
        _validate_follow_url_fields(field.nested_fields or [], f"{path}.nested_fields", issues)


def _check_unknown_keys(raw_config: Dict[str, Any], issues: List[ValidationIssue]) -> None:
    """Warn on top-level keys Pydantic would silently ignore (P8.1)."""
    known = set(ScraperConfig.model_fields.keys())
    for key in raw_config:
        if key not in known:
            issues.append(
                ValidationIssue("config", f"Unknown configuration key: {key}", severity="warning")
            )


def validate_config_data(raw_config: Dict[str, Any], config_path: Optional[Path] = None) -> ValidationResult:
    issues: List[ValidationIssue] = []
    _check_unknown_keys(raw_config, issues)
    try:
        config = ScraperConfig(**raw_config)
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ())) or "config"
            issues.append(ValidationIssue(location, error.get("msg", "Invalid value")))
        # Pydantic's model_validator(mode='after') aborts on the FIRST cross-field error,
        # so a config with several violations reports only one. Re-run the semantic checks
        # against a lenient, validation-skipping parse so every violation surfaces.
        partial = _lenient_parse(raw_config)
        if partial is not None:
            _validate_delay_pair(partial, issues)
            _validate_mode_requirements(partial, issues)
            _validate_follow_url_fields(partial.fields, "fields", issues)
        return ValidationResult(None, raw_config, issues)
    except Exception as exc:
        return ValidationResult(None, raw_config, [ValidationIssue("config", str(exc))])

    _validate_fields(config.fields, "fields", issues)
    if config.cookies_file and config_path:
        cookie_path = Path(config.cookies_file)
        if not cookie_path.is_absolute():
            cookie_path = config_path.parent / cookie_path
        if not cookie_path.exists():
            issues.append(ValidationIssue("cookies_file", f"File does not exist: {cookie_path}"))

    auth = config.authentication
    if auth:
        required = {
            "oauth_password": ["token_url", "client_id", "client_secret", "username", "password"],
            "bearer": ["client_secret"],
        }[auth.type]
        for name in required:
            if not getattr(auth, name):
                issues.append(ValidationIssue(f"authentication.{name}", "This field is required"))

    for index, domain in enumerate(config.url_policy.allowed_domains):
        if not domain or any(char in domain for char in "/?#"):
            issues.append(ValidationIssue(f"url_policy.allowed_domains[{index}]", "Invalid hostname"))
    # Cross-field semantic checks. Pydantic's model_validator(mode='after') raises on the
    # first problem, so these mirror the same rules here to collect ALL issues at once.
    # Direct ScraperConfig() construction still enforces them via the model validators.
    _validate_delay_pair(config, issues)
    _validate_mode_requirements(config, issues)
    _validate_follow_url_fields(config.fields, "fields", issues)
    return ValidationResult(config, raw_config, issues)


def validate_config_file(path: str | Path) -> ValidationResult:
    config_path = Path(path)
    try:
        raw = load_config(str(config_path))
    except FileNotFoundError:
        return ValidationResult(None, None, [ValidationIssue("config", f"File not found: {config_path}")])
    except json.JSONDecodeError as exc:
        return ValidationResult(None, None, [ValidationIssue("json", f"Invalid JSON: {exc.msg}")])
    except Exception as exc:
        return ValidationResult(None, None, [ValidationIssue("config", str(exc))])
    if not isinstance(raw, dict):
        return ValidationResult(None, None, [ValidationIssue("config", "Root value must be a JSON object")])
    return validate_config_data(raw, config_path)
