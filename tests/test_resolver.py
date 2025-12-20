import pytest
from engine.resolver import HtmlResolver
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