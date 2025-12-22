# Attribute Extraction Guide

## Overview

Glider now supports extracting **HTML attributes** (href, src, data-*, class, etc.) in addition to text content. This is essential for scraping:
- Links (href)
- Images (src, alt)
- Videos (poster, data-video-id)
- Custom data attributes (data-*)
- CSS classes
- Any other HTML attribute

---

## Basic Usage

### Before (Text Only)

```json
{
  "name": "product_image",
  "selectors": [{"type": "css", "value": "img.product"}]
}
```
**Result**: Returns alt text or empty string

### After (Attribute Extraction)

```json
{
  "name": "product_image",
  "selectors": [{"type": "css", "value": "img.product"}],
  "attribute": "src"
}
```
**Result**: Returns image URL (e.g., `https://example.com/image.jpg`)

---

## Common Use Cases

### 1. Extract Links (href)

```json
{
  "name": "product_links",
  "is_list": true,
  "selectors": [{"type": "css", "value": "a.product-link"}],
  "attribute": "href"
}
```

**HTML Input**:
```html
<a class="product-link" href="/products/laptop-123">Gaming Laptop</a>
<a class="product-link" href="/products/mouse-456">Wireless Mouse</a>
```

**Output**:
```json
{
  "product_links": [
    "/products/laptop-123",
    "/products/mouse-456"
  ]
}
```

---

### 2. Extract Images (src)

```json
{
  "name": "product_images",
  "is_list": true,
  "selectors": [{"type": "css", "value": "div.gallery img"}],
  "attribute": "src"
}
```

**HTML Input**:
```html
<div class="gallery">
  <img src="https://cdn.example.com/img1.jpg" alt="Product 1">
  <img src="https://cdn.example.com/img2.jpg" alt="Product 2">
</div>
```

**Output**:
```json
{
  "product_images": [
    "https://cdn.example.com/img1.jpg",
    "https://cdn.example.com/img2.jpg"
  ]
}
```

---

### 3. Extract Data Attributes (data-*)

```json
{
  "name": "product_id",
  "selectors": [{"type": "css", "value": "div.product-card"}],
  "attribute": "data-product-id"
}
```

**HTML Input**:
```html
<div class="product-card" data-product-id="SKU-98765" data-category="electronics">
  Laptop XYZ
</div>
```

**Output**:
```json
{
  "product_id": "SKU-98765"
}
```

---

### 4. Extract Multiple Attributes from Same Element

```json
{
  "name": "products",
  "is_list": true,
  "selectors": [{"type": "css", "value": "div.item"}],
  "children": [
    {
      "name": "name",
      "selectors": [{"type": "css", "value": "h3"}]
    },
    {
      "name": "link",
      "selectors": [{"type": "css", "value": "a"}],
      "attribute": "href"
    },
    {
      "name": "image",
      "selectors": [{"type": "css", "value": "img"}],
      "attribute": "src"
    },
    {
      "name": "product_id",
      "selectors": [{"type": "css", "value": "."}],
      "attribute": "data-id",
      "comment": "'.' selects current context element"
    }
  ]
}
```

**HTML Input**:
```html
<div class="item" data-id="12345">
  <h3>Gaming Laptop</h3>
  <a href="/laptop">View Details</a>
  <img src="laptop.jpg">
</div>
```

**Output**:
```json
{
  "products": [
    {
      "name": "Gaming Laptop",
      "link": "/laptop",
      "image": "laptop.jpg",
      "product_id": "12345"
    }
  ]
}
```

---

### 5. Extract CSS Classes

```json
{
  "name": "rating",
  "selectors": [{"type": "css", "value": "span.stars"}],
  "attribute": "class"
}
```

**HTML Input**:
```html
<span class="stars rating-4-5">★★★★☆</span>
```

**Output**:
```json
{
  "rating": "stars rating-4-5"
}
```

---

### 6. Extract Video Metadata

```json
{
  "name": "video_info",
  "selectors": [{"type": "css", "value": "video"}],
  "children": [
    {
      "name": "poster_image",
      "selectors": [{"type": "css", "value": "."}],
      "attribute": "poster"
    },
    {
      "name": "video_src",
      "selectors": [{"type": "css", "value": "source"}],
      "attribute": "src"
    },
    {
      "name": "video_type",
      "selectors": [{"type": "css", "value": "source"}],
      "attribute": "type"
    }
  ]
}
```

---

## Advanced Features

### Combining with Transformers

You can apply transformers to extracted attributes:

```json
{
  "name": "price",
  "selectors": [{"type": "css", "value": "span.price"}],
  "attribute": "data-price",
  "transformers": [{"name": "to_float"}]
}
```

**HTML Input**:
```html
<span class="price" data-price="29.99">$29.99</span>
```

**Output**:
```json
{
  "price": 29.99
}
```

---

### XPath Support

Attribute extraction works with XPath selectors too:

```json
{
  "name": "social_links",
  "is_list": true,
  "selectors": [{"type": "xpath", "value": "//footer//a[@class='social']"}],
  "attribute": "href"
}
```

---

### Nested Attribute Extraction

