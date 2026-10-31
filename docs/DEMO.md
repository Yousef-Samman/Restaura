# Restaura demo: 3-minute script and how to run it

## Run it for the recording

```bash
cd backend
pip install -r requirements.lock && pip install --no-deps -e .
export RESTAURA_ANTHROPIC_API_KEY=sk-ant-...      # your key; never commit it. Without it the agents run in rules mode.
rm -f restaura.db                                  # a fresh start every time: the same sample data, no clicks left over
python -m uvicorn app.main:create_app --factory --port 8000
```

Open http://localhost:8000. The sign-in page has two buttons in demo mode, so nobody needs a password:

- **Open the manager app**: use a phone-sized window (about 390 px wide).
- **Open the cashier iPad**: use a window about 1024 x 768. It pairs this browser as the demo iPad and signs in as Sara.

Demo logins, if you prefer to type them: manager / `manager-demo`; on the iPad, Sara's PIN is `1111` (Omar 2222, Lina 3333, Faisal 4444, Huda 5555). `DEMO_MODE=0` turns the buttons off for a real store.

**Before you press record:** sign in as the manager, tap **Run stock check now** on Today, and wait about 25 seconds. The agent's draft order is then waiting on the Orders tab, so the video doesn't have to wait for Claude. Then sign out and start again from the top, or just open the second window.

All sample data is labelled as sample data in the app and in the README: the store's sales history, recipes, staff, suppliers (fictional `@example` addresses) and the deliberate mistakes in the data. The email goes to a log, not to anyone, unless you set `SMTP_*`.

## The script (about 2:55)

Say it at a calm pace: about 330 words. The times are targets.

| Time | Screen and action | Say |
| --- | --- | --- |
| 0:00 | Sign-in page. Tap **Open the manager app**. Today shows "Needs you". | "Every restaurant has two jobs that depend on someone remembering: sell a little more at the counter, and never run out of what you sell. Restaura is a set of AI agents that own those jobs, and a manager who stays in charge." |
| 0:20 | Switch to the iPad window (already open as the cashier). Tap **Hazelnut crepe**, then **Next: AI suggestions**. | "At the counter, the cashier helper reads the order and suggests what this customer is likely to add." |
| 0:35 | Tap **+ Add** on the Spanish latte. Go to payment. Tap **NearPay**, then **Simulate a card tap**. | "One tap, a bigger order, and it's paid. We measured it on held-out orders: it picks the right add-on far more often than just suggesting best sellers." |
| 0:55 | Manager window. Tap **Orders**. Show the orange card from the stock agent. Tap a changed line: old number crossed out, reason underneath. | "After closing, the stock agent works out what to order. Claude chooses which tool to use next: the forecast, the stock, the supplier lead times. But the code owns every number. When Claude changes a quantity, it must give a reason, and you see the old number crossed out." |
| 1:20 | Tap **Approve and send**, choose **WhatsApp**, send. | "Nothing is sent without the manager. One tap, and the order goes to the supplier on WhatsApp or email." |
| 1:30 | **Stock** tab. Show "What the stock agent has learned": **Order 20% more milk**. Tap **Apply**. | "Now the part that matters. The agent learns. This manager raised milk on three of the last four orders, so the agent suggests ordering more from now on, with the reason. It never changes anything until the manager taps Apply." |
| 1:50 | **More › Forecast**. Scroll to **Special days**: Promotion, 43% busier. | "The forecast learns too. The manager tags promotions, and it learns how much busier they are, so the next one is forecast higher." |
| 2:05 | Scroll up to the card **Check before the agents learn**: "102 of the 102 orders have an identical twin." Tap **It's a mistake, leave it out**. | "But an agent that learns from bad data learns the wrong lesson. So before they learn, code flags records that don't fit. This day was imported twice. The rules catch that one, and Claude explains the cases the rules can't settle: this other day stopped at 3 pm. The manager decides. Nothing is deleted." |
| 2:30 | **More › Agent evaluation**. Scroll to "Learning, and checking the data first". | "We test everything on data the agents haven't seen. Learning cuts the forecast error on promotion days from 22% to 12%. The data check cuts the forecast error from 14% to 6% when data is wrong, and rules plus Claude judged 65 of 77 records right with none wrong, better than Claude alone." |
| 2:50 | Back to Today, or the logo. | "Restaura. Agents that learn, a manager who decides." |

## Notes for the recording

- **What is an agent and what is not.** Three are real tool-using agents (stock, manager overview, staff). The cashier helper, invoice reader and data check are single Claude calls. The forecast, expenses and routines are code. Don't call them all "agents" on camera; the script above doesn't.
- **If Claude is slow or down,** the app falls back to the rules by itself and says so ("run by the rules"). That is also a robustness point worth one sentence.
- **The numbers** (22% to 12%, 14% to 6%, 65 of 77) come from `backend/evals/RESULTS.md`; re-run `python -m evals --ai` and change the script if they move.
- **If you want the manager overview** (a fourth beat), tap **Brief me now** on Today. It takes about 20 seconds with Claude, so it doesn't fit in 3 minutes without cutting.
- **Judging criteria to hit:** unseen-data results (the evaluation page), robustness (the fallback line), evaluation and iteration (learning on vs off), technical judgment (rules first, Claude for the rest, code owns numbers), engineering quality (100 tests, CI, lock file) and communication (this video).
