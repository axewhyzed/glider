import json
import os
import re
from pathlib import Path
from typing import Any, List, Union, Dict
from engine.schemas import TransformerType

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
                value = float(value)
            elif name == TransformerType.TO_INT:
                value = int(float(value)) # Handle "12.0" -> 12
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
            # If transformation fails, keep original value or None? 
            # Usually better to return None or log error. 
            # For resilience, we keep the value but maybe it's wrong type.
            pass
            
    return value

def load_config(path: str) -> Dict[str, Any]:
    """Loads JSON config with Environment Variable expansion."""
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Expand ${VAR} or $VAR
    # Matches ${VAR} or $VAR
    pattern = re.compile(r'\$\{([^}]+)\}|\$([a-zA-Z0-9_]+)')
    
    def replace_env(match):
        var_name = match.group(1) or match.group(2)
        return os.environ.get(var_name, match.group(0)) # Return original if not found
        
    expanded_content = pattern.sub(replace_env, content)
    return json.loads(expanded_content)