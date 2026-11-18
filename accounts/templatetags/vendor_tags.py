"""Template helpers for vendor pages: {% load vendor_tags %}."""
from django import template

from scportal.vendor_tools import phone_numbers

register = template.Library()


@register.inclusion_tag('includes/phone_links.html')
def phone_links(*values, compact=False):
	"""Each number in the given fields as a click-to-call link, plus a WhatsApp link for mobiles."""
	return {'numbers': phone_numbers(*values), 'compact': compact}
