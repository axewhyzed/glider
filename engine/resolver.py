from lxml import html as lxml_html
from typing import Any, List, Optional
from loguru import logger  # Added logger
from engine.schemas import DataField, SelectorType
from engine.utils import apply_transformers

class HtmlResolver:
    """
    Parses HTML and resolves DataFields using CSS/XPath selectors.
    """
    def __init__(self, html_content: str):
        self.tree = lxml_html.fromstring(html_content)

    def resolve_field(self, field: DataField) -> Any:
        results = []

        for selector in field.selectors:
            found_elements = self._select_elements(self.tree, selector.type, selector.value)
            
            if found_elements:
                for el in found_elements:
                    extracted_val = self._extract_value(el, field)
                    if extracted_val is not None:
                        results.append(extracted_val)
                
                if results:
                    break
        
        if field.children and results:
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
        except Exception as e:
            # FIX: Log the error so we know why extraction failed
            logger.error(f"Selector Error ({type_}: {value}): {e}")
            return []
        return []

    def _extract_value(self, element, field: DataField) -> Any:
        if field.children:
            return element
            
        val = ""
        if field.attribute:
            val = element.get(field.attribute, "")
        else:
            val = element.text_content()
            
        return apply_transformers(val, field.transformers)

    def _resolve_children(self, parent_field: DataField, elements: List[Any]) -> Any:
        extracted_data = []
        for el in elements:
            row_data = {}
            children = parent_field.children or []
            for child in children:
                child_val = self._resolve_child_field(el, child)
                row_data[child.name] = child_val
            extracted_data.append(row_data)
            
        if parent_field.is_list:
            return extracted_data
        return extracted_data[0] if extracted_data else None

    def _resolve_child_field(self, parent_element, field: DataField) -> Any:
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
        elements = self._select_elements(self.tree, selector_obj.type, selector_obj.value)
        if elements:
            return elements[0].get(attribute)
        return None