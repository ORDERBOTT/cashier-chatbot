# Cashier Chatbot

An AI-powered restaurant cashier chatbot built with FastAPI, OpenAI, and Redis. It handles natural-language food ordering conversations through a browser-based chat UI — taking orders, answering menu and restaurant questions, applying modifiers, resolving ambiguous items via fuzzy matching, and pinging staff on demand.

---

## Table of Contents

- [Architecture](#architecture)
- [Conversation Flow](#conversation-flow)
- [Setup](#setup)
- [Adding Menu Data & Restaurant Info](#adding-menu-data--restaurant-info)
- [Running the Server](#running-the-server)
- [Project Structure](#project-structure)
- [Development Commands](#development-commands)

---

## Architecture

```
Browser (index.html)
    │  POST /api/bot/message
    ▼
ChatReplyService
    ├── StateResolver          — classifies the user's intent (GPT-4o-mini, JSON mode)
    │   └── StateVerifier      — double-checks low-confidence or invalid-transition results
    │
    └── StateHandlerFactory    — routes to the correct handler
            │
            ├── Greeting / Farewell / Misc / VagueMessage / HumanEscalation
            ├── RestaurantQuestionHandler  — answers from restaurant_context Redis key
            ├── MenuQuestionHandler        — answers from menu_context Redis key
            ├── PickupPingHandler          — signals order-ready status to frontend
            └── FoodOrderHandlerFactory
                    ├── FoodOrderStateResolver  — classifies the order sub-intent
                    └── Handlers
                            ├── new_order        — extract → fuzzy match → add to state
                            ├── add_to_order     — extract new items, merge into state
                            ├── modify_order     — change quantity / modifier on existing item
                            ├── remove_from_order
                            ├── swap_item        — atomic remove + add
                            └── cancel_order

Redis (per user_id)
    menu_context:{user_id}               — full menu text for menu Q&A
    menu_item_names:{user_id}            — comma-separated names for fuzzy matching
    restaurant_context:{user_id}         — restaurant info for restaurant Q&A
    restaurant_name_location:{user_id}   — name + address for greeting
```

**Key design decisions:**

- **Stateless backend** — the frontend sends the full conversation history and current order state with every request; the server holds no session.
- **Two-stage intent classification** — a fast primary classifier is checked by an independent verifier only when confidence is low or the state transition is invalid.
- **Fuzzy item matching** — user item names are matched against canonical menu names using RapidFuzz (WRatio scorer), with three outcomes: confirmed (≥ 70), ambiguous (multiple close matches), or not found (< 50).
- **All AI calls use `gpt-4o-mini`** in JSON mode with `temperature=0` for deterministic extraction, and `temperature=0.4–0.7` for natural-language replies.

---

## Conversation Flow

### Conversation states

| State | Trigger | Response |
|---|---|---|
| `greeting` | First message / hello | Welcome with restaurant name and location |
| `farewell` | Goodbye / thanks | Warm sign-off |
| `menu_question` | Questions about dishes, prices, allergens | Answered from menu context |
| `restaurant_question` | Hours, location, parking, seating | Answered from restaurant context |
| `food_order` | Placing or changing an order | Routed to food order sub-state |
| `pickup_ping` | "How long?" / "Is it ready?" | `pickup_ping: true` flag sent to frontend |
| `human_escalation` | "Can I speak to someone?" | `ping_for_human: true` flag — triggers staff popup |
| `vague_message` | Unclear intent | Clarifying question |
| `misc` | Off-topic chat | Brief reply + redirect |

### Food order sub-states

| Sub-state | Example |
|---|---|
| `new_order` | "I'll have a burger and a Coke" |
| `add_to_order` | "Also get me some fries" |
| `modify_order` | "Make the burger a double" |
| `remove_from_order` | "Actually drop the Coke" |
| `swap_item` | "Swap the Coke for a milkshake" |
| `cancel_order` | "Cancel everything" |

### Order confirmation flow

After each successful order update the bot asks "Is that all?". The next message is classified as `confirm`, `modify`, or `unclear` by a dedicated finalization classifier — bypassing the main intent pipeline entirely.

### Item matching

When a user names an item:

1. Exact case-insensitive match → confirmed immediately.
2. Fuzzy match score ≥ 70 with no close competitors → confirmed, name normalised to canonical menu name.
3. Multiple matches within 6 points of each other → bot asks "Did you mean X, Y, or Z?" and sets `has_pending_clarification: true`.
4. Best score < 50 → "I couldn't find that on our menu."

---

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)
- Redis (local or remote)
- An OpenAI API key

### Install

```bash
git clone <repo-url>
cd cashier-chatbot
uv sync
```

### Environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
REDIS_URL=redis://127.0.0.1:6379
ENVIRONMENT=development
```

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key (used for all AI calls) |
| `REDIS_URL` | Yes | Redis connection URL |
| `ENVIRONMENT` | No | `development` (default), `staging`, or `production` |

---

## Adding Menu Data & Restaurant Info

All data is stored in Redis, scoped per `user_id`. The default `user_id` used by the web UI is `"1"`.

### Menu items

Menu items are defined in `src/constants.py` as `MENU_ITEM_MAP`. Each entry follows this structure:

```python
"Item Name": {
    "description": "Short description of the item.",
    "price": 9.50,                              # float
    "modifiers": [                              # size / preparation options
        "Make it double (+£2.00)",
        "Make it gluten-free (+£1.00)",
    ],
    "add_ons": [                                # extras
        "Extra cheese (£1.00)",
        "Bacon (£1.50)",
    ],
},
```

To add, remove, or edit menu items, update `MENU_ITEM_MAP` in `src/constants.py`, then re-run the seed script.

### Restaurant context

The seed script (`scripts/seed_menu.py`) writes the restaurant name and address:

```python
RESTAURANT_NAME_LOCATION_STRING = "The Burger Joint, 123 Main St, Anytown, USA"
```

To answer questions about hours, parking, seating etc., set the `restaurant_context` key directly in Redis:

```bash
redis-cli SET "restaurant_context:1" "Opening hours: Mon–Sun 10am–10pm. Seating: 60 covers. Free parking at rear. Phone: 01234 567890."
```

Or extend `scripts/seed_menu.py` to write this key alongside the others.

### Seed the data

After any changes to `src/constants.py` or the seed script, run:

```bash
python scripts/seed_menu.py
```

This writes three Redis keys for `user_id = "1"`:

| Key | Content |
|---|---|
| `menu_context:1` | Full menu text with prices, descriptions, modifiers, and add-ons |
| `menu_item_names:1` | Comma-separated item names used for fuzzy matching |
| `restaurant_name_location:1` | Restaurant name and address shown in the greeting |

---

## Running the Server

```bash
uvicorn src.main:app --reload
```

Open `http://localhost:8000` in your browser. The chat UI is served from `templates/index.html`.

### API

`POST /api/bot/message`

**Request body:**

```json
{
  "user_id": "1",
  "latest_message": "I'll have a Classic Beef Burger please",
  "message_history": [],
  "order_state": null,
  "previous_state": null,
  "previous_food_order_state": null,
  "awaiting_order_confirmation": false,
  "has_pending_clarification": false
}
```

**Response:**

```json
{
  "chatbot_message": "Got it! I've added 1x Classic Beef Burger to your order. Is that all?",
  "order_state": { "items": [{ "name": "Classic Beef Burger", "quantity": 1, "modifier": null }] },
  "pickup_ping": false,
  "ping_for_human": false,
  "previous_state": "food_order",
  "previous_food_order_state": "new_order",
  "awaiting_order_confirmation": true,
  "has_pending_clarification": false
}
```

The frontend is responsible for maintaining state between turns and sending it back with each request.

**Response flags:**

| Flag | Effect |
|---|---|
| `pickup_ping: true` | Shows the "Order Placed" modal with order summary |
| `ping_for_human: true` | Shows the "Cashier Called" staff popup |
| `has_pending_clarification: true` | Order state not updated yet; bot is waiting for user input |
| `awaiting_order_confirmation: true` | Next message goes directly to the finalization classifier |

---

## Project Structure

```
cashier-chatbot/
├── scripts/
│   ├── seed_menu.py          # Seed menu + restaurant data into Redis
│   ├── create_app.py         # Scaffold a new src/<module> directory
│   └── init_ai.py            # Scaffold an src/ai/ module structure
│
├── src/
│   ├── main.py               # FastAPI app, lifespan, router registration
│   ├── config.py             # Pydantic settings (reads .env)
│   ├── database.py           # Async SQLAlchemy engine + session factory
│   ├── cache.py              # Redis async helpers (cache_get, cache_set, cache_delete)
│   ├── constants.py          # MENU_ITEM_MAP, MENU_CONTEXT_STRING
│   │
│   ├── chatbot/
│   │   ├── router.py                  # POST /api/bot/message
│   │   ├── service.py                 # ChatReplyService — top-level orchestrator
│   │   ├── chatbot_ai.py              # ChatbotAI — all OpenAI calls
│   │   ├── handlers.py                # StateHandlerFactory — one handler per ConversationState
│   │   ├── food_order_handlers.py     # FoodOrderHandlerFactory — order sub-state handlers + fuzzy matching
│   │   ├── state_resolver.py          # StateResolver + FoodOrderStateResolver
│   │   ├── prompts.py                 # All system prompts
│   │   ├── schema.py                  # BotMessageRequest, BotMessageResponse, OrderItem, …
│   │   ├── internal_schemas.py        # AI response schemas (IntentAnalysis, etc.)
│   │   ├── constants.py               # ConversationState, FoodOrderState enums
│   │   ├── exceptions.py              # AIServiceError, UnhandledStateError, …
│   │   └── exception_handlers.py      # FastAPI exception handler registration
│   │
│   └── menu/                          # Scaffolded module — ingestion endpoint stub
│
├── templates/
│   └── index.html            # Browser chat UI (vanilla JS, no build step)
│
├── tests/
├── pyproject.toml            # Dependencies + project metadata (uv)
├── alembic.ini
└── .env                      # Local environment variables (do not commit)
```

---

## Development Commands

```bash
# Run dev server
uvicorn src.main:app --reload

# Seed menu and restaurant data into Redis
python scripts/seed_menu.py

# Lint
ruff check .

# Lint and auto-fix
ruff check --fix .

# Format
ruff format .

# Run tests
pytest

# Scaffold a new app module under src/
python scripts/create_app.py <module_name>

# Database migrations (if wiring up SQLAlchemy models)
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
alembic current
```

---

## Real Conversation Testing

This repo ships with a validation suite built from **20 real Smash n Wings customer iMessage conversations**. The test runner replays each customer's messages through the chatbot one by one, then compares the final `order_state` against a hand-verified expected item list.

### Prerequisites

| Dependency | Why |
|---|---|
| **Redis** | The chatbot caches menu data and restaurant context per `user_id` |
| **OpenAI API key** | All intent classification and extraction calls go through `gpt-4o-mini` |
| **Python 3.13+ & uv** | Package management and runner |

### 1. Start Redis

If you have Docker installed:

```bash
docker run -d --name redis -p 6379:6379 redis:latest
```

Or if Redis is already running locally, just make sure it's reachable at `127.0.0.1:6379`.

### 2. Create a `.env` file

```env
OPENAI_API_KEY=sk-...
REDIS_URL=redis://127.0.0.1:6379
ENVIRONMENT=development
```

Firebase credentials (`FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY`, `RESTAURANT_ID`) are optional for local testing — the server will skip Firebase init if they are not set.

### 3. Install dependencies

```bash
uv sync
```

### 4. Seed menu data into Redis

```bash
uv run python scripts/seed_menu.py
```

This writes the menu context, item names, and restaurant info into Redis for `user_id = "1"`.

### 5. Start the server

```bash
uv run uvicorn src.main:app --reload
```

Verify it's running — open [http://localhost:8000](http://localhost:8000) in your browser. You should see the chat UI.

### 6. Run the Real Conversation Test

In the browser at `http://localhost:8000`:

1. Click the **Real Convo Test** button (orange, in the header bar).
2. The runner will replay all 20 conversations automatically:
   - Each customer message is sent to the bot one at a time.
   - The bot's response and order state update are shown in real time.
   - After all messages in a conversation are sent, the final order is validated.
3. A **PASS/FAIL** result banner appears after each conversation with a detailed item-by-item comparison.
4. After all 20 conversations, an overall summary shows how many passed.
5. Results are saved to `test_results/run_<timestamp>.txt`.

### What gets validated

The test checks the **final `order_state.items`** after all customer messages are sent. For each conversation it verifies:

- Every expected item is present (by fuzzy name match).
- Item quantities are correct.
- No unexpected extra items are in the order.

Modifiers are intentionally **not** validated — the LLM's modifier assignment is non-deterministic and many real customer requests (e.g. "well done", "light onions") don't map to defined menu modifier options.

### Test data

| File | Description |
|---|---|
| `data/real_conversations_validation.json` | 20 real conversations: customer messages + expected final items |
| `data/validation_test_set.json` | 4 synthetic scripted conversations (used by the **Run Tests** button) |

### Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/bot/real-convo-testing` | GET | Serves the real conversation test set |
| `/api/bot/auto-testing` | GET | Serves the synthetic test set |
| `/api/bot/save-test-results` | POST | Saves test run results to `test_results/` |

### Conversation coverage

The 20 conversations span a range of real ordering patterns:

- **Simple orders** — single items (fish sandwich, chicken sub, hot honey burger)
- **Multi-item orders** — 2–4 items in one message (burger + sub + fries + poppers)
- **Multi-turn orders** — customer adds items across separate messages
- **Modifier requests** — "no onions", "add bacon", "extra toasted", "double patty"
- **Quantity orders** — "3 chicken subs", "2 classic burgers"
- **Name + pickup** — customers provide names and request pickup times
- **Non-order messages** — greetings, "how long?", "ASAP", "sounds good"

---

## UI Regression Automation

This repo also includes a Selenium UI driver that replays user-only message flows in the browser UI and **keeps each flow window open** for manual validation.

### Install Selenium

```bash
uv add selenium
```

### Run the flows

1. Start the server:

```bash
uv run uvicorn src.main:app --reload
```

2. In a new terminal, run:

```bash
uv run python scripts/automated_testing.py --flows-file regression_user_flows.test_menu.json
```

The script will open **one new browser window per flow** and will not close them. Press `Ctrl+C` in the terminal when you're done reviewing, then close the browser windows.
