# FitFindr

FitFindr is a multi-tool AI agent for secondhand shopping. It searches a mock resale dataset, retries when the exact search is too narrow, compares prices, checks a trend snapshot, remembers style preferences across sessions, suggests an outfit, and generates a short shareable fit card.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the repo root:

```bash
GROQ_API_KEY=your_key_here
```

Run tests:

```bash
python -m pytest tests/
```

Run the app:

```bash
python app.py
```

Open the local URL printed in the terminal.

## Tool Inventory

### `search_listings(description: str, size: str | None = None, max_price: float | None = None) -> list[dict]`

Purpose: searches `data/listings.json` for resale items that match the user's request.

Inputs:
- `description` (`str`): item keywords, such as `"vintage graphic tee"`.
- `size` (`str | None`): optional size filter, such as `"M"`, `"S"`, `"US 8"`, or `"W30"`.
- `max_price` (`float | None`): optional maximum price.

Output: a list of matching listing dictionaries sorted by relevance. Each listing includes `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`. If nothing matches, the function returns `[]`.

### `suggest_outfit(new_item: dict, wardrobe: dict) -> str`

Purpose: suggests one or two complete outfit ideas for the selected listing.

Inputs:
- `new_item` (`dict`): one listing selected from `search_listings`.
- `wardrobe` (`dict`): a wardrobe object with an `items` list. The agent may also attach `_style_profile` and `_trend_info` context before calling this tool.

Output: a non-empty outfit suggestion string. If the wardrobe has items, the suggestion names specific pieces from the wardrobe. If the wardrobe is empty, it gives general styling advice.

### `create_fit_card(outfit: str, new_item: dict) -> str`

Purpose: turns the outfit suggestion into a short caption for sharing the look.

Inputs:
- `outfit` (`str`): the suggestion returned by `suggest_outfit`.
- `new_item` (`dict`): the selected listing.

Output: a 2-4 sentence caption-style string. If `outfit` is empty, the function returns `"I need an outfit suggestion before I can create a fit card."`

### `compare_price(new_item: dict) -> dict`

Purpose: estimates whether the selected listing is a good price based on comparable listings in the dataset.

Input:
- `new_item` (`dict`): the selected listing.

Output: a dictionary with `assessment`, `item_price`, `average_comparable_price`, `median_comparable_price`, `comparable_count`, `comparable_titles`, and `reasoning`. Comparables are listings in the same category with overlapping style tags or colors.

### `update_style_profile(query: str, wardrobe: dict) -> dict`

Purpose: remembers the user's style preferences across sessions.

Inputs:
- `query` (`str`): the user's current request.
- `wardrobe` (`dict`): the current wardrobe object.

Output: a dictionary with saved `preferences`, recurring `style_tags`, and `last_query`. It persists to `.fitfindr_style_profile.json`, which is ignored by git.

### `load_style_profile() -> dict`

Purpose: loads the saved style profile from disk so later sessions can use it without re-entry.

Output: a dictionary with `preferences`, `style_tags`, and `last_query`. If no file exists, it returns an empty profile.

### `check_trends(new_item: dict) -> dict`

Purpose: matches the selected item to a 2026 secondhand trend snapshot.

Input:
- `new_item` (`dict`): the selected listing.

Output: a dictionary with `trend_name`, `source`, `source_url`, `matched_terms`, and `styling_angle`. The trend snapshot uses Depop's 2026 trend categories as summarized by Who What Wear: https://www.whowhatwear.com/fashion/shopping/depop-trend-predictions-2026.

## Planning Loop

The planning loop is implemented in `run_agent(query, wardrobe)`.

1. Create a new session dictionary.
2. Parse the user query into `description`, `size`, and `max_price`.
3. Update/load style memory with `update_style_profile(query, wardrobe)` and store it in `session["style_profile"]`.
4. Call `search_listings(description, size, max_price)`.
5. If the exact search returns no results, retry automatically with loosened constraints:
   - retry without size if size was provided;
   - retry without max price if max price was provided;
   - retry without both if both filters existed.
6. Store any retry explanation in `session["retry_note"]`.
7. If all searches return no results, set `session["error"]` and return immediately.
8. If results exist, select the first result and store it in `session["selected_item"]`.
9. Call `compare_price(selected_item)` and store the result in `session["price_assessment"]`.
10. Call `check_trends(selected_item)` and store the result in `session["trend_info"]`.
11. Attach style memory and trend context to a copy of the wardrobe.
12. Call `suggest_outfit(selected_item, contextual_wardrobe)`.
13. Store the returned string in `session["outfit_suggestion"]`.
14. If the outfit string is blank, set `session["error"]` and return.
15. Call `create_fit_card(outfit_suggestion, selected_item)`.
16. Store the caption in `session["fit_card"]` and return the session.

The key branch is after search. A successful search continues through price, trend, memory-aware styling, and fit card tools. An empty exact search triggers retries before the agent gives up.

## State Management

The session dictionary is the single state object for one interaction:

