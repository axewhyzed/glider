"""Bounded sitemap XML discovery."""

from __future__ import annotations

from collections import deque
from typing import Awaitable, Callable, Deque, List, Set
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
    max_documents: int = 10000,
    max_queue: int = 10000,
    max_bytes: int = 10_000_000,
) -> List[str]:
    """Walk sitemap indexes with deterministic order and bounded recursion."""
    discovered: List[str] = []
    discovered_set: Set[str] = set()
    seen: Set[str] = set()
    scheduled: Set[str] = set()
    queue: Deque[tuple[str, int]] = deque()
    for url in roots:
        if url not in scheduled and len(queue) < max_queue:
            scheduled.add(url)
            queue.append((url, 0))

    documents = 0
    while queue and len(discovered) < max_urls and documents < max_documents:
        sitemap_url, depth = queue.popleft()
        if sitemap_url in seen or depth > max_depth:
            continue
        seen.add(sitemap_url)
        documents += 1
        if not await is_allowed(sitemap_url):
            continue
        content = await fetch(sitemap_url)
        if len(content.encode("utf-8")) > max_bytes:
            continue
        try:
            urls, children = parse_sitemap(content, sitemap_url)
        except ElementTree.ParseError:
            continue
        for url in urls:
            if url not in discovered_set and await is_allowed(url):
                discovered_set.add(url)
                discovered.append(url)
                if len(discovered) >= max_urls:
                    break
        if depth < max_depth:
            for child in children:
                if child in seen or child in scheduled:
                    continue
                if len(queue) >= max_queue:
                    break
                scheduled.add(child)
                queue.append((child, depth + 1))
    return discovered
