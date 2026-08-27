# Tenders — the bidding flow

A customer posts a construction requirement with the budget they expect to
pay. An admin approves it, matching vendors quote against it, and the customer
picks the quote they like. From there the project runs to completion.

This is the mirror image of `bookings`: there the admin picks the vendor, here
the vendors come to the customer.

```
                                        ┌─ REJECTED ──┐ (customer fixes it,
                                        │             │  publishes again)
DRAFT ──publish──> PENDING_APPROVAL ──approve──> OPEN ──award──> AWARDED
                                                   │                 │
                                                   │              start
                                              CANCELLED              ↓
                                                             IN_PROGRESS
                                                                     │
                                                     progress · milestones
                                                                     ↓
                                                             COMPLETED ──> review
```

## Status meanings

| Status | Who acts next | Notes |
|---|---|---|
| `DRAFT` | Customer | Editable. Attach drawings here. Invisible to vendors. |
| `PENDING_APPROVAL` | Admin | Waiting in the dashboard queue. Still invisible to vendors. |
| `REJECTED` | Customer | Sent back with a reason. Editable again, can be re-published. |
| `OPEN` | Vendors | Matching vendors notified; bids accepted until `bid_deadline`. |
| `AWARDED` | Vendor | A bid was accepted; losing bids auto-rejected. |
| `IN_PROGRESS` | Vendor | Progress updates and milestones run here. |
| `COMPLETED` | Customer | Review can be left. |
| `CANCELLED` | — | Customer pulled it; live bidders were told. |

## Endpoints

All under `/api/tenders/`. JWT as everywhere else.

### Customer

| Method | Path | Purpose |
|---|---|---|
| POST | `/` | Create a tender (lands as `DRAFT`) |
| GET | `/my/` | My tenders (`?status=` to filter) |
| GET | `/<id>/` | Full detail |
| PATCH | `/<id>/` | Edit — `DRAFT` / `REJECTED` only |
| DELETE | `/<id>/` | Delete a draft |
| POST | `/<id>/publish/` | Send for admin review |
| POST | `/<id>/attachments/` | Upload a drawing (multipart: `file`, `caption`) |
| DELETE | `/attachments/<id>/` | Remove one |
| GET | `/<id>/bids/` | Compare bids (`?sort=amount\|timeline\|rating`) |
| POST | `/bids/<id>/accept/` | Select the vendor — awards the tender |
| POST | `/<id>/cancel/` | Pull the tender (`reason` optional) |
| POST | `/milestones/<id>/pay/` | Record a milestone as settled |
| POST | `/<id>/review/` | Rate the vendor (`rating` 1–5, `comment`) |

### Vendor

| Method | Path | Purpose |
|---|---|---|
| GET | `/open/` | Browse tenders they cover (`?category=` `?project_type=` `?pincode=` `?district=`) |
| GET | `/<id>/` | Tender detail |
| POST | `/<id>/bid/` | Submit a bid (milestones nested) |
| PATCH | `/<id>/bid/` | Revise it while bidding is open |
| DELETE | `/<id>/bid/` | Withdraw it |
| GET | `/my-bids/` | Every bid they have placed |
| GET | `/awarded/` | Projects they won |
| POST | `/<id>/start/` | Begin work |
| GET | `/<id>/progress/` | Update history |
| POST | `/<id>/progress/add/` | Post an update (multipart: `message`, `percent_complete`, `images[]`) |
| POST | `/milestones/<id>/reach/` | Mark a stage complete |
| POST | `/<id>/complete/` | Finish the project |

Submitting a bid, with the payment plan nested:

```json
{
  "amount": "1400000",
  "work_plan": "Three phases, own labour",
  "timeline_days": 180,
  "milestones": [
    {"title": "Foundation", "amount": "400000"},
    {"title": "Structure",  "amount": "600000"},
    {"title": "Finishing",  "amount": "400000"}
  ]
}
```

Every save replaces the milestone set wholesale. Omitting `milestones` from a
PATCH keeps the existing plan; sending `[]` clears it.

## Rules worth knowing

- **Admin approval gates publishing.** A tender never reaches a vendor until
  someone approves it in the dashboard. `publish` moves it to
  `PENDING_APPROVAL`, not `OPEN`.
- **One bid per vendor per tender**, enforced by a DB constraint. Vendors
  revise rather than re-submit, so the customer never compares two quotes from
  the same outfit.
- **Phone numbers are withheld until a deal exists.** The customer sees a
  vendor's number only after accepting their bid; a vendor sees the customer's
  number only after winning. An open tender is not a lead list.
- **Milestones hang off the bid, not the tender.** `tender.milestones` reads
  the winning bid's, so there is no copying and nothing to drift. Losing bids
  keep theirs; they simply stop mattering.
- **No money moves.** `pay` records what the customer says they settled, the
  same way `Booking.payment_status` does. Wiring a gateway is a separate job.
- **Reviews go in `reviews.Review`**, pointed at the tender instead of a
  booking, so a tender counts towards the vendor's rating everywhere it is
  already shown — pro vendor cards, profile page, dashboard.

## Vendor matching

Who sees a tender follows the same most-specific-wins rule as
`VendorQuerySet.for_service`:

- the tender's subcategory is one they cover (directly or via a service); or
- they hold the whole category and have not narrowed themselves inside it; or
- the tender names only a category and they do anything inside it.

Two methods implement this from opposite ends — `TenderQuerySet.for_vendor`
(what one vendor sees) and `Tender.matching_vendors` (who hears about one
tender). **They must agree**; `test_matching_vendors_agrees_with_the_vendor_feed`
is there to catch it if they ever stop.

## Tests

```bash
python manage.py test tenders
```

50 tests covering the flow end to end plus the access rules. They sandbox
`MEDIA_ROOT`, so uploads never land in the project's real media folder.

## The apps

Both Flutter apps are built against these endpoints.

**customer_app** — reached from the home screen banner and
Profile → My tenders.

| Screen | Does |
|---|---|
| `my_tenders_screen.dart` | Active / Closed tabs, cards flagging bids waiting |
| `create_tender_screen.dart` | The whole brief, budget, timeline, site and drawings; saves a draft or publishes |
| `tender_detail_screen.dart` | Status, brief, attachments, vendor, milestones, progress, review |
| `tender_bids_screen.dart` | Compare bids by price / rating / timeline, then award |
| `utils/tender_format.dart` | Rupee, date and status formatting shared by all four |

**vendor_app** — reached from Dashboard → Quick actions → Tenders.

| Screen | Does |
|---|---|
| `tenders_screen.dart` | Open / My bids / Projects tabs |
| `tender_detail_screen.dart` | The brief and drawings, plus submit / revise / withdraw |
| `submit_bid_screen.dart` | Price against budget, work plan, timeline, milestone editor |
| `tender_project_screen.dart` | Start, post progress with photos, mark stages done, complete |
| `utils/tender_format.dart` | Same helpers, hand-rolled (the vendor app has no `intl`) |

Two details worth keeping if these screens are reworked:

- The **customer's contact number is withheld** by the server until a vendor
  wins, and the vendor detail screen says so explicitly rather than showing an
  empty field. Same in reverse on the customer's bid comparison.
- The **milestone mismatch warning** in `submit_bid_screen.dart` is a prompt,
  not a block — a vendor may legitimately quote a figure their stages do not
  sum to, and the customer sees both numbers either way.
