"""Brand images HA 2026.3+ picks up from custom_components/<domain>/brand/."""

import struct
from pathlib import Path

import pytest

BRAND = Path(__file__).parents[1] / "custom_components" / "vodafone_station_arris" / "brand"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


@pytest.mark.parametrize(("name", "size"), [("icon.png", 256), ("icon@2x.png", 512)])
def test_icon_is_square_png_of_brands_size(name: str, size: int) -> None:
    assert png_size(BRAND / name) == (size, size)
