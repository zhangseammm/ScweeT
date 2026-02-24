from __future__ import annotations

import json
import sys
import os
from datetime import datetime, timezone
from typing import Any, Optional

from apify import Actor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Scweet import Scweet


def _parse_cookies_input(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass
        return stripped
    return raw


def _build_source_value(actor_input: dict[str, Any], mode: str) -> str:
    if mode == "search":
        parts = []
        if actor_input.get("search_query"):
            parts.append(actor_input["search_query"])
        if actor_input.get("any_words"):
            parts.append(f"({' OR '.join(actor_input['any_words'])})")
        if actor_input.get("exact_phrases"):
            for phrase in actor_input["exact_phrases"]:
                parts.append(f'"{phrase}"')
        if actor_input.get("exclude_words"):
            for word in actor_input["exclude_words"]:
                parts.append(f"-{word}")
        if actor_input.get("hashtags_any"):
            hashtag_parts = []
            for h in actor_input["hashtags_any"]:
                tag = h if h.startswith(("#", "$")) else f"#{h}"
                hashtag_parts.append(tag)
            parts.append(f"({' OR '.join(hashtag_parts)})")
        if actor_input.get("lang"):
            parts.append(f"lang:{actor_input['lang']}")
        return " AND ".join(parts) if parts else "all"
    else:
        targets = actor_input.get("profile_urls") or []
        return ", ".join(targets) if targets else "none"


def _extract_user_fields(tweet_data: dict[str, Any]) -> dict[str, Any]:
    core = tweet_data.get("core", {})
    user_results = core.get("user_results", {}).get("result", {})
    legacy_user = user_results.get("legacy", {})

    handle = legacy_user.get("screen_name", "")
    followers_count = legacy_user.get("followers_count", 0)
    is_blue_verified = user_results.get("is_blue_verified", False)
    verified_type = user_results.get("verified_type") or legacy_user.get("verified_type")

    return {
        "handle": handle,
        "followers_count": followers_count,
        "is_blue_verified": is_blue_verified,
        "verified_type": verified_type,
    }


def _extract_tweet_fields(tweet_data: dict[str, Any]) -> dict[str, Any]:
    legacy = tweet_data.get("legacy", {})
    rest_id = tweet_data.get("rest_id", "")

    core = tweet_data.get("core", {})
    user_results = core.get("user_results", {}).get("result", {})
    legacy_user = user_results.get("legacy", {})
    handle = legacy_user.get("screen_name", "")

    created_at = legacy.get("created_at", "")
    tweet_url = f"https://x.com/{handle}/status/{rest_id}" if handle and rest_id else ""
    text = legacy.get("full_text", "")

    views = tweet_data.get("views", {})
    view_count = views.get("count")
    if view_count is not None:
        try:
            view_count = int(view_count)
        except (ValueError, TypeError):
            view_count = 0
    else:
        view_count = 0

    return {
        "created_at": created_at,
        "tweet_url": tweet_url,
        "text": text,
        "view_count": view_count,
        "favorite_count": legacy.get("favorite_count", 0),
        "quote_count": legacy.get("quote_count", 0),
        "reply_count": legacy.get("reply_count", 0),
        "retweet_count": legacy.get("retweet_count", 0),
    }


def _format_tweet_for_dataset(
    tweet_data: dict[str, Any],
    source_root: str,
    source_value: str,
) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc).isoformat()

    user_fields = _extract_user_fields(tweet_data)
    tweet_fields = _extract_tweet_fields(tweet_data)

    return {
        "collected_at_utc": now_utc,
        "source_root": source_root,
        "source_value": source_value,
        "user": user_fields,
        "tweet": tweet_fields,
    }


def _format_follow_for_dataset(
    follow_item: dict[str, Any],
    source_root: str,
    source_value: str,
) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc).isoformat()

    return {
        "collected_at_utc": now_utc,
        "source_root": source_root,
        "source_value": source_value,
        "target": follow_item.get("target", ""),
        "type": follow_item.get("type", source_root),
        "user": {
            "handle": follow_item.get("username", ""),
            "user_id": follow_item.get("user_id", ""),
            "followers_count": follow_item.get("followers_count", 0),
            "is_blue_verified": follow_item.get("is_blue_verified", False),
            "verified_type": follow_item.get("verified_type"),
        },
    }


def _format_user_info_for_dataset(
    user_item: dict[str, Any],
    source_value: str,
) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc).isoformat()
    legacy = user_item.get("legacy", {})

    return {
        "collected_at_utc": now_utc,
        "source_root": "user_info",
        "source_value": source_value,
        "user": {
            "handle": legacy.get("screen_name", ""),
            "name": legacy.get("name", ""),
            "user_id": user_item.get("rest_id", ""),
            "followers_count": legacy.get("followers_count", 0),
            "following_count": legacy.get("friends_count", 0),
            "tweet_count": legacy.get("statuses_count", 0),
            "is_blue_verified": user_item.get("is_blue_verified", False),
            "verified_type": user_item.get("verified_type"),
            "description": legacy.get("description", ""),
            "created_at": legacy.get("created_at", ""),
            "location": legacy.get("location", ""),
        },
    }


