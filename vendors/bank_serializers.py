from rest_framework import serializers

from .bank_models import (
    ACCOUNT_NUMBER_RE, IFSC_RE, UPI_RE, VendorBankAccount,
)


class VendorBankAccountSerializer(serializers.ModelSerializer):
    """
    Read side. Never carries the account number in full.

    The vendor already knows their own number; echoing it back only creates
    another place for it to leak from. The last four is enough to recognise
    the right account.
    """
    account_number = serializers.CharField(
        source='masked_account_number', read_only=True
    )
    account_type_display = serializers.CharField(
        source='get_account_type_display', read_only=True
    )
    is_payable = serializers.BooleanField(read_only=True)

    class Meta:
        model = VendorBankAccount
        fields = [
            'account_holder_name', 'account_number', 'ifsc_code', 'bank_name',
            'branch_name', 'account_type', 'account_type_display', 'upi_id',
            'is_verified', 'is_payable', 'verified_at', 'updated_at',
        ]
        read_only_fields = fields


class VendorBankAccountWriteSerializer(serializers.ModelSerializer):
    """
    Write side, used for both the first save and every later change.

    Validation is strict on purpose. A typo here does not fail loudly -- it
    quietly sends someone else's money to a stranger's account, and the first
    anyone hears of it is a vendor asking where their payout went.
    """

    # Typed twice, the way every bank's own form does it, because there is no
    # way to notice a wrong digit by reading it back.
    confirm_account_number = serializers.CharField(write_only=True)

    class Meta:
        model = VendorBankAccount
        fields = [
            'account_holder_name', 'account_number', 'confirm_account_number',
            'ifsc_code', 'bank_name', 'branch_name', 'account_type', 'upi_id',
        ]

    def validate_account_holder_name(self, value):
        value = ' '.join(value.split())
        if len(value) < 3:
            raise serializers.ValidationError(
                "Enter the full name on the bank account."
            )
        return value

    def validate_account_number(self, value):
        value = value.strip().replace(' ', '')
        if not ACCOUNT_NUMBER_RE.match(value):
            raise serializers.ValidationError(
                "An account number is 9 to 18 digits, with no letters or spaces."
            )
        return value

    def validate_ifsc_code(self, value):
        value = value.strip().upper().replace(' ', '')
        if not IFSC_RE.match(value):
            raise serializers.ValidationError(
                "That IFSC code does not look right. It is 11 characters, "
                "like SBIN0001234."
            )
        return value

    def validate_upi_id(self, value):
        value = (value or '').strip().lower()
        if value and not UPI_RE.match(value):
            raise serializers.ValidationError(
                "A UPI id looks like yourname@bank."
            )
        return value

    def validate(self, attrs):
        # Compared after both have been cleaned, so a stray space in one of
        # them is not reported as a mismatch.
        confirm = attrs.pop('confirm_account_number', '')
        confirm = confirm.strip().replace(' ', '')
        if attrs.get('account_number') != confirm:
            raise serializers.ValidationError(
                {'confirm_account_number': "The account numbers do not match."}
            )
        return attrs
