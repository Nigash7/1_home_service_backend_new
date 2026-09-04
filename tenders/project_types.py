"""
What kind of place a tender is about.

Kept in a module of its own, importing nothing but Django, so `services` can
name the same list when a quote-only service pre-fills the tender form. Living
inside `tenders.models` it could not be: that module reaches into `payments`,
and a service importing it would drag the whole chain along.
"""

from django.db import models


class ProjectType(models.TextChoices):
    HOUSE = 'HOUSE', 'Independent House'
    APARTMENT = 'APARTMENT', 'Apartment / Flat'
    VILLA = 'VILLA', 'Villa'
    COMMERCIAL = 'COMMERCIAL', 'Commercial Space'
    RENOVATION = 'RENOVATION', 'Renovation / Remodel'
    INTERIOR = 'INTERIOR', 'Interior Work'
    OTHER = 'OTHER', 'Other'
