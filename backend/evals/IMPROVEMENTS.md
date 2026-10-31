# What the evaluation found, and what changed

Each row is a problem the tests found, the change made, and the measurement before and after.
Run `python -m evals --ai` to reproduce the "after" numbers (they are in `RESULTS.md`).

| # | Found by | Problem | Change | Before | After |
|---|---|---|---|---|---|
| 1 | Forecast backtest on real U Walk sales | The forecast (average of the same weekday over 4 weeks) was no better than simple baselines: it lags for weeks after a change in level, such as summer. | Forecast = last 7 days' average x the weekday's share of a normal week over 8 weeks (`app/forecast.py`). Approved by Yousef. | 26.4% error on the last 6 weeks (best simple baseline 23.8%) | 20.8%; synthetic store 8.0% -> 6.7% |
| 2 | Invoice eval, repeated reads | The reader sometimes wrote ingredient names slightly differently (for example with the unit), and the code then dropped every match on that invoice. | The answer schema only allows the restaurant's own ingredient names; tolerant lookup as a second guard (`app/agents/invoice.py`). | 4 of 21 invoice reads (two runs) lost their ingredient matches | 48/48 lines matched over 4 repeated reads of 3 invoices |
| 3 | Stock agent eval, "numbers not in the facts" check | Claude's briefing did its own arithmetic (for example 817 g, the honey amount before rounding, while the order says 900 g). | Prompt: copy numbers exactly from the facts, no own arithmetic (`app/agents/stock_agent.py`). | 2 numbers not in the facts, 1 run | 0 in 5 runs |
| 4 | Robustness test "Claude answers in the wrong shape" | Valid JSON of the wrong shape crashed the stock agent (server error). | Every Claude answer is checked against its schema; a wrong shape falls back to the rules (`app/agents/llm.py`). | Server error | Rules answer, 5 failure modes tested |
| 5 | Code review while writing the "Claude unreachable" test | The Claude client waited up to 10 minutes with 2 retries, so a slow API could freeze the cashier screen. | 30-second timeout, 1 retry, configurable (`RESTAURA_LLM_TIMEOUT`). | Up to 10 min | 30 s, then rules |
| 6 | Robustness tests on POS sales reports | A quantity like "two" caused a server error; a negative quantity silently added stock; a missing column gave an unclear message. | The whole report is checked before anything is recorded, with row-by-row messages (`app/sales_report.py`). | 500 error / wrong stock | Clear 400 message, stock unchanged (9 bad-file cases tested) |
| 7 | Code review during the eval | A menu item without a recipe never reduces stock, with no warning. | The stock agent warns about items with no recipe (`app/stock.py`). | Silent | Warned (scenario test) |
| 8 | Learning eval (stock, 30 simulated stores) | After the manager applied a suggestion, the agent counted the old edits again and suggested the same change twice: 29% of its suggestions were wrong. | Only evidence after the last applied lesson counts (`app/agents/stock_memory.py`). | 29% wrong suggestions | 0 of 158 wrong |
| 9 | Forecast backtest, synthetic and real U Walk sales | Two ways for the forecast to correct itself looked sensible: switching each day to the method closest lately, and correcting a steady lean. | Both tested and **rejected**: they made the error worse on both data sets. Kept as rows in `RESULTS.md`. Special days were built instead. | App 6.7% / 20.8% (switching 6.7% / 21.3%, lean 7.1% / 21.7%) | Special days on tagged days: 22.3% -> 11.8% |
| 10 | Data check eval, Claude asked about every flagged record | Claude alone called the correction of a typing slip a mistake, and called days imported twice "busy days" (more orders alone is not proof). | Rules settle what they are sure of; the twin-order fact is measured by code; Claude only gets the rest (`app/agents/data_check.py`). | Claude alone: 58 right, 1 wrong of 77 | Rules then Claude: 65 right, 0 wrong, 4x fewer Claude calls |
| 11 | Data check eval, learning with mistakes in the data | One count typed with a missing zero made the stock agent see waste that was not there, and hid the real waste. A day imported twice lifted the forecast. | Records that don't fit are held out of learning until the manager decides. | Forecast error 14.3%; real waste found in 3 of 30 stores | 6.3%; 16 of 30 stores |
| 12 | Tech review against the hackathon criteria | Wrong logins, staff PINs and the pairing code could be guessed without limit; installs were not pinned. | Lockout after 5 wrong tries (`app/throttle.py`); `requirements.lock` used by CI. | Unlimited guesses | 5 tries, then locked 15 minutes |

## Findings kept as they are

- **Cashier helper on the app's own sample data** ties the best-seller baseline (69.1% vs 69.5% hit@2). The sample data pairs
  items almost at random apart from one common add-on, so best sellers are already near the best possible answer. On a store
  whose customers pair items in their own way, learning from orders wins clearly (86.6% vs 62.1%). This is why the helper
  learns from the store's orders instead of using fixed rules.
- **Invoice reader on a covered quantity** says it can't read it rather than guessing (3/3). It could also have worked the
  quantity out from the line total; both count as correct, a wrong number would not.
- **Real invoices**: the five real photos are not in the repository (public) and their values have not been confirmed by a
  person yet, so they are not used as ground truth.
