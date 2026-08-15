import pytest

from engine.resolver import HtmlResolver, JsonResolver, ResolverParseError
from engine.schemas import DataField, ScraperConfig, Selector, SelectorType
from engine.scraper import ScraperEngine
from engine.validation import validate_config_data


def test_invalid_json_is_a_parse_failure():
    with pytest.raises(ResolverParseError):
        JsonResolver("{not-json")


def test_null_json_cursor_stops_pagination():
    resolver = JsonResolver('{"data": {"after": null}}')
    selector = Selector(type=SelectorType.JSON, value="data.after")
    assert resolver.get_attribute(selector, "href") is None


def test_json_regex_uses_nested_context():
    resolver = JsonResolver('{"items": [{"value": "one"}, {"value": "two"}]}')
    field = DataField(
        name="value",
        selectors=[Selector(type=SelectorType.REGEX, value=r'"value"\s*:\s*"([^"]+)"')],
    )
    assert resolver.resolve_field(field, context={"value": "two"}) == "two"


def test_nested_html_regex_selector_uses_parent_element():
    resolver = HtmlResolver('<div class="item"><span>SKU-42</span></div>')
    field = DataField(
        name="items",
        is_list=True,
        selectors=[Selector(type=SelectorType.CSS, value="div.item")],
        children=[
            DataField(
                name="sku",
                selectors=[Selector(type=SelectorType.REGEX, value=r"SKU-\d+")],
            )
        ],
    )
    assert resolver.resolve_field(field) == [{"sku": "SKU-42"}]


@pytest.mark.asyncio
async def test_all_falsy_record_is_not_dropped(tmp_path):
    config = ScraperConfig(name="falsy", base_url="https://example.com", fields=[])
    engine = ScraperEngine(config)
    engine.bloom_path = tmp_path / "dedupe.bloom"
    engine.batch_size = 1
    captured = []

    async def capture(value):
        captured.append(value)

    engine.output_callback = capture
    await engine._merge_data({"score": 0, "available": False, "description": None})
    assert captured == [{"items": [{"score": 0, "available": False, "description": None}]}]


def test_semantic_validation_catches_bad_delay_and_follow_url():
    result = validate_config_data(
        {
            "name": "bad",
            "base_url": "https://example.com",
            "min_delay": 5,
            "max_delay": 1,
            "fields": [
                {
                    "name": "links",
                    "selector": "a",
                    "follow_url": True,
                }
            ],
        }
    )
    assert not result.valid
    messages = " ".join(issue.message for issue in result.issues)
    assert "min_delay" in messages or "less than or equal" in messages
    assert "nested_fields" in messages


def test_semantic_validation_reports_all_mode_errors():
    """Multiple independent violations surface together, not first-only."""
    result = validate_config_data(
        {
            "name": "multi",
            "mode": "list",  # requires start_urls
            "start_urls": [],
            "fields": [
                {
                    "name": "links",
                    "selector": "a",
                    "follow_url": True,  # requires nested_fields
                }
            ],
        }
    )
    assert not result.valid
    messages = " ".join(issue.message for issue in result.issues)
    assert "start_urls" in messages
    assert "nested_fields" in messages


def test_semantic_validation_delay_issue_path():
    result = validate_config_data(
        {
            "name": "delay",
            "base_url": "https://example.com",
            "min_delay": 5,
            "max_delay": 1,
            "fields": [],
        }
    )
    paths = [issue.path for issue in result.issues]
    assert "min_delay" in paths


def test_max_depth_is_configurable():
    config = ScraperConfig(
        name="depth",
        base_url="https://example.com",
        max_depth=0,
        fields=[],
    )
    assert config.max_depth == 0


# --- Extraction validation (P6.2) ---

@pytest.mark.asyncio
async def test_min_records_default_disabled():
    config = ScraperConfig(name="v", base_url="https://example.com", fields=[])
    assert config.validation.min_records_per_page == 0


@pytest.mark.asyncio
async def test_min_records_violation_fails_page(tmp_path):
    from engine.schemas import ExtractionValidation
    config = ScraperConfig(
        name="v",
        base_url="https://example.com",
        fields=[],
        validation=ExtractionValidation(min_records_per_page=3, fail_on_empty=True),
    )
    engine = ScraperEngine(config)
    engine.bloom_path = tmp_path / "b.bloom"
    failure = engine._validate_extraction({"books": [{"t": "one"}]})
    assert failure == "validation_error"


@pytest.mark.asyncio
async def test_required_field_missing_fails(tmp_path):
    from engine.schemas import ExtractionValidation
    config = ScraperConfig(
        name="v",
        base_url="https://example.com",
        fields=[],
        validation=ExtractionValidation(required_fields=["title"], fail_on_empty=True),
    )
    engine = ScraperEngine(config)
    engine.bloom_path = tmp_path / "b.bloom"
    assert engine._validate_extraction({"books": []}) == "validation_error"
    assert engine._validate_extraction({"title": "ok"}) is None


@pytest.mark.asyncio
async def test_soft_mode_warns_but_continues(tmp_path):
    from engine.schemas import ExtractionValidation
    config = ScraperConfig(
        name="v",
        base_url="https://example.com",
        fields=[],
        validation=ExtractionValidation(min_records_per_page=5, fail_on_empty=False),
    )
    engine = ScraperEngine(config)
    engine.bloom_path = tmp_path / "b.bloom"
    assert engine._validate_extraction({"books": [{"t": "one"}]}) is None  # soft mode
