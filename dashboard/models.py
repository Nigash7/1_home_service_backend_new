from django.conf import settings
from django.db import models

from .permissions import ALL_PERMISSIONS, PERMISSION_LABELS, clean_permissions


class AdminRole(models.Model):
    """
    A named bundle of dashboard accesses, created by an admin.

    The names are the admin's own ("Booking Desk", "Content Team") -- nothing
    in the code branches on a particular role. What a role can reach lives in
    `permissions`, a list of codes from `dashboard.permissions`.
    """

    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.JSONField(
        default=list, blank=True,
        help_text='Permission codes from dashboard.permissions.PERMISSION_GROUPS.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Switch off to block everyone holding this role without deleting it.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # A code that no longer exists in the catalogue must not linger and
        # silently start meaning something else later.
        self.permissions = clean_permissions(self.permissions)
        super().save(*args, **kwargs)

    def has_permission(self, code):
        return self.is_active and code in set(self.permissions or ())

    @property
    def permission_set(self):
        return set(self.permissions or ()) & ALL_PERMISSIONS

    @property
    def permission_labels(self):
        return [PERMISSION_LABELS[code] for code in clean_permissions(self.permissions)]


class AdminProfile(models.Model):
    """
    Turns an ordinary `accounts.User` into a dashboard login.

    The username and password are the user's own -- this only records who they
    are in the panel and which role they hold. No profile means no dashboard,
    which is why access is checked here and not on `is_staff`: `is_staff` also
    opens Django's own admin site, and dashboard staff have no business there.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='admin_profile',
    )
    full_name = models.CharField(max_length=200)
    role = models.ForeignKey(
        AdminRole, on_delete=models.PROTECT,
        null=True, blank=True, related_name='staff',
        help_text='Left empty for a super admin, who is not limited by a role.',
    )
    is_super_admin = models.BooleanField(
        default=False,
        help_text='Bypasses every permission check and can manage roles and users.',
    )
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='admin_profiles_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['full_name']
        verbose_name = 'Dashboard user'
        verbose_name_plural = 'Dashboard users'

    def __str__(self):
        return f'{self.full_name} ({self.user.username})'

    @property
    def role_display(self):
        if self.is_super_admin:
            return 'Super Admin'
        return self.role.name if self.role else 'No role'

    @property
    def can_sign_in(self):
        """Every switch that has to be on before this login works."""
        return (
            self.is_active
            and self.user.is_active
            and (self.is_super_admin or (self.role is not None and self.role.is_active))
        )

    def permission_codes(self):
        """The set this user actually holds. Super admins hold everything."""
        if self.is_super_admin:
            return set(ALL_PERMISSIONS)
        if self.role is None or not self.role.is_active:
            return set()
        return self.role.permission_set

    def has_permission(self, code):
        if self.is_super_admin:
            return True
        return bool(self.role) and self.role.has_permission(code)


class AdminLoginAttempt(models.Model):
    """
    Every sign-in try at the dashboard, successful or not.

    This is both the audit trail an admin reads and the data the lockout is
    computed from -- see `dashboard.security`. Nothing here stores a password
    or any part of one.
    """

    class Outcome(models.TextChoices):
        SUCCESS = 'SUCCESS', 'Signed in'
        BAD_PASSWORD = 'BAD_PASSWORD', 'Wrong password'
        UNKNOWN_USER = 'UNKNOWN_USER', 'No such user'
        NO_ACCESS = 'NO_ACCESS', 'No dashboard access'
        LOCKED_OUT = 'LOCKED_OUT', 'Blocked, locked out'

    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=255, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    cleared = models.BooleanField(
        default=False,
        help_text=(
            'Set when an admin unlocks the account. A cleared attempt stays in '
            'the log but no longer counts towards a lockout.'
        ),
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Sign-in attempt'
        verbose_name_plural = 'Sign-in attempts'
        indexes = [
            models.Index(fields=['username', 'created_at']),
            models.Index(fields=['ip_address', 'created_at']),
        ]

    def __str__(self):
        return f'{self.username} @ {self.ip_address} -- {self.get_outcome_display()}'

    @property
    def succeeded(self):
        return self.outcome == self.Outcome.SUCCESS


class CustomerNotification(models.Model):
    """Notifications for customers (booking updates, vendor assigned, etc.)."""
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE,
        related_name='notifications'
    )
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.CASCADE,
        null=True, blank=True, related_name='notifications'
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.customer}"
