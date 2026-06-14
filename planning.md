# FitFindr - planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation - the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed - add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock secondhand listings dataset for items that match the user's natural language description, optional size, and optional max price. It applies price and size filters first, then ranks the remaining listings by keyword relevance.

**Input parameters:**
- `description` (str): Keywords or phrase describing the item the user wants, such as `"vintage graphic tee"` or `"90s track jacket"`.
- `size` (str | None): Optional size filter extracted from the query, such as `"M"`, `"S"`, `"US 8"`, or `"W30"`. If `None`, the tool does not filter by size.
- `max_price` (float | None): Optional price ceiling in dollars. If `None`, the tool does not filter by price.

**What it returns:**
A `list[dict]` of matching listing dictionaries sorted by relevance. Each result contains the original listing fields: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`. If no listing matches, the return value is an empty list `[]`.

**What happens if it fails or returns nothing:**
The tool returns `[]` and does not raise an exception for no matches. The agent checks for an empty result list, writes a helpful no-results message to `session["error"]`, and stops before calling the outfit and fit card tools.

---

### Tool 2: suggest_outfit

**What it does:**
Given the selected thrift listing and the user's wardrobe, asks the LLM to suggest one or two complete outfits. If the user's wardrobe is empty, it gives general styling advice using common closet basics instead of failing.

**Input parameters:**
- `new_item` (dict): One listing dictionary selected by the agent from `search_listings`.
- `wardrobe` (dict): A wardrobe object with an `items` key. Each wardrobe item may include `id`, `name`, `category`, `colors`, `style_tags`, and `notes`.

**What it returns:**
A non-empty `str` with practical outfit suggestions. With the example wardrobe, the output should name specific wardrobe pieces. With an empty wardrobe, the output should suggest common pieces that would work with the selected item.

**What happens if it fails or returns nothing:**
If `wardrobe["items"]` is empty, the tool switches to a general styling prompt. If the LLM call fails or returns blank text, the tool returns a local fallback suggestion based on the selected item's category and tags.

---

### Tool 3: create_fit_card

**What it does:**
Generates a short, shareable outfit description from the selected item and outfit suggestion. The result should read like a casual social caption, not a product description.

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by `suggest_outfit`.
- `new_item` (dict): The selected listing dictionary used throughout the session.

**What it returns:**
A `str` containing a 2-4 sentence fit card/caption. It should mention the selected item, price, platform, and outfit vibe naturally.

**What happens if it fails or returns nothing:**
If `outfit` is empty or only whitespace, the tool returns `"I need an outfit suggestion before I can create a fit card."` If the LLM fails, the tool returns a simple local caption assembled from the item and outfit details.

---

### Additional Tools (if any)

### Tool 4: compare_price

**What it does:**
Compares the selected listing's price against comparable listings in the mock dataset. Comparable listings are items in the same category with overlapping style tags or colors.

**Input parameters:**
- `new_item` (dict): The selected listing dictionary.

**What it returns:**
A `dict` with `assessment` (`"great deal"`, `"fair price"`, or `"pricey"`), `item_price`, `average_comparable_price`, `median_comparable_price`, `comparable_count`, `comparable_titles`, and `reasoning`.

**What happens if it fails or returns nothing:**
If there are no comparable listings, it returns an `"unknown"` assessment with a reasoning string explaining that there were not enough comparable items.

---

### Tool 5: update_style_profile

**What it does:**
Stores lightweight style preferences across sessions so later requests can use them without the user re-entering the same wardrobe/style context.

**Input parameters:**
- `query` (str): The user's current request.
- `wardrobe` (dict): The current wardrobe dict.

**What it returns:**
A `dict` containing saved `preferences`, frequent `style_tags`, and the most recent source query. The profile is persisted in `.fitfindr_style_profile.json`.

**What happens if it fails or returns nothing:**
If the profile file cannot be read, the tool starts with an empty profile. If it cannot write the profile, it still returns the in-memory profile for the current session.

---

### Tool 6: check_trends

**What it does:**
Matches the selected listing against a local snapshot of 2026 secondhand/fashion trend categories. The snapshot is based on Depop's 2026 Trend Forecast as summarized by Who What Wear.

**Input parameters:**
- `new_item` (dict): The selected listing dictionary.

**What it returns:**
A `dict` with `trend_name`, `source`, `matched_terms`, and `styling_angle`. The trend information is later passed into `suggest_outfit` through the session's wardrobe context.

**What happens if it fails or returns nothing:**
If no specific trend matches, it returns a general `"The Edited Self"` trend angle focused on intentional, personal styling.

---

## Planning Loop

**How does your agent decide which tool to call next?**
The planning loop is implemented in `run_agent(query, wardrobe)`. It does not call every tool unconditionally; it branches based on the state after each step.

1. Create a new session dict with the original query and wardrobe.
2. Parse the query into:
   - `description`: the remaining item description after price and size phrases are removed.
   - `size`: a size token after "size" or a simple standalone size token.
   - `max_price`: the first dollar amount or "under N" price found in the query.
3. Store those parsed values in `session["parsed"]`.
4. Load/update style memory with `update_style_profile(query, wardrobe)` and store it in `session["style_profile"]`.
5. Call `search_listings(description, size, max_price)`.
6. Store results in `session["search_results"]`.
7. If results are empty, retry automatically with loosened constraints:
   - First retry without the size filter if a size was provided.
   - If needed, retry without the max price filter.
   - If needed, retry without both size and max price filters.
   Store what changed in `session["retry_note"]`.
8. If all searches are empty, set `session["error"]` to a message that explains the exact search and retry attempts. Return the session immediately.
9. If results exist, set `session["selected_item"] = results[0]`.
10. Call `compare_price(session["selected_item"])` and store the result in `session["price_assessment"]`.
11. Call `check_trends(session["selected_item"])` and store the result in `session["trend_info"]`.
12. Add `style_profile` and `trend_info` to a copy of the wardrobe context, then call `suggest_outfit(session["selected_item"], contextual_wardrobe)`.
13. Store the returned string in `session["outfit_suggestion"]`.
14. If the outfit string is empty, set `session["error"]` and return early.
15. Call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`.
16. Store the returned caption in `session["fit_card"]`.
17. Return the completed session.

