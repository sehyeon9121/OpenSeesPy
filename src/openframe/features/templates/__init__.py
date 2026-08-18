"""Bundled starter models ("템플릿") shown on the home screen's Templates
card - see ``catalog.py`` for the manifest format and ``presentation`` for
the gallery page that browses them."""

from openframe.features.templates.catalog import TemplateEntry, load_template_catalog

__all__ = ["TemplateEntry", "load_template_catalog"]
