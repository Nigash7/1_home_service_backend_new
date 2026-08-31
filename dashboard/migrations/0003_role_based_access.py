"""
Turns the dashboard's dead `AdminUser` config record into a real login.

`AdminUser` was never wired to authentication -- it held a name, an email and
seven hard-coded permission booleans, while sign-in ran off `accounts.User`.
It is renamed rather than dropped because the notifications app has foreign
keys into it, and renaming keeps those rows pointing at the same people.

Each surviving row is then attached to the `accounts.User` that shares its
email address, which is the login it always should have been.
"""

import django.db.models.deletion
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations, models


def attach_logins(apps, schema_editor):
    """
    Give every profile the `accounts.User` it belongs to.

    Matched on email, which is what the old sign-in screen asked for. A
    profile with no matching account gets a placeholder login that cannot be
    used until an admin sets a password on it -- deleting it instead would
    take the notifications hanging off it down with it.
    """
    AdminProfile = apps.get_model('dashboard', 'AdminProfile')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    for profile in AdminProfile.objects.all():
        user = None
        if profile.email:
            user = User.objects.filter(email__iexact=profile.email).first()

        if user is None:
            base = (profile.email.split('@')[0] if profile.email else '') or 'admin'
            username = base[:140]
            suffix = 0
            while User.objects.filter(username=username).exists():
                suffix += 1
                username = f'{base[:135]}-{suffix}'

            user = User.objects.create(
                username=username,
                email=profile.email or '',
                password=make_password(None),  # unusable until an admin sets one
                role='ADMIN',
                is_active=False,
                is_staff=False,
            )
            profile.is_active = False

        profile.user = user
        profile.is_super_admin = (
            profile.legacy_role == 'SUPER_ADMIN' or bool(user.is_superuser)
        )
        profile.save()

    # Anyone who already had the keys keeps them: without this the superuser
    # that runs the migration would be locked out of the panel it just gained.
    for user in User.objects.filter(is_superuser=True):
        AdminProfile.objects.get_or_create(
            user=user,
            defaults={
                'full_name': (
                    f'{user.first_name} {user.last_name}'.strip() or user.username
                ),
                'is_super_admin': True,
                'is_active': True,
            },
        )


def detach_logins(apps, schema_editor):
    """Put the email back where the login pointed, so the rename can reverse."""
    AdminProfile = apps.get_model('dashboard', 'AdminProfile')
    for profile in AdminProfile.objects.select_related('user'):
        if profile.user_id and not profile.email:
            profile.email = profile.user.email or f'{profile.user.username}@example.invalid'
            profile.save(update_fields=['email'])


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0002_customernotification'),
        # notifications builds its foreign keys against the old name, so it has
        # to be in place before the rename moves the table out from under it.
        ('notifications', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ---- keep the table (and the notification rows pointing at it) ----
        migrations.RenameModel(old_name='AdminUser', new_name='AdminProfile'),
        migrations.RenameField(
            model_name='adminprofile', old_name='last_login', new_name='last_login_at',
        ),
        # The old CharField role has to move out of the way before the FK of
        # the same name moves in. Kept under a temporary name so the data
        # migration below can still read which rows were super admins.
        migrations.RenameField(
            model_name='adminprofile', old_name='role', new_name='legacy_role',
        ),

        # ---- the new role model ----
        migrations.CreateModel(
            name='AdminRole',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('permissions', models.JSONField(
                    blank=True, default=list,
                    help_text='Permission codes from dashboard.permissions.PERMISSION_GROUPS.')),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text='Switch off to block everyone holding this role without deleting it.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Role',
                'verbose_name_plural': 'Roles',
                'ordering': ['name'],
            },
        ),

        # ---- the sign-in log the lockout is computed from ----
        migrations.CreateModel(
            name='AdminLoginAttempt',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.CharField(db_index=True, max_length=150)),
                ('ip_address', models.GenericIPAddressField(blank=True, db_index=True, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=255)),
                ('outcome', models.CharField(choices=[
                    ('SUCCESS', 'Signed in'),
                    ('BAD_PASSWORD', 'Wrong password'),
                    ('UNKNOWN_USER', 'No such user'),
                    ('NO_ACCESS', 'No dashboard access'),
                    ('LOCKED_OUT', 'Blocked, locked out'),
                ], max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('cleared', models.BooleanField(
                    default=False,
                    help_text=(
                        'Set when an admin unlocks the account. A cleared attempt stays in '
                        'the log but no longer counts towards a lockout.'
                    ))),
            ],
            options={
                'verbose_name': 'Sign-in attempt',
                'verbose_name_plural': 'Sign-in attempts',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='adminloginattempt',
            index=models.Index(fields=['username', 'created_at'],
                               name='dashboard_a_usernam_37bebe_idx'),
        ),
        migrations.AddIndex(
            model_name='adminloginattempt',
            index=models.Index(fields=['ip_address', 'created_at'],
                               name='dashboard_a_ip_addr_55dbdc_idx'),
        ),

        # ---- profile gains its login and its role ----
        migrations.AddField(
            model_name='adminprofile',
            name='user',
            field=models.OneToOneField(
                null=True,  # tightened below, once every row has one
                on_delete=django.db.models.deletion.CASCADE,
                related_name='admin_profile',
                to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='adminprofile',
            name='role',
            field=models.ForeignKey(
                blank=True, null=True,
                help_text='Left empty for a super admin, who is not limited by a role.',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='staff', to='dashboard.adminrole'),
        ),
        migrations.AddField(
            model_name='adminprofile',
            name='is_super_admin',
            field=models.BooleanField(
                default=False,
                help_text='Bypasses every permission check and can manage roles and users.'),
        ),
        migrations.AddField(
            model_name='adminprofile',
            name='created_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='admin_profiles_created', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='adminprofile',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),

        migrations.RunPython(attach_logins, detach_logins),

        # ---- retire what the booleans and the email were standing in for ----
        migrations.AlterField(
            model_name='adminprofile',
            name='user',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='admin_profile', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RemoveField(model_name='adminprofile', name='email'),
        migrations.RemoveField(model_name='adminprofile', name='legacy_role'),
        migrations.RemoveField(model_name='adminprofile', name='can_manage_bookings'),
        migrations.RemoveField(model_name='adminprofile', name='can_manage_vendors'),
        migrations.RemoveField(model_name='adminprofile', name='can_manage_customers'),
        migrations.RemoveField(model_name='adminprofile', name='can_manage_services'),
        migrations.RemoveField(model_name='adminprofile', name='can_manage_content'),
        migrations.RemoveField(model_name='adminprofile', name='can_manage_discounts'),
        migrations.RemoveField(model_name='adminprofile', name='can_view_reports'),

        migrations.AlterModelOptions(
            name='adminprofile',
            options={
                'ordering': ['full_name'],
                'verbose_name': 'Dashboard user',
                'verbose_name_plural': 'Dashboard users',
            },
        ),

        # The email-OTP sign-in this replaces. Never read by the login view --
        # that kept its codes in the session -- so nothing depends on it.
        migrations.DeleteModel(name='OtpCode'),
    ]
