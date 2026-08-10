# AUTH_USER_MODEL = "accounts.User"
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Create a superuser if it does not already exist"

    def handle(self, *args, **kwargs):
        User = get_user_model()

        username = "nigash2"

        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING("Superuser already exists.")
            )
            return

        User.objects.create_superuser(
            username="nigash2",
            email="nigash6385@gmail.com",
            password="27422742@n",
            role="ADMIN",
            phone_number="9876543210",
        )

        self.stdout.write(
            self.style.SUCCESS("Superuser created successfully!")
        )