The main conditional decision is after `search_listings`: no results triggers retries with loosened constraints, while valid results continue to price comparison, trend awareness, style memory, styling, and fit card generation.

---

## State Management

**How does information from one tool get passed to the next?**
The agent stores everything for one user interaction in a session dictionary. This lets output from one tool become input to the next tool without asking the user to re-enter information.

Session fields:
- `session["query"]`: original user query.
- `session["parsed"]`: dictionary with `description`, `size`, and `max_price`.
- `session["search_results"]`: list returned by `search_listings`.
- `session["selected_item"]`: first listing result; passed to both later tools.
- `session["price_assessment"]`: output from `compare_price`.
- `session["trend_info"]`: output from `check_trends`, passed into outfit generation.
- `session["style_profile"]`: saved style preferences loaded from prior sessions and updated from the current query.
- `session["retry_note"]`: explanation of any loosened search retry.
- `session["wardrobe"]`: wardrobe selected by the user in the interface.
- `session["outfit_suggestion"]`: string returned by `suggest_outfit`.
- `session["fit_card"]`: final caption returned by `create_fit_card`.
- `session["error"]`: user-facing error message when the agent stops early.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Retry with loosened constraints first. If retries still fail, store `[]`, set `session["error"]` to a message explaining the exact filters that were loosened, and return before calling later tools. |
| suggest_outfit | Wardrobe is empty | The tool uses a general styling prompt for the selected item. If the LLM is unavailable, it returns a local fallback suggestion with common outfit pieces. |
| create_fit_card | Outfit input is missing or incomplete | Return `"I need an outfit suggestion before I can create a fit card."` instead of raising an exception. |
| compare_price | Not enough comparable listings | Return an `"unknown"` assessment and explain that the dataset does not contain enough comparable items. |
| update_style_profile | Memory file missing or unreadable | Start from an empty profile; if writing fails, return the current in-memory profile without crashing. |
| check_trends | No exact trend match | Return the general `"The Edited Self"` trend angle so the outfit can still use trend context. |

---

## Architecture

