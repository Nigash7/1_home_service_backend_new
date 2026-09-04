# Payments (Razorpay)

Collects money for a booking and holds it. The platform is the merchant of
record — a captured payment sits in **our** Razorpay account, never the
vendor's — so the money is genuinely held and can still be refunded in full
while work is in dispute.

## Endpoints

| Method | Path | Who | Does |
|---|---|---|---|
| POST | `/api/payments/order/` | Customer | Opens a Razorpay order for a booking. Body: `{"booking_id": 12}` |
| POST | `/api/payments/verify/` | Customer | Confirms what Checkout returned |
| GET | `/api/payments/my/` | Customer | Payment history |
| GET | `/api/payments/booking/<id>/` | Customer | True payment state for one booking |
| POST | `/api/payments/webhook/razorpay/` | Razorpay | Server-to-server callback |

## Flow

```
POST /order/          -> Payment(CREATED), returns order_id + key_id + amount(paise)
   app opens Razorpay Checkout with those
POST /verify/         -> signature check -> fetch from Razorpay -> Payment(CAPTURED)
   ... and independently ...
webhook payment.captured -> Payment(CAPTURED)
```

Both paths end in `services.mark_paid()`, which is idempotent. They race by
design and either one alone is enough — that is the point. A customer whose
app is killed mid-checkout still ends up paid, because the webhook lands
regardless.

**Bookings are not the only thing charged through this account.** A tender
confirmation fee — the percentage a customer pays to lock in the vendor whose
bid they picked — uses `gateway` and this same webhook URL, but keeps its own
records in `tenders.TenderConfirmationFee` and its own order/verify endpoints
under `/api/tenders/`. The webhook recognises those orders and hands them to
`tenders.services`; see `_handle_tender_fee` in `views.py`. It is a separate
model on purpose: a platform fee is never released to a vendor and never paid
out, so the escrow half of `Payment` would only ever be wrong on it.

## Where the money lands

Razorpay settles captured money to the bank account registered against the
Razorpay account itself -- Razorpay Dashboard -> Account & Settings -> Banking
details. No API call can point one payment at a different bank, so there is
nothing to configure here and nothing in the database recording it. If money
is arriving in the wrong account, that is the place to change it.

## The four rules that keep this honest

1. **The amount never comes from the client.** `/order/` reads
   `booking.amount` on the server. A request body carrying `amount` is
   ignored. Without this a customer sets their own price.
2. **A valid signature is necessary but not sufficient.** `/verify/` also
   calls `payment.fetch` and checks the status is really `captured`, the
   `order_id` matches, and the amount is not short. The signature only proves
   the ids are genuine, not that money moved.
3. **The webhook refuses everything unless `RAZORPAY_WEBHOOK_SECRET` is set.**
   An unsigned webhook endpoint is a public "mark this booking paid" button.
   This is deliberate — see `test_webhook_refused_when_no_secret_configured`.
4. **Money is rupees in the DB, paise on the wire.** Use `to_paise` /
   `to_rupees` in `models.py`, never float arithmetic: `int(19.99 * 100)` is
   `1998`, an undercharge that only shows up in reconciliation.

## Escrow

`Payment.payout_status` is `HELD` on capture. `services.release_to_vendor()`
moves it to `RELEASED` and is the escrow release decision. It refuses unless
the payment is captured, still held, and the booking is `COMPLETED`.

It does **not** move funds — vendor payouts are still made outside the
platform. It is the record of the decision, and after it
`refundable_amount` drops to zero. Wiring actual disbursement means Razorpay
Route or RazorpayX; that is the next step, not something this app pretends to
do.

## Setup

`.env` (never commit it — it is gitignored, and was previously tracked):

```
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=          # from the dashboard, see below
RAZORPAY_CURRENCY=INR
```

Webhook: Razorpay Dashboard → Settings → Webhooks → Add.

- URL `https://<host>/api/payments/webhook/razorpay/`
- Events: `payment.captured`, `payment.failed`, `order.paid`,
  `refund.processed`, `refund.created`
- Copy the secret it generates into `RAZORPAY_WEBHOOK_SECRET`

`RAZORPAY_IS_LIVE` is derived from the key prefix, and every `Payment` records
it, so test takings never inflate real reporting.

## Tests

```
python manage.py test payments --settings=config.settings_test
```

`config/settings_test.py` runs against in-memory SQLite so the suite never
creates or drops a database on the shared Postgres server.

