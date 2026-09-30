"""Save a supplier's trade, material category, material, brand and project links from plain names.

Names that are not yet in the master data are created, so the Excel upload and the
supplier form accept the same free-text values as the original spreadsheet.
"""
import re

from django.db.models import Q

from materials.models import Brand, Material, MaterialCategory, Trade
from projects.models import Project
from relationships.models import (
	SupplierBrand, SupplierMaterial, SupplierMaterialCategory, SupplierProject, SupplierTrade,
)

DEFAULT_MATERIAL_CATEGORY = 'General'
LINK_FIELDS = ('trades', 'material_categories', 'materials', 'brands', 'projects')


def split_names(value):
	if value is None:
		return []
	names = [name.strip() for name in re.split(r'[,;|\n]+', str(value)) if name.strip()]
	return list(dict.fromkeys(names))


def join_names(names):
	return ', '.join(names)


def named_record(model, name):
	record = model.objects.filter(name__iexact=name).first()
	return record or model.objects.create(name=name)


def project_record(name):
	record = Project.objects.filter(Q(name__iexact=name) | Q(code__iexact=name)).first()
	if record:
		return record
	code = name[:50]
	suffix = 2
	while Project.objects.filter(code__iexact=code).exists():
		code = f'{name[:45]}-{suffix}'
		suffix += 1
	return Project.objects.create(code=code, name=name)


def _material(name, category, category_given):
	if not category_given:
		matches = Material.objects.filter(name__iexact=name)
		if matches.count() == 1:
			return matches.first()
	record = Material.objects.filter(category=category, name__iexact=name).first()
	return record or Material.objects.create(category=category, name=name)


def save_links(supplier, names):
	"""Replace the supplier's links with the given lists of names (keys from LINK_FIELDS)."""
	categories = [named_record(MaterialCategory, name) for name in names.get('material_categories', [])]
	materials = []
	material_names = names.get('materials', [])
	for index, name in enumerate(material_names):
		if len(categories) == len(material_names):
			category = categories[index]
		elif categories:
			category = categories[0]
		else:
			category = named_record(MaterialCategory, DEFAULT_MATERIAL_CATEGORY)
		materials.append(_material(name, category, bool(categories)))

	supplier.trade_links.all().delete()
	supplier.material_category_links.all().delete()
	supplier.material_links.all().delete()
	supplier.brand_links.all().delete()
	supplier.project_links.all().delete()
	for trade in dict.fromkeys(named_record(Trade, name) for name in names.get('trades', [])):
		SupplierTrade.objects.create(supplier=supplier, trade=trade)
	for category in dict.fromkeys(categories):
		SupplierMaterialCategory.objects.create(supplier=supplier, category=category)
	for material in dict.fromkeys(materials):
		SupplierMaterial.objects.create(supplier=supplier, material=material, unit_of_supply=supplier.unit_of_supply)
	for brand in dict.fromkeys(named_record(Brand, name) for name in names.get('brands', [])):
		SupplierBrand.objects.create(supplier=supplier, brand=brand)
	for project in dict.fromkeys(project_record(name) for name in names.get('projects', [])):
		SupplierProject.objects.create(supplier=supplier, project=project)


def current_names(supplier):
	return {
		'trades': [link.trade.name for link in supplier.trade_links.select_related('trade').order_by('pk')],
		'material_categories': [link.category.name for link in supplier.material_category_links.select_related('category').order_by('pk')],
		'materials': [link.material.name for link in supplier.material_links.select_related('material').order_by('pk')],
		'brands': [link.brand.name for link in supplier.brand_links.select_related('brand').order_by('pk')],
		'projects': [link.project.name for link in supplier.project_links.select_related('project').order_by('pk')],
	}
