"""Catalog state backed only by records from NASA PSI (bundled or live)."""
from .models import Investigation

NASA_PSI_SOURCE = "https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation"
_LIVE_INVESTIGATIONS: list[Investigation] = []
_BUNDLED_INVESTIGATIONS: list[Investigation] = []
_CATALOG_SOURCE = "NASA PSI archive unavailable"


def get_catalog() -> list[Investigation]:
    """Prefer current live records; otherwise use the bundled PSI snapshot."""
    return (_LIVE_INVESTIGATIONS or _BUNDLED_INVESTIGATIONS).copy()


def set_bundled_catalog(records: list[Investigation]) -> None:
    global _BUNDLED_INVESTIGATIONS, _CATALOG_SOURCE
    _BUNDLED_INVESTIGATIONS = records.copy()
    _CATALOG_SOURCE = "NASA PSI bundled snapshot" if records else "NASA PSI archive unavailable"


def set_live_catalog(records: list[Investigation]) -> None:
    global _LIVE_INVESTIGATIONS, _CATALOG_SOURCE
    _LIVE_INVESTIGATIONS = records.copy()
    if records:
        _CATALOG_SOURCE = "NASA PSI live catalogue"
    elif not _BUNDLED_INVESTIGATIONS:
        _CATALOG_SOURCE = "NASA PSI archive unavailable"


def catalog_source() -> str:
    return _CATALOG_SOURCE


def get_live_catalog() -> list[Investigation]:
    return _LIVE_INVESTIGATIONS.copy()
