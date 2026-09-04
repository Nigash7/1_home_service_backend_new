"""
How a service's price turns into an amount.

`Service.price` is only ever a rate. What it is a rate *of* is the pricing
type: a flat ₹800, or ₹15 for every square foot, or nothing at all because the
vendor has to come and look first. Everything that shows a price or works one
out reads it from here, so the service card, the cart and the booking
subtotal cannot drift apart.
"""

from decimal import Decimal, InvalidOperation

from django.db import models


class PricingType(models.TextChoices):
    FIXED = 'FIXED', 'Fixed'
    STARTING_FROM = 'STARTING_FROM', 'Starting From'
    PER_HOUR = 'PER_HOUR', 'Per Hour'
    PER_DAY = 'PER_DAY', 'Per Day'
    PER_SQ_FT = 'PER_SQ_FT', 'Per Sq. Ft.'
    PER_SQ_M = 'PER_SQ_M', 'Per Sq. Meter'
    PER_VISIT = 'PER_VISIT', 'Per Visit'
    PER_ITEM = 'PER_ITEM', 'Per Item'
    PER_UNIT = 'PER_UNIT', 'Per Unit'
    PER_KM = 'PER_KM', 'Per Kilometer'
    PER_ROOM = 'PER_ROOM', 'Per Room'
    PER_SEAT = 'PER_SEAT', 'Per Seat'
    PER_KG = 'PER_KG', 'Per Kg'
    CUSTOM_QUOTE = 'CUSTOM_QUOTE', 'Custom / Quote'


# unit          what one of the rate buys, for "₹15 / sq ft"
# measure       what the customer is asked for, for the input's label
# decimals      whether a fraction of the unit is a real thing to charge for
_META = {
    PricingType.FIXED: ('', '', False),
    PricingType.STARTING_FROM: ('', '', False),
    PricingType.PER_HOUR: ('hour', 'Hours', True),
    PricingType.PER_DAY: ('day', 'Days', False),
    PricingType.PER_SQ_FT: ('sq ft', 'Area (sq ft)', True),
    PricingType.PER_SQ_M: ('m²', 'Area (m²)', True),
    PricingType.PER_VISIT: ('visit', 'Visits', False),
    PricingType.PER_ITEM: ('item', 'Items', False),
    PricingType.PER_UNIT: ('unit', 'Units', False),
    PricingType.PER_KM: ('km', 'Distance (km)', True),
    PricingType.PER_ROOM: ('room', 'Rooms', False),
    PricingType.PER_SEAT: ('seat', 'Seats', False),
    PricingType.PER_KG: ('kg', 'Weight (kg)', True),
    PricingType.CUSTOM_QUOTE: ('', '', False),
}

# The two that do not multiply anything. FIXED and STARTING_FROM are still
# counted -- two AC services is two of them -- they are just counted as
# services rather than measured in some unit.
UNMEASURED = {PricingType.FIXED, PricingType.STARTING_FROM,
              PricingType.CUSTOM_QUOTE}


def unit_label(pricing_type):
    """"sq ft" for PER_SQ_FT, empty for the types that measure nothing."""
    return _META.get(pricing_type, _META[PricingType.FIXED])[0]


def measure_label(pricing_type):
    """What to put above the quantity box: "Area (sq ft)", "Hours"."""
    return _META.get(pricing_type, _META[PricingType.FIXED])[1]


def allows_decimal_quantity(pricing_type):
    """
    Whether half of one is a real amount to charge for.

    True for the things that are measured -- area, weight, distance, time --
    and false for the things that are counted, because half a room is not a
    quantity anybody means.
    """
    return _META.get(pricing_type, _META[PricingType.FIXED])[2]


def needs_quantity(pricing_type):
    """
    Whether the customer is asked for an amount before this can be priced.

    False for a flat price and for a quote, true for everything measured --
    which is what tells the app to show a number box instead of a +/- stepper.
    """
    return pricing_type not in UNMEASURED


def is_quote_only(pricing_type):
    """A price nobody can work out until a vendor has looked at the job."""
    return pricing_type == PricingType.CUSTOM_QUOTE


def shows_duration(pricing_type):
    """
    Whether "how long it takes" is a fact worth stating about this service.

    Only for the two flat types. On a per-hour service the customer chooses
    the hours, so a fixed duration contradicts them; on per-sq-ft or per-day
    it says nothing; and a quote has not been scoped yet. Those all leave it
    out rather than showing a number nobody set on purpose.
    """
    return pricing_type in (PricingType.FIXED, PricingType.STARTING_FROM)


def format_amount(amount):
    """
    A rupee figure the way the apps write it: no decimals when it is whole,
    two when it is not, so ₹800 does not read as ₹800.00.
    """
    quantised = round(float(amount), 2)
    if quantised == int(quantised):
        return f'₹{int(quantised):,}'
    return f'₹{quantised:,.2f}'


def price_label(price, pricing_type):
    """
    The one line a card shows instead of a bare number:

        FIXED           ₹800
        STARTING_FROM   From ₹499
        PER_SQ_FT       ₹15 / sq ft
        CUSTOM_QUOTE    Price on request
    """
    if is_quote_only(pricing_type):
        return 'Price on request'

    money = format_amount(price)
    if pricing_type == PricingType.STARTING_FROM:
        return f'From {money}'

    unit = unit_label(pricing_type)
    return f'{money} / {unit}' if unit else money


# ---------------------------------------------------------------------------
# Reading a cart line back. Both the booking subtotal and the discount
# calculator run over the same posted lines, so they parse them the same way.
# ---------------------------------------------------------------------------

def parse_money(value, default=Decimal('0')):
    """A posted price as a Decimal. Money never goes through float here."""
    try:
        return Decimal(str(value if value not in (None, '') else default))
    except (InvalidOperation, TypeError, ValueError):
        return default


def parse_quantity(value, default=Decimal('1')):
    """
    A cart line's quantity as something we can multiply money by.

    Decimal, not int: a per-sq-ft line carries 1000 and a per-kg line 2.5, and
    rounding those to whole numbers would quietly change what the customer is
    charged. Zero, negative and unreadable all fall back to one, which is what
    a missing quantity has always meant here.
    """
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    return quantity if quantity > 0 else default


def line_total(line):
    """`price` x `qty` for one posted cart line, as a Decimal."""
    return parse_money(line.get('price')) * parse_quantity(line.get('qty'))
