# Usage Examples

A collection of ready-to-use configuration recipes for common scraping scenarios.

---

## 1. Static HTML Pagination — Books to Scrape

Scrape titles, prices, and availability from all pages of `books.toscrape.com`.

```json
{
  "name": "books_scraper",
  "base_url": "http://books.toscrape.com",
  "mode": "pagination",
  "rate_limit": 10,
  "concurrency": 4,
  "use_checkpointing": true,
  "fields": [
    {
      "name": "books",
      "selector": "article.product_pod",
      "is_list": true,
      "children": [
        {"name": "title",        "selector": "h3 a",                   "attribute": "title"},
        {"name": "price",        "selector": "p.price_color",          "transformers": ["strip", "to_float"]},
        {"name": "availability", "selector": "p.instock.availability",  "transformers": ["strip"]}
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "css", "value": "li.next a"},
    "max_pages": 50
  }
}
```

---

## 2. JavaScript-Rendered Site — Quotes to Scrape (Playwright)

Scrape a site that renders content with JavaScript.

```json
{
  "name": "quotes_js",
  "base_url": "http://quotes.toscrape.com/js/",
  "mode": "pagination",
  "use_playwright": true,
  "wait_for_selector": "div.quote",
  "fields": [
    {
      "name": "quotes",
      "selector": "div.quote",
      "is_list": true,
      "children": [
        {"name": "text",   "selector": "span.text",      "transformers": ["strip"]},
        {"name": "author", "selector": "small.author"},
        {"name": "tags",   "selector": "div.tags a.tag",  "is_list": true}
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "css", "value": "li.next a"},
    "max_pages": 10
  }
}
```

---

## 3. JSON API — Unauthenticated Reddit

Scrape public Reddit JSON feeds without authentication.

```json
{
  "name": "reddit_public",
  "base_url": "https://www.reddit.com",
  "mode": "list",
  "rate_limit": 2,
  "response_type": "json",
  "headers": {"User-Agent": "MyBot/1.0 (research project)"},
  "start_urls": [
    "https://www.reddit.com/r/technology/new.json",
    "https://www.reddit.com/r/python/hot.json"
  ],
  "fields": [
    {
      "name": "posts",
      "selectors": [{"type": "json", "value": "data.children[*].data"}],
      "is_list": true,
      "children": [
        {"name": "title",   "selectors": [{"type": "json", "value": "title"}]},
        {"name": "author",  "selectors": [{"type": "json", "value": "author"}]},
        {"name": "upvotes", "selectors": [{"type": "json", "value": "ups"}]},
        {"name": "url",     "selectors": [{"type": "json", "value": "url"}]}
      ]
    }
  ]
}
```

---

## 4. JSON API with OAuth — Reddit Authenticated

Scrape Reddit with OAuth 2.0 authentication and cursor-based pagination.

```json
{
  "name": "reddit_oauth",
  "base_url": "https://oauth.reddit.com/r/python/hot",
  "mode": "pagination",
  "response_type": "json",
  "rate_limit": 1,
  "headers": {"User-Agent": "MyBot/1.0 (by /u/yourusername)"},
  "authentication": {
    "type": "oauth_password",
    "token_url": "https://www.reddit.com/api/v1/access_token",
    "client_id": "${REDDIT_CLIENT_ID}",
    "client_secret": "${REDDIT_CLIENT_SECRET}",
    "username": "${REDDIT_USERNAME}",
    "password": "${REDDIT_PASSWORD}"
  },
  "fields": [
    {
      "name": "posts",
      "is_list": true,
      "selectors": [{"type": "json", "value": "data.children[*].data"}],
      "children": [
        {"name": "title",     "selectors": [{"type": "json", "value": "title"}]},
        {"name": "score",     "selectors": [{"type": "json", "value": "score"}]},
        {"name": "author",    "selectors": [{"type": "json", "value": "author"}]},
        {"name": "permalink", "selectors": [{"type": "json", "value": "permalink"}]}
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "json", "value": "data.after"},
    "max_pages": 10,
    "query_param": "after"
  }
}
```

Set credentials via environment variables:
```bash
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
export REDDIT_USERNAME=...
export REDDIT_PASSWORD=...
python main.py configs/reddit_oauth.json
```

---

## 5. Attribute Extraction — Images & Links

Extract image URLs and link hrefs alongside text content.

```json
{
  "name": "image_scraper",
  "base_url": "http://books.toscrape.com",
  "fields": [
    {
      "name": "books",
      "selector": "article.product_pod",
      "is_list": true,
      "children": [
        {"name": "title",      "selector": "h3 a",              "attribute": "title"},
        {"name": "detail_url", "selector": "h3 a",              "attribute": "href"},
        {"name": "image_url",  "selector": "div.image_container img", "attribute": "src"},
        {"name": "price",      "selector": "p.price_color",     "transformers": ["strip", "to_float"]},
        {"name": "rating",     "selector": "p.star-rating",     "attribute": "class"}
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "css", "value": "li.next a"},
    "max_pages": 5
  }
}
```

---

## 6. Recursive Link Following — Blog Posts

Scrape a listing page then follow each post link to extract full content.

```json
{
  "name": "blog_scraper",
  "base_url": "https://example-blog.com/posts",
  "mode": "pagination",
  "rate_limit": 3,
  "min_delay": 1.0,
  "max_delay": 2.0,
  "use_checkpointing": true,
  "max_nested_urls": 20,
  "fields": [
    {
      "name": "post_links",
      "selector": "article.post a.read-more",
      "attribute": "href",
      "is_list": true,
      "follow_url": true,
      "nested_fields": [
        {"name": "title",      "selector": "h1.post-title"},
        {"name": "date",       "selector": "time.published", "attribute": "datetime"},
        {"name": "author",     "selector": "span.author-name"},
        {"name": "body",       "selector": "div.post-content"},
        {"name": "tags",       "selector": "a.tag", "is_list": true}
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "css", "value": "a.next-page"},
    "max_pages": 10
  }
}
```

