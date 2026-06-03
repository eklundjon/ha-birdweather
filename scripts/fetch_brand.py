"""Fetch the official BirdWeather app icon and write the Home Assistant brand
assets (served by HA's 2026.3+ brand proxy from custom_components/<domain>/brand/).

Source: BirdWeather's PWA icon at app.birdweather.com (the official mark, a
512x512 transparent PNG). Re-run to refresh if BirdWeather updates their icon.
"""

import io
import os
import urllib.request

from PIL import Image

SRC = "https://app.birdweather.com/android-chrome-512x512.png"
OUT = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "birdweather", "brand"
)


def main() -> None:
    data = urllib.request.urlopen(SRC, timeout=30).read()  # noqa: S310 (trusted host)
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.size != (512, 512):
        img = img.resize((512, 512), Image.LANCZOS)

    os.makedirs(OUT, exist_ok=True)
    img.save(os.path.join(OUT, "icon@2x.png"))                       # 512x512
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon.png"))  # 256x256
    print("wrote icon.png (256) + icon@2x.png (512) to", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
