from django import forms
from django.contrib import admin
from django.contrib.auth.hashers import make_password
from accounts.models import User
from .models import Vendor, VendorDocument


class VendorDocumentInline(admin.TabularInline):
    model = VendorDocument
    extra = 1


class VendorAdminForm(forms.ModelForm):
    """
    Lets the admin create a vendor's LOGIN (username + password) at the
    same time as creating their Vendor profile, in ONE screen.
    """
    username = forms.CharField(max_length=150, required=True, help_text="Login username for the vendor app")
    password = forms.CharField(
        widget=forms.PasswordInput, required=False,
        help_text="Set a password. Leave blank when editing to keep the existing password."
    )
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=False)
    phone_number = forms.CharField(max_length=15, required=True)

    class Meta:
        model = Vendor
        fields = ['categories', 'service_area', 'address', 'verification_status', 'is_available']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If editing an existing vendor, pre-fill the linked user's details
        if self.instance and self.instance.pk and self.instance.user_id:
            u = self.instance.user
            self.fields['username'].initial = u.username
            self.fields['first_name'].initial = u.first_name
            self.fields['last_name'].initial = u.last_name
            self.fields['phone_number'].initial = u.phone_number
            self.fields['password'].required = False

    def save(self, commit=True):
        vendor = super().save(commit=False)

        if vendor.pk and vendor.user_id:
            # Editing an existing vendor -> update the linked user
            user = vendor.user
        else:
            # Creating a new vendor -> create a new User for them
            user = User(role=User.Role.VENDOR)

        user.username = self.cleaned_data['username']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data.get('last_name', '')
        user.phone_number = self.cleaned_data['phone_number']
        user.role = User.Role.VENDOR

        if self.cleaned_data.get('password'):
            user.password = make_password(self.cleaned_data['password'])

        user.save()
        vendor.user = user

        if commit:
            vendor.save()
            self.save_m2m()
        return vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    form = VendorAdminForm
    list_display = ('user', 'service_area', 'verification_status', 'is_available', 'category_list', 'created_at')
    list_filter = ('verification_status', 'is_available', 'categories', 'service_area')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'service_area')
    inlines = [VendorDocumentInline]

    fieldsets = (
        ('Login Credentials (Vendor App)', {
            'fields': ('username', 'password', 'first_name', 'last_name', 'phone_number')
        }),
        ('Vendor Details', {
            'fields': ('categories', 'service_area', 'address', 'verification_status', 'is_available')
        }),
    )

    def category_list(self, obj):
        return ", ".join(c.name for c in obj.categories.all())
    category_list.short_description = "Categories"


from .bank_models import VendorBankAccount, VendorBankAccountChange


@admin.register(VendorBankAccount)
class VendorBankAccountAdmin(admin.ModelAdmin):
    list_display = ('vendor', 'masked_account_number', 'ifsc_code',
                    'bank_name', 'is_verified', 'updated_at')
    list_filter = ('is_verified', 'account_type')
    search_fields = ('vendor__user__username', 'ifsc_code', 'bank_name')
    readonly_fields = ('masked_account_number', 'verified_at', 'verified_by',
                       'created_at', 'updated_at')
    # The full number is what a payout is made against; it is not something to
    # leave sitting on a list page. Use the vendor dashboard to act on these.
    exclude = ('account_number',)


@admin.register(VendorBankAccountChange)
class VendorBankAccountChangeAdmin(admin.ModelAdmin):
    list_display = ('vendor', 'old_account_masked', 'new_account_masked',
                    'changed_by', 'changed_at')
    search_fields = ('vendor__user__username',)
    readonly_fields = [f.name for f in VendorBankAccountChange._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
