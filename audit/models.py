from django.conf import settings
from django.db import models


class AuditEntry(models.Model):
	"""One change to a supplier, subcontractor or their documents: who, when, and what changed."""

	class Kind(models.TextChoices):
		SUPPLIER = 'supplier', 'Supplier'
		SUBCONTRACTOR = 'subcontractor', 'Labour & Composite'

	class Action(models.TextChoices):
		CREATED = 'created', 'Created'
		UPDATED = 'updated', 'Edited'
		STATUS = 'status', 'Status changed'
		DELETED = 'deleted', 'Moved to recycle bin'
		RESTORED = 'restored', 'Restored'
		PURGED = 'purged', 'Deleted permanently'
		DOCUMENT_ADDED = 'document_added', 'Document uploaded'
		DOCUMENT_REMOVED = 'document_removed', 'Document deleted'

	kind = models.CharField(max_length=20, choices=Kind.choices)
	object_id = models.PositiveIntegerField()
	object_label = models.CharField(max_length=300, help_text='Code and name at the time, kept after permanent deletion.')
	action = models.CharField(max_length=20, choices=Action.choices)
	changes = models.JSONField(default=list, blank=True, help_text='[{"field": label, "old": text, "new": text}]')
	note = models.CharField(max_length=300, blank=True)
	user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
	at = models.DateTimeField(auto_now_add=True, db_index=True)

	class Meta:
		ordering = ['-at', '-pk']
		indexes = [models.Index(fields=['kind', 'object_id'], name='audit_object_idx')]
		verbose_name_plural = 'audit entries'

	def __str__(self):
		return f'{self.get_action_display()}: {self.object_label}'
