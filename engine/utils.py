import json
import os
import re
from pathlib import Path
from typing import Any, List, Union, Dict
from engine.schemas import TransformerType

def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '_') -> Dict[str, Any]:
    """
    Flattens a nested dictionary into a single level with a separator.
    Used for CSV export of nested data structures.
    """
    items: List[tuple] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def apply_transformers(value: Any, transformers: List[Any]) -> Any:
    if value is None:
        return None
        
    for transformer in transformers:
        name = transformer.name
        args = transformer.args
        
        try:
            if name == TransformerType.STRIP:
                if isinstance(value, str):
                    value = value.strip()
            elif name == TransformerType.TO_FLOAT:
                # Basic cleaning for currency symbols and commas
                if isinstance(value, str):
                    value = value.replace('$', '').replace(',', '').strip()
                value = float(value)
            elif name == TransformerType.TO_INT:
                if isinstance(value, str):
                    # Extract digits only or handle float strings
                    digits = "".join(re.findall(r'\d+', value))
                    value = int(digits) if digits else 0
                else:
                    value = int(float(value))
            elif name == TransformerType.REGEX:
                if isinstance(value, str) and args:
                    pattern = args[0]
                    match = re.search(pattern, value)
                    if match:
                        value = match.group(1) if match.groups() else match.group(0)
                    else:
                        value = None
            elif name == TransformerType.REPLACE:
                if isinstance(value, str) and len(args) >= 2:
                    value = value.replace(args[0], args[1])
        except Exception:
            # For resilience, keep the value if transformation fails
            pass
            
    return value

def load_config(path: str) -> Dict[str, Any]:
    """Loads JSON config with Environment Variable expansion."""
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    pattern = re.compile(r'\$\{([^}]+)\}|\$([a-zA-Z0-9_]+)')
    
    def replace_env(match):
        var_name = match.group(1) or match.group(2)
        return os.environ.get(var_name, match.group(0))
        
    expanded_content = pattern.sub(replace_env, content)
    return json.loads(expanded_content)