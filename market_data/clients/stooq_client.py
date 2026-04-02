"""Stooq bulk-ZIP download client.

Stooq publishes daily and intraday (5-min, hourly) datasets as large ZIP
archives.  This client downloads, extracts, indexes, and caches those
archives in the raw layer.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Iterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from market_data.common.dates import utc_now
from market_data.common.hashing import hash_bytes
from market_data.common.logging import get_logger

log = get_logger("clients.stooq")

_TIMEOUT = httpx.Timeout(30.0, read=120.0)

DAILY_US_STOCKS = "https://stooq.com/db/h/db/d/?b=d_us_txt"
DAILY_WORLD_INDICES = "https://stooq.com/db/h/db/d/?b=d_world_txt"
FIVE_MIN_US = "https://stooq.com/db/h/db/d/?b=5_us_txt"
HOURLY_US = "https://stooq.com/db/h/db/d/?b=h_us_txt"

TICKER_DAILY_URL = "https://stooq.com/q/d/l/?s={ticker}.us&d1={start}&d2={end}&i=d"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=30))
def download_zip(url: str, dest_dir: Path) -> Path:
    """Download a ZIP archive from Stooq and store it in *dest_dir*.

    Returns the path to the downloaded file.  If a file with the same
    content hash already exists, the download is skipped.
    """
    log.info("downloading %s", url)
    dest_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (market-data-research)",
        "Accept": "application/zip",
    }
    import hashlib
    filename = url.rsplit("/", 1)[-1]
    stem = filename.replace(".zip", "")
    tmp_path = dest_dir / f"{stem}_downloading.zip"

    hasher = hashlib.sha256()
    total_bytes = 0

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
                    hasher.update(chunk)
                    total_bytes += len(chunk)

    content_hash = hasher.hexdigest()[:16]
    dest_path = dest_dir / f"{stem}_{content_hash}.zip"

    if dest_path.exists():
        tmp_path.unlink(missing_ok=True)
        log.info("already cached: %s", dest_path.name)
        return dest_path

    tmp_path.rename(dest_path)
    log.info("saved %s (%.1f MB)", dest_path.name, total_bytes / 1e6)
    return dest_path


def extract_zip(zip_path: Path, extract_dir: Path) -> list[Path]:
    """Extract a ZIP archive to *extract_dir*."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            target = extract_dir / member
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())
            extracted.append(target)

    log.info("extracted %d files from %s", len(extracted), zip_path.name)
    return extracted


def iter_csv_files(directory: Path, suffix: str = ".txt") -> Iterator[Path]:
    """Yield all CSV/TXT data files in a Stooq extract directory."""
    yield from sorted(directory.rglob(f"*{suffix}"))


def parse_stooq_ticker(filepath: Path) -> str:
    """Derive the Stooq ticker symbol from the file path.

    Stooq organises files as ``data/<market>/<freq>/<exchange>/<ticker>.txt``.
    """
    return filepath.stem.upper()


def build_raw_metadata(url: str, zip_path: Path) -> dict:
    return {
        "source_url": url,
        "fetched_at_utc": utc_now().isoformat(),
        "content_hash": hash_bytes(zip_path.read_bytes()),
        "dataset_name": zip_path.stem,
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
def download_ticker_csv(
    ticker: str,
    dest_dir: Path,
    start_date: str = "20100101",
    end_date: str | None = None,
) -> Path | None:
    """Download daily CSV for a single ticker from Stooq.

    This is the per-ticker fallback when bulk ZIP downloads require CAPTCHA.
    Returns the path to the saved CSV, or None if ticker has no data.
    """
    if end_date is None:
        end_date = utc_now().strftime("%Y%m%d")

    url = TICKER_DAILY_URL.format(ticker=ticker.lower(), start=start_date, end=end_date)
    headers = {"User-Agent": "Mozilla/5.0 (market-data-research)"}

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

    text = resp.text.strip()
    if not text or "No data" in text or len(text) < 50:
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{ticker.upper()}.txt"
    out_path.write_text(text)
    return out_path
