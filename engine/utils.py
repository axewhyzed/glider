import re
from typing import List, Any
from engine.schemas import Transformer, TransformerType

def apply_transformers(text: str, transformers: List[Transformer]) -> Any:
    """
    Applies a chain of cleaning operations to the raw text.
    """
    if not text:
        return None
        
    current_value = text
    
    for t in transformers:
        # 1. STRIP (Trim whitespace)
        if t.name == TransformerType.STRIP:
            if isinstance(current_value, str):
                current_value = current_value.strip()
            
        # 2. TO_FLOAT (Extract price)
        elif t.name == TransformerType.TO_FLOAT:
            try:
                # Remove everything that isn't a digit or a dot (e.g. "£51.77" -> "51.77")
                clean = re.sub(r'[^\d.]', '', str(current_value))
                current_value = float(clean)
            except ValueError:
                current_value = 0.0 # Soft fail
                
        # 3. TO_INT (Extract count)
        elif t.name == TransformerType.TO_INT:
            try:
                # Remove non-digits
                clean = re.sub(r'[^\d]', '', str(current_value))
                current_value = int(clean)
            except ValueError:
                current_value = 0
                
        # 4. REGEX (Extract pattern)
        elif t.name == TransformerType.REGEX:
            # Config format: "args": ["(Start|Stop)"]
            if t.args and len(t.args) > 0:
                pattern = t.args[0]
                match = re.search(pattern, str(current_value))
                if match:
                    # If regex has a group (), return that. Else return full match.
                    current_value = match.group(1) if match.groups() else match.group(0)
                else:
                    current_value = None

        # 5. REPLACE (Simple text swap)
        elif t.name == TransformerType.REPLACE:
            # Config format: "args": ["Old", "New"]
            if t.args and len(t.args) >= 2:
                current_value = str(current_value).replace(t.args[0], t.args[1])
    
    return current_value