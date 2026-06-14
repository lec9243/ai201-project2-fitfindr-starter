from agent import run_agent
from tools import (
    check_trends,
    compare_price,
    create_fit_card,
    load_style_profile,
    search_listings,
    suggest_outfit,
    update_style_profile,
)
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe


def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)

    assert isinstance(results, list)
    assert len(results) > 0
    assert "tee" in results[0]["title"].lower() or "tee" in results[0]["description"].lower()


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)

    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)

    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    results = search_listings("track jacket", size="M", max_price=50)

    assert results
    assert all("M" in item["size"].upper().replace("/", " ").split() for item in results)


def test_suggest_outfit_empty_wardrobe_handles_llm_failure(monkeypatch):
    def fail_groq(*args, **kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("tools._call_groq", fail_groq)
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]

    suggestion = suggest_outfit(item, get_empty_wardrobe())

    assert isinstance(suggestion, str)
    assert suggestion.strip()
    assert item["title"] in suggestion


def test_suggest_outfit_uses_llm_text_when_available(monkeypatch):
    monkeypatch.setattr(
        "tools._call_groq",
        lambda *args, **kwargs: "Pair it with the baggy straight-leg jeans and chunky white sneakers.",
    )
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]

    suggestion = suggest_outfit(item, get_example_wardrobe())

    assert "baggy straight-leg jeans" in suggestion


def test_create_fit_card_empty_outfit_returns_error_message():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]

    fit_card = create_fit_card("", item)

    assert fit_card == "I need an outfit suggestion before I can create a fit card."


def test_create_fit_card_uses_llm_text_when_available(monkeypatch):
    monkeypatch.setattr(
        "tools._call_groq",
        lambda *args, **kwargs: "Thrifted the tee on depop for $24. Baggy denim, chunky sneakers, done.",
    )
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]

    fit_card = create_fit_card("Pair it with baggy jeans and chunky sneakers.", item)

    assert "Thrifted the tee" in fit_card


def test_agent_no_results_stops_before_fit_card(monkeypatch, tmp_path):
    monkeypatch.setenv("FITFINDR_STYLE_MEMORY", str(tmp_path / "style.json"))
    session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())

    assert session["error"]
    assert session["search_results"] == []
    assert session["selected_item"] is None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None


def test_compare_price_returns_assessment():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]

    assessment = compare_price(item)

    assert assessment["assessment"] in {"great deal", "fair price", "pricey", "unknown"}
    assert assessment["comparable_count"] > 0
    assert "median price" in assessment["reasoning"]


def test_check_trends_returns_matching_trend():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]

    trend = check_trends(item)

    assert trend["trend_name"] == "Neo Nostalgia"
    assert trend["matched_terms"]
    assert "Depop 2026 Trend Forecast" in trend["source"]


def test_style_profile_memory_persists_between_sessions(monkeypatch, tmp_path):
    memory_path = tmp_path / "style_profile.json"
    monkeypatch.setenv("FITFINDR_STYLE_MEMORY", str(memory_path))

    first_profile = update_style_profile(
        "I mostly wear baggy jeans and chunky sneakers.",
        get_empty_wardrobe(),
    )
    second_profile = load_style_profile()

    assert memory_path.exists()
    assert first_profile == second_profile
    assert any("baggy jeans" in preference for preference in second_profile["preferences"])


def test_retry_logic_with_loosened_constraints(monkeypatch, tmp_path):
    monkeypatch.setenv("FITFINDR_STYLE_MEMORY", str(tmp_path / "style.json"))
    monkeypatch.setattr(
        "tools._call_groq",
        lambda *args, **kwargs: "Use the saved streetwear preference and the trend context.",
    )

    session = run_agent("90s track jacket size XS under $50", get_example_wardrobe())

    assert session["error"] is None
    assert session["retry_note"] == "No exact matches, so I retried without the size filter."
    assert session["selected_item"]["title"] == "90s Track Jacket — Navy/White Stripe"
    assert session["fit_card"]
