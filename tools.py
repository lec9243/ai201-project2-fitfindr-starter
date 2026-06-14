"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import json
import re
from collections import Counter
from statistics import median

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _call_groq(prompt: str, *, temperature: float, max_tokens: int) -> str:
    """Call the Groq chat completion API and return stripped response text."""
    client = _get_groq_client()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are FitFindr, a concise secondhand fashion stylist. "
                    "Give specific, practical advice in a casual voice."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "looking",
    "mostly",
    "of",
    "on",
    "or",
    "out",
    "style",
    "the",
    "there",
    "to",
    "under",
    "wear",
    "what",
    "whats",
    "with",
    "would",
}

TREND_SOURCE_URL = "https://www.whowhatwear.com/fashion/shopping/depop-trend-predictions-2026"
TREND_SOURCE_LABEL = "Depop 2026 Trend Forecast via Who What Wear, published January 15, 2026"

_TREND_SNAPSHOT = [
    {
        "trend_name": "Modern Uniforms",
        "terms": [
            "classic",
            "minimal",
            "basics",
            "button",
            "button-down",
            "trousers",
            "denim",
            "polo",
            "belt",
            "ralph",
        ],
        "styling_angle": (
            "lean into dependable outfit repetition with clean staples, neutral layers, "
            "and one polished detail"
        ),
    },
    {
        "trend_name": "Neo Nostalgia",
        "terms": [
            "vintage",
            "90s",
            "y2k",
            "70s",
            "2000s",
            "grunge",
            "band",
            "graphic",
            "flannel",
            "slip",
        ],
        "styling_angle": (
            "mix archive-feeling pieces from different decades instead of recreating "
            "one exact era"
        ),
    },
    {
        "trend_name": "Everyday Ceremony",
        "terms": [
            "feminine",
            "floral",
            "silk",
            "velvet",
            "glam",
            "statement",
            "dress",
            "skirt",
            "mary",
            "jane",
        ],
        "styling_angle": (
            "make a normal day feel dressed-up with texture, shape, and a deliberate "
            "accessory choice"
        ),
    },
    {
        "trend_name": "Romanticized Sports",
        "terms": [
            "athletic",
            "track",
            "sport",
            "sneakers",
            "windbreaker",
            "bike",
            "shorts",
            "platform",
            "jersey",
        ],
        "styling_angle": (
            "treat sportswear as playful styling material by pairing athletic pieces "
            "with sharper or softer wardrobe staples"
        ),
    },
]

_STYLE_KEYWORDS = {
    "athletic",
    "baggy",
    "basics",
    "classic",
    "cozy",
    "cottagecore",
    "denim",
    "earth tones",
    "feminine",
    "graphic tee",
    "grunge",
    "minimal",
    "oversized",
    "preppy",
    "streetwear",
    "vintage",
    "wide-leg",
    "y2k",
}


def _tokens(text: str) -> list[str]:
    """Normalize a text field into searchable tokens."""
    return [
        token
        for token in _WORD_RE.findall((text or "").lower())
        if token not in _STOPWORDS and not token.isdigit()
    ]


def _style_memory_path() -> str:
    """Return the runtime style memory file path."""
    return os.environ.get("FITFINDR_STYLE_MEMORY", ".fitfindr_style_profile.json")


def _default_style_profile() -> dict:
    """Return an empty style profile structure."""
    return {
        "preferences": [],
        "style_tags": [],
        "last_query": None,
    }


def load_style_profile() -> dict:
    """
    Load saved style preferences from disk.

    Returns an empty profile if the file does not exist or cannot be read.
    """
    path = _style_memory_path()
    if not os.path.exists(path):
        return _default_style_profile()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _default_style_profile()

    profile = _default_style_profile()
    profile["preferences"] = list(data.get("preferences") or [])
    profile["style_tags"] = list(data.get("style_tags") or [])
    profile["last_query"] = data.get("last_query")
    return profile


