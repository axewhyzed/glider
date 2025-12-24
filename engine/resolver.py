import json
import re # <--- NEW
from jsonpath_ng import parse
from lxml import html as lxml_html
from typing import Any, List, Optional
from loguru import logger
from engine.schemas import DataField, SelectorType
from engine.utils import apply_transformers

class JsonResolver:
    """
    Parses JSON content and resolves DataFields using JSONPath.
    """
    def __init__(self, content: str):
        self.raw_content = content # <--- Keep raw content for Regex
        try:
            self.data = json.loads(content)
        except json.JSONDecodeError:
            self.data = {}
            logger.error("❌ Failed to parse JSON content")

    def resolve_field(self, field: DataField, context: Any = None) -> Any:
        current_data = context if context is not None else self.data
        results = []

        for selector in field.selectors:
            # [NEW] Handle Raw Regex Selector
            if selector.type == SelectorType.REGEX:
                try:
                    # Find all unique matches in the raw content
                    matches = list(set(re.findall(selector.value, self.raw_content)))
                    results.extend(matches)
                except Exception as e:
                    logger.warning(f"Regex Error ({selector.value}): {e}")
            
            # Handle JSONPath
            elif selector.type == SelectorType.JSON:
                try:
                    jsonpath_expr = parse(selector.value)
                    matches = jsonpath_expr.find(current_data)
                    results.extend([match.value for match in matches])
                except Exception as e:
                    logger.warning(f"JSONPath Error ({selector.value}): {e}")

        # Handle Children (Recursive)
        if field.children and results:
            return self._resolve_children(field, results)

        if field.is_list:
            return results
        
        # Apply transformers to single result
        val = results[0] if results else None
        return apply_transformers(val, field.transformers)

    def _resolve_children(self, parent_field: DataField, items: List[Any]) -> Any:
        extracted_data = []
        for item in items:
            row_data = {}
            children = parent_field.children or []
            for child in children:
                child_val = self.resolve_field(child, context=item)
                row_data[child.name] = child_val
            extracted_data.append(row_data)

        if parent_field.is_list:
            return extracted_data
        return extracted_data[0] if extracted_data else None

    def get_attribute(self, selector_obj, attribute: str) -> Optional[str]:
        if selector_obj.type == SelectorType.JSON:
             try:
                jsonpath_expr = parse(selector_obj.value)
                matches = jsonpath_expr.find(self.data)
                if matches:
                    return str(matches[0].value)
             except Exception:
                 pass
        return None

class HtmlResolver:
    """
    Parses HTML and resolves DataFields using CSS/XPath selectors.
    """
    def __init__(self, html_content: str):
        self.raw_content = html_content # <--- Keep raw
        self.tree = lxml_html.fromstring(html_content)

    def resolve_field(self, field: DataField) -> Any:
        results = []

        for selector in field.selectors:
            # [NEW] Handle Raw Regex Selector
            if selector.type == SelectorType.REGEX:
                try:
                    matches = list(set(re.findall(selector.value, self.raw_content)))
                    results.extend(matches)
                    if results: break # Prioritize finding something
                except Exception as e:
                    logger.warning(f"Regex Error ({selector.value}): {e}")
                continue

            # Standard Selectors
            found_elements = self._select_elements(self.tree, selector.type, selector.value)
            if found_elements:
                for el in found_elements:
                    extracted_val = self._extract_value(el, field)
                    if extracted_val is not None:
                        results.append(extracted_val)
                if results: break
        
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
            logger.error(f"Selector Error ({type_}: {value}): {e}")
            return []
        return []

    def _extract_value(self, element, field: DataField) -> Any:
        if field.children: return element
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
        if parent_field.is_list: return extracted_data
        return extracted_data[0] if extracted_data else None

    def _resolve_child_field(self, parent_element, field: DataField) -> Any:
        results = []
        for selector in field.selectors:
            found = self._select_elements(parent_element, selector.type, selector.value)
            for item in found:
                val = self._extract_value(item, field)
                if val is not None: results.append(val)
            if results: break
        if field.children and results: return self._resolve_children(field, results)
        if field.is_list: return results
        return results[0] if results else None
    
    def get_attribute(self, selector_obj, attribute: str) -> Optional[str]:
        elements = self._select_elements(self.tree, selector_obj.type, selector_obj.value)
        if elements: return elements[0].get(attribute)
        return None