from .gstin import GST_PORTAL_SEARCH_URL, STATE_CODES


def gst(request):
	"""Settings for static/js/gstin.js, rendered with json_script by templates/includes/gstin_script.html."""
	return {'gst_config': {'portal': GST_PORTAL_SEARCH_URL, 'states': STATE_CODES}}