def _save_style_profile(profile: dict) -> None:
    """Persist the style profile if the runtime path is writable."""
    try:
        with open(_style_memory_path(), "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
    except OSError:
        return


def _unique_limited(values: list[str], limit: int = 12) -> list[str]:
    """Deduplicate strings while preserving order."""
    seen = set()
    result = []
    for value in values:
        clean_value = str(value).strip()
        key = clean_value.lower()
        if clean_value and key not in seen:
            seen.add(key)
            result.append(clean_value)
        if len(result) >= limit:
            break
    return result


def _extract_preference_phrases(query: str) -> list[str]:
    """Extract user style phrases from natural language."""
    query = query or ""
    patterns = [
        r"(?:i mostly wear|i usually wear|i wear a lot of|my style is|i like|i love|i am into|i'm into)\s+([^.;]+)",
    ]
    phrases = []
    for pattern in patterns:
        for match in re.finditer(pattern, query, flags=re.IGNORECASE):
            phrase = re.sub(r"\s+", " ", match.group(1)).strip(" ,")
            if phrase:
                phrases.append(phrase)
    return phrases


def _extract_style_tags(query: str, wardrobe: dict) -> list[str]:
    """Extract style tags from query text and wardrobe item tags."""
    tags = []
    query_lower = (query or "").lower()
    for keyword in sorted(_STYLE_KEYWORDS):
        if keyword in query_lower:
            tags.append(keyword)

    for item in (wardrobe.get("items", []) if isinstance(wardrobe, dict) else []):
        tags.extend(item.get("style_tags") or [])

    return _unique_limited(tags, limit=12)


def _profile_summary(style_profile: dict | None) -> str:
    """Format saved style memory for prompts."""
    if not isinstance(style_profile, dict):
        return ""
    parts = []
    preferences = style_profile.get("preferences") or []
    tags = style_profile.get("style_tags") or []
    if preferences:
        parts.append("saved preferences: " + "; ".join(preferences[:3]))
    if tags:
        parts.append("recurring style tags: " + ", ".join(tags[:8]))
    return " | ".join(parts)


def _listing_text(listing: dict) -> str:
    """Combine searchable listing fields into one string."""
    return " ".join(
        [
            listing.get("title") or "",
            listing.get("title") or "",
            listing.get("description") or "",
            listing.get("category") or "",
            listing.get("brand") or "",
            listing.get("platform") or "",
            " ".join(listing.get("style_tags") or []),
            " ".join(listing.get("style_tags") or []),
            " ".join(listing.get("colors") or []),
        ]
    )


def _size_matches(listing_size: str, requested_size: str | None) -> bool:
    """Return whether a listing size satisfies the requested size token."""
    if requested_size is None or not str(requested_size).strip():
        return True

    requested = str(requested_size).strip().upper()
    normalized_listing = re.sub(r"[^A-Z0-9.]+", " ", (listing_size or "").upper())
    listing_tokens = normalized_listing.split()

    if requested in listing_tokens:
        return True

    if requested.isdigit() or re.fullmatch(r"\d+(?:\.\d+)?", requested):
        return requested in listing_tokens or f"US {requested}" in (listing_size or "").upper()

    return False


def _format_item(new_item: dict) -> str:
    """Format item details for an LLM prompt or fallback sentence."""
    title = new_item.get("title", "this item")
    price = new_item.get("price")
    price_text = f"${price:.0f}" if isinstance(price, (int, float)) else "unknown price"
    colors = ", ".join(new_item.get("colors") or [])
    tags = ", ".join(new_item.get("style_tags") or [])
    return (
        f"{title} ({price_text} on {new_item.get('platform', 'resale')}; "
        f"category: {new_item.get('category', 'unknown')}; "
        f"size: {new_item.get('size', 'unknown')}; "
        f"condition: {new_item.get('condition', 'unknown')}; "
        f"colors: {colors or 'not listed'}; tags: {tags or 'not listed'})"
    )


def _wardrobe_lines(wardrobe: dict) -> list[str]:
    """Format wardrobe items as short prompt lines."""
    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []
    lines = []
    for item in items:
        colors = ", ".join(item.get("colors") or [])
        tags = ", ".join(item.get("style_tags") or [])
        notes = item.get("notes") or ""
        line = (
            f"- {item.get('name', 'Unnamed item')} "
            f"({item.get('category', 'unknown')}; colors: {colors}; tags: {tags})"
        )
        if notes:
            line += f" Notes: {notes}"
        lines.append(line)
    return lines


def _first_wardrobe_item(wardrobe: dict, category: str) -> dict | None:
    """Return the first wardrobe item in a category."""
    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []
    return next((item for item in items if item.get("category") == category), None)


def _fallback_outfit(new_item: dict, wardrobe: dict) -> str:
    """Return a useful outfit suggestion when the LLM is unavailable."""
    title = new_item.get("title", "this thrift find")
    category = new_item.get("category", "")
    tags = ", ".join(new_item.get("style_tags") or ["secondhand"])
    profile_text = _profile_summary(wardrobe.get("_style_profile") if isinstance(wardrobe, dict) else {})
    trend_info = wardrobe.get("_trend_info", {}) if isinstance(wardrobe, dict) else {}
    trend_sentence = ""
    if trend_info:
        trend_sentence = (
            f" This also connects to {trend_info.get('trend_name', 'current resale trends')}: "
            f"{trend_info.get('styling_angle', 'style it intentionally')}."
        )
    profile_sentence = f" Since your saved style profile says {profile_text}, keep that direction visible." if profile_text else ""

    has_wardrobe = isinstance(wardrobe, dict) and bool(wardrobe.get("items"))
    if has_wardrobe:
        candidates = []
        for wanted_category in ["bottoms", "tops", "outerwear", "shoes", "accessories"]:
            if wanted_category == category:
                continue
            item = _first_wardrobe_item(wardrobe, wanted_category)
            if item:
                candidates.append(item["name"])

        if candidates:
            return (
                f"Pair {title} with {', '.join(candidates[:4])}. "
                f"That keeps the look grounded in the item's {tags} vibe while "
                f"still feeling wearable and complete.{trend_sentence}{profile_sentence}"
            )

    if category == "tops":
        return (
            f"Style {title} with relaxed straight-leg jeans, chunky sneakers or "
            f"combat boots, and a simple crossbody bag. The {tags} mood will feel "
            f"intentional if you keep the base pieces easy and slightly oversized."
            f"{trend_sentence}{profile_sentence}"
        )
    if category == "bottoms":
        return (
            f"Wear {title} with a fitted tank or baby tee, a cropped jacket, and "
            f"clean sneakers. Keep the top simple so the {tags} shape stays central."
            f"{trend_sentence}{profile_sentence}"
        )
    if category == "shoes":
        return (
            f"Use {title} to anchor straight-leg denim, a soft tee, and an oversized "
            f"layer. That gives the outfit a casual {tags} direction without overdoing it."
            f"{trend_sentence}{profile_sentence}"
        )
    if category == "outerwear":
        return (
            f"Layer {title} over a plain tee or tank with dark denim and simple shoes. "
            f"Let the jacket carry the {tags} energy.{trend_sentence}{profile_sentence}"
        )
    return (
        f"Build around {title} with clean basics in matching colors and one textured "
        f"layer to make the {tags} vibe feel deliberate.{trend_sentence}{profile_sentence}"
    )


def _fallback_fit_card(outfit: str, new_item: dict) -> str:
    """Return a short caption when the LLM is unavailable."""
    title = new_item.get("title", "this thrift find")
    platform = new_item.get("platform", "resale")
    price = new_item.get("price")
    price_text = f"${price:.0f}" if isinstance(price, (int, float)) else "a good price"
    outfit_start = outfit.strip().split(".")[0].lower()
    return (
        f"Thrifted {title} on {platform} for {price_text}. "
        f"Styled it with {outfit_start} for an easy secondhand look that feels pulled together."
    )


def update_style_profile(query: str, wardrobe: dict) -> dict:
    """
    Remember user style preferences across sessions.

    Args:
        query: User's natural language request.
        wardrobe: Current wardrobe dict.

    Returns:
        A style profile dict with preferences, style_tags, and last_query.
    """
    profile = load_style_profile()
    preferences = profile.get("preferences", [])
    style_tags = profile.get("style_tags", [])

    preferences = _unique_limited(preferences + _extract_preference_phrases(query), limit=8)
    style_tags = _unique_limited(style_tags + _extract_style_tags(query, wardrobe), limit=12)

    updated_profile = {
        "preferences": preferences,
        "style_tags": style_tags,
        "last_query": query,
    }
    _save_style_profile(updated_profile)
    return updated_profile


def compare_price(new_item: dict) -> dict:
    """
    Compare a listing's price against similar listings in the mock dataset.

    Args:
        new_item: The selected listing dict.

    Returns:
        A dict with assessment, comparable prices, comparable count, titles, and reasoning.
    """
    if not isinstance(new_item, dict) or not new_item:
        return {
            "assessment": "unknown",
            "item_price": None,
            "average_comparable_price": None,
            "median_comparable_price": None,
            "comparable_count": 0,
            "comparable_titles": [],
            "reasoning": "No selected item was provided for price comparison.",
        }

    item_tags = set(tag.lower() for tag in new_item.get("style_tags") or [])
    item_colors = set(color.lower() for color in new_item.get("colors") or [])
    item_category = new_item.get("category")
    comparables = []

    for listing in load_listings():
        if listing.get("id") == new_item.get("id"):
            continue
        if listing.get("category") != item_category:
            continue

        listing_tags = set(tag.lower() for tag in listing.get("style_tags") or [])
        listing_colors = set(color.lower() for color in listing.get("colors") or [])
        overlap = len(item_tags & listing_tags) * 2 + len(item_colors & listing_colors)
        if overlap > 0:
            comparables.append((overlap, listing))

    if not comparables:
        for listing in load_listings():
            if listing.get("id") != new_item.get("id") and listing.get("category") == item_category:
                comparables.append((0, listing))

    if not comparables:
        return {
            "assessment": "unknown",
            "item_price": new_item.get("price"),
            "average_comparable_price": None,
            "median_comparable_price": None,
            "comparable_count": 0,
            "comparable_titles": [],
            "reasoning": "There are no comparable listings in the dataset for this category.",
        }

    comparables.sort(key=lambda item: (-item[0], item[1].get("price", 0)))
    comparable_listings = [listing for _, listing in comparables[:8]]
    prices = [float(listing["price"]) for listing in comparable_listings]
    item_price = float(new_item.get("price", 0))
    average_price = sum(prices) / len(prices)
    median_price = median(prices)

    if item_price <= median_price * 0.85:
        assessment = "great deal"
    elif item_price <= median_price * 1.15:
        assessment = "fair price"
    else:
        assessment = "pricey"

    return {
        "assessment": assessment,
        "item_price": item_price,
        "average_comparable_price": round(average_price, 2),
        "median_comparable_price": round(median_price, 2),
        "comparable_count": len(comparable_listings),
        "comparable_titles": [listing["title"] for listing in comparable_listings[:3]],
        "reasoning": (
            f"This {item_category} listing is ${item_price:.0f}; similar {item_category} "
            f"items in the dataset have a median price of ${median_price:.0f}."
        ),
    }


def check_trends(new_item: dict) -> dict:
    """
    Match a selected item to a 2026 resale trend snapshot.

    Args:
        new_item: The selected listing dict.

    Returns:
        A dict with trend_name, source, source_url, matched_terms, and styling_angle.
    """
    if not isinstance(new_item, dict) or not new_item:
        return {
            "trend_name": "The Edited Self",
            "source": TREND_SOURCE_LABEL,
            "source_url": TREND_SOURCE_URL,
            "matched_terms": [],
            "styling_angle": "style with intentional staples and pieces that feel personal",
        }

    searchable = _listing_text(new_item).lower()
    best_match = None
    best_terms = []
    best_score = 0

    for trend in _TREND_SNAPSHOT:
        matched_terms = [term for term in trend["terms"] if term in searchable]
        score = len(matched_terms)
        if score > best_score:
            best_match = trend
            best_terms = matched_terms
            best_score = score

    if not best_match:
        return {
            "trend_name": "The Edited Self",
            "source": TREND_SOURCE_LABEL,
            "source_url": TREND_SOURCE_URL,
            "matched_terms": [],
            "styling_angle": "style with intentional staples and pieces that feel personal",
        }

    return {
        "trend_name": best_match["trend_name"],
        "source": TREND_SOURCE_LABEL,
        "source_url": TREND_SOURCE_URL,
        "matched_terms": best_terms,
        "styling_angle": best_match["styling_angle"],
    }


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    query_tokens = _tokens(description)
    if not query_tokens:
        return []

    scored_results: list[tuple[int, float, dict]] = []
    for listing in load_listings():
        if max_price is not None and listing.get("price", 0) > max_price:
            continue
        if not _size_matches(listing.get("size", ""), size):
            continue

        searchable_text = _listing_text(listing).lower()
        listing_token_counts = Counter(_tokens(searchable_text))
        score = sum(listing_token_counts.get(token, 0) for token in query_tokens)

        description_lower = (description or "").lower()
        for tag in listing.get("style_tags") or []:
            if tag.lower() in description_lower:
                score += 3

        if (listing.get("category") or "").lower() in query_tokens:
            score += 2

        if score > 0:
            scored_results.append((score, float(listing.get("price", 0)), listing))

    scored_results.sort(key=lambda item: (-item[0], item[1], item[2].get("title", "")))
    return [listing for _, _, listing in scored_results]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    if not isinstance(new_item, dict) or not new_item:
        return "I need a selected listing before I can suggest an outfit."

    wardrobe_items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []
    item_text = _format_item(new_item)
    style_profile = wardrobe.get("_style_profile", {}) if isinstance(wardrobe, dict) else {}
    trend_info = wardrobe.get("_trend_info", {}) if isinstance(wardrobe, dict) else {}
    extra_context = []
    profile_text = _profile_summary(style_profile)
    if profile_text:
        extra_context.append(f"Saved style profile: {profile_text}")
    if trend_info:
        extra_context.append(
            "Trend context: "
            f"{trend_info.get('trend_name', 'Current trend')} from {trend_info.get('source', 'trend snapshot')}. "
            f"Use this styling angle: {trend_info.get('styling_angle', 'style it intentionally')}."
        )
    context_block = "\n".join(extra_context)

    if wardrobe_items:
        prompt = f"""
Create 1-2 complete outfit ideas for this thrifted item:
{item_text}

Use pieces from this wardrobe when possible:
{chr(10).join(_wardrobe_lines(wardrobe))}

Additional context:
{context_block or "No saved style or trend context."}

Requirements:
- Name exact wardrobe pieces when using them.
- Reflect the saved style profile or trend context if provided.
- If trend context is provided, mention the trend name once and apply its styling angle.
- Include shoes and one styling detail.
- Keep the response to 4-6 sentences.
- Sound practical and conversational, not like a product ad.
""".strip()
    else:
        prompt = f"""
The user has not added wardrobe items yet. Give general styling ideas for:
{item_text}

Additional context:
{context_block or "No saved style or trend context."}

Requirements:
- Suggest common pieces someone might already own.
- Reflect the saved style profile or trend context if provided.
- If trend context is provided, mention the trend name once and apply its styling angle.
- Include shoes and one styling detail.
- Keep the response to 3-5 sentences.
- Do not criticize the empty wardrobe.
""".strip()

    try:
        response = _call_groq(prompt, temperature=0.7, max_tokens=350)
    except Exception:
        response = ""

    return response or _fallback_outfit(new_item, wardrobe if isinstance(wardrobe, dict) else {"items": []})


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        return "I need an outfit suggestion before I can create a fit card."
    if not isinstance(new_item, dict) or not new_item:
        return "I need a selected listing before I can create a fit card."

    prompt = f"""
Write a short shareable outfit caption for this thrifted find.

Item:
{_format_item(new_item)}

Outfit idea:
{outfit.strip()}

Requirements:
- 2-4 sentences.
- Casual and specific, like an OOTD caption.
- Mention the item title, price, and platform naturally once.
- Capture the outfit vibe.
- Do not sound like a product listing.
""".strip()

    try:
        response = _call_groq(prompt, temperature=0.95, max_tokens=220)
    except Exception:
        response = ""

    return response or _fallback_fit_card(outfit, new_item)
