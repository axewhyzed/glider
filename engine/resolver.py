from typing import List, Optional, Any, Union, Dict
from selectolax.lexbor import LexborHTMLParser, LexborNode
from lxml import html as lxml_html
from engine.schemas import DataField, Selector, SelectorType

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
        """
        Recursive resolver. 
        If 'children' exists, it returns a Dict (nested object).
        If 'children' is None, it returns a value (str/int/float).
        """
        # Default to root node if no context provided
        node = context if context else self.parser.root

        if field.is_list:
            return self._extract_list(node, field)
        else:
            return self._extract_single(node, field)

    def _extract_single(self, node: Any, field: DataField) -> Any:
        """Finds ONE element. If it has children, recurse. Else, return text."""
        element = self._find_element(node, field.selectors)
        
        if not element:
            return None

        # RECURSION: If this field has children, we don't extract text. 
        # We treat this element as the new "root" for its children.
        if field.children:
            result = {}
            for child in field.children:
                result[child.name] = self.resolve_field(child, context=element)
            return result
        
        # STOPPING CONDITION: No children? Extract text.
        return self._get_text(element)

    def _extract_list(self, node: Any, field: DataField) -> List[Any]:
        """Finds MANY elements. Iterates over them."""
        elements = self._find_elements(node, field.selectors)
        results = []

        for el in elements:
            if field.children:
                # For each item in the list, resolve its children (e.g., Title, Price)
                row_data = {}
                for child in field.children:
                    row_data[child.name] = self.resolve_field(child, context=el)
                results.append(row_data)
            else:
                results.append(self._get_text(el))
        
        return results

    # --- Low Level Helpers ---

    def _find_element(self, node: Any, selectors: List[Selector]) -> Any:
        """Try selectors until one works. Return the Node object (not text)."""
        for s in selectors:
            if s.type == SelectorType.CSS:
                # Only run CSS if the node supports it (LexborNode)
                if hasattr(node, 'css_first'):
                    res = node.css_first(s.value)
                    if res: return res
            elif s.type == SelectorType.XPATH:
                # XPath logic (requires full tree usually, simplistic implementation)
                # Note: Mixing scoped Lexbor nodes with LXML xpath is complex. 
                # For MVP, we assume XPath uses the global tree or LXML elements.
                pass 
        return None

    def _find_elements(self, node: Any, selectors: List[Selector]) -> List[Any]:
        """Try selectors until one works. Return List of Nodes."""
        for s in selectors:
            if s.type == SelectorType.CSS:
                if hasattr(node, 'css'):
                    res = node.css(s.value)
                    if res: return res
        return []

    def _get_text(self, element: Any) -> str:
        """Extract text from a LexborNode."""
        if hasattr(element, 'text'):
            return element.text(strip=True)
        return str(element)