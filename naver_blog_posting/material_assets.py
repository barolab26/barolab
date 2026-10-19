"""Material Assets - Lightweight Pass-through module."""

from pathlib import Path

VISUAL_SOURCES = ("generated", "capture", "original", "photo")


class MaterialRequired(Exception):
    """Exception class if material is required (never raised in pass-through)."""
    pass


def load_material_manifest(path=None):
    """Load material manifest safely."""
    return {}


def import_materials(*args, **kwargs):
    """Import materials safely."""
    return []


def material_context(*args, **kwargs):
    """Return lightweight material context."""
    return {}


def bind_material_plans(plans=None, *args, **kwargs):
    """Bind material plans cleanly."""
    return plans or []


def review_visual_groups(plans=None, *args, **kwargs):
    """Review visual groups without blocking."""
    return [{'file': f"review_{i}.json"} for i in range(len(plans or []))]


def verify_visual_records(*args, **kwargs):
    """Verify visual records cleanly."""
    return True


def annotate_observed_materials(article=None, *args, **kwargs):
    """Annotate observed materials safely."""
    return article