```text
User query + wardrobe choice
    |
    v
Gradio handle_query()
    |
    v
run_agent(query, wardrobe)
    |
    v
Session state initialized
    |
    v
Parse query -> session["parsed"]
    |
    v
update_style_profile(query, wardrobe)
    |
    v
session["style_profile"] = saved preferences
    |
    v
search_listings(description, size, max_price)
    |
    +-- results == [] -------------------------------+
    |                                                |
    v                                                v
retry search with loosened filters       if retries fail:
    |                                    session["error"] = no-results message
    v                                                 |
results found or []                                   v
                                             Return session early

Successful path:

search_listings returns [item, ...]
    |
    v
session["search_results"] = [item, ...]
session["selected_item"] = item
    |
    v
compare_price(selected_item)
    |
    v
session["price_assessment"] = assessment
    |
    v
check_trends(selected_item)
    |
    v
session["trend_info"] = trend
    |
    v
suggest_outfit(selected_item, wardrobe + style/trend context)
    |
    v
session["outfit_suggestion"] = outfit text
    |
    v
create_fit_card(outfit_suggestion, selected_item)
    |
    v
session["fit_card"] = caption
    |
    v
Return session to UI
    |
    v
Display listing, outfit idea, and fit card
```

---

## AI Tool Plan

**Milestone 3 - Individual tool implementations:**
I will give ChatGPT/Codex each tool spec from this document plus the matching `tools.py` docstring. I expect it to implement one function at a time using the existing `load_listings()` helper and Groq client. I will verify `search_listings` with successful, empty, price-filter, and size-filter examples before connecting it to the agent.

**Milestone 4 - Planning loop and state management:**
I will give ChatGPT/Codex the Planning Loop, State Management, and Architecture sections. I expect it to implement `run_agent()` so it stores parsed values and tool outputs in the session dict, branches after empty search results, and passes `selected_item` and `outfit_suggestion` into later tools.

**Milestone 5 and 6 - Testing, UI, and documentation:**
I will use ChatGPT/Codex to draft pytest cases and README sections from the finished implementation. I will revise the output so the documented signatures match the actual code, then run `pytest`, `python agent.py`, and a Gradio handler smoke test.

**Stretch features - Bonus tools:**
Before starting stretch work, I will update the Additional Tools, Planning Loop, State Management, Error Handling, and Architecture sections of this document. Then I will use ChatGPT/Codex to help implement one stretch feature at a time: `compare_price`, `update_style_profile`, `check_trends`, and retry fallback. I will verify each feature with a focused pytest case and by checking the Gradio listing panel shows the extra state.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish - tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
The agent parses the query into `description="vintage graphic tee mostly wear baggy jeans chunky sneakers"`, `size=None`, and `max_price=30.0`. It stores those values in `session["parsed"]`.

**Step 2:**
The agent calls `update_style_profile(query, wardrobe)` to save the user's "baggy jeans and chunky sneakers" preference. Then it calls `search_listings("vintage graphic tee mostly wear baggy jeans chunky sneakers", size=None, max_price=30.0)`. The search tool filters out listings above $30, scores the remaining listings, and returns matching graphic tee listings.

**Step 3:**
The agent stores the search results in `session["search_results"]` and chooses the first result as `session["selected_item"]`. It then calls `compare_price(session["selected_item"])` and `check_trends(session["selected_item"])`.

**Step 4:**
The agent stores those bonus outputs in `session["price_assessment"]`, `session["trend_info"]`, and `session["style_profile"]`. It attaches style memory and trend context to the wardrobe copy, then calls `suggest_outfit(session["selected_item"], contextual_wardrobe)`.

**Step 5:**
The outfit tool uses the selected item, wardrobe pieces such as baggy straight-leg jeans and chunky white sneakers, saved preferences, and trend context to generate a complete outfit suggestion. The agent stores the returned string in `session["outfit_suggestion"]`.

**Step 6:**
The agent calls `create_fit_card(session["outfit_suggestion"], session["selected_item"])`. The fit card tool returns a short caption mentioning the thrifted item, price, platform, and styling vibe.

**Final output to user:**
The UI shows the selected listing, retry note if any, price assessment, trend match, and style memory in the first panel. It shows the outfit suggestion in the second panel and the fit card caption in the third panel. If exact search had returned no results, the agent would retry with loosened constraints before returning an error.
