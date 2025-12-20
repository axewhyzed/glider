from typing import List, Optional, Any
from selectolax.lexbor import LexborHTMLParser
from lxml import html as lxml_html
from engine.schemas import DataField, Selector, SelectorType
from engine.utils import apply_transformers

class HtmlResolver:
    """
    Parses HTML using Selectolax (CSS) with a lazy-loaded fallback to lxml (XPath).
    """
    def __init__(self, html_content: str):
        self.raw_html = html_content
        self.parser = LexborHTMLParser(self.raw_html)
        self._lxml_tree = None

    @property
    def lxml_tree(self):
        """Lazy loads lxml only if XPath is actually requested."""
        if self._lxml_tree is None:
            self._lxml_tree = lxml_html.fromstring(self.raw_html)
        return self._lxml_tree

    def resolve_field(self, field: DataField, context: Any = None) -> Any:
        # Context usually is a LexborNode. For XPath, we assume global scope for now 
        # as mixing local Selectolax context with lxml is complex.
        node = context if context else self.parser.root

        if field.is_list:
            return self._extract_list(node, field)
        else:
            return self._extract_single(node, field)

    def _extract_single(self, node: Any, field: DataField) -> Any:
        element = self._find_element(node, field.selectors)
        
        if not element:
            return None

        # Recursion
        if field.children:
            result = {}
            for child in field.children:
                result[child.name] = self.resolve_field(child, context=element)
            return result
        
        # Base Case
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
                # Lexbor Logic
                if hasattr(node, 'css_first'):
                    res = node.css_first(s.value)
                    if res: return res
            elif s.type == SelectorType.XPATH:
                # LXML Logic (Fallback)
                try:
                    # Note: This ignores 'node' context and searches root for MVP
                    results = self.lxml_tree.xpath(s.value)
                    if results: return results[0]
                except Exception:
                    continue
        return None

    def _find_elements(self, node: Any, selectors: List[Selector]) -> List[Any]:
        for s in selectors:
            if s.type == SelectorType.CSS:
                if hasattr(node, 'css'):
                    res = node.css(s.value)
                    if res: return res
            elif s.type == SelectorType.XPATH:
                try:
                    results = self.lxml_tree.xpath(s.value)
                    if results: return results
                except Exception:
                    continue
        return []

    def _get_text(self, element: Any) -> str:
        # Handle Lexbor Node
        if hasattr(element, 'text'):
            return element.text(strip=True)
        # Handle LXML Element
        if hasattr(element, 'text_content'):
            return element.text_content().strip()
        return str(element).strip()

    def get_attribute(self, selector: Selector, attribute: str) -> Optional[str]:
        if selector.type == SelectorType.CSS:
            if self.parser.root:
                element = self.parser.root.css_first(selector.value)
                if element:
                    return element.attributes.get(attribute)
        elif selector.type == SelectorType.XPATH:
             try:
                results = self.lxml_tree.xpath(selector.value)
                if results:
                    return results[0].get(attribute)
             except Exception:
                 pass
        return None