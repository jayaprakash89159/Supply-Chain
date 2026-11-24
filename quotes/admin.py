from django.contrib import admin

from .models import QuoteRecipient, QuoteRequest


class QuoteRecipientInline(admin.TabularInline):
	model = QuoteRecipient
	extra = 0
	readonly_fields = ('kind', 'vendor_code', 'vendor_name', 'emails', 'status', 'error', 'sent_at')
	can_delete = False


@admin.register(QuoteRequest)
class QuoteRequestAdmin(admin.ModelAdmin):
	list_display = ('subject', 'sent_by', 'created_at')
	readonly_fields = ('created_at',)
	inlines = [QuoteRecipientInline]
