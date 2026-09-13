"""Instagram adapter using instaloader — no API key required.

IMPORTANT PRECAUTIONS (read before running):
- Never use your primary Instagram account. Create a throwaway.
- Run from your home IP, not cloud/datacenter IPs (AWS, DigitalOcean, etc.)
  — Instagram blocks datacenter ranges immediately.
- Keep max_posts low (10-20) for first runs to test without triggering locks.
- If your account gets a "challenge required" error, Instagram detected
  automation — wait 24h before retrying with longer delays.
"""

import asyncio
import logging
import random
import time
from datetime import timezone

import instaloader

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent, SourceAdapter

logger = logging.getLogger(__name__)

_MIN_POST_DELAY = 4.0
_MAX_POST_DELAY = 8.0
_MIN_COMMENT_DELAY = 2.0
_MAX_COMMENT_DELAY = 5.0
_RATE_LIMIT_BACKOFF = 120  # seconds to wait on 429 / login wall


class RateLimitedError(Exception):
    """Raised when Instagram rate-limits or challenges the session."""


class InstagramAdapter(SourceAdapter):
    """Collects posts, captions, and comments from public Instagram profiles.

    Rate-limit precautions:
    - Randomized 4-8s delay between post fetches
    - Randomized 2-5s delay between comment page fetches
    - 120s backoff on 429 / connection errors, with retry
    - Graceful degradation: returns partial results on rate limit
    """

    def __init__(
        self,
        max_posts: int = 20,
        max_comments_per_post: int = 50,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._max_posts = max_posts
        self._max_comments_per_post = max_comments_per_post
        self._rate_limit_hits = 0
        self._max_rate_limit_retries = 2
        self._loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
            max_connection_attempts=3,
            request_timeout=30.0,
        )
        if username and password:
            try:
                self._loader.login(username, password)
                logger.info("Logged in to Instagram as %s", username)
            except instaloader.exceptions.TwoFactorAuthRequiredException:
                logger.error("Instagram requires 2FA — use a throwaway account without 2FA")
            except instaloader.exceptions.BadCredentialsException:
                logger.warning("Instagram login failed, continuing without auth")
            except instaloader.exceptions.ConnectionException as e:
                if "challenge" in str(e).lower():
                    logger.error("Instagram challenge required — account flagged for automation")
                else:
                    logger.warning("Instagram connection error during login: %s", e)

    @property
    def platform(self) -> str:
        return "instagram"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.TOS_RISK

    def _sleep_between_posts(self) -> None:
        delay = random.uniform(_MIN_POST_DELAY, _MAX_POST_DELAY)
        time.sleep(delay)

    def _sleep_between_comments(self) -> None:
        delay = random.uniform(_MIN_COMMENT_DELAY, _MAX_COMMENT_DELAY)
        time.sleep(delay)

    def _handle_rate_limit(self, context: str) -> bool:
        """Handle a rate limit hit. Returns True if we should retry, False to stop."""
        self._rate_limit_hits += 1
        if self._rate_limit_hits > self._max_rate_limit_retries:
            logger.error(
                "Instagram rate limit hit %d times — stopping collection to avoid account lock",
                self._rate_limit_hits,
            )
            return False
        logger.warning(
            "Instagram rate-limited during %s — backing off %ds (hit %d/%d)",
            context,
            _RATE_LIMIT_BACKOFF,
            self._rate_limit_hits,
            self._max_rate_limit_retries,
        )
        time.sleep(_RATE_LIMIT_BACKOFF)
        return True

    def _fetch_comments_for_post(
        self, post: "instaloader.Post", handle: str
    ) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        comment_count = 0

        try:
            for comment in post.get_comments():
                if comment_count >= self._max_comments_per_post:
                    break

                c_text = comment.text or ""
                if not c_text:
                    continue

                c_ts = (
                    comment.created_at_utc.replace(tzinfo=timezone.utc)
                    if comment.created_at_utc
                    else None
                )

                results.append(
                    NormalizedContent(
                        source_platform="instagram",
                        content_type="comment",
                        external_id=str(comment.id),
                        text=c_text,
                        author=comment.owner.username if comment.owner else None,
                        timestamp=c_ts,
                        parent_id=post.shortcode,
                        url=f"https://www.instagram.com/p/{post.shortcode}/",
                        access_method=self.access_method,
                        compliance_status=self.compliance_status,
                        metadata={
                            "like_count": comment.likes_count,
                            "post_shortcode": post.shortcode,
                        },
                    )
                )
                comment_count += 1

                for reply in comment.answers:
                    r_text = reply.text or ""
                    if not r_text:
                        continue

                    r_ts = (
                        reply.created_at_utc.replace(tzinfo=timezone.utc)
                        if reply.created_at_utc
                        else None
                    )

                    results.append(
                        NormalizedContent(
                            source_platform="instagram",
                            content_type="reply",
                            external_id=str(reply.id),
                            text=r_text,
                            author=reply.owner.username if reply.owner else None,
                            timestamp=r_ts,
                            parent_id=str(comment.id),
                            url=f"https://www.instagram.com/p/{post.shortcode}/",
                            access_method=self.access_method,
                            compliance_status=self.compliance_status,
                            metadata={
                                "like_count": reply.likes_count,
                                "post_shortcode": post.shortcode,
                            },
                        )
                    )
                    comment_count += 1

                self._sleep_between_comments()

        except instaloader.exceptions.QueryReturnedNotFoundException:
            logger.debug("Comments unavailable for post %s", post.shortcode)
        except instaloader.exceptions.ConnectionException as e:
            if "429" in str(e) or "rate" in str(e).lower():
                if not self._handle_rate_limit(f"comments on {post.shortcode}"):
                    return results
            elif "login" in str(e).lower() or "challenge" in str(e).lower():
                logger.warning(
                    "Instagram login wall hit fetching comments for %s — "
                    "try providing throwaway credentials",
                    post.shortcode,
                )
            else:
                logger.warning("Connection error fetching comments for %s: %s", post.shortcode, e)

        return results

    def _collect_sync(self, handle: str) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        self._rate_limit_hits = 0

        try:
            profile = instaloader.Profile.from_username(
                self._loader.context, handle
            )
        except instaloader.exceptions.ProfileNotExistsException:
            logger.error("Instagram profile not found: %s", handle)
            return []
        except instaloader.exceptions.LoginRequiredException:
            logger.error(
                "Instagram requires login to view @%s — "
                "provide throwaway credentials via username/password params",
                handle,
            )
            return []
        except instaloader.exceptions.ConnectionException as e:
            if "429" in str(e):
                logger.error("Instagram rate-limited on profile fetch for @%s", handle)
            else:
                logger.error("Instagram connection error for @%s: %s", handle, e)
            return []

        post_count = 0
        for post in profile.get_posts():
            if post_count >= self._max_posts:
                break

            caption = post.caption or ""
            title = post.title or ""
            text = f"{title}\n\n{caption}".strip() if title else caption

            ts = post.date_utc.replace(tzinfo=timezone.utc) if post.date_utc else None

            results.append(
                NormalizedContent(
                    source_platform="instagram",
                    content_type="post",
                    external_id=post.shortcode,
                    text=text,
                    author=handle,
                    timestamp=ts,
                    url=f"https://www.instagram.com/p/{post.shortcode}/",
                    access_method=self.access_method,
                    compliance_status=self.compliance_status,
                    metadata={
                        "like_count": post.likes,
                        "comment_count": post.comments,
                        "video_view_count": post.video_view_count if post.is_video else None,
                        "is_video": post.is_video,
                        "hashtags": list(post.caption_hashtags),
                        "mentions": list(post.caption_mentions),
                        "typename": post.typename,
                    },
                )
            )

            results.extend(self._fetch_comments_for_post(post, handle))

            post_count += 1
            self._sleep_between_posts()

            if self._rate_limit_hits > self._max_rate_limit_retries:
                logger.warning(
                    "Stopping early after %d posts due to rate limiting", post_count
                )
                break

        return results

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        """Collect posts and comments from an Instagram profile.

        Args:
            identifier: Instagram username (e.g. "creatorname") — no @ prefix needed.
        """
        handle = identifier.strip().lstrip("@")
        logger.info("Collecting Instagram data for @%s", handle)

        results = await asyncio.to_thread(self._collect_sync, handle)

        posts = sum(1 for r in results if r.content_type == "post")
        comments = sum(1 for r in results if r.content_type in ("comment", "reply"))
        logger.info(
            "Instagram collection complete: %d posts, %d comments for @%s "
            "(rate limit hits: %d)",
            posts, comments, handle, self._rate_limit_hits,
        )
        return results