async def _run_search(scweet: Scweet, actor_input: dict[str, Any], limit: int) -> list[dict]:
    since = actor_input.get("since")
    if not since:
        Actor.log.error("'since' date is required for search mode")
        return []

    search_sort = actor_input.get("search_sort", "Latest")
    display_type = "Latest" if search_sort == "Latest" else "Top"

    return await scweet.asearch(
        since=since,
        until=actor_input.get("until"),
        search_query=actor_input.get("search_query"),
        any_words=actor_input.get("any_words"),
        exact_phrases=actor_input.get("exact_phrases"),
        exclude_words=actor_input.get("exclude_words"),
        hashtags_any=actor_input.get("hashtags_any"),
        lang=actor_input.get("lang"),
        has_images=actor_input.get("has_images", False),
        has_videos=actor_input.get("has_videos", False),
        has_links=actor_input.get("has_links", False),
        has_mentions=actor_input.get("has_mentions", False),
        has_hashtags=actor_input.get("has_hashtags", False),
        verified_only=actor_input.get("verified_only", False),
        blue_verified_only=actor_input.get("blue_verified_only", False),
        display_type=display_type,
        limit=limit,
        resume=True,
    )


async def _run_profile_timeline(scweet: Scweet, actor_input: dict[str, Any], limit: int) -> list[dict]:
    profile_urls = actor_input.get("profile_urls")
    if not profile_urls:
        Actor.log.error("'profile_urls' is required for profile_timeline mode")
        return []

    return await scweet.aprofile_tweets(
        usernames=profile_urls,
        limit=limit,
        resume=True,
        cursor_handoff=True,
    )


async def _run_followers(scweet: Scweet, actor_input: dict[str, Any], limit: int) -> list[dict]:
    profile_urls = actor_input.get("profile_urls")
    if not profile_urls:
        Actor.log.error("'profile_urls' is required for followers mode")
        return []

    return await scweet.aget_followers(
        usernames=profile_urls,
        limit=limit,
        resume=True,
        cursor_handoff=True,
    )


async def _run_following(scweet: Scweet, actor_input: dict[str, Any], limit: int) -> list[dict]:
    profile_urls = actor_input.get("profile_urls")
    if not profile_urls:
        Actor.log.error("'profile_urls' is required for following mode")
        return []

    return await scweet.aget_following(
        usernames=profile_urls,
        limit=limit,
        resume=True,
        cursor_handoff=True,
    )


async def _run_user_info(scweet: Scweet, actor_input: dict[str, Any]) -> list[dict]:
    profile_urls = actor_input.get("profile_urls")
    if not profile_urls:
        Actor.log.error("'profile_urls' is required for user_info mode")
        return []

    result = await scweet.aget_user_information(
        usernames=profile_urls,
        include_meta=True,
    )

    if isinstance(result, dict):
        return result.get("items", [])
    return result


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        source_mode = actor_input.get("source_mode", "search")
        max_items = actor_input.get("max_items", 1000)
        cookies = _parse_cookies_input(actor_input.get("cookies"))
        proxy = actor_input.get("proxy") or None
        concurrency = actor_input.get("concurrency", 5)

        Actor.log.info(f"Starting Scweet actor in '{source_mode}' mode, max_items={max_items}")

        if not cookies:
            Actor.log.warning("No cookies/auth_token provided — most operations require authentication")

        scweet = Scweet.from_sources(
            db_path="scweet_state.db",
            cookies=cookies,
            proxy=proxy,
            output_format="none",
            provision_on_init=True,
            concurrency=concurrency,
        )

        source_value = _build_source_value(actor_input, source_mode)
        results: list[dict] = []

        if source_mode == "search":
            results = await _run_search(scweet, actor_input, max_items)
        elif source_mode == "profile_timeline":
            results = await _run_profile_timeline(scweet, actor_input, max_items)
        elif source_mode == "followers":
            results = await _run_followers(scweet, actor_input, max_items)
        elif source_mode == "following":
            results = await _run_following(scweet, actor_input, max_items)
        elif source_mode == "user_info":
            results = await _run_user_info(scweet, actor_input)
        else:
            Actor.log.error(f"Unknown source_mode: {source_mode}")

        Actor.log.info(f"Collected {len(results)} raw items, formatting for dataset...")

        pushed = 0
        for item in results:
            if source_mode in ("search", "profile_timeline"):
                formatted = _format_tweet_for_dataset(item, source_mode, source_value)
            elif source_mode in ("followers", "following"):
                formatted = _format_follow_for_dataset(item, source_mode, source_value)
            elif source_mode == "user_info":
                formatted = _format_user_info_for_dataset(item, source_value)
            else:
                formatted = item

            await Actor.push_data(formatted)
            pushed += 1

            if pushed % 100 == 0:
                await Actor.set_status_message(f"Pushed {pushed}/{len(results)} items to dataset")

        await Actor.set_status_message(f"Done. Pushed {pushed} items to dataset.")
        Actor.log.info(f"Actor finished. Total items pushed: {pushed}")
