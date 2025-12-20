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
        # 1. STRIP
        if t.name == TransformerType.STRIP:
            if isinstance(current_value, str):
                current_value = current_value.strip()
            
        # 2. TO_FLOAT (Enhanced for Locale)
        elif t.name == TransformerType.TO_FLOAT:
            try:
                val_str = str(current_value).strip()
                
                # Check for custom separators in args: [decimal_sep, thousand_sep]
                # Default: decimal='.', thousand=',' (US/UK)
                decimal_sep = "."
                thousand_sep = ","
                
                if t.args and len(t.args) >= 1:
                    decimal_sep = t.args[0]
                if t.args and len(t.args) >= 2:
                    thousand_sep = t.args[1]

                # Remove thousand separators
                val_str = val_str.replace(thousand_sep, "")
                # Replace decimal separator with dot (Python standard)
                val_str = val_str.replace(decimal_sep, ".")
                
                # Clean remaining non-numeric chars (except dot and minus)
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
    
    return current_value