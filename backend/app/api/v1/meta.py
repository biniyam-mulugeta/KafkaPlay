"""Front-end bootstrap data: branding, capabilities of *this deployment*, locales.

The React app fetches this before rendering so the theme, product name, and
auth mode are never baked into the bundle. That is what makes the image
white-labelable without a rebuild.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import SettingsDep
from app.clusters.models import MaskPreset
from app.config import AuthMode

router = APIRouter(prefix="/meta", tags=["meta"])

# productName is deliberately None: a theme that fails to load should fall back
# to APP_NAME, not silently rename the product to something else.
_FALLBACK_THEME: dict[str, Any] = {
    "name": "neutral",
    "productName": None,
    "logo": None,
    "favicon": "◷",
    "colors": {},
}


class ThemeInfo(BaseModel):
    name: str
    product_name: str
    logo: str | None = None
    favicon: str | None = None
    colors: dict[str, Any] = {}
    fonts: dict[str, str] = {}


class MetaResponse(BaseModel):
    app_name: str
    version: str
    auth_mode: AuthMode
    # True when the deployment is wide open; the UI shows a permanent banner.
    insecure_no_auth: bool
    read_only: bool
    masking_enabled: bool
    mask_presets: list[MaskPreset]
    prometheus_enabled: bool
    sampler_enabled: bool
    default_locale: str
    available_locales: list[str]
    theme: ThemeInfo


def _load_theme(theme_dir: Path, fallback_product_name: str) -> ThemeInfo:
    """Read themes/<name>/theme.json, tolerating a missing or broken file.

    A broken theme must not take the console down; it falls back to neutral.
    """
    theme_file = theme_dir / "theme.json"
    data = dict(_FALLBACK_THEME)
    if theme_file.is_file():
        try:
            loaded = json.loads(theme_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass

    # The logo is optional by design: the Unideb crest is not redistributable,
    # so a missing file must degrade to a text wordmark rather than a broken
    # image.
    logo = data.get("logo")
    if logo and not (theme_dir / str(logo)).is_file():
        logo = None

    return ThemeInfo(
        name=str(data.get("name", theme_dir.name)),
        product_name=str(data.get("productName") or fallback_product_name),
        logo=f"/brand/{logo}" if logo else None,
        favicon=data.get("favicon"),
        colors=data.get("colors", {}),
        fonts=data.get("fonts", {}),
    )


def _available_locales() -> list[str]:
    locales_dir = Path("locales")
    if not locales_dir.is_dir():
        return ["en"]
    found = sorted(p.stem for p in locales_dir.glob("*.json"))
    return found or ["en"]


@router.get("", response_model=MetaResponse, summary="Deployment metadata for the UI")
def get_meta(settings: SettingsDep) -> MetaResponse:
    from app import __version__

    return MetaResponse(
        app_name=settings.app_name,
        version=__version__,
        auth_mode=settings.auth_mode,
        insecure_no_auth=settings.is_no_auth,
        read_only=settings.read_only,
        masking_enabled=settings.masking_enabled,
        mask_presets=list(MaskPreset),
        prometheus_enabled=settings.prometheus_url is not None,
        sampler_enabled=settings.sampler_enabled,
        default_locale=settings.default_locale,
        available_locales=_available_locales(),
        theme=_load_theme(settings.theme_dir, settings.app_name),
    )
