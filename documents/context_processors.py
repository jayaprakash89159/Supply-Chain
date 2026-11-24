def document_alerts(request):
	"""Number of expired / soon-expiring documents, for the badge on the Documents menu item."""
	if not getattr(request, 'user', None) or not request.user.is_authenticated:
		return {}
	from .views import alert_counts

	expired, expiring = alert_counts()
	return {'document_alert_count': expired + expiring}
