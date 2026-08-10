from django.contrib import admin
from .models import ServiceForm, FormStep, FormOption, FormSubmission


class FormOptionInline(admin.TabularInline):
    model = FormOption
    extra = 2
    fields = ('label', 'sort_order')


class FormStepInline(admin.StackedInline):
    model = FormStep
    extra = 1
    fields = ('title', 'description', 'field_type', 'is_required', 'allow_custom', 'step_order')
    show_change_link = True


@admin.register(ServiceForm)
class ServiceFormAdmin(admin.ModelAdmin):
    list_display = ('name', 'service', 'subcategory', 'category', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    autocomplete_fields = ('service', 'subcategory', 'category')
    inlines = [FormStepInline]


@admin.register(FormStep)
class FormStepAdmin(admin.ModelAdmin):
    list_display = ('title', 'form', 'field_type', 'is_required', 'step_order')
    list_filter = ('field_type', 'is_required')
    search_fields = ('title', 'form__name')
    inlines = [FormOptionInline]


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'form', 'customer', 'booking', 'submitted_at')
    list_filter = ('form',)
    readonly_fields = ('form', 'customer', 'booking', 'responses', 'submitted_at')

    def has_add_permission(self, request):
        return False