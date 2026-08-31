"""
Tests for role-based dashboard access and the sign-in lockout.

The first test is the one that keeps the rest honest: it walks every URL the
dashboard publishes and fails if one is missing from the permission map. A
view that nobody classified is refused at runtime, so without this test the
first symptom of a forgotten entry would be a colleague locked out of a page
they should have.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import get_resolver, reverse
from django.utils import timezone

from .models import AdminLoginAttempt, AdminProfile, AdminRole
from . import permissions as perms
from . import security

User = get_user_model()


def make_admin(username, password='sup3r-secret-pw', permissions=None,
               super_admin=False, role_active=True, active=True):
    user = User.objects.create_user(
        username=username, password=password, role=User.Role.ADMIN,
    )
    role = None
    if not super_admin:
        role = AdminRole.objects.create(
            name=f'Role for {username}',
            permissions=permissions or [],
            is_active=role_active,
        )
    profile = AdminProfile.objects.create(
        user=user, full_name=username.title(), role=role,
        is_super_admin=super_admin, is_active=active,
    )
    return profile


class PermissionMapCoverageTests(TestCase):
    """Every dashboard URL must say which access it needs."""

    def test_every_dashboard_url_is_classified(self):
        from . import urls as dashboard_urls

        published = {
            pattern.name for pattern in dashboard_urls.urlpatterns if pattern.name
        }
        classified = set(perms.URL_PERMISSIONS) | perms.PUBLIC_URL_NAMES

        missing = published - classified
        self.assertFalse(
            missing,
            'These dashboard URLs are not in URL_PERMISSIONS, so they are '
            f'refused to everyone but a super admin: {sorted(missing)}',
        )

    def test_map_has_no_urls_that_do_not_exist(self):
        from . import urls as dashboard_urls

        published = {
            pattern.name for pattern in dashboard_urls.urlpatterns if pattern.name
        }
        stale = set(perms.URL_PERMISSIONS) - published
        self.assertFalse(stale, f'Mapped but no longer routed: {sorted(stale)}')

    def test_every_mapped_permission_is_in_the_catalogue(self):
        for url_name, required in perms.URL_PERMISSIONS.items():
            codes = (
                list(required.values()) if isinstance(required, dict)
                else [required]
            )
            for code in codes:
                if code is None:
                    continue
                self.assertIn(
                    code, perms.ALL_PERMISSIONS,
                    f'{url_name} needs "{code}", which is not a real permission',
                )

    def test_resolver_reaches_every_mapped_name(self):
        resolver = get_resolver()
        for url_name in perms.URL_PERMISSIONS:
            self.assertIn(url_name, resolver.reverse_dict, f'{url_name} is unroutable')


class SignInTests(TestCase):

    def setUp(self):
        self.profile = make_admin('desk', permissions=['bookings.view'])

    def test_correct_password_signs_in(self):
        response = self.client.post(reverse('dashboard_login'), {
            'username': 'desk', 'password': 'sup3r-secret-pw',
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(
            self.client.session['admin_user_id'], self.profile.user_id,
        )

    def test_wrong_password_does_not_sign_in(self):
        response = self.client.post(reverse('dashboard_login'), {
            'username': 'desk', 'password': 'not-it',
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('admin_user_id', self.client.session)

    def test_unknown_user_and_wrong_password_read_the_same(self):
        """The form must not confirm which usernames exist."""
        wrong_password = self.client.post(reverse('dashboard_login'), {
            'username': 'desk', 'password': 'not-it',
        })
        no_such_user = self.client.post(reverse('dashboard_login'), {
            'username': 'nobody-here', 'password': 'not-it',
        })
        self.assertContains(wrong_password, 'Incorrect username or password')
        self.assertContains(no_such_user, 'Incorrect username or password')

    def test_account_without_a_profile_is_refused(self):
        User.objects.create_user(
            username='shopper', password='sup3r-secret-pw',
            role=User.Role.CUSTOMER,
        )
        response = self.client.post(reverse('dashboard_login'), {
            'username': 'shopper', 'password': 'sup3r-secret-pw',
        })
        self.assertNotIn('admin_user_id', self.client.session)
        self.assertContains(response, 'does not have dashboard access')

    def test_switched_off_role_blocks_sign_in(self):
        make_admin('paused', permissions=['bookings.view'], role_active=False)
        self.client.post(reverse('dashboard_login'), {
            'username': 'paused', 'password': 'sup3r-secret-pw',
        })
        self.assertNotIn('admin_user_id', self.client.session)

    def test_bare_superuser_gets_a_profile_on_first_sign_in(self):
        User.objects.create_superuser(username='root', password='sup3r-secret-pw')
        response = self.client.post(reverse('dashboard_login'), {
            'username': 'root', 'password': 'sup3r-secret-pw',
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(
            AdminProfile.objects.get(user__username='root').is_super_admin
        )

    def test_sign_in_rotates_the_session_key(self):
        self.client.get(reverse('dashboard_login'))
        before = self.client.session.session_key
        self.client.post(reverse('dashboard_login'), {
            'username': 'desk', 'password': 'sup3r-secret-pw',
        })
        self.assertNotEqual(before, self.client.session.session_key)

    def test_every_attempt_is_logged(self):
        self.client.post(reverse('dashboard_login'), {
            'username': 'desk', 'password': 'not-it',
        })
        self.client.post(reverse('dashboard_login'), {
            'username': 'desk', 'password': 'sup3r-secret-pw',
        })
        outcomes = list(
            AdminLoginAttempt.objects.order_by('created_at')
            .values_list('outcome', flat=True)
        )
        self.assertEqual(outcomes, ['BAD_PASSWORD', 'SUCCESS'])


class BruteForceTests(TestCase):

    def setUp(self):
        self.profile = make_admin('target', permissions=['bookings.view'])
        self.url = reverse('dashboard_login')

    def guess(self, times, username='target', password='wrong-guess', **extra):
        for _ in range(times):
            self.client.post(
                self.url, {'username': username, 'password': password}, **extra
            )

    def test_the_right_password_is_refused_once_locked(self):
        self.guess(security.USERNAME_THRESHOLD)

        response = self.client.post(self.url, {
            'username': 'target', 'password': 'sup3r-secret-pw',
        })
        self.assertNotIn('admin_user_id', self.client.session)
        self.assertContains(response, 'Too many failed sign-in attempts')

    def test_one_short_of_the_threshold_still_works(self):
        self.guess(security.USERNAME_THRESHOLD - 1)

        response = self.client.post(self.url, {
            'username': 'target', 'password': 'sup3r-secret-pw',
        })
        self.assertRedirects(response, reverse('dashboard'))

    def test_a_blocked_attempt_does_not_extend_the_lock(self):
        """Otherwise anyone could keep a real admin out just by hammering."""
        self.guess(security.USERNAME_THRESHOLD)
        first = security.lock_status('target', '127.0.0.1').until

        self.guess(10)
        self.assertEqual(security.lock_status('target', '127.0.0.1').until, first)

    def test_the_lock_lifts_when_the_wait_is_served(self):
        self.guess(security.USERNAME_THRESHOLD)
        self.assertTrue(security.lock_status('target', '127.0.0.1').locked)

        AdminLoginAttempt.objects.update(
            created_at=timezone.now() - timedelta(minutes=20),
        )
        self.assertFalse(security.lock_status('target', '127.0.0.1').locked)

    def test_a_single_guess_re_locks_once_the_wait_is_served(self):
        """
        Past the threshold an attacker gets one guess per lockout window, not
        a fresh batch of five -- which is what makes guessing hopeless rather
        than merely slow.
        """
        self.guess(security.USERNAME_THRESHOLD)
        AdminLoginAttempt.objects.update(
            created_at=timezone.now() - timedelta(minutes=20),
        )
        self.assertFalse(security.lock_status('target', None).locked)

        self.guess(1)
        self.assertTrue(security.lock_status('target', None).locked)

    def test_the_wait_escalates_with_total_failures(self):
        """Each tier of accumulated failures costs the attacker more time."""
        waits = []
        for _ in range(security.IP_THRESHOLD):
            AdminLoginAttempt.objects.create(
                username='target', ip_address='127.0.0.1',
                outcome=AdminLoginAttempt.Outcome.BAD_PASSWORD,
            )
            status = security.lock_status('target', None)
            if status.locked:
                waits.append(status.seconds_left)

        self.assertEqual(
            sorted(set(waits)),
            [15 * 60 - 1, 60 * 60 - 1, 24 * 60 * 60 - 1],
        )

    def test_a_successful_sign_in_wipes_the_count(self):
        self.guess(security.USERNAME_THRESHOLD - 1)
        self.client.post(self.url, {
            'username': 'target', 'password': 'sup3r-secret-pw',
        })
        self.client.get(reverse('dashboard_logout'))

        self.guess(security.USERNAME_THRESHOLD - 1)
        self.assertFalse(security.lock_status('target', None).locked)

    def test_one_address_locks_after_spraying_many_usernames(self):
        """A username counter never sees a password tried once per account."""
        for i in range(security.IP_THRESHOLD):
            self.client.post(
                self.url,
                {'username': f'staff{i}', 'password': 'Password123'},
                REMOTE_ADDR='203.0.113.9',
            )

        status = security.lock_status('someone-else', '203.0.113.9')
        self.assertTrue(status.locked)
        self.assertEqual(status.scope, security.SCOPE_IP)

    def test_locking_one_username_leaves_others_alone(self):
        make_admin('bystander', permissions=['bookings.view'])
        self.guess(security.USERNAME_THRESHOLD)

        response = self.client.post(self.url, {
            'username': 'bystander', 'password': 'sup3r-secret-pw',
        })
        self.assertRedirects(response, reverse('dashboard'))

    def test_unlocking_clears_the_count_but_keeps_the_log(self):
        self.guess(security.USERNAME_THRESHOLD)
        logged = AdminLoginAttempt.objects.count()

        security.clear_failures(security.SCOPE_USERNAME, 'target')

        self.assertFalse(security.lock_status('target', None).locked)
        self.assertEqual(AdminLoginAttempt.objects.count(), logged)

    def test_a_forwarded_address_is_used_when_present(self):
        for i in range(security.IP_THRESHOLD):
            self.client.post(
                self.url,
                {'username': f'staff{i}', 'password': 'Password123'},
                HTTP_X_FORWARDED_FOR='198.51.100.4, 10.0.0.1',
                REMOTE_ADDR='10.0.0.1',
            )
        self.assertTrue(security.lock_status('anyone', '198.51.100.4').locked)

    def test_the_unlock_page_lists_and_clears_a_lock(self):
        boss = make_admin('boss', super_admin=True)
        self.guess(security.USERNAME_THRESHOLD)

        self.client.post(reverse('dashboard_login'), {
            'username': 'boss', 'password': 'sup3r-secret-pw',
        })
        page = self.client.get(reverse('login_security'))
        self.assertContains(page, 'target')

        self.client.post(reverse('login_security_unlock'), {
            'scope': 'username', 'key': 'target',
        })
        self.assertFalse(security.lock_status('target', None).locked)
        self.assertTrue(boss.is_super_admin)


class PermissionEnforcementTests(TestCase):

    def sign_in(self, username):
        self.client.post(reverse('dashboard_login'), {
            'username': username, 'password': 'sup3r-secret-pw',
        })

    def test_a_granted_page_opens(self):
        make_admin('reader', permissions=['bookings.view'])
        self.sign_in('reader')
        self.assertEqual(self.client.get(reverse('bookings_list')).status_code, 200)

    def test_a_page_outside_the_role_is_refused(self):
        make_admin('reader', permissions=['bookings.view'])
        self.sign_in('reader')

        response = self.client.get(reverse('vendors_list'))
        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response, 'not part of your role', status_code=403,
        )

    def test_view_access_does_not_include_acting(self):
        """Reading bookings must not let someone cancel one."""
        make_admin('reader', permissions=['bookings.view'])
        self.sign_in('reader')

        response = self.client.post(reverse('cancel_booking', args=[1]))
        self.assertRedirects(response, reverse('dashboard'))

    def test_the_dashboard_home_is_open_to_everyone_signed_in(self):
        make_admin('minimal', permissions=['support.view'])
        self.sign_in('minimal')
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_a_super_admin_reaches_everything(self):
        make_admin('boss', super_admin=True)
        self.sign_in('boss')
        for name in ('vendors_list', 'reports', 'roles_list', 'login_security'):
            self.assertEqual(
                self.client.get(reverse(name)).status_code, 200, name,
            )

    def test_the_sidebar_only_shows_what_the_role_can_open(self):
        make_admin('reader', permissions=['bookings.view'])
        self.sign_in('reader')

        home = self.client.get(reverse('dashboard'))
        self.assertContains(home, reverse('bookings_list'))
        self.assertNotContains(home, reverse('vendors_list'))
        self.assertNotContains(home, reverse('roles_list'))

    def test_signing_out_ends_access(self):
        make_admin('reader', permissions=['bookings.view'])
        self.sign_in('reader')
        self.client.get(reverse('dashboard_logout'))

        response = self.client.get(reverse('bookings_list'))
        self.assertRedirects(response, reverse('dashboard_login'))

    def test_revoking_a_role_takes_effect_on_the_next_request(self):
        profile = make_admin('reader', permissions=['bookings.view'])
        self.sign_in('reader')

        profile.role.permissions = ['support.view']
        profile.role.save()

        self.assertEqual(self.client.get(reverse('bookings_list')).status_code, 403)

    def test_disabling_an_account_signs_it_out(self):
        profile = make_admin('reader', permissions=['bookings.view'])
        self.sign_in('reader')

        AdminProfile.objects.filter(pk=profile.pk).update(is_active=False)

        response = self.client.get(reverse('bookings_list'))
        self.assertRedirects(response, reverse('dashboard_login'))

    def test_an_ajax_denial_comes_back_as_json(self):
        make_admin('reader', permissions=['bookings.view'])
        self.sign_in('reader')

        response = self.client.post(
            reverse('home_section_reorder', args=[1]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])


class EscalationTests(TestCase):
    """Nobody may hand out an access they do not hold themselves."""

    def sign_in(self, username):
        self.client.post(reverse('dashboard_login'), {
            'username': username, 'password': 'sup3r-secret-pw',
        })

    def test_a_role_cannot_be_given_more_than_its_author_holds(self):
        make_admin('hr', permissions=['system.roles', 'support.view'])
        self.sign_in('hr')

        self.client.post(reverse('role_add'), {
            'name': 'Sneaky',
            'is_active': 'on',
            'permissions': ['support.view', 'payments.manage'],
        })

        role = AdminRole.objects.get(name='Sneaky')
        self.assertEqual(role.permissions, ['support.view'])

    def test_a_role_holding_more_than_the_editor_cannot_be_edited(self):
        make_admin('hr', permissions=['system.roles'])
        strong = AdminRole.objects.create(
            name='Finance', permissions=['payments.manage'],
        )
        self.sign_in('hr')

        response = self.client.get(reverse('role_edit', args=[strong.id]))
        self.assertRedirects(response, reverse('roles_list'))

        strong.refresh_from_db()
        self.assertEqual(strong.permissions, ['payments.manage'])

    def test_only_a_super_admin_can_create_a_super_admin(self):
        make_admin('hr', permissions=['system.staff', 'support.view'])
        role = AdminRole.objects.create(name='Helper', permissions=['support.view'])
        self.sign_in('hr')

        self.client.post(reverse('admin_user_add'), {
            'username': 'newbie', 'full_name': 'New Bie',
            'password': 'sup3r-secret-pw', 'confirm_password': 'sup3r-secret-pw',
            'role': str(role.id), 'is_active': 'on', 'is_super_admin': 'on',
        })

        self.assertFalse(
            AdminProfile.objects.get(user__username='newbie').is_super_admin
        )

    def test_a_super_admin_account_is_not_editable_by_staff(self):
        boss = make_admin('boss', super_admin=True)
        make_admin('hr', permissions=['system.staff'])
        self.sign_in('hr')

        response = self.client.get(reverse('admin_user_edit', args=[boss.id]))
        self.assertRedirects(response, reverse('admin_users_list'))

    def test_a_stronger_role_is_not_offered_when_assigning_one(self):
        make_admin('hr', permissions=['system.staff', 'support.view'])
        AdminRole.objects.create(name='Finance', permissions=['payments.manage'])
        weak = AdminRole.objects.create(name='Helper', permissions=['support.view'])
        self.sign_in('hr')

        page = self.client.get(reverse('admin_user_add'))
        self.assertContains(page, 'Helper')
        self.assertNotContains(page, 'Finance')
        self.assertTrue(weak.is_active)

    def test_the_last_super_admin_cannot_be_deleted(self):
        boss = make_admin('boss', super_admin=True)
        other = make_admin('boss2', super_admin=True)
        self.sign_in('boss')

        self.client.post(reverse('admin_user_delete', args=[other.id]))
        self.assertFalse(AdminProfile.objects.filter(pk=other.pk).exists())

        # `boss` is now the only one left, and is also signing the request.
        self.client.post(reverse('admin_user_delete', args=[boss.id]))
        self.assertTrue(AdminProfile.objects.filter(pk=boss.pk).exists())


class RoleAndUserFlowTests(TestCase):
    """The flow an admin actually follows: name a role, then hand out logins."""

    def setUp(self):
        make_admin('boss', super_admin=True)
        self.client.post(reverse('dashboard_login'), {
            'username': 'boss', 'password': 'sup3r-secret-pw',
        })

    def test_an_admin_names_a_role_and_picks_its_accesses(self):
        self.client.post(reverse('role_add'), {
            'name': 'Booking Desk',
            'description': 'Handles incoming jobs',
            'is_active': 'on',
            'permissions': ['bookings.view', 'bookings.manage', 'bookings.assign'],
        })

        role = AdminRole.objects.get(name='Booking Desk')
        self.assertEqual(
            role.permissions, ['bookings.view', 'bookings.manage', 'bookings.assign'],
        )

    def test_an_unknown_permission_code_is_dropped(self):
        self.client.post(reverse('role_add'), {
            'name': 'Odd', 'is_active': 'on',
            'permissions': ['bookings.view', 'made.up'],
        })
        self.assertEqual(AdminRole.objects.get(name='Odd').permissions, ['bookings.view'])

    def test_a_role_with_no_accesses_is_refused(self):
        self.client.post(reverse('role_add'), {'name': 'Empty', 'is_active': 'on'})
        self.assertFalse(AdminRole.objects.filter(name='Empty').exists())

    def test_a_role_in_use_cannot_be_deleted(self):
        profile = make_admin('desk', permissions=['bookings.view'])
        self.client.post(reverse('role_delete', args=[profile.role_id]))
        self.assertTrue(AdminRole.objects.filter(pk=profile.role_id).exists())

    def test_the_new_user_can_sign_in_with_what_the_admin_set(self):
        role = AdminRole.objects.create(
            name='Booking Desk', permissions=['bookings.view'],
        )
        self.client.post(reverse('admin_user_add'), {
            'username': 'priya', 'full_name': 'Priya R',
            'email': 'priya@example.com',
            'password': 'kite-harbour-92', 'confirm_password': 'kite-harbour-92',
            'role': str(role.id), 'is_active': 'on',
        })

        self.client.get(reverse('dashboard_logout'))
        response = self.client.post(reverse('dashboard_login'), {
            'username': 'priya', 'password': 'kite-harbour-92',
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(self.client.get(reverse('bookings_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 403)

    def test_a_new_user_is_kept_out_of_the_django_admin_site(self):
        role = AdminRole.objects.create(name='Desk', permissions=['bookings.view'])
        self.client.post(reverse('admin_user_add'), {
            'username': 'priya', 'full_name': 'Priya R',
            'password': 'kite-harbour-92', 'confirm_password': 'kite-harbour-92',
            'role': str(role.id), 'is_active': 'on',
        })
        self.assertFalse(User.objects.get(username='priya').is_staff)

    def test_mismatched_passwords_create_nothing(self):
        role = AdminRole.objects.create(name='Desk', permissions=['bookings.view'])
        self.client.post(reverse('admin_user_add'), {
            'username': 'priya', 'full_name': 'Priya R',
            'password': 'kite-harbour-92', 'confirm_password': 'something-else',
            'role': str(role.id), 'is_active': 'on',
        })
        self.assertFalse(User.objects.filter(username='priya').exists())

    def test_a_weak_password_is_refused(self):
        role = AdminRole.objects.create(name='Desk', permissions=['bookings.view'])
        self.client.post(reverse('admin_user_add'), {
            'username': 'priya', 'full_name': 'Priya R',
            'password': '12345678', 'confirm_password': '12345678',
            'role': str(role.id), 'is_active': 'on',
        })
        self.assertFalse(User.objects.filter(username='priya').exists())

    def test_resetting_a_password_also_clears_their_lockout(self):
        profile = make_admin('desk', permissions=['bookings.view'])

        self.client.get(reverse('dashboard_logout'))
        for _ in range(security.USERNAME_THRESHOLD):
            self.client.post(reverse('dashboard_login'), {
                'username': 'desk', 'password': 'nope',
            })
        self.assertTrue(security.lock_status('desk', None).locked)

        self.client.post(reverse('dashboard_login'), {
            'username': 'boss', 'password': 'sup3r-secret-pw',
        })
        self.client.post(reverse('admin_user_password', args=[profile.id]), {
            'password': 'otter-lantern-41', 'confirm_password': 'otter-lantern-41',
        })

        self.assertFalse(security.lock_status('desk', None).locked)
        profile.user.refresh_from_db()
        self.assertTrue(profile.user.check_password('otter-lantern-41'))
