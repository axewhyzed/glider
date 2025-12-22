from lxml import html as lxml_html
from typing import Any, List, Optional
from engine.schemas import DataField, SelectorType
from engine.utils import apply_transformers

class HtmlResolver:
    """
    Parses HTML and resolves DataFields using CSS/XPath selectors.
    Strictly uses the normalized 'selectors' list.
    """
    def __init__(self, html_content: str):
        self.tree = lxml_html.fromstring(html_content)

    def resolve_field(self, field: DataField) -> Any:
        """
        Resolves a single field.
        If field.is_list=True, returns a list of results.
        Otherwise, returns the first match.
        """
        results = []

        # STABILITY: We only look at 'selectors'. The shorthand 'selector'
        # was merged into this list by the Schema Validator.
        for selector in field.selectors:
            found_elements = self._select_elements(self.tree, selector.type, selector.value)
            
            if found_elements:
                for el in found_elements:
                    extracted_val = self._extract_value(el, field)
                    if extracted_val is not None:
                        results.append(extracted_val)
                
                # If we found data with this selector, we stop (Priority Order)
                if results:
                    break
        
        # Handle Children (Nested Scraping)
        if field.children and results:
             # We need to resolve children against the elements found, not the extracted strings.
             # This requires re-selecting or passing elements.
             # For the sake of this logic, we assume results are elements if children exist.
             # However, _extract_value returns strings usually. 
             # We need to ensure we pass elements for child resolution.
             # Note: logic inside _extract_value handles this return type.
             return self._resolve_children(field, results) 
        
        if field.is_list:
            return results
        return results[0] if results else None

    def _select_elements(self, element, type_: SelectorType, value: str) -> List[Any]:
        try:
            if type_ == SelectorType.CSS:
                return element.cssselect(value)
            elif type_ == SelectorType.XPATH:
                return element.xpath(value)
        except Exception:
            return []
        return []

    def _extract_value(self, element, field: DataField) -> Any:
        """Extracts text or attribute, applying transformers."""
        # If we have children, we return the element itself to process sub-fields
        if field.children:
            return element
            
        val = ""
        if field.attribute:
            val = element.get(field.attribute, "")
        else:
            val = element.text_content()
            
        return apply_transformers(val, field.transformers)

    def _resolve_children(self, parent_field: DataField, elements: List[Any]) -> Any:
        """Process nested fields for each parent element found."""
        extracted_data = []
        for el in elements:
            row_data = {}
            # FIX: Explicitly handle None for Pylance safety
            children = parent_field.children or []
            for child in children:
                child_val = self._resolve_child_field(el, child)
                row_data[child.name] = child_val
            extracted_data.append(row_data)
            
        if parent_field.is_list:
            return extracted_data
        return extracted_data[0] if extracted_data else None

    def _resolve_child_field(self, parent_element, field: DataField) -> Any:
        """Similar to resolve_field but scoped to a parent element."""
        results = []
        for selector in field.selectors:
            found = self._select_elements(parent_element, selector.type, selector.value)
            for item in found:
                val = self._extract_value(item, field)
                if val is not None:
                    results.append(val)
            if results: break
            
        if field.children and results:
             return self._resolve_children(field, results)

        if field.is_list:
            return results
        return results[0] if results else None
    
    def get_attribute(self, selector_obj, attribute: str) -> Optional[str]:
        """Helper for pagination to quickly get an attribute."""
        elements = self._select_elements(self.tree, selector_obj.type, selector_obj.value)
        if elements:
            return elements[0].get(attribute)
        return None