"""Reddit adapter using public JSON feeds — no API key required."""

import asyncio
import logging
import random
import time
from datetime import datetime, timezone

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent, SourceAdapter

logger = logging.getLogger(__name__)

_USER_AGENT = "CORP-Research/1.0 (educational; non-commercial)"
_MIN_REQUEST_INTERVAL = 2.0
_MAX_REQUEST_INTERVAL = 4.0


class RedditAdapter(SourceAdapter):
    """Collects posts and comments from Reddit subreddits via public JSON feeds."""

    def __init__(
        self,
        max_posts: int = 50,
        max_comments_per_post: int = 100,
        sort: str = "hot",
    ) -> None:
        self._max_posts = max_posts
        self._max_comments_per_post = max_comments_per_post
        self._sort = sort
        self._last_request = 0.0

    @property
    def platform(self) -> str:
        return "reddit"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    def _throttle(self) -> None:
        interval = random.uniform(_MIN_REQUEST_INTERVAL, _MAX_REQUEST_INTERVAL)
        elapsed = time.monotonic() - self._last_request
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request = time.monotonic()

    @retry(
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        reraise=True,
    )
    def _get_json(self, url: str, params: dict | None = None) -> dict:
        self._throttle()
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            timeout=15.0,
            follow_redirects=True,
        ) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "10"))
                logger.warning("Reddit rate-limited, waiting %ds", retry_after)
                time.sleep(retry_after)
                resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    def _fetch_posts(self, subreddit: str) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        after: str | None = None
        remaining = self._max_posts

        while remaining > 0:
            params: dict = {"limit": min(remaining, 25), "raw_json": 1}
            if after:
                params["after"] = after

            url = f"https://www.reddit.com/r/{subreddit}/{self._sort}.json"
            data = self._get_json(url, params)

            listing = data.get("data", {})
            children = listing.get("children", [])
            if not children:
                break

            for child in children:
                if child.get("kind") != "t3":
                    continue
                post = child["data"]
                if post.get("stickied"):
                    continue

                created = post.get("created_utc")
                ts = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
                title = post.get("title", "")
                body = post.get("selftext", "")
                text = f"{title}\n\n{body}".strip() if body else title

                results.append(
                    NormalizedContent(
                        source_platform="reddit",
                        content_type="post",
                        external_id=post["id"],
                        text=text,
                        author=post.get("author"),
                        timestamp=ts,
                        url=f"https://www.reddit.com{post.get('permalink', '')}",
                        access_method=self.access_method,
                        compliance_status=self.compliance_status,
                        metadata={
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0),
                            "subreddit": subreddit,
                            "upvote_ratio": post.get("upvote_ratio", 0),
                            "link_flair_text": post.get("link_flair_text"),
                        },
                    )
                )
                remaining -= 1

            after = listing.get("after")
            if not after:
                break

        return results

    def _parse_comment_tree(
        self, comments: list[dict], post_id: str, parent_id: str | None = None
    ) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []

        for item in comments:
            if item.get("kind") != "t1":
                continue
            c = item["data"]
            body = c.get("body", "")
            if not body or body == "[deleted]" or body == "[removed]":
                continue

            created = c.get("created_utc")
            ts = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
            content_type = "reply" if parent_id else "comment"

            results.append(
                NormalizedContent(
                    source_platform="reddit",
                    content_type=content_type,
                    external_id=c["id"],
                    text=body,
                    author=c.get("author"),
                    timestamp=ts,
                    parent_id=parent_id or post_id,
                    url=f"https://www.reddit.com{c.get('permalink', '')}",
                    access_method=self.access_method,
                    compliance_status=self.compliance_status,
                    metadata={
                        "score": c.get("score", 0),
                        "post_id": post_id,
                    },
                )
            )

            replies = c.get("replies")
            if isinstance(replies, dict):
                children = replies.get("data", {}).get("children", [])
                results.extend(
                    self._parse_comment_tree(children, post_id, parent_id=c["id"])
                )

        return results

    def _fetch_comments(self, permalink: str, post_id: str) -> list[NormalizedContent]:
        url = f"https://www.reddit.com{permalink}.json"
        params = {"limit": self._max_comments_per_post, "raw_json": 1, "sort": "top"}
        data = self._get_json(url, params)

        if not isinstance(data, list) or len(data) < 2:
            return []

        comment_listing = data[1].get("data", {}).get("children", [])
        return self._parse_comment_tree(comment_listing, post_id)

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        """Collect posts and comments from a subreddit.

        Args:
            identifier: subreddit name (e.g. "creatoreconomy") — no r/ prefix needed.
        """
        subreddit = identifier.strip().removeprefix("r/").removeprefix("/r/")
        logger.info("Collecting from r/%s", subreddit)

        posts = await asyncio.to_thread(self._fetch_posts, subreddit)
        logger.info("Fetched %d posts from r/%s", len(posts), subreddit)

        results: list[NormalizedContent] = list(posts)
        for post in posts:
            permalink = post.url.replace("https://www.reddit.com", "") if post.url else None
            if not permalink:
                continue
            comments = await asyncio.to_thread(
                self._fetch_comments, permalink, post.external_id
            )
            results.extend(comments)
            logger.debug(
                "Fetched %d comments for post %s", len(comments), post.external_id
            )

        logger.info(
            "Reddit collection complete: %d total items from r/%s",
            len(results),
            subreddit,
        )
        return results
