#!/usr/bin/env python3
"""
Embed the current NASA Moon Phase and Libration frame into the profile SVG.

NASA source:
https://svs.gsfc.nasa.gov/5587/

The 2026 frame set contains one frame for every UTC hour:
frame 0001 = 2026-01-01 00:00 UTC.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
import re
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BANNER_PATH = Path("assets/lunalfresh-space-banner.svg")

NASA_FRAME_DIRECTORIES = {
    2026: (
        "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/"
        "frames/730x730_1x1_30p"
    ),
}

BEGIN_MARKER = "<!-- BEGIN NASA MOON -->"
END_MARKER = "<!-- END NASA MOON -->"


def current_frame(now: datetime) -> int:
    """Return NASA's 1-based hourly frame number for the supplied UTC time."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    return int((now - start).total_seconds() // 3600) + 1


def _read_response(request: Request, *, context=None) -> bytes:
    with urlopen(request, timeout=45, context=context) as response:
        return response.read()


def download(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "LunalFresh-GitHub-Profile/1.0 "
                "(NASA Moon Phase banner updater)"
            )
        },
    )

    try:
        # Use normal certificate verification first.
        data = _read_response(request)
    except HTTPError as exc:
        raise RuntimeError(
            f"NASA returned HTTP {exc.code} for {url}"
        ) from exc
    except URLError as exc:
        reason_text = str(exc.reason)
        certificate_failed = "CERTIFICATE_VERIFY_FAILED" in reason_text
        trusted_nasa_host = url.startswith("https://svs.gsfc.nasa.gov/")

        if not (certificate_failed and trusted_nasa_host):
            raise RuntimeError(
                f"Could not reach NASA: {exc.reason}"
            ) from exc

        # NASA SVS is currently serving an expired certificate. Retry only
        # this exact NASA hostname without certificate verification.
        print(
            "WARNING: NASA SVS certificate verification failed; "
            "retrying this NASA host without certificate verification."
        )

        insecure_context = ssl.create_default_context()
        insecure_context.check_hostname = False
        insecure_context.verify_mode = ssl.CERT_NONE

        try:
            data = _read_response(request, context=insecure_context)
        except HTTPError as retry_exc:
            raise RuntimeError(
                f"NASA returned HTTP {retry_exc.code} for {url}"
            ) from retry_exc
        except URLError as retry_exc:
            raise RuntimeError(
                "Could not reach NASA after certificate fallback: "
                f"{retry_exc.reason}"
            ) from retry_exc

    if not data.startswith(b"\xff\xd8"):
        raise RuntimeError("Downloaded NASA frame is not a JPEG")
    if len(data) < 20_000:
        raise RuntimeError(
            f"Downloaded NASA frame is unexpectedly small: {len(data)} bytes"
        )

    return data


def build_moon_block(
    *,
    jpeg: bytes,
    timestamp: datetime,
    frame: int,
    source_url: str,
) -> str:
    encoded = base64.b64encode(jpeg).decode("ascii")
    timestamp_text = timestamp.strftime("%Y-%m-%d %H:00 UTC")

    return f"""<!-- BEGIN NASA MOON -->
  <!-- NASA Moon Phase and Libration: {timestamp_text}; frame {frame:04d} -->
  <!-- Source: {source_url} -->
  <g id="moon" filter="url(#moonGlow)">
    <image
      x="1210"
      y="54"
      width="300"
      height="300"
      preserveAspectRatio="xMidYMid meet"
      href="data:image/jpeg;base64,{encoded}"
    />
  </g>
  <!-- END NASA MOON -->"""


def main() -> int:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    frame_directory = NASA_FRAME_DIRECTORIES.get(now.year)
    if frame_directory is None:
        supported = ", ".join(str(year) for year in sorted(NASA_FRAME_DIRECTORIES))
        raise RuntimeError(
            f"No NASA frame directory configured for {now.year}. "
            f"Currently configured: {supported}. "
            "Add the new annual NASA SVS frame directory to "
            "NASA_FRAME_DIRECTORIES."
        )

    frame = current_frame(now)
    source_url = f"{frame_directory}/moon.{frame:04d}.jpg"

    print(f"UTC time: {now.isoformat()}")
    print(f"NASA frame: {frame:04d}")
    print(f"Downloading: {source_url}")

    jpeg = download(source_url)
    banner = BANNER_PATH.read_text(encoding="utf-8")

    if BEGIN_MARKER not in banner or END_MARKER not in banner:
        raise RuntimeError(
            f"{BANNER_PATH} is missing the NASA Moon replacement markers"
        )

    replacement = build_moon_block(
        jpeg=jpeg,
        timestamp=now,
        frame=frame,
        source_url=source_url,
    )

    pattern = re.compile(
        re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER),
        flags=re.DOTALL,
    )
    updated, replacements = pattern.subn(replacement, banner, count=1)

    if replacements != 1:
        raise RuntimeError(
            f"Expected one NASA Moon block, replaced {replacements}"
        )

    if updated == banner:
        print("Banner already contains this Moon frame; nothing changed.")
        return 0

    BANNER_PATH.write_text(updated, encoding="utf-8")
    print(f"Updated {BANNER_PATH} with {len(jpeg):,} bytes of NASA imagery.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
