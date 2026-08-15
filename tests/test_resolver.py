import pytest
from engine.resolver import HtmlResolver, JsonResolver
from engine.schemas import DataField, Selector, SelectorType

SAMPLE_HTML = """
<html>
    <body>
        <div class="product">
            <h1>Gaming Laptop</h1>
            <span class="price">$999.99</span>
            <ul class="specs">
                <li>16GB RAM</li>
                <li>512GB SSD</li>
            </ul>
        </div>
        <div class="product">
            <h1>Office Mouse</h1>
            <span class="price">$19.99</span>
        </div>
    </body>
</html>
"""

def test_css_selector_single():
    resolver = HtmlResolver(SAMPLE_HTML)
    field = DataField(
        name="title",
        selectors=[Selector(type=SelectorType.CSS, value="h1")]
    )
    # css_first returns the first match
    assert resolver.resolve_field(field) == "Gaming Laptop"

def test_xpath_selector_single():
    resolver = HtmlResolver(SAMPLE_HTML)
    field = DataField(
        name="price",
        selectors=[Selector(type=SelectorType.XPATH, value="//span[@class='price']")]
    )
    assert resolver.resolve_field(field) == "$999.99"

def test_list_extraction():
    resolver = HtmlResolver(SAMPLE_HTML)
    field = DataField(
        name="products",
        is_list=True,
        selectors=[Selector(type=SelectorType.CSS, value="div.product")],
        children=[
            DataField(name="name", selectors=[Selector(type=SelectorType.CSS, value="h1")])
        ]
    )
    results = resolver.resolve_field(field)
    assert len(results) == 2
    assert results[0]['name'] == "Gaming Laptop"
    assert results[1]['name'] == "Office Mouse"

def test_missing_element_returns_none():
    resolver = HtmlResolver(SAMPLE_HTML)
    field = DataField(
        name="missing",
        selectors=[Selector(type=SelectorType.CSS, value=".nonexistent")]
    )
    assert resolver.resolve_field(field) is None


# --- JsonResolver.get_attribute pagination tests (Bug 1 fix) ---

JSON_API_CONTENT = '{"data": {"after": "token_abc", "children": []}}'


def test_json_get_attribute_with_json_selector():
    """Explicit JSON selector type should resolve the pagination token."""
    resolver = JsonResolver(JSON_API_CONTENT)
    sel = Selector(type=SelectorType.JSON, value="data.after")
    assert resolver.get_attribute(sel, "href") == "token_abc"


def test_json_get_attribute_with_css_selector_shorthand():
    """
    Shorthand string selectors are normalised to CSS type by the schema.
    JsonResolver.get_attribute must still resolve them via JSONPath so that
    JSON-API pagination works when the user uses shorthand syntax.
    """
    resolver = JsonResolver(JSON_API_CONTENT)
    # Simulate what happens when pagination.selector is set via shorthand string:
    # the schema normalises it to SelectorType.CSS.
    css_sel = Selector(type=SelectorType.CSS, value="data.after")
    assert resolver.get_attribute(css_sel, "href") == "token_abc"


def test_json_get_attribute_missing_path_returns_none():
    resolver = JsonResolver(JSON_API_CONTENT)
    sel = Selector(type=SelectorType.JSON, value="data.nonexistent")
    assert resolver.get_attribute(sel, "href") is None


# --- JsonResolver multi-selector fallback tests ---

MULTI_SELECTOR_JSON = '{"v1": {"title": "Hello"}, "v2": {"name": "World"}}'


def test_json_first_selector_wins_when_it_matches():
    """First selector returns data; second selector must not be applied."""
    resolver = JsonResolver(MULTI_SELECTOR_JSON)
    field = DataField(
        name="title",
        selectors=[
            Selector(type=SelectorType.JSON, value="v1.title"),
            Selector(type=SelectorType.JSON, value="v2.name"),
        ],
    )
    assert resolver.resolve_field(field) == "Hello"


def test_json_fallback_to_second_selector_when_first_misses():
    """First selector returns nothing; second selector should be tried."""
    resolver = JsonResolver(MULTI_SELECTOR_JSON)
    field = DataField(
        name="title",
        selectors=[
            Selector(type=SelectorType.JSON, value="v1.nonexistent"),
            Selector(type=SelectorType.JSON, value="v2.name"),
        ],
    )
    assert resolver.resolve_field(field) == "World"


def test_json_regex_first_selector_wins_when_it_matches():
    """First REGEX selector returns data; second selector must not be applied."""
    resolver = JsonResolver(MULTI_SELECTOR_JSON)
    field = DataField(
        name="greeting",
        selectors=[
            Selector(type=SelectorType.REGEX, value=r'"title":\s*"([^"]+)"'),
            Selector(type=SelectorType.REGEX, value=r'"name":\s*"([^"]+)"'),
        ],
    )
    result = resolver.resolve_field(field)
    assert result == "Hello"


def test_json_regex_fallback_to_second_selector_when_first_misses():
    """First REGEX selector returns nothing; second should be tried."""
    resolver = JsonResolver(MULTI_SELECTOR_JSON)
    field = DataField(
        name="greeting",
        selectors=[
            Selector(type=SelectorType.REGEX, value=r'"nomatch":\s*"([^"]+)"'),
            Selector(type=SelectorType.REGEX, value=r'"name":\s*"([^"]+)"'),
        ],
    )
    result = resolver.resolve_field(field)
    assert result == "World"


# --- Selector compile cache tests (P6.3) ---

def test_jsonpath_cache_returns_compiled_expr():
    from engine.resolver import _compile_jsonpath
    first = _compile_jsonpath("data.after")
    second = _compile_jsonpath("data.after")
    assert first is second


def test_regex_cache_returns_compiled_pattern():
    from engine.resolver import _compile_regex
    first = _compile_regex(r"Order #(\d+)")
    second = _compile_regex(r"Order #(\d+)")
    assert first is second


def test_cached_compile_still_resolves_correctly():
    resolver = JsonResolver('{"data": {"after": "tok"}}')
    sel = Selector(type=SelectorType.JSON, value="data.after")
    assert resolver.get_attribute(sel, "href") == "tok"


def test_compile_cache_bounded():
    from engine.resolver import _compile_regex
    _compile_regex.cache_clear()
    for i in range(600):
        _compile_regex(f"pattern-{i}")
    assert _compile_regex.cache_info().currsize <= 512
    _compile_regex.cache_clear()


def test_no_job_state_in_compile_cache():
    """Compiled expressions are stateless: same input, same object, no bound results."""
    from engine.resolver import _compile_jsonpath
    first = _compile_jsonpath("$.items[*]")
    second = _compile_jsonpath("$.items[*]")
    assert first is second
    # Cache hit does not change resolution
    resolver = JsonResolver('{"items": [{"v": 1}]}')
    sel = Selector(type=SelectorType.JSON, value="$.items[*].v")
    assert resolver.resolve_field(DataField(name="v", selectors=[sel], is_list=True)) == [1]