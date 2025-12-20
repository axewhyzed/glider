import pytest
from engine.schemas import Transformer, TransformerType
from engine.utils import apply_transformers

def test_strip_transformer():
    t = Transformer(name=TransformerType.STRIP)
    assert apply_transformers("  hello  ", [t]) == "hello"
    assert apply_transformers(None, [t]) is None

def test_to_float_standard():
    t = Transformer(name=TransformerType.TO_FLOAT)
    assert apply_transformers(" $1,234.56 ", [t]) == 1234.56
    assert apply_transformers("invalid", [t]) == 0.0

def test_to_float_european():
    # Test European format: 1.234,56 (dot thousands, comma decimal)
    t = Transformer(name=TransformerType.TO_FLOAT, args=[",", "."])
    assert apply_transformers("€1.234,56", [t]) == 1234.56

def test_to_int():
    t = Transformer(name=TransformerType.TO_INT)
    assert apply_transformers("Order #12345", [t]) == 12345
    assert apply_transformers("No digits", [t]) == 0

def test_regex_extraction():
    # Extract order ID
    t = Transformer(name=TransformerType.REGEX, args=[r"Order: (\d+)"])
    assert apply_transformers("Your Order: 9999 confirmed", [t]) == "9999"
    # No match returns None
    assert apply_transformers("No match here", [t]) is None

def test_chained_transformers():
    # Strip -> Replace -> To_Int
    t1 = Transformer(name=TransformerType.STRIP)
    t2 = Transformer(name=TransformerType.REPLACE, args=["k", "000"])
    t3 = Transformer(name=TransformerType.TO_INT)
    
    # "  10k  " -> "10k" -> "10000" -> 10000
    assert apply_transformers("  10k  ", [t1, t2, t3]) == 10000