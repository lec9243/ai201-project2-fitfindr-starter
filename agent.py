"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import (
    check_trends,
    compare_price,
    create_fit_card,
    search_listings,
    suggest_outfit,
    update_style_profile,
)


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "price_assessment": None,    # dict returned by compare_price
        "trend_info": None,          # dict returned by check_trends
        "style_profile": None,       # persisted style memory for the user
        "retry_note": None,          # message if search retried with loosened filters
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract description, size, and max price from a natural language query.
    This is intentionally lightweight so the parser is predictable in tests.
    """
    raw_query = query or ""
    normalized = raw_query.lower()

    max_price = None
    price_match = re.search(r"(?:under|below|less than)\s*\$?\s*(\d+(?:\.\d+)?)", normalized)
    if not price_match:
        price_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", normalized)
    if price_match:
        max_price = float(price_match.group(1))

    size = None
    size_pattern = (
        r"\b(?:in\s+)?size\s*[:=]?\s*"
        r"(one size|xxs|xs|s|m|l|xl|xxl|w\d{2}(?:\s*l\d{2})?|\d+(?:\.\d+)?)\b"
    )
    size_match = re.search(size_pattern, normalized)
    if size_match:
        size = size_match.group(1).upper()
        size = re.sub(r"\s+", " ", size)
    else:
        letter_size_match = re.search(r"\b(XXS|XS|XXL|XL|S|M|L)\b", raw_query.upper())
        if letter_size_match:
            size = letter_size_match.group(1)

    description = normalized
    description = re.sub(r"(?:under|below|less than)\s*\$?\s*\d+(?:\.\d+)?", " ", description)
    description = re.sub(r"\$\s*\d+(?:\.\d+)?", " ", description)
    description = re.sub(size_pattern, " ", description)
    description = re.sub(r"\b(i'?m|im|i am)\s+looking\s+for\b", " ", description)
    description = re.sub(r"\blooking\s+for\b", " ", description)
    description = re.sub(r"\bwhat'?s\s+out\s+there\b", " ", description)
    description = re.sub(r"\bhow\s+would\s+i\s+style\s+it\b", " ", description)
    description = re.sub(r"[^a-z0-9'\s/-]", " ", description)
    description = re.sub(r"\s+", " ", description).strip()

    return {
        "description": description or normalized.strip(),
        "size": size,
        "max_price": max_price,
    }


def _search_with_fallback(parsed: dict) -> tuple[list[dict], str | None, list[str]]:
    """
    Search once with exact constraints, then retry with loosened constraints.

    Returns:
        (results, retry_note, attempted_fallbacks)
    """
    description = parsed["description"]
    size = parsed["size"]
    max_price = parsed["max_price"]

    results = search_listings(description, size=size, max_price=max_price)
    if results:
        return results, None, []

    fallback_attempts = []
    candidates = []
    if size:
        candidates.append((None, max_price, "without the size filter"))
    if max_price is not None:
        candidates.append((size, None, "without the max price filter"))
    if size and max_price is not None:
        candidates.append((None, None, "without the size and max price filters"))

    for retry_size, retry_price, label in candidates:
        fallback_attempts.append(label)
        retry_results = search_listings(description, size=retry_size, max_price=retry_price)
        if retry_results:
            return (
                retry_results,
                f"No exact matches, so I retried {label}.",
                fallback_attempts,
            )

    return [], None, fallback_attempts


def _wardrobe_with_context(wardrobe: dict, style_profile: dict, trend_info: dict) -> dict:
    """Copy the wardrobe and attach non-schema context for suggest_outfit."""
    contextual_wardrobe = dict(wardrobe or {})
    contextual_wardrobe["items"] = list((wardrobe or {}).get("items", []))
    contextual_wardrobe["_style_profile"] = style_profile
    contextual_wardrobe["_trend_info"] = trend_info
    return contextual_wardrobe


def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)

    parsed = _parse_query(query)
    session["parsed"] = parsed
    session["style_profile"] = update_style_profile(query, wardrobe)

    results, retry_note, fallback_attempts = _search_with_fallback(parsed)
    session["search_results"] = results
    session["retry_note"] = retry_note

    if not results:
        filters = []
        if parsed["size"]:
            filters.append(f"size {parsed['size']}")
        if parsed["max_price"] is not None:
            filters.append(f"under ${parsed['max_price']:.0f}")
        filter_text = f" with {', '.join(filters)}" if filters else ""
        retry_text = ""
        if fallback_attempts:
            retry_text = f" I also retried {', '.join(fallback_attempts)}, but still found nothing."
        session["error"] = (
            f"I could not find listings for '{parsed['description']}'{filter_text}. "
            f"{retry_text} Try a broader description, a higher max price, or leaving size blank."
        )
        return session

    selected_item = results[0]
    session["selected_item"] = selected_item
    session["price_assessment"] = compare_price(selected_item)
    session["trend_info"] = check_trends(selected_item)

    contextual_wardrobe = _wardrobe_with_context(
        wardrobe,
        session["style_profile"],
        session["trend_info"],
    )
    outfit = suggest_outfit(selected_item, contextual_wardrobe)
    session["outfit_suggestion"] = outfit

    if not outfit or not outfit.strip():
        session["error"] = (
            "I found a listing, but could not create an outfit suggestion for it. "
            "Try again with a more complete wardrobe or a different item."
        )
        return session

    session["fit_card"] = create_fit_card(outfit, selected_item)
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        if session["retry_note"]:
            print(f"Retry: {session['retry_note']}")
        print(f"Price check: {session['price_assessment']['assessment']} — {session['price_assessment']['reasoning']}")
        print(f"Trend: {session['trend_info']['trend_name']} — {session['trend_info']['styling_angle']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== Retry path: track jacket wrong size ===\n")
    session_retry = run_agent(
        query="90s track jacket size XS under $50",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Retry note: {session_retry['retry_note']}")
    if session_retry["error"]:
        print(f"Error: {session_retry['error']}")
    else:
        print(f"Found after retry: {session_retry['selected_item']['title']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