Each extracted record will also contain `_source_url` and `_parent_url` automatically.

---

## 7. Dynamic Site with Interactions — Search Results (Playwright)

Fill a search bar, click search, wait for results, then scrape.

```json
{
  "name": "search_results",
  "base_url": "https://example.com/search",
  "mode": "pagination",
  "use_playwright": true,
  "wait_for_selector": "div.results",
  "interactions": [
    {"type": "fill",   "selector": "#search-input",  "value": "gaming laptops"},
    {"type": "click",  "selector": "button.search-btn"},
    {"type": "wait",   "duration": 2000},
    {"type": "scroll"}
  ],
  "fields": [
    {
      "name": "results",
      "selector": "div.result-item",
      "is_list": true,
      "children": [
        {"name": "title", "selector": "h3.title"},
        {"name": "price", "selector": "span.price", "transformers": ["strip", "to_float"]},
        {"name": "url",   "selector": "a",          "attribute": "href"}
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "css", "value": "a[aria-label='Next page']"},
    "max_pages": 5
  }
}
```

---

## 8. Proxy Rotation with Authentication

Rotate through proxies while scraping an API with a static bearer token.

```json
{
  "name": "proxied_api",
  "base_url": "https://api.example.com/listings",
  "mode": "pagination",
  "response_type": "json",
  "rate_limit": 3,
  "proxies": [
    "http://user:pass@proxy1.example.com:8080",
    "http://user:pass@proxy2.example.com:8080",
    "http://user:pass@proxy3.example.com:8080"
  ],
  "authentication": {
    "type": "bearer",
    "client_secret": "${API_TOKEN}"
  },
  "fields": [
    {
      "name": "listings",
      "selectors": [{"type": "json", "value": "data.items[*]"}],
      "is_list": true,
      "children": [
        {"name": "id",    "selectors": [{"type": "json", "value": "id"}]},
        {"name": "title", "selectors": [{"type": "json", "value": "title"}]},
        {"name": "price", "selectors": [{"type": "json", "value": "price"}]}
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "json", "value": "meta.next_cursor"},
    "max_pages": 50,
    "query_param": "cursor"
  }
}
```

---

## 9. XPath Selectors

Use XPath when CSS selectors aren't expressive enough.

```json
{
  "name": "xpath_example",
  "base_url": "https://example.com/products",
  "fields": [
    {
      "name": "products",
      "selectors": [{"type": "xpath", "value": "//div[contains(@class,'product') and not(contains(@class,'sponsored'))]"}],
      "is_list": true,
      "children": [
        {
          "name": "title",
          "selectors": [{"type": "xpath", "value": ".//h2[@class='title']"}]
        },
        {
          "name": "price",
          "selectors": [{"type": "xpath", "value": ".//span[@itemprop='price']"}],
          "transformers": ["to_float"]
        },
        {
          "name": "in_stock",
          "selectors": [{"type": "xpath", "value": ".//meta[@itemprop='availability']"}],
          "attribute": "content"
        }
      ]
    }
  ]
}
```

---

## 10. Regex Selectors — Extract Structured Data from Free Text

Use regex selectors to extract data from unstructured text or JSON responses.

```json
{
  "name": "regex_example",
  "base_url": "https://example.com/listings",
  "response_type": "json",
  "fields": [
    {
      "name": "phone_numbers",
      "selectors": [{"type": "regex", "value": "\\+?\\d[\\d\\s\\-]{7,}\\d"}],
      "is_list": true
    },
    {
      "name": "emails",
      "selectors": [{"type": "regex", "value": "[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}"}],
      "is_list": true
    }
  ]
}
```

---

## 11. Fallback Selectors

Try multiple selectors in order; the first that returns results is used.  Useful for sites with inconsistent markup.

```json
{
  "name": "fallback_selectors",
  "base_url": "https://example.com",
  "fields": [
    {
      "name": "price",
      "selectors": [
        {"type": "css",   "value": "span.sale-price"},
        {"type": "css",   "value": "span.regular-price"},
        {"type": "xpath", "value": "//div[@class='price']//text()"},
        {"type": "regex", "value": "\\$[\\d,.]+"}
      ],
      "transformers": ["strip", "to_float"]
    }
  ]
}
```

---

## 12. Cookie-Based Session

Scrape a site that requires a login session by providing pre-obtained cookies.

**1. Create `session_cookies.json`:**
```json
{
  "sessionid": "abc123xyz",
  "csrftoken": "def456uvw"
}
```

**2. Reference it in your config:**
```json
{
  "name": "members_area",
  "base_url": "https://example.com/members/listings",
  "cookies_file": "session_cookies.json",
  "rate_limit": 2,
  "min_delay": 1.0,
  "fields": [
    {
      "name": "listings",
      "selector": "div.listing",
      "is_list": true,
      "children": [
        {"name": "title",  "selector": "h3"},
        {"name": "posted", "selector": "time", "attribute": "datetime"}
      ]
    }
  ]
}
```

---

## Output Structure

All examples produce two output files in the `data/` directory:

**JSON** (`data/<name>_<timestamp>.json`):
```json
[
  {"title": "Item A", "price": 9.99},
  {"title": "Item B", "price": 14.99}
]
```

**CSV** (`data/<name>_<timestamp>.csv`):
```
title,price
Item A,9.99
Item B,14.99
```

Nested objects are flattened in CSV with `_` as the separator (e.g. `author_name`, `author_url`).  List values are joined with ` | `.
