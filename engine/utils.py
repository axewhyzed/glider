import re
from typing import List, Any, Dict, Optional
from engine.schemas import Transformer, TransformerType

def apply_transformers(text: Optional[str], transformers: List[Transformer]) -> Any:
    if not text: return None
    current_value = text
    
    for t in transformers:
        if t.name == TransformerType.STRIP and isinstance(current_value, str):
            current_value = current_value.strip()
        elif t.name == TransformerType.TO_FLOAT:
            try:
                val_str = str(current_value).strip()
                decimal_sep = t.args[0] if t.args and len(t.args) >= 1 else "."
                thousand_sep = t.args[1] if t.args and len(t.args) >= 2 else ","
                clean = re.sub(r'[^\d.-]', '', val_str.replace(thousand_sep, "").replace(decimal_sep, "."))
                current_value = float(clean)
            except ValueError: current_value = 0.0
        elif t.name == TransformerType.TO_INT:
            try: current_value = int(re.sub(r'[^\d]', '', str(current_value)))
            except ValueError: current_value = 0
        elif t.name == TransformerType.REGEX and t.args:
            match = re.search(t.args[0], str(current_value))
            current_value = match.group(1) if match and match.groups() else (match.group(0) if match else None)
        elif t.name == TransformerType.REPLACE and t.args and len(t.args) >= 2:
            current_value = str(current_value).replace(t.args[0], t.args[1])
            
    return current_value

def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '_') -> Dict[str, Any]:
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict): items.extend(flatten_dict(v, new_key, sep=sep).items())
        else: items.append((new_key, v))
    return dict(items)