# Transformers Reference

Transformers are post-processing functions applied to a field's extracted value.  They are defined in the `transformers` list of a `DataField` and run in order, left-to-right.  Any failing transformer is silently skipped and the current value is passed unchanged.

---

## Shorthand vs Full Object Syntax

```json
// Shorthand string (no arguments)
"transformers": ["strip", "to_int"]

// Full object (required when passing arguments)
"transformers": [{"name": "to_float", "args": [".", ","]}]

// Mixed
"transformers": ["strip", {"name": "replace", "args": ["€", ""]}, "to_float"]
```

---

## Available Transformers

### `strip`

Removes leading and trailing whitespace from a string.  A no-op on non-string values.

```json
"transformers": ["strip"]
```

**Examples:**

| Input | Output |
|---|---|
| `"  Hello World  "` | `"Hello World"` |
| `"\n  $9.99\t"` | `"$9.99"` |
| `null` | `null` |

---

### `to_float`

Converts a string to a floating-point number.

* Strips currency symbols, whitespace, and comma thousands separators automatically.
* Returns `0.0` on parse failure.
* Optionally accepts `args` for custom separators (e.g. European number formats).

```json
"transformers": [{"name": "to_float"}]

// European format: "1.234,56" → 1234.56
// args[0] = thousands separator, args[1] = decimal separator
"transformers": [{"name": "to_float", "args": [".", ","]}]
```

**Examples:**

| Input | Args | Output |
|---|---|---|
| `"$1,234.56"` | — | `1234.56` |
| `" €99.99 "` | — | `99.99` |
| `"€1.234,56"` | `[".", ","]` | `1234.56` |
| `"free"` | — | `0.0` |
| `"-12.5"` | — | `-12.5` |

---

### `to_int`

Extracts the **first contiguous digit group** from a string and converts it to an integer.

* Returns `0` when no digit group is found.
* Useful for extracting counts, quantities, or IDs embedded in text.

```json
"transformers": ["to_int"]
```

**Examples:**

| Input | Output |
|---|---|
| `"Order #12345"` | `12345` |
| `"12 items, 34 available"` | `12` (first group only) |
| `"No digits here"` | `0` |
| `42.7` | `42` |

---

### `regex`

Applies a Python regular expression to the value and returns either:
* The contents of **capture group 1** if a group is defined.
* The **full match** if no capture group is defined.
* `null` if there is no match.

```json
"transformers": [{"name": "regex", "args": ["pattern"]}]
```

**Examples:**

| Input | Pattern | Output |
|---|---|---|
| `"Order ID: ORD-9876"` | `"ORD-(\\d+)"` | `"9876"` |
| `"2025-01-15"` | `"(\\d{4})"` | `"2025"` |
| `"Price: $29.99"` | `"\\$([\\d.]+)"` | `"29.99"` |
| `"No match"` | `"\\d+"` | `null` |

---

### `replace`

Performs a simple string replacement.  Requires exactly two arguments: the substring to find and the replacement string.

```json
"transformers": [{"name": "replace", "args": ["old_value", "new_value"]}]
```

**Examples:**

| Input | Args | Output |
|---|---|---|
| `"€ 1.234,56"` | `["€ ", ""]` | `"1.234,56"` |
| `"10k views"` | `["k", "000"]` | `"10000 views"` |
| `"N/A"` | `["N/A", ""]` | `""` |

---

## Chaining Transformers

Transformers are applied sequentially.  Each transformer receives the output of the previous one as input.

### Example: Parse "10k" as integer 10000

```json
"transformers": [
  "strip",
  {"name": "replace", "args": ["k", "000"]},
  "to_int"
]
```

Steps: `"  10k  "` → `"10k"` → `"10000"` → `10000`

---

### Example: Extract and convert a price from an attribute

```json
{
  "name": "price",
  "selector": "span.price",
  "attribute": "data-price-eur",
  "transformers": [
    {"name": "replace", "args": [",", "."]},
    "to_float"
  ]
}
```

HTML: `<span class="price" data-price-eur="29,99">€29.99</span>`  
Output: `29.99`

---

### Example: Extract a numeric ID from a URL

```json
{
  "name": "product_id",
  "selector": "a.product",
  "attribute": "href",
  "transformers": [
    {"name": "regex", "args": ["/product/(\\d+)/"]}
  ]
}
```

Input: `"/shop/product/4567/details"`  
Output: `"4567"`

---

### Example: Parse a European-format price

```json
{
  "name": "price",
  "selector": "p.price",
  "transformers": [
    "strip",
    {"name": "to_float", "args": [".", ","]}
  ]
}
```

Input: `"€ 1.299,99"`  
Output: `1299.99`

---

## Behaviour on `null`

If the field's selector returns no match, the value passed to transformers is `null`.  All transformers immediately return `null` without processing when the input is `null`.

---

## Error Handling

If a transformer raises an exception (e.g. invalid regex pattern, wrong argument count), the exception is silently caught and the current value is passed unchanged to the next transformer.  This ensures partial transformation results are still captured rather than losing the field entirely.
