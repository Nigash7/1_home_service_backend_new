"""
State names, and the one way the whole project compares them.

Every state on this platform is free text: a customer types theirs into the
profile form, a geocoder fills one in from GPS, an admin picks one for a
vendor. "kerala", "Kerala " and "KERALA" are the same place, and a customer
must not be told nobody serves their zone over a capital letter.

So a state is stored as typed but always *matched* on its normalized key, and
the canonical spelling is offered wherever there is a form to offer it on.
"""

import re
import unicodedata

# The 28 states and 8 union territories, spelled as the forms offer them.
INDIAN_STATES = [
    'Andhra Pradesh',
    'Arunachal Pradesh',
    'Assam',
    'Bihar',
    'Chhattisgarh',
    'Goa',
    'Gujarat',
    'Haryana',
    'Himachal Pradesh',
    'Jharkhand',
    'Karnataka',
    'Kerala',
    'Madhya Pradesh',
    'Maharashtra',
    'Manipur',
    'Meghalaya',
    'Mizoram',
    'Nagaland',
    'Odisha',
    'Punjab',
    'Rajasthan',
    'Sikkim',
    'Tamil Nadu',
    'Telangana',
    'Tripura',
    'Uttar Pradesh',
    'Uttarakhand',
    'West Bengal',
    # Union territories
    'Andaman and Nicobar Islands',
    'Chandigarh',
    'Dadra and Nagar Haveli and Daman and Diu',
    'Delhi',
    'Jammu and Kashmir',
    'Ladakh',
    'Lakshadweep',
    'Puducherry',
]

# Spellings that arrive from elsewhere -- older names, and what geocoders and
# address forms hand back -- mapped onto the name this project uses.
_ALIASES = {
    'orissa': 'Odisha',
    'pondicherry': 'Puducherry',
    'pondichery': 'Puducherry',
    'uttaranchal': 'Uttarakhand',
    'nct of delhi': 'Delhi',
    'national capital territory of delhi': 'Delhi',
    'new delhi': 'Delhi',
    'delhi ncr': 'Delhi',
    'jammu kashmir': 'Jammu and Kashmir',
    'j and k': 'Jammu and Kashmir',
    'tamilnadu': 'Tamil Nadu',
    'chattisgarh': 'Chhattisgarh',
    'dadra and nagar haveli': 'Dadra and Nagar Haveli and Daman and Diu',
    'daman and diu': 'Dadra and Nagar Haveli and Daman and Diu',
    'andaman nicobar islands': 'Andaman and Nicobar Islands',
}


def _slug(value):
    """Lower case, accents stripped, punctuation dropped, spaces collapsed."""
    if not value:
        return ''

    text = unicodedata.normalize('NFKD', str(value))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace('&', ' and ')
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


# Canonical name by its own slug, so an incoming spelling can be looked up.
_CANONICAL_BY_SLUG = {_slug(name): name for name in INDIAN_STATES}


def canonical_state(value):
    """
    The project's spelling of `value` when it recognises the state, otherwise
    the text as given with its whitespace tidied.

    An unrecognised state is kept rather than rejected -- this list is not the
    authority on where somebody lives, and a vendor covering a place we have
    not listed should still be storable.
    """
    slug = _slug(value)
    if not slug:
        return ''

    slug = _slug(_ALIASES.get(slug, slug))
    if slug in _CANONICAL_BY_SLUG:
        return _CANONICAL_BY_SLUG[slug]

    return ' '.join(str(value).split())


def state_key(value):
    """
    The key a state is matched on. Both sides of every comparison go through
    this, so a customer's "kerala" and a vendor's "Kerala" meet, and so do
    "Orissa" and "Odisha".

    Returns '' for anything empty, which callers read as "no state given".
    """
    return _slug(canonical_state(value))


def normalize_region(value):
    """
    The match key for a place we hold no list of -- a district.

    India has some 800 of them and no keyed geocoding service to check them
    against, so a district stays free text on both sides: the customer types
    theirs into their profile and an admin types the vendor's. This is what
    makes "ernakulam", "Ernakulam" and " ERNAKULAM " one place anyway.
    """
    return _slug(value)


def district_label(value):
    """A district as it will be stored: the text as typed, whitespace tidied."""
    return ' '.join(str(value).split()) if value else ''


def districts_for(state):
    """
    The districts a picker offers for `state`, or [] when we hold none.

    An empty list is the signal to let the district be typed rather than
    picked: it means our data does not cover this state, and refusing to save
    a profile over a gap in *our* list would stop somebody booking at all.
    """
    from .districts_data import DISTRICTS_BY_STATE

    key = state_key(state)
    if not key:
        return []

    for name, districts in DISTRICTS_BY_STATE.items():
        if state_key(name) == key:
            return list(districts)
    return []


def is_known_district(state, district):
    """
    Whether `district` is one of the ones we offer for `state`.

    True when we hold no list for the state -- there is nothing to check
    against, and an unknown state is not the customer's fault.
    """
    districts = districts_for(state)
    if not districts:
        return True

    key = normalize_region(district)
    return any(normalize_region(name) == key for name in districts)
