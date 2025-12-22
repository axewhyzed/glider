import re
from typing import List, Any, Dict, Optional
from urllib.parse import urljoin
from engine.schemas import Transformer, TransformerType

def apply_transformers(text: Optional[str], transformers: List[Transformer], base_url: Optional[str] = None) -> Any:
    """
    Applies a chain of cleaning operations to the raw text.
    
    Args:
        text: Raw text to transform
        transformers: List of transformations to apply
        base_url: Base URL for to_absolute_url transformer (optional)
    """
    if not text:
        return None
        
    current_value = text
    
    for t in transformers:
        # 1. STRIP
        if t.name == TransformerType.STRIP:
            if isinstance(current_value, str):
                current_value = current_value.strip()
            
        # 2. TO_FLOAT (Enhanced for Locale)
        elif t.name == TransformerType.TO_FLOAT:
            try:
                val_str = str(current_value).strip()
                decimal_sep = "."
                thousand_sep = ","
                
                if t.args and len(t.args) >= 1:
                    decimal_sep = t.args[0]
                if t.args and len(t.args) >= 2:
                    thousand_sep = t.args[1]

                val_str = val_str.replace(thousand_sep, "")
                val_str = val_str.replace(decimal_sep, ".")
                
                clean = re.sub(r'[^\d.-]', '', val_str)
                current_value = float(clean)
            except ValueError:
                current_value = 0.0
                
        # 3. TO_INT
        elif t.name == TransformerType.TO_INT:
            try:
                clean = re.sub(r'[^\d]', '', str(current_value))
                current_value = int(clean)
            except ValueError:
                current_value = 0
                
        # 4. REGEX
        elif t.name == TransformerType.REGEX:
            if t.args and len(t.args) > 0:
                pattern = t.args[0]
                match = re.search(pattern, str(current_value))
                if match:
                    current_value = match.group(1) if match.groups() else match.group(0)
                else:
                    current_value = None

        # 5. REPLACE
        elif t.name == TransformerType.REPLACE:
            if t.args and len(t.args) >= 2:
                current_value = str(current_value).replace(t.args[0], t.args[1])
        
        # 6. TO_ABSOLUTE_URL (M1 FIX)
        elif t.name == TransformerType.TO_ABSOLUTE_URL:
            if base_url and isinstance(current_value, str):
                current_value = urljoin(base_url, current_value)
            else:
                # If no base_url provided, keep as-is
                pass
    
    return current_value

def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '_') -> Dict[str, Any]:
    """
    Recursively flattens a nested dictionary.
    { "product": { "price": 10 } } -> { "product_price": 10 }
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)
