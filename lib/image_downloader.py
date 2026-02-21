"""Download and save recipe images."""

import sys
from pathlib import Path
from typing import Optional

import requests


def download_image(url: str, target_path: Path) -> Optional[Path]:
    """Download an image from a URL and save it locally.

    Args:
        url: Image URL to download
        target_path: Local path to save the image

    Returns:
        Path to saved image, or None on failure
    """
    try:
        response = requests.get(url, timeout=15, stream=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; KitchenOS/1.0)"
        })
        response.raise_for_status()

        # Verify it's actually an image
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            print(f"  -> Not an image: {content_type}", file=sys.stderr)
            return None

        # Create parent directory
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write image data
        with open(target_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return target_path

    except Exception as e:
        print(f"  -> Image download failed: {e}", file=sys.stderr)
        # Clean up partial download
        if target_path.exists():
            target_path.unlink()
        return None
