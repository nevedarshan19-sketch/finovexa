from __future__ import annotations

import hashlib
from datetime import datetime

import httpx

from ...config import settings


class NewsError(Exception):
    pass


class NewsClient:
    @property
    def configured(self) -> bool:
        return bool(settings.NEWS_API_KEY)

    def fetch(self, query: str | None = None) -> list[dict]:
        if not self.configured:
            raise NewsError("News provider is not configured.")
        try:
            response = httpx.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query or "(gold OR silver OR Nifty OR Sensex OR \"Indian stocks\")",
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 20,
                    "apiKey": settings.NEWS_API_KEY,
                },
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise NewsError("Could not reach the news provider.") from exc
        if response.status_code == 429:
            raise NewsError("News provider rate limit reached.")
        if response.status_code >= 400:
            raise NewsError(f"News provider failed ({response.status_code}).")
        body = response.json()
        if body.get("status") != "ok":
            raise NewsError("News provider returned an unsuccessful response.")
        articles = []
        for item in body.get("articles", []):
            url = item.get("url")
            title = (item.get("title") or "").strip()
            if not url or not title or title == "[Removed]":
                continue
            articles.append(
                {
                    "external_id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:40],
                    "title": title[:255],
                    "source": (item.get("source") or {}).get("name", "Unknown source")[:120],
                    "url": url[:500],
                    "published_at": datetime.fromisoformat(
                        (item.get("publishedAt") or "").replace("Z", "+00:00")
                    ),
                    "summary": (item.get("description") or "No summary supplied by the provider.")[:2000],
                    "implications": None,
                    "risks": None,
                    "instruments": [],
                    "data_mode": "live",
                }
            )
        return articles


news_client = NewsClient()
