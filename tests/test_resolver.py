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