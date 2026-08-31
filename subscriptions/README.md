# Subscriptions — vendor membership plans

An admin builds a catalogue of tiers (Free, Silver, Gold). New vendors land on
the free one, see what they are on in the app, and can ask to move up.

**Nothing charges anybody.** The price on a plan is a label. Terms are granted
by hand, and money taken offline is typed onto the subscription row — the same
arrangement as the rest of the payments side, which holds no float of its own.
Wiring a gateway to this later means creating the subscription after a
successful capture instead of from a dashboard form; nothing else changes.

**Nothing is gated on a plan either.** A vendor with no subscription gets jobs,
bids on tenders and takes payouts exactly like a vendor on Gold. The one place
anything should ever ask the question is:

```python
VendorSubscription.objects.active_for(vendor)   # -> subscription or None
```

Gating a feature is a matter of calling that and acting on the answer.

## Who gets a plan, and how

```
signup ──> free default tier (ensure_default_subscription)
             │
             ├─ picked a paid tier on the signup screen?
             │     └──> SubscriptionUpgradeRequest (PENDING)
             │
             └─ tapped Upgrade in the app later?
                   └──> SubscriptionUpgradeRequest (PENDING)
                             │
                    admin answers in the dashboard
                       ├─ approve ──> assign_plan() starts the term
                       └─ reject  ──> nothing changes
```

A vendor **never grants themselves a tier.** Nothing charges them, so a
self-served upgrade would be a giveaway — and whoever is sitting on Gold the
day payments go live would be sitting there for free. They ask; an admin
decides; approving is what starts the term.

Vendors who registered before plans existed are caught up with:

```
python manage.py backfill_free_subscriptions --dry-run   # count first
python manage.py backfill_free_subscriptions
```

It creates a free `Free` plan if the catalogue has no default, skips anyone
already on a live plan, and refuses outright if the default tier costs money.
Safe to run again whenever.

## The models

**`SubscriptionPlan`** — a tier. `price` of 0 makes it free. `billing_period`
sets how long one term runs (30 / 90 / 180 / 365 days, or `LIFETIME` for a term
with no end date at all). `is_default` marks the tier new vendors should land
on and is a single seat: setting it on one plan takes it off whichever plan
held it before.

**`VendorSubscription`** — one vendor's term on one plan. A vendor collects
these over time; the history is kept and never rewritten.

**`SubscriptionUpgradeRequest`** — a vendor asking to be moved. One open
request at a time, so the admin queue stays meaningful. `quoted_price` freezes
what the tier cost when they asked, so a later price change cannot rewrite the
offer they were looking at.

```
                    assign_plan()
   (no plan) ─────────────────────────> ACTIVE ──end_date passes──> EXPIRED
                                          │  ▲                          │
                              cancel()    │  └──────────────────────────┘
                                          ↓        renew() / assign_plan()
                                      CANCELLED
```

## One live plan per vendor

`active()` — and its row-level twin `is_active` — mean *marked ACTIVE, started,
and not past the end date*. A lapsed row stays `ACTIVE` in the database until
something sweeps it, so the date window is always checked as well. The
dashboard calls `VendorSubscription.objects.expire_due()` when the subscriber
pages are opened, which is why there is no cron.

`assign_plan()` cancels everything the vendor holds before creating the new
term — the running one *and* any renewal queued behind it. A queued term left
in place would quietly put them back on the old plan weeks later.

## Renewing vs changing plan

These are different operations and go down different paths:

- **`renew(subscription)`** — another term on the *same* plan. A term still
  running is picked up the day after it ends and left **queued**: the running
  term stays live and the new one takes over on its own once `expire_due()`
  closes the old one. Renewing early costs the vendor nothing and never drops
  them off the plan mid-term. Refused if a renewal is already queued, if the
  vendor has since moved to another plan, or if the plan never expires.
- **`assign_plan(vendor, plan)`** — a *different* plan, starting now. Clears
  the board first, as above.

## Endpoints

Under `/api/subscriptions/`. A vendor can ask for a plan; only an admin can
grant one.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/plans/` | open | Active tiers. Open, so the signup screen can show them before an account exists |
| GET | `/me/` | vendor | `{current, pending_request, plans, history}` — the whole subscription screen in one call |
| POST | `/upgrade-requests/` | vendor | `{plan, note}` — ask to move. Changes nothing until an admin approves |
| GET | `/upgrade-requests/` | vendor | Their own requests |
| POST | `/upgrade-requests/<id>/withdraw/` | vendor | Take back an unanswered request |

`POST /api/vendors/signup/` also accepts an optional `plan`. It never grants
that plan: the vendor lands on the free default either way, and anything above
it becomes a request.

`current` is `null` when a vendor holds nothing. Normal, not an error — though
once a free tier is the default, only pre-backfill vendors will see it.

## Dashboard

| Page | URL name |
|---|---|
| Plan catalogue | `subscription_plans_list` |
| Add / edit plan | `subscription_plan_add`, `subscription_plan_edit` |
| Subscribers, plus a tab for vendors on no plan | `subscribers_list` |
| One vendor: current plan, assign, renew, cancel, history | `vendor_subscription` |
| Upgrade request queue (sidebar badge shows the pending count) | `subscription_requests_list` |

A plan somebody has been on cannot be deleted — that would take their history
with it. Deactivate it instead: it stops being offered, the record stays.

## Vendor app

| Screen | What it does |
|---|---|
| Signup — "Choose your plan" | Tiles from `/plans/`, free tier preselected. Optional: Submit works untouched, and a catalogue that fails to load hides the section rather than blocking a registration. |
| Profile — plan card | Rides along in the `/api/vendors/me/` payload (no extra call), taps through to the plan screen. |
| `SubscriptionScreen` | Current plan, an open request with a Withdraw button, and the other tiers with "Request this plan". |

Every one of those says the same thing in the vendor's own words: asking sends
a request, nothing is charged in the app, and their plan does not change until
an admin approves it.

## Notifications

`vendor.subscription_started`, `vendor.subscription_upgrade_approved`,
`vendor.subscription_upgrade_rejected`, `vendor.subscription_ended` — all in
the usual registry, all routed to `/subscription`. Assembling them lives in
`subscriptions/notifications.py`; nothing else builds a context dict itself.

An approved upgrade sends only the approval message: `assign_plan(notify=False)`
suppresses the generic "you're on X" so the vendor gets the better story.
Cancelling from the dashboard sends "ended", but a plan *change* does not —
there the news is the new plan, not the old one closing.
