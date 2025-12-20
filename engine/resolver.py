from typing import List, Optional, Any
from selectolax.lexbor import LexborHTMLParser
from lxml import html as lxml_html
from engine.schemas import DataField, Selector, SelectorType
from engine.utils import apply_transformers

class HtmlResolver:
    """
    Parses HTML using Selectolax (CSS) OR lxml (XPath) with lazy loading.
    """
    def __init__(self, html_content: str):
        self.raw_html = html_content
        self._parser = None
        self._lxml_tree = None

    @property
    def parser(self):
        """Lazy load Selectolax only if CSS is requested."""
        if self._parser is None:
            self._parser = LexborHTMLParser(self.raw_html)
        return self._parser

    @property
    def lxml_tree(self):
        """Lazy load lxml only if XPath is requested."""
        if self._lxml_tree is None:
            self._lxml_tree = lxml_html.fromstring(self.raw_html)
        return self._lxml_tree

    def resolve_field(self, field: DataField, context: Any = None) -> Any:
        node = context 
        if field.is_list:
            return self._extract_list(node, field)
        else:
            return self._extract_single(node, field)

    def _extract_single(self, node: Any, field: DataField) -> Any:
        element = self._find_element(node, field.selectors)
        if not element:
            return None

        if field.children:
            result = {}
            for child in field.children:
                result[child.name] = self.resolve_field(child, context=element)
            return result
        
        raw_text = self._get_text(element)
        return apply_transformers(raw_text, field.transformers)

    def _extract_list(self, node: Any, field: DataField) -> List[Any]:
        elements = self._find_elements(node, field.selectors)
        results = []
        for el in elements:
            if field.children:
                row_data = {}
                for child in field.children:
                    row_data[child.name] = self.resolve_field(child, context=el)
                results.append(row_data)
            else:
                raw_text = self._get_text(el)
                cleaned_text = apply_transformers(raw_text, field.transformers)
                results.append(cleaned_text)
        return results

    def _find_element(self, node: Any, selectors: List[Selector]) -> Any:
        for s in selectors:
            if s.type == SelectorType.CSS:
                current_node = node if node else self.parser.root
                if current_node and hasattr(current_node, 'css_first'):
                    res = current_node.css_first(s.value)
                    if res: return res
            elif s.type == SelectorType.XPATH:
                if node and hasattr(node, 'xpath'):
                    try:
                        results = node.xpath(s.value)
                        if results: return results[0]
                    except Exception: continue
                else:
                    try:
                        results = self.lxml_tree.xpath(s.value)
                        if results: return results[0]
                    except Exception: continue
        return None

    def _find_elements(self, node: Any, selectors: List[Selector]) -> List[Any]:
        for s in selectors:
            if s.type == SelectorType.CSS:
                current_node = node if node else self.parser.root
                if current_node and hasattr(current_node, 'css'):
                    res = current_node.css(s.value)
                    if res: return res
            elif s.type == SelectorType.XPATH:
                if node and hasattr(node, 'xpath'):
                    try:
                        results = node.xpath(s.value)
                        if results: return results
                    except Exception: continue
                else:
                    try:
                        results = self.lxml_tree.xpath(s.value)
                        if results: return results
                    except Exception: continue
        return []

    def _get_text(self, element: Any) -> str:
        if hasattr(element, 'text'):
            return element.text(strip=True)
        if hasattr(element, 'text_content'):
            return element.text_content().strip()
        return str(element).strip()

    def get_attribute(self, selector: Selector, attribute: str) -> Optional[str]:
        element = self._find_element(None, [selector])
        if element:
            if hasattr(element, 'attributes'): 
                return element.attributes.get(attribute)
            if hasattr(element, 'get'): 
                return element.get(attribute)
        return None