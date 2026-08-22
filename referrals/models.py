import secrets

from django.db import models
from django.utils import timezone


# Ambiguous characters (0/O, 1/I) left out so codes survive being read aloud.
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
CODE_LENGTH = 8


class ReferralProgram(models.Model):
    """
    Single settings row driving the whole referral programme: the reward
    amounts and every piece of copy the app shows. Edited from the dashboard.
    """
    is_active = models.BooleanField(
        default=True, help_text="Turn the whole programme on or off in the app",
    )

    referrer_reward = models.DecimalField(
        max_digits=10, decimal_places=2, default=50,
        help_text="What the existing customer earns per successful referral",
    )
    friend_reward = models.DecimalField(
        max_digits=10, decimal_places=2, default=50,
        help_text="What the invited friend gets on their first booking",
    )

    # Copy. {amount} and {friend_amount} are replaced with the values above,
    # so changing the reward keeps every screen in step.
    home_banner_title = models.CharField(max_length=120, default='Refer and get free services')
    home_banner_subtitle = models.CharField(max_length=120, default='Invite and get ₹{amount}*')

    profile_card_title = models.CharField(max_length=120, default='Refer & earn ₹{amount}')
    profile_card_subtitle = models.CharField(
        max_length=200, default='Get ₹{amount} when your friend completes their first booking',
    )
    profile_card_button = models.CharField(max_length=40, default='Refer now')

    screen_title = models.CharField(max_length=120, default='Refer and get FREE services')
    screen_description = models.TextField(
        default='Invite your friends to try our services. They get instant ₹{friend_amount} off. '
                'You win ₹{amount} once they take a service.',
    )

    step_one = models.CharField(max_length=200, default='Invite your friends & get rewarded')
    step_two = models.CharField(max_length=200, default='They get ₹{friend_amount} on their first service')
    step_three = models.CharField(max_length=200, default='You get ₹{amount} once their service is completed')

    share_message = models.TextField(
        default='Hey! Book trusted home services with my code {code} and get ₹{friend_amount} off '
                'your first booking.',
        help_text="Sent when the customer shares. {code} is their referral code.",
    )
    terms = models.TextField(
        blank=True,
        default='Rewards are credited once your friend\'s first booking is completed. '
                'Rewards cannot be exchanged for cash.',
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Referral Program"
        verbose_name_plural = "Referral Program"

    def __str__(self):
        return f"Referral Program (₹{self.referrer_reward})"

    @classmethod
    def get_solo(cls):
        """The one and only settings row, created with defaults on first use."""
        program, _ = cls.objects.get_or_create(pk=1)
        return program

    def fill(self, text, code=''):
        """Substitutes the reward amounts (and code) into a piece of copy."""
        return (
            (text or '')
            .replace('{amount}', f'{self.referrer_reward:.0f}')
            .replace('{friend_amount}', f'{self.friend_reward:.0f}')
            .replace('{code}', code)
        )


class ReferralCode(models.Model):
    """The share code belonging to one customer. Created the first time they
    open the Refer & Earn screen."""
    customer = models.OneToOneField(
        'customers.Customer', on_delete=models.CASCADE, related_name='referral_code',
    )
    code = models.CharField(max_length=12, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} ({self.customer})"

    @classmethod
    def generate_unique_code(cls):
        while True:
            code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if not cls.objects.filter(code=code).exists():
                return code

    @classmethod
    def for_customer(cls, customer):
        existing = cls.objects.filter(customer=customer).first()
        if existing:
            return existing
        return cls.objects.create(customer=customer, code=cls.generate_unique_code())


class Referral(models.Model):
    """
    One invited friend. Starts PENDING at signup, flips to EARNED when that
    friend's first booking completes, and an admin marks it SETTLED once the
    reward has actually been handed over.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending first booking'
        EARNED = 'EARNED', 'Earned — reward owed'
        SETTLED = 'SETTLED', 'Settled'

    referrer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE, related_name='referrals_made',
    )
    # A customer can only ever be referred by one person.
    referred_customer = models.OneToOneField(
        'customers.Customer', on_delete=models.CASCADE, related_name='referred_by',
    )
    code_used = models.CharField(max_length=12)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reward_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    first_booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='referrals_triggered',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    earned_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    settled_note = models.CharField(
        max_length=200, blank=True, help_text="How the reward was paid out",
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.referrer} → {self.referred_customer} ({self.status})"

    def mark_earned(self, booking, amount):
        self.status = self.Status.EARNED
        self.reward_amount = amount
        self.first_booking = booking
        self.earned_at = timezone.now()
        self.save(update_fields=['status', 'reward_amount', 'first_booking', 'earned_at'])

    def mark_settled(self, note=''):
        self.status = self.Status.SETTLED
        self.settled_note = note
        self.settled_at = timezone.now()
        self.save(update_fields=['status', 'settled_note', 'settled_at'])
