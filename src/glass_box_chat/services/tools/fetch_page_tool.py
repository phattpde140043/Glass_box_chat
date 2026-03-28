from __future__ import annotations

import asyncio
import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from html.parser import HTMLParser

from .tool_gateway import BaseTool, ToolInput, ToolOutput


class HTMLTextExtractor(HTMLParser):
    """Extract plain text and metadata from HTML."""
    
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.title = ""
        self.description = ""
        self.in_script = False
        self.in_style = False
        self.skip_tags = {"script", "style", "noscript", "meta", "link", "br", "hr"}
    
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" or tag == "style":
            if tag == "script":
                self.in_script = True
            else:
                self.in_style = True
        elif tag == "title":
            pass  # Will be captured in handle_data
        elif tag == "meta":
            # Extract meta description
            for key, value in attrs:
                if key == "name" and value and value.lower() == "description":
                    # Find the content attribute
                    for k2, v2 in attrs:
                        if k2 == "content" and v2:
                            self.description = v2
    
    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_script = False
        elif tag == "style":
            self.in_style = False
        elif tag in ("p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"):
            # Add line break for block elements
            if self.text_parts and self.text_parts[-1] != "\n":
                self.text_parts.append("\n")
    
    def handle_data(self, data: str) -> None:
        if not (self.in_script or self.in_style):
            text = data.strip()
            if text and text not in ("\n", " "):
                self.text_parts.append(text)
                self.text_parts.append(" ")
    
    def get_text(self) -> str:
        """Return cleaned text."""
        text = "".join(self.text_parts)
        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text)
        return text.strip()[:5000]  # Limit to 5000 chars


class FetchPageTool(BaseTool):
    """Fetch and parse web page content."""
    
    def __init__(self, timeout_seconds: float = 8.0) -> None:
        super().__init__(
            name="fetch_page",
            description="Fetch and parse a web page URL to extract text, title, and metadata.",
            timeout_seconds=timeout_seconds,
            max_retries=2,
        )
        self._timeout_seconds = timeout_seconds
    
    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """Fetch page and return parsed content."""
        async def _fetch(inp: ToolInput) -> ToolOutput:
            url = inp.query.strip()
            
            # Validate URL
            try:
                result = urlparse(url)
                if not result.scheme:
                    url = f"https://{url}"
                    result = urlparse(url)
                if not result.netloc:
                    return ToolOutput(
                        success=False,
                        content=f"Invalid URL: {inp.query}",
                        confidence=0.0,
                    )
            except Exception as e:
                return ToolOutput(
                    success=False,
                    content=f"Failed to parse URL: {inp.query} - {str(e)}",
                    confidence=0.0,
                )
            
            # Fetch page
            try:
                # Allow SSL verification to be disabled in development
                verify_ssl = not os.getenv("FETCH_PAGE_SKIP_SSL_VERIFY", "false").strip().lower() in ("1", "true", "yes")
                async with httpx.AsyncClient(timeout=self._timeout_seconds, verify=verify_ssl) as client:
                    response = await client.get(
                        url,
                        follow_redirects=True,
                        headers={
                            "User-Agent": "GlassBoxResearch/1.0 (Page Fetcher)",
                        },
                    )
                    response.raise_for_status()
                    html_content = response.text
            except httpx.TimeoutException:
                return ToolOutput(
                    success=False,
                    content=f"Request timeout fetching {url}",
                    confidence=0.0,
                )
            except Exception as e:
                return ToolOutput(
                    success=False,
                    content=f"Failed to fetch {url}: {str(e)}",
                    confidence=0.0,
                )
            
            # Parse HTML
            try:
                extractor = HTMLTextExtractor()
                extractor.feed(html_content)
                
                # Extract title (basic fallback)
                title_match = re.search(r"<title>([^<]+)</title>", html_content, re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else "No title"
                
                if not extractor.title and title:
                    extractor.title = title
                
                text = extractor.get_text()
                if not text:
                    return ToolOutput(
                        success=False,
                        content=f"No readable content extracted from {url}",
                        confidence=0.2,
                    )
                
                # Format output
                content_lines = [
                    f"Page: {title}\n",
                    f"URL: {url}\n",
                ]
                
                if extractor.description:
                    content_lines.append(f"Description: {extractor.description}\n")
                
                content_lines.append(f"\n{text}\n")
                content = "".join(content_lines)
                
                return ToolOutput(
                    success=True,
                    content=content,
                    source_url=url,
                    data={
                        "title": title,
                        "text": text[:3000],  # Store first 3000 chars
                        "description": extractor.description,
                        "url": url,
                    },
                    confidence=0.85,  # High confidence for successfully fetched page
                    metadata={
                        "content_length": len(text),
                        "title_extracted": bool(title),
                        "source": "fetch_page",
                    },
                )
            except Exception as e:
                return ToolOutput(
                    success=False,
                    content=f"Failed to parse page content: {str(e)}",
                    confidence=0.0,
                )
        
        return await self.execute_with_retry(tool_input, _fetch)
