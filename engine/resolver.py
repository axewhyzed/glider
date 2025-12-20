from typing import List, Optional, Any, Union, Dict
from selectolax.lexbor import LexborHTMLParser, LexborNode
from lxml import html as lxml_html
from engine.schemas import DataField, Selector, SelectorType
# NEW IMPORT
from engine.utils import apply_transformers

class HtmlResolver:
    def __init__(self, html_content: str):
        self.raw_html = html_content
        self.parser = LexborHTMLParser(self.raw_html)
        self._lxml_tree = None

    @property
    def lxml_tree(self):
        if self._lxml_tree is None:
            self._lxml_tree = lxml_html.fromstring(self.raw_html)
        return self._lxml_tree

    def resolve_field(self, field: DataField, context: Any = None) -> Any:
        node = context if context else self.parser.root

        if field.is_list:
            return self._extract_list(node, field)
        else:
            return self._extract_single(node, field)

    def _extract_single(self, node: Any, field: DataField) -> Any:
        element = self._find_element(node, field.selectors)
        
        if not element:
            return None

        # Recursion for nested objects
        if field.children:
            result = {}
            for child in field.children:
                result[child.name] = self.resolve_field(child, context=element)
            return result
        
        # Base Case: Extract Text + Transform
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

    # --- Low Level Helpers ---

    def _find_element(self, node: Any, selectors: List[Selector]) -> Any:
        for s in selectors:
            if s.type == SelectorType.CSS:
                if hasattr(node, 'css_first'):
                    res = node.css_first(s.value)
                    if res: return res
        return None

    def _find_elements(self, node: Any, selectors: List[Selector]) -> List[Any]:
        for s in selectors:
            if s.type == SelectorType.CSS:
                if hasattr(node, 'css'):
                    res = node.css(s.value)
                    if res: return res
        return []

    def _get_text(self, element: Any) -> str:
        if hasattr(element, 'text'):
            return element.text(strip=True)
        return str(element)

    def get_attribute(self, selector: Selector, attribute: str) -> Optional[str]:
        if selector.type == SelectorType.CSS:
            if self.parser.root:
                element = self.parser.root.css_first(selector.value)
                if element:
                    return element.attributes.get(attribute)
        return None