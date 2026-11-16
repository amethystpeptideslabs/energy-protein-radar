"""Small shared helpers: UTF-8 file IO, dates, URL normalization, money rounding."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
CENT = Decimal("0.01")

TRACKING_PARAMS = {"gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_", "tag", "srsltid", "_ga"}


def now_local() -> datetime:
    override = os.environ.get("DEAL_RADAR_NOW")  # tests / replays: ISO timestamp
    if override:
        dt = datetime.fromisoformat(override)
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    return datetime.now(TZ)


def today() -> date:
    return now_local().date()


def iso_now() -> str:
    return now_local().isoformat(timespec="seconds")


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def days_ago(d: date, n: int) -> date:
    return d - timedelta(days=n)


def money(x: Any) -> Decimal:
    """Exact decimal from float/str/int; never binary-float arithmetic for prices."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def cents(x: Any) -> Decimal:
    return money(x).quantize(CENT, rounding=ROUND_HALF_UP)


def normalize_url(url: str) -> str:
    """Canonical form for provenance matching: lowercase scheme/host, no www, no fragment,
    no tracking params, no trailing slash."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(query), ""))


def url_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data: Any, *, indent: int | None = 1) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent, default=str)
    write_text(path, text + "\n")


def write_text(path: Path, text: str) -> None:
    """Atomic UTF-8 write with LF newlines (same bytes on Windows and Linux)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
