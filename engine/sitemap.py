"""Bounded sitemap XML discovery."""

from __future__ import annotations

from typing import Awaitable, Callable, List, Set
from urllib.parse import urljoin
from xml.etree import ElementTree


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap(content: str, base_url: str = "") -> tuple[List[str], List[str]]:
    """Return URL entries and nested sitemap entries from XML content."""
    root = ElementTree.fromstring(content)
    urls: List[str] = []
    children: List[str] = []
    root_kind = _local_name(root.tag)
    for element in root.iter():
        if _local_name(element.tag) != "loc" or not element.text:
            continue
        value = urljoin(base_url, element.text.strip())
        if root_kind == "sitemapindex":
            children.append(value)
        else:
            urls.append(value)
    return urls, children


async def discover_sitemap(
    roots: List[str],
    fetch: Callable[[str], Awaitable[str]],
    is_allowed: Callable[[str], Awaitable[bool]],
    *,
    max_urls: int = 10000,
    max_depth: int = 3,
) -> List[str]:
    """Walk sitemap indexes with deterministic order and bounded recursion."""
    discovered: List[str] = []
    seen: Set[str] = set()
    queue: List[tuple[str, int]] = [(url, 0) for url in roots]
    while queue and len(discovered) < max_urls:
        sitemap_url, depth = queue.pop(0)
        if sitemap_url in seen or depth > max_depth:
            continue
        seen.add(sitemap_url)
        if not await is_allowed(sitemap_url):
            continue
        content = await fetch(sitemap_url)
        try:
            urls, children = parse_sitemap(content, sitemap_url)
        except ElementTree.ParseError:
            continue
        for url in urls:
            if url not in discovered and await is_allowed(url):
                discovered.append(url)
                if len(discovered) >= max_urls:
                    break
        if depth < max_depth:
            queue.extend((child, depth + 1) for child in children if child not in seen)
    return discovered
