from typing import List, Optional, Any
from selectolax.lexbor import LexborHTMLParser
from lxml import html as lxml_html
from engine.schemas import DataField, Selector, SelectorType
from engine.utils import apply_transformers

class HtmlResolver:
    """
    Parses HTML using Selectolax (CSS) with a lazy-loaded fallback to lxml (XPath).
    Supports both text content and attribute extraction.
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
        
        if element is None:
            return None

        # If field has children, recurse into nested structure
        if field.children:
            result = {}
            for child in field.children:
                result[child.name] = self.resolve_field(child, context=element)
            return result
        
        # Extract attribute or text based on field configuration
        if field.attribute:
            raw_value = self._get_attribute(element, field.attribute)
        else:
            raw_value = self._get_text(element)
        
        # Apply transformers to extracted value
        return apply_transformers(raw_value, field.transformers)

    def _extract_list(self, node: Any, field: DataField) -> List[Any]:
        elements = self._find_elements(node, field.selectors)
        results = []
        
        for el in elements:
            # If field has children, extract nested data
            if field.children:
                row_data = {}
                for child in field.children:
                    row_data[child.name] = self.resolve_field(child, context=el)
                results.append(row_data)
            else:
                # Extract attribute or text
                if field.attribute:
                    raw_value = self._get_attribute(el, field.attribute)
                else:
                    raw_value = self._get_text(el)
                
                # Apply transformers
                cleaned_value = apply_transformers(raw_value, field.transformers)
                results.append(cleaned_value)
        
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
        """
        Extract text content from an element.
        Handles both Selectolax and lxml elements.
        """
        # Selectolax: has callable .text() method
        if hasattr(element, 'text') and callable(element.text):
            return str(element.text(strip=True))
            
        # lxml: .text_content() gets inner text of element and children
        if hasattr(element, 'text_content'):
            return str(element.text_content().strip())
            
        # Fallback for lxml elements - direct text property
        if hasattr(element, 'text') and element.text:
            return str(element.text).strip()
            
        return str(element).strip()

    def _get_attribute(self, element: Any, attribute: str) -> str:
        """
        Extract attribute value from an element.
        Handles both Selectolax and lxml elements.
        
        Args:
            element: The HTML element
            attribute: Attribute name (e.g., 'href', 'src', 'data-id')
            
        Returns:
            Attribute value as string, or empty string if not found
        """
        # Selectolax: uses .attributes dictionary
        if hasattr(element, 'attributes'):
            value = element.attributes.get(attribute)
            return str(value) if value is not None else ""
        
        # lxml: uses .get() method
        if hasattr(element, 'get'):
            value = element.get(attribute)
            return str(value) if value is not None else ""
        
        # Fallback
        return ""

    def get_attribute(self, selector: Selector, attribute: str) -> Optional[str]:
        """
        Utility method to extract a single attribute value.
        Used primarily for pagination links.
        """
        element = self._find_element(None, [selector])
        if element:
            return self._get_attribute(element, attribute) or None
        return None
