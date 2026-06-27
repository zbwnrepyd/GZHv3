"""Shared display_role defaults for card items.

Extracted from card_config_service.py so render_assembler.py and
card_config_repo.py can reuse the same logic without circular imports.

Import convention:
    from services.role_defaults import default_role_for_field, default_role_for_media
"""


def default_role_for_field(field_key: str) -> str:
    """Return the display_role for a field based on its field_key."""
    if field_key in ("company_name",):
        return "title"
    if field_key in ("company_type",):
        return "subtitle"
    return "body"


def default_role_for_media(media_key: str) -> str:
    """Return the display_role for a media asset based on its asset_key."""
    if media_key == "logo":
        return "logo"
    if media_key in ("flywheel", "timeline", "chart_competitive", "chart_ecosystem"):
        return "chart"
    if media_key in ("competitors_logo_strip",):
        return "decoration"
    return "hero_image"