The gateway is patched throughout — these test our rules, not Razorpay's. The
forgery cases (bad checkout signature, unsigned webhook, underpayment,
paying for someone else's booking, replayed webhook) matter more than the
happy path and are covered.

## Customer app

`customer_app` drives this through `lib/services/payment_service.dart`, which
wraps the `razorpay_flutter` plugin and hands back a single awaitable result.
The UI is `lib/widgets/pay_now_card.dart`, shown on the booking detail screen
whenever a live booking is unpaid, and opened automatically when the customer
taps "Pay now" on the booking-confirmed dialog.

Three behaviours there are deliberate and worth keeping:

- **Razorpay saying "success" is not success.** The app only treats a booking
  as paid once `/verify/` agrees.
- **A charge we could not confirm is never retried.** If verification cannot
  reach the server, the app asks `/booking/<id>/` and, failing that, shows a
  "being confirmed" notice with no pay button. The webhook settles it. This is
  the difference between a lost connection and a double charge.
- **The plugin's listeners are torn down with the widget**, and a checkout
  still open when the screen closes completes as cancelled rather than
  leaving the caller awaiting forever.

Release builds need `android/app/proguard-rules.pro` — R8 strips Razorpay's
callback classes otherwise and payments fail silently in release only.

## Testing with test keys

Razorpay's sandbox cards, on the Checkout sheet:

| Card | Result |
|---|---|
| `4111 1111 1111 1111` | Success (any future expiry, any CVV) |
| `5104 0600 0000 0008` | Success (Mastercard) |
| UPI id `success@razorpay` | Success |
| UPI id `failure@razorpay` | Failure |

The webhook needs a public URL. `ngrok http 8000`, then point the dashboard
webhook at `https://<ngrok-id>.ngrok.io/api/payments/webhook/razorpay/`.
Without it the browser callback still works, but the lost-connection path
has no backstop.

## Dashboard

**Payments** in the sidebar lists every gateway payment, with a "currently
held" total at the top — captured money not yet released, which is the number
an operator actually needs. Filter by status or by held/released/refunded, or
search an order id, payment id, or bare booking number.

The per-payment controls live on the booking detail page, under a **Razorpay**
card:

- **Release to vendor** — the escrow release. Disabled until the booking is
  `COMPLETED`, and irreversible: after it the payment can no longer be
  refunded.
- **Refund** — folded behind a disclosure so it is never the easy mis-click.
  A blank amount refunds the whole remaining balance; a figure refunds part.
  Partial refunds accumulate rather than overwrite.

Two guards worth keeping:

1. **Released money cannot be refunded.** The platform no longer holds it, and
   refunding anyway would leave the books short with nothing to show why.
2. **The old manual payment form disappears once a booking has a gateway
   payment.** Hand-editing `payment_status` there would silently contradict
   Razorpay. Cash-only bookings keep the manual switch, which is what it was
   always for.

Refunds call Razorpay first and write our records second, so a refund the
gateway rejects leaves nothing behind. The matching webhook lands later and is
harmless — `apply_refund` writes the cumulative total either way.

## Where the money goes: vendor payout accounts

`vendors/bank_models.py` holds `VendorBankAccount` (one per vendor) and
`VendorBankAccountChange` (append-only history). The vendor adds and edits it
themselves in the app; an admin verifies it on the vendor's dashboard page.

| Method | Path | Who |
|---|---|---|
| GET | `/api/vendors/me/bank-account/` | Vendor |
| PUT | `/api/vendors/me/bank-account/` | Vendor |
| GET | `/api/vendors/me/bank-account/history/` | Vendor |

There is no id in any of those URLs — they resolve through
`request.user.vendor_profile`, so one vendor reaching another's details is not
something the routing permits.

### Four rules

1. **The full account number never leaves the server.** Reads return
   `XXXXXXXX9012`. The vendor knows their own number; echoing it back only
   adds a place for it to leak from. Changing the account means typing it
   again, twice, with paste disabled on the confirm field.
2. **Changing the details clears `is_verified`.** Without this, someone with a
   stolen vendor session could point payouts at their own bank and keep the
   badge that makes the account look safe to pay. Re-saving *identical*
   details is not treated as a change, so opening the form and saving does not
   cost a vendor their verification.
3. **Every change is recorded, masked.** `VendorBankAccountChange` answers
   "when did this change and to what" during a payment dispute. Old numbers
   are stored masked — the full value would spread it to another table for no
   extra answer.
4. **The vendor is notified on every change**, including ones they made
   themselves. If someone else made it, that message is how the real vendor
   finds out.

### The link to release

`release_to_vendor()` refuses when the vendor has no payout account —
releasing money to a vendor with nowhere to send it records a debt that
cannot be settled, and nobody notices until the vendor asks. An *unverified*
account does not block release; it shows as a warning next to the button, and
on the vendor's dashboard page.

Account numbers are stored unencrypted. Indian account numbers plus IFSC are
not card data — no PCI obligation, and they are printed on every cheque — so
this matches what Indian marketplaces normally do, with DB-level encryption
as the usual control. Worth a deliberate decision before going live rather
than a default.

## Sending money out: RazorpayX

A **separate product** from the gateway above, with its own dashboard, its own
credentials, and a virtual account that payouts are debited from. The Python
SDK covers only the gateway, so `payments/payoutx.py` calls the REST API
directly.

Three entities, created once and reused:

```
Contact       the vendor, as a party we pay          cont_...
Fund account  their bank account, under that contact  fa_...
Payout        one transfer out to a fund account      pout_...
```

Off until `RAZORPAYX_ACCOUNT_NUMBER` is set. Until then releasing stays what
it was — a bookkeeping record — and nothing else changes.

### The double-payment guards

Money leaving is the direction where a mistake is expensive, so there are
three separate defences and they are all load-bearing:

1. **`Payout` is a OneToOne on `Payment`.** The database itself refuses a
   second payout for the same payment, so a double-clicked button cannot
   create one.
2. **An idempotency key per attempt**, sent as `X-Payout-Idempotency`.
   Generated once and replayed on retry, so RazorpayX returns the original
   payout instead of making another.
3. **`create_payout` is deliberately not wrapped in one transaction.** The
   payout row and its key are committed *before* RazorpayX is called. Were it
   atomic, a timeout would roll the row away, the retry would mint a fresh
   key, and the vendor would be paid twice. This is the subtlest of the three
   and the easiest to undo by accident — `test_a_retry_after_a_timeout_replays_the_same_key`
   is what stops that.

Following from those, a failed payout is only retried when RazorpayX gave a
**definite** no. A timeout leaves the row `pending` with its key intact,
because the money may well have moved.

A **reversed** payout puts the payment back to `HELD` and clears
`released_at` — the bank returned the money, so it is ours and refundable
again.

### Penny-drop verification

`vendors/payout_services.py` sends ₹1 to a fund account and reads back the
name the bank holds. That name is the actual check — an account merely
existing is not evidence it belongs to this vendor.

| Outcome | Meaning | Effect |
|---|---|---|
| `ACTIVE` | Real account, name matches | Auto-verified |
| `NAME_MISMATCH` | Real account, different name | Shown to an admin |
| `INVALID` | No such account | Never verified |

Name matching normalises titles and punctuation and compares word sets before
characters, so `Mr. Ramesh Kumar`, `RAMESH KUMAR` and `KUMAR RAMESH` all match
— reordered Indian names are the norm, not a mismatch. The threshold is
`RAZORPAYX_NAME_MATCH_THRESHOLD` (0.85).

A mismatch never *removes* an admin's verification. Some banks report names
oddly, and a bad automated read must not undo a human decision.

### Setup

```
RAZORPAYX_KEY_ID=            # blank falls back to the gateway keys
RAZORPAYX_KEY_SECRET=
RAZORPAYX_ACCOUNT_NUMBER=    # X dashboard -> Account Details. Blank = off
RAZORPAYX_PAYOUT_MODE=IMPS   # NEFT above RAZORPAYX_IMPS_LIMIT
RAZORPAYX_VALIDATE_ACCOUNTS=True
```

Add these webhook events alongside the payment ones, same URL:
`payout.processed`, `payout.failed`, `payout.reversed`, `payout.updated`,
`fund_account.validation.completed`.

Creating a payout returns `queued` or `processing` — only the webhook says
whether the money landed, so the webhook is not optional here.

`queue_if_low_balance` is on: a payout with insufficient balance is held by
RazorpayX and released when the account is topped up, rather than failing and
leaving a vendor unpaid with no record of why.

## Still to do

- **Nothing tops up the RazorpayX account.** Gateway takings settle to your
  bank on Razorpay's normal cycle; funding X is a manual transfer. Until that
  is part of someone's routine, payouts will queue.
- **No payout reconciliation job.** If a webhook is missed, a payout sits
  `processing` forever. A daily sweep calling `payoutx.fetch_payout` on
  anything in flight would close that.