- `query`: original user query.
- `parsed`: extracted `description`, `size`, and `max_price`.
- `search_results`: list returned by exact search or fallback search.
- `selected_item`: top listing result; passed into price comparison, trend check, outfit suggestion, and fit card.
- `price_assessment`: result from `compare_price`.
- `trend_info`: result from `check_trends`; passed into outfit generation.
- `style_profile`: saved preferences loaded/updated by `update_style_profile`.
- `retry_note`: explanation when the search had to loosen constraints.
- `wardrobe`: selected example or empty wardrobe.
- `outfit_suggestion`: text returned by `suggest_outfit`.
- `fit_card`: caption returned by `create_fit_card`.
- `error`: message set when the flow stops early.

The selected listing flows from search to the downstream tools through `session["selected_item"]`. The outfit suggestion flows into `create_fit_card` through `session["outfit_suggestion"]`. Style memory persists outside the session in `.fitfindr_style_profile.json`, so a later interaction can use preferences saved from an earlier one.

## Error Handling

`search_listings`: if the exact search returns `[]`, the agent retries with loosened filters. If retries still return `[]`, the agent returns a message that explains the failed query and what to try next.

`suggest_outfit`: if the wardrobe is empty, it uses a general styling prompt. If Groq is unavailable or the LLM call fails, it returns a local fallback suggestion based on the item category, trend context, and saved style profile.

`create_fit_card`: if the outfit input is empty, it returns a clear message instead of raising an exception. If Groq fails, it creates a simple local caption from the selected item and outfit text.

`compare_price`: if no comparable listings exist, it returns an `"unknown"` assessment and explains that the dataset does not have enough comparable items.

`update_style_profile` / `load_style_profile`: if the memory file is missing or unreadable, FitFindr starts with an empty profile. If writing fails, the current session still uses the in-memory profile.

`check_trends`: if no specific trend matches, it returns the broader `"The Edited Self"` trend angle so styling can still use trend context.

Tested failure examples:
- `search_listings("designer ballgown", size="XXS", max_price=5)` returns `[]`.
- `run_agent("90s track jacket size XS under $50", wardrobe)` retries without size and finds the medium track jacket.
- `suggest_outfit(item, get_empty_wardrobe())` returns styling advice.
- `create_fit_card("", item)` returns the missing-outfit message.

## Stretch Features

Price comparison: `compare_price` compares the selected item's price with up to eight same-category listings that overlap in tags or colors. The app displays the assessment and reasoning in the listing panel.

Style profile memory: `update_style_profile` extracts phrases such as "I mostly wear baggy jeans and chunky sneakers" and recurring wardrobe tags, then stores them in `.fitfindr_style_profile.json`. A second interaction can use those saved preferences even if the user does not repeat them.

Trend awareness: `check_trends` uses a local 2026 trend snapshot based on Depop's forecast categories: Modern Uniforms, Neo Nostalgia, Everyday Ceremony, and Romanticized Sports. The matched trend is passed into `suggest_outfit`, so the outfit suggestion can reflect the trend angle.

Retry logic with fallback: if `search_listings` returns no exact results, the agent automatically retries with loosened size and/or price filters and tells the user what changed.

## Demo Suggestions

Use this for the required happy path:

```text
vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers.
```

This shows search, price comparison, trend match, style memory, outfit suggestion, and fit card.

Use this to show retry bonus:

```text
90s track jacket size XS under $50
```

The exact search fails because the track jacket is size M, then FitFindr retries without size and explains the adjustment.

Use this to show a hard failure:

```text
designer ballgown size XXS under $5
```

The agent tries the exact search and fallback searches, then gives a specific message about broadening the description, price, or size.

To show style memory, run the first query above, then run:

```text
white platform sneakers size 8
```

The listing panel will show saved style memory, and the outfit suggestion can use those remembered preferences without the user repeating them.

## Spec Reflection

The spec helped most with the planning loop. Writing the no-results branch before coding made it clear that the agent should stop after empty search attempts instead of calling the outfit and fit card tools with invalid input.

One implementation detail diverged from the original base plan: I added stretch tools after the required flow was working. That changed the order between search and outfit generation because the selected item now also flows into price comparison and trend awareness before styling.

## AI Usage

I used ChatGPT/Codex with the Tool 1 section of `planning.md` and the `tools.py` docstring to implement `search_listings`. I reviewed the output to make sure it used `load_listings()`, filtered price and size before scoring, and returned `[]` for no matches.

I used ChatGPT/Codex with the Planning Loop, State Management, and Architecture sections of `planning.md` to implement `run_agent()`. I revised the code to use lightweight regex parsing so the query extraction would be easy to test.

I used ChatGPT/Codex again after deciding to add stretch features. I directed it to add price comparison, style memory, trend awareness, and retry fallback while keeping the three required tool signatures intact. I reviewed the generated structure and kept the required `suggest_outfit(new_item, wardrobe)` signature by passing style and trend context through the wardrobe dictionary.