```json
{
  "name": "articles",
  "is_list": true,
  "selectors": [{"type": "css", "value": "article"}],
  "children": [
    {
      "name": "title",
      "selectors": [{"type": "css", "value": "h2"}]
    },
    {
      "name": "author",
      "selectors": [{"type": "css", "value": "span.author"}],
      "children": [
        {
          "name": "name",
          "selectors": [{"type": "css", "value": "."}]
        },
        {
          "name": "profile_url",
          "selectors": [{"type": "css", "value": "a"}],
          "attribute": "href"
        }
      ]
    }
  ]
}
```

---

## Error Handling

### Missing Attributes

If an attribute doesn't exist, Glider returns an empty string:

```json
{
  "name": "alt_text",
  "selectors": [{"type": "css", "value": "img"}],
  "attribute": "alt"
}
```

**HTML Input**:
```html
<img src="image.jpg">
```

**Output**:
```json
{
  "alt_text": ""
}
```

---

### Case Sensitivity

Attribute names are **case-insensitive** and automatically normalized:

```json
{"attribute": "DATA-ID"}  // Converted to "data-id"
{"attribute": "Href"}      // Converted to "href"
```

---

## Performance Considerations

- **No performance penalty**: Attribute extraction is as fast as text extraction
- **Works with both Selectolax and lxml**: Unified API across parsers
- **Lazy evaluation**: Only extracts attributes when specified

---

## Common Patterns

### E-commerce Product Scraping

```json
{
  "name": "products",
  "is_list": true,
  "selectors": [{"type": "css", "value": "div.product"}],
  "children": [
    {"name": "title", "selectors": [{"type": "css", "value": "h3"}]},
    {"name": "url", "selectors": [{"type": "css", "value": "a"}], "attribute": "href"},
    {"name": "image", "selectors": [{"type": "css", "value": "img"}], "attribute": "src"},
    {"name": "price", "selectors": [{"type": "css", "value": "span.price"}], "transformers": [{"name": "to_float"}]},
    {"name": "sku", "selectors": [{"type": "css", "value": "."}], "attribute": "data-sku"}
  ]
}
```

---

### Social Media Links

```json
{
  "name": "social_media",
  "selectors": [{"type": "css", "value": "footer"}],
  "children": [
    {"name": "twitter", "selectors": [{"type": "css", "value": "a.twitter"}], "attribute": "href"},
    {"name": "facebook", "selectors": [{"type": "css", "value": "a.facebook"}], "attribute": "href"},
    {"name": "instagram", "selectors": [{"type": "css", "value": "a.instagram"}], "attribute": "href"}
  ]
}
```

---

### Image Gallery with Metadata

```json
{
  "name": "gallery",
  "is_list": true,
  "selectors": [{"type": "css", "value": "div.photo"}],
  "children": [
    {"name": "url", "selectors": [{"type": "css", "value": "img"}], "attribute": "src"},
    {"name": "alt", "selectors": [{"type": "css", "value": "img"}], "attribute": "alt"},
    {"name": "width", "selectors": [{"type": "css", "value": "img"}], "attribute": "width", "transformers": [{"name": "to_int"}]},
    {"name": "height", "selectors": [{"type": "css", "value": "img"}], "attribute": "height", "transformers": [{"name": "to_int"}]}
  ]
}
```

---

## Backward Compatibility

✅ **All existing configs work without changes**

- If `attribute` is not specified, defaults to text extraction
- No breaking changes to existing functionality
- Fully backward compatible with v2.5 and earlier

---

## FAQ

**Q: Can I extract multiple attributes from one element?**  
A: Yes! Use nested children with different `attribute` values on the same parent.

**Q: What if the attribute doesn't exist?**  
A: Returns empty string (`""`), not `null`.

**Q: Does this work with XPath?**  
A: Yes! Attribute extraction works with both CSS and XPath selectors.

**Q: Can I apply transformers to attributes?**  
A: Absolutely! Transformers work the same way as with text content.

**Q: Is there a performance impact?**  
A: No, attribute extraction is just as fast as text extraction.

---

## Example Output

Running the example config:

```bash
python main.py configs/attribute_extraction_example.json
```

**Sample Output**:
```json
{
  "books": [
    {
      "title": "A Light in the Attic",
      "title_link": "catalogue/a-light-in-the-attic_1000/index.html",
      "image_url": "media/cache/2c/da/2cdad67c44b002e7ead0cc35693c0e8b.jpg",
      "price": 51.77,
      "availability": "In stock",
      "rating": "star-rating Three"
    },
    {
      "title": "Tipping the Velvet",
      "title_link": "catalogue/tipping-the-velvet_999/index.html",
      "image_url": "media/cache/26/0c/260c6ae16bce31c8f8c95daddd9f4a1c.jpg",
      "price": 53.74,
      "availability": "In stock",
      "rating": "star-rating One"
    }
  ]
}
```

---

## Migration from v2.5

No changes needed! Your existing configs continue to work:

```json
// v2.5 config (still works)
{
  "name": "title",
  "selectors": [{"type": "css", "value": "h1"}]
}

// v2.6+ config (new feature)
{
  "name": "title_link",
  "selectors": [{"type": "css", "value": "h1 a"}],
  "attribute": "href"  // NEW!
}
```

---

## Summary

✅ **Fully backward compatible**  
✅ **Works with CSS and XPath**  
✅ **Supports all HTML attributes**  
✅ **Integrates with transformers**  
✅ **Zero performance overhead**  
✅ **Handles missing attributes gracefully**  

Attribute extraction unlocks powerful new use cases for Glider! 🚀
