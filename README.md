<div align="center">

<img src="assets/restaura-icon-rounded-224.png" alt="Restaura logo" width="112">

# Restaura

*Latin* **restaurare**, "to restore". Written Restaura in code and docs.

**AI agents that run the two jobs every restaurant forgets to do on a busy day:**<br>
**sell a little more at the cashier, and never run out of what you sell.**

![Status](https://img.shields.io/badge/status-in%20development-B8923F?style=for-the-badge&labelColor=2E3A1C)
![Tool-using agents](https://img.shields.io/badge/tool--using%20agents-stock%20%C2%B7%20overview%20%C2%B7%20staff-667A3E?style=for-the-badge&labelColor=2E3A1C)
![Learns](https://img.shields.io/badge/learns%20from-what%20happened-667A3E?style=for-the-badge&labelColor=2E3A1C)
![Human approval](https://img.shields.io/badge/manager%20approves-spend%20%26%20changes-B8923F?style=for-the-badge&labelColor=2E3A1C)

[The problem](#the-problem) · [The solution](#the-solution) · [Agents](#meet-the-agents) · [Evaluation](#evaluation) · [Run it](#run-it) · [Brand](#brand)

<img src="assets/restaura-banner.png" alt="Restaura: AI agents for the restaurant counter and the stock room" width="100%">

</div>

---

## The problem

A restaurant has two daily jobs that depend on someone remembering to do them.

- **At the cashier**, a good upsell only happens if the cashier thinks of it.
- **Behind the counter**, the manager has to work out from sales how much of each ingredient was used, notice what is running low, and place supplier orders in time.

When either step is missed, sales are lost or an item runs out in the middle of service.

## The solution

Restaura is a web app, responsive on laptop and phone, with an AI agent that **owns each process end to end**. The manager stays in control: agents act on their own for everything routine, and ask for approval only when money is spent or a record changes.

```mermaid
flowchart LR
    A[Order at the cashier] --> B[Cashier helper suggests add-ons]
    B --> C[Sale recorded]
    C --> D[Recipes turn items into ingredient use]
    D --> E[Estimated stock updates]
    E --> F{Below the manager's minimum?}
    F -- no --> G[Nothing to do]
    F -- yes --> H[Agent drafts the supplier order]
    H --> I[Manager approves in one tap]
    I --> J[Order emailed to the supplier]
    J --> K[Delivery logged from an invoice photo]
    K --> E
    E -. out of stock .-> B
```

## Meet the agents

### 1. Cashier helper
Works while the order is being taken.

- Suggests add-ons and upgrades that fit what is already in the order
- Hides items that are out of stock, so a customer is never sold what the kitchen can't make
- Shows the manager, in real time, what is helping sales

### 2. Stock-to-order agent
Works after the branch closes.

| Step | What the agent does | Who acts |
| --- | --- | --- |
| Read the day | Takes the day's sales from the POS | Agent |
| Convert | Uses each item's recipe to work out ingredient use | Agent |
| Track | Keeps an estimated stock level per ingredient | Agent |
| Notice | Flags ingredients below the minimum the manager set, or that will run out before the supplier can deliver | Agent |
| Draft | Writes the supplier order with quantities | Agent |
| Approve | One tap to approve or edit | **Manager** |
| Send | Emails the approved order to the supplier, or opens WhatsApp with the order typed in | Agent |
| Receive | Reads a photo of the supplier invoice to log the delivery (manual entry as a fallback) | Agent |
| Correct | A monthly physical count corrects the estimate | **Manager** |

### How the stock agent decides
The stock-to-order agent and the manager overview are real tool-using agents. Claude chooses which tool to call next (read the forecast, check stock, adjust a quantity, draft an order, finish), reads each result, and decides the next step. Code keeps ownership of the numbers.

```mermaid
flowchart LR
    R[Rules calculate quantities] --> L{Claude picks a tool}
    L --> T[Tool runs in code and returns facts]
    T --> L
    L -- adjust --> W["Change within 0.5x to 1.5x, never below use until delivery, with a reason"]
    W --> D[Draft order]
    L -- finish --> D
    D --> M[Manager reviews: changed lines are marked in orange]
    L -. no answer or error .-> F[Rules run the same tools in fixed order]
    F --> D
```

Every step is saved and shown on the manager's steps page, so the manager can see what the agent looked at and why it changed a number.

### One shared brain
Both agents read and write the same database. What the cashier sells drives what the stock agent orders, and what the stock agent knows has run out disappears from the cashier's screen.

### How the agents learn
Each agent keeps a record of what it did and what happened next, and uses it the next time. Code measures every number, and the manager decides: a lesson is a **suggestion with a reason**, never a silent change.

| Agent | Learns from | What it learns |
| --- | --- | --- |
| Forecast | Days the manager tags (Eid, payday, a promotion) | How much busier each kind of day is, so the next one is forecast higher and a busy day no longer skews the normal pattern. It also replays the last 4 weeks every day and shows its own error. |
| Stock | The manager's edits to its drafts, real delivery days, stock counts | Order that much more or less of an ingredient, a supplier's real delivery days, and ingredients used more than the recipes say. Shown on the Stock tab; applied only on **Apply**. |
| Staff | Past tips, their results and the manager's weekly reviews | What works for each person, and it stops repeating a tip that failed twice. |

**The data check runs first.** One wrong record can teach an agent a wrong lesson (a count typed as 240 instead of 2400, a day imported twice). Code flags records that don't fit, rules settle the clear cases (an extra zero, a day imported twice), Claude explains the rest using the facts and the Saudi calendar, and the manager decides. A flagged record is held out of learning until then. Nothing is deleted.

Learning is tested like everything else: each agent is run with learning on and off, and with the data check on and off, on the same data. Ideas that made results worse were tested and dropped (see [`backend/evals/IMPROVEMENTS.md`](backend/evals/IMPROVEMENTS.md)).

## More of the restaurant

These sections are built and share the same database. The manager overview is a tool-using agent when a key is set; the others run on rules today, and the most used ones become Claude agents next.

| Section | What it does |
| --- | --- |
| Manager overview | A tool-using agent that reads every section, can start the stock check, and ranks what needs the manager first with a short briefing |
| Forecast | Next 7 days of sales (recent level adjusted for the weekday, chosen by backtest), special days it learns from, its own weekly accuracy, tomorrow's prep and which ingredients will run out |
| Expenses | Monthly and one-off costs, supplier deliveries at cost, and estimated profit |
| Routines | Opening, mid-shift and closing checklists ticked on the cashier iPad |
| Staff | PIN clock-in on the cashier iPad, shifts, lateness and hours worked, a weekly manager review for everyone, and a Staff agent that gives each person a tip that fits them |
| Suppliers | Add, edit and remove suppliers; lead days feed the stock agent |
| Supplier messaging | Orders by email or WhatsApp |

## Principles

- **Agents own a process, humans own decisions.** Anything that spends money or changes a record waits for approval.
- **Grounded, not invented.** Agents work from the store's own sales, recipes and invoices.
- **Explainable.** Every suggestion and every order shows why it was made.

## Evaluation

Every agent is tested on data it has not seen and compared with a simple method a person could use instead.
One command runs it all and writes the report; CI runs it on every push.

```bash
cd backend
pip install -r requirements.lock && pip install --no-deps -e .   # the exact versions CI uses
python -m pytest          # 100 tests: features, robustness, and regression checks on the evaluation
python -m evals           # held-out evaluation, rules only (no key needed)
python -m evals --ai      # also the Claude path, with a small model to keep costs low
```

Latest run, from [`backend/evals/RESULTS.md`](backend/evals/RESULTS.md):

| Agent | Test | Simple method | Restaura |
| --- | --- | --- | --- |
| Cashier helper | Held-out week, store with its own pairing habits: one of 2 suggestions was really added | Best sellers 62.1% | Rules 86.6%, with Claude 88.2% |
| Forecast | Real U Walk sales, last 6 weeks, average error over the next 7 days (lower is better) | Same day last week 23.8% | 20.8% (previous method 26.4%) |
| Stock-to-order | Hand-worked scenario; 300 random stores | | 6/6 order lines exact; 100% recall and precision |
| Invoice reader | Drawn invoices with known values: clean, blurry, phone photo, smudged | | 100% of lines read right in every condition; never guessed a covered number |
| Forecast learning | Error on days the manager tagged (learning off vs on) | 22.3% | 11.8% |
| Stock learning | Order lines the manager still had to edit, 30 simulated stores x 10 weeks (off vs on) | 1146 | 388, with 0 of 158 suggestions wrong |
| Data check | Forecast error with days imported twice or only partly (no check vs check) | 14.3% | 6.3% |
| Data check | Records judged right out of 77 with known truth: rules alone / Claude alone / rules, then Claude | 59 / 58 (1 wrong) | 65, 0 wrong |

The manager app shows the latest results under **More › Agent evaluation**, and can run the checks again from there.
`python -m evals --with-tests` also records which tests passed, for that page.

What the tests found and what changed because of them: [`backend/evals/IMPROVEMENTS.md`](backend/evals/IMPROVEMENTS.md).

## Status

In development. Runs as a demo for one store, using sample data, test recipes and a built-in demo cashier screen. Real supplier invoices and menus are not stored in this public repository.

## Run it

**Just want to try it or record a demo?** See [`docs/DEMO.md`](docs/DEMO.md): the sign-in page has one-tap buttons in demo mode, and there is a 3-minute script.

```bash
cd backend
pip install -r requirements.lock && pip install --no-deps -e .
python -m uvicorn app.main:create_app --factory --port 8000
```

Open http://localhost:8000 and sign in. Each account gets its own screens:

| Account | Where it works | Screens |
| --- | --- | --- |
| `manager` | Any device, phone first | Today (overview), sales, supplier orders, stock, and under More: deliveries, forecast, expenses, routines, staff |
| `cashier` | Only on a device the manager paired as the cashier iPad | The cashier screen, staff clock-in and daily checklists |

Sample staff clock in on the iPad with PINs `1111` to `5555`. To pair the cashier iPad, sign in as the manager, tap **Pair a cashier iPad** and enter the 6-digit code on the iPad's sign-in page. Demo passwords come from `MANAGER_PASSWORD` and `CASHIER_PASSWORD` (see [`.env.example`](.env.example)); set your own before sharing the app. The app starts with sample data. Without `ANTHROPIC_API_KEY` the agents run in rules mode; set the key (see [`.env.example`](.env.example)) to switch them to Claude. Set `NIGHTLY_STOCK_CHECK=23:30` (store time) and the stock agent runs by itself after closing, so the draft orders are waiting for the manager's approval in the morning; nothing is sent without approval.


## Stack

| Layer | Technology |
| --- | --- |
| Backend | Python, FastAPI |
| Database | SQLite by default, PostgreSQL via `DATABASE_URL` |
| Web app | Responsive HTML, CSS and JavaScript served by the backend |
| Agents | Anthropic Claude API |

## Security

No keys or `.env` files are committed to this repository. The API key is supplied as an environment variable. See [`.gitignore`](.gitignore).

- **Guessing is slowed down.** After 5 wrong tries the same account from the same address is locked for 15 minutes, even for the right password. This covers the manager and cashier passwords, each staff PIN, the clock-in PIN and the iPad pairing code (`app/throttle.py`, in memory, one server process).
- **Passwords are salted and hashed** (PBKDF2); sessions are random tokens stored hashed; cookies are `HttpOnly` and `SameSite=Lax`. Set `SECURE_COOKIES=1` behind HTTPS.
- **Cashier accounts work only on an iPad the manager paired**, and a session ends if the iPad is unpaired.
- **The app warns at start-up** while the demo passwords are in use. Set `MANAGER_PASSWORD` and `CASHIER_PASSWORD`.
- **Claude never acts alone on money or records.** Its answers are checked against a schema, and a wrong shape falls back to the rules.

## Brand

<img src="assets/restaura-icon-rounded-224.png" alt="" width="72" align="left">

The mark is a serving cloche, the dome a restaurant lifts to present a dish, with a small AI spark. The wordmark is RESTAURA in capitals with MMXXVI (2026) below it, like a Roman plaque. Ivory `#FBFAF2` · Olive `#667A3E` · Brass `#B8923F` · Ink `#2E3A1C`, set in Josefin Sans. Files and rules are in [docs/BRAND.md](docs/BRAND.md).

<br clear="left">

---

<div align="center">

Built by **Yousef Samman**

</div>
