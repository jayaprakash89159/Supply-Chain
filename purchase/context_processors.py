def purchase_alerts(request):
	"""How many POs are waiting for this user's approval, for the badge on the Purchase orders menu item."""
	user = getattr(request, 'user', None)
	if user is None or not user.is_authenticated:
		return {}
	from .models import ApprovalLevel, PurchaseOrder
	from .views import can_approve

	if not ApprovalLevel.objects.filter(is_active=True, approvers=user).exists():
		return {'show_purchase_menu': user.is_superuser}
	waiting = sum(1 for order in PurchaseOrder.objects.filter(status=PurchaseOrder.Status.PENDING) if can_approve(user, order)[0])
	return {'show_purchase_menu': True, 'po_approval_count': waiting}
