# NOTES

Fill in every field below before you submit. We read this file first: a submission with an empty field is not graded.
Write in your own words. If you did not fix something, set Status to `not fixed` and say what you found and tried; that still counts.
Status is one of: `fixed`, `partly fixed`, `not fixed`. Commits: the short hashes of the commits for this item, or `none`.

## 1. Report

> Finance says that on some days the revenue in the daily report is higher than what the payment provider paid out, and a few orders show more money received than their total.

**Status:** fixed

**What I saw:** Replaying the same successful webhook twice inserted two payment rows; a 1,200-cent payment was counted as 2,400 cents.

**Root cause:** The webhook handler inserted every delivery without checking its event ID, and the database did not enforce event-ID uniqueness.

**Fix and why:** Payment processing now runs in an immediate transaction, treats an identical event replay as a no-op, rejects reuse of an event ID with different details, and enforces unique event IDs in SQLite. Separate successful events are still recorded; any amount above the order total is surfaced as `overpaid` and exposed through `paid_cents` and `overpaid_cents` on the order.

**How I verified it:** The retry regression test confirms two identical deliveries produce one row and 1,200 cents total. A separate 500-cent payment after the order is paid returns `overpaid` and reports 500 cents excess. The full suite passes.

**Commits:** `090e8fe`

## 2. Report

> Products show as sold out, or nearly, while the shelf is full. Staff say it gets worse on days when many customers abandon checkout.

**Status:** fixed

**What I saw:** Creating an order reserved stock immediately. Cancelling an unpaid (pending) order left both the stock reservation and coupon use in place.

**Root cause:** Cancellation restored stock only when the order was already paid, even though pending orders reserve stock at creation.

**Fix and why:** Cancellation now restores reserved stock for pending as well as paid orders and rolls the operation back atomically on failure. Coupon usage is also returned. A checkout that remains pending must still be cancelled through the existing endpoint; this project has no automatic reservation-expiry job.

**How I verified it:** The regression test creates a pending order with a coupon, cancels it, and confirms stock and coupon usage return to their original values. The existing paid-order cancellation test also passes.

**Commits:** `95a0736`

## 3. Report

> Customers in taxed regions who used a coupon say the tax on their receipt is too high. Receipts without a coupon are right.

**Status:** fixed

**What I saw:** A 1,200-cent California order with a 10% coupon charged 87 cents tax instead of 78 cents.

**Root cause:** Pricing calculated tax on the pre-discount subtotal, then subtracted the coupon.

**Fix and why:** The discount is now computed before tax, and tax is applied to the discounted taxable subtotal.

**How I verified it:** A regression test asserts the 120-cent discount, 78-cent tax, and 1,158-cent total; no-coupon pricing tests still pass.

**Commits:** `b6229c0`

## 4. Report

> Our shop in India (UTC+5:30) says sales taken in the morning do not appear in that day's report and turn up under the day before.

**Status:** fixed

**What I saw:** A payment at 02:00 UTC on March 10 (07:30 in India) was excluded from the March 10 shop-local report.

**Root cause:** The report bounds added the UTC offset to local midnight instead of subtracting it to convert local midnight to UTC.

**Fix and why:** Daily report bounds now subtract the requested offset, so a UTC+05:30 local day starts at 18:30 UTC on the preceding date.

**How I verified it:** The regression test checks that the 02:00 UTC payment appears on the March 10 India report and not the March 9 report. The UTC report test also passes.

**Commits:** `458f92e`

## 5. Report

> Ever since we started running two server workers, we have sold more units of an item than we had, and its stock went negative.

**Status:** fixed

**What I saw:** Two catalog instances cached one remaining unit. After the first reserved it, the second still accepted a reservation from its stale stock value, allowing stock to go negative.

**Root cause:** Stock availability was checked against a per-process cache, followed by an unconditional decrement.

**Fix and why:** Catalog reads now query SQLite, and reservations use one conditional `UPDATE ... WHERE stock >= qty`. SQLite decides the winner atomically across workers; a failed update reports the current availability.

**How I verified it:** A regression test uses two independent connections and stale reads against the same SQLite file; the second reservation raises `OutOfStock` and stock remains zero. Existing stock and price tests pass.

**Commits:** `f34bf27`

## 6. Open question

> Open question from support, no single right answer: sometimes a customer really does pay twice for one order (two separate payments, not a retry of the same one). Today the system records both and says nothing. Decide what should happen, build the smallest version of your decision, and explain what it costs in `NOTES.md`.

**My decision:** Ignore exact webhook retries, but retain and flag distinct successful payments that exceed the order's balance so the excess can be refunded.

**Why:** A repeated provider event is not a second payment. A different event ID represents a separate successful charge and should not be silently discarded or misreported as ordinary payment.

**What it costs:** The project has no refund integration or operator queue. An overpayment is visible in the order response and webhook result, but someone must arrange the refund manually. Daily revenue continues to represent the money actually received until refunded.

**What I built:** Event IDs are unique and replay-safe. A distinct event that takes the cumulative amount above the order total is stored, returns `overpaid`, and is reflected in the order's `overpaid_cents`.

**How I verified it:** Regression tests prove a replay is counted once and a separate excess payment is recorded and flagged.

**Commits:** `090e8fe`

## Other things I noticed

Problems outside the reports: what, where, and whether you fixed them. Write `none` if there were none.

None outside the reported issues.

## Session logs

Which AI tools you used, and one line per file in `session_logs/`.

Used Copilot SDK in VS Code. No raw session-export tool was available in this environment; `session_logs/` currently contains only its README, so the required full session export still needs to be added from the VS Code chat export before submission.
