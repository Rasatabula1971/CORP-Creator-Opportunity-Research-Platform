"""Instagram adapter using instaloader — no API key required."""

import asyncio
import logging
import time
from datetime import timezone

import instaloader

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent, SourceAdapter

logger = logging.getLogger(__name__)

_REQUEST_DELAY = 5.0  # seconds between requests to avoid rate limits


class InstagramAdapter(SourceAdapter):
    """Collects posts, captions, and comments from public Instagram profiles."""

    def __init__(
        self,
        max_posts: int = 30,
        max_comments_per_post: int = 50,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._max_posts = max_posts
        self._max_comments_per_post = max_comments_per_post
        self._loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
        )
        if username and password:
            try:
                self._loader.login(username, password)
                logger.info("Logged in to Instagram as %s", username)
            except instaloader.exceptions.BadCredentialsException:
                logger.warning("Instagram login failed, continuing without auth")

    @property
    def platform(self) -> str:
        return "instagram"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.TOS_RISK

    def _collect_sync(self, handle: str) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []

        try:
            profile = instaloader.Profile.from_username(
                self._loader.context, handle
            )
        except instaloader.exceptions.ProfileNotExistsException:
            logger.error("Instagram profile not found: %s", handle)
            return []
        except instaloader.exceptions.ConnectionException as e:
            logger.error("Instagram connection error for %s: %s", handle, e)
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
            except instaloader.exceptions.QueryReturnedNotFoundException:
                logger.debug("Comments unavailable for post %s", post.shortcode)
            except instaloader.exceptions.ConnectionException as e:
                logger.warning("Rate limited fetching comments for %s: %s", post.shortcode, e)

            post_count += 1
            time.sleep(_REQUEST_DELAY)

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
            "Instagram collection complete: %d posts, %d comments for @%s",
            posts, comments, handle,
        )
        return results
