"""Resumable, checksum-verified downloads of public dataset files.

Large dump servers drop long connections, so downloads resume from the partial file with HTTP Range
requests and are only moved into place after the published checksum matches.
"""

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1 << 20


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteFile:
    url: str
    filename: str
    sha256: str | None = None
    sha1: str | None = None


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: Path, remote: RemoteFile) -> None:
    for algorithm, expected in (("sha256", remote.sha256), ("sha1", remote.sha1)):
        if expected and file_digest(path, algorithm) != expected.lower():
            raise DownloadError(f"{algorithm} mismatch for {path.name}")


def download(
    remote: RemoteFile,
    dest_dir: Path,
    client: httpx.Client,
    *,
    max_attempts: int = 10,
    backoff_seconds: float = 2.0,
) -> Path:
    """Download `remote` into `dest_dir`, resuming partial files. Returns the final path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / remote.filename
    if dest.exists():
        return dest

    partial = dest_dir / f"{remote.filename}.part"
    for attempt in range(1, max_attempts + 1):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with client.stream("GET", remote.url, headers=headers) as response:
                if response.status_code == httpx.codes.REQUESTED_RANGE_NOT_SATISFIABLE:
                    break  # the partial file is already complete
                response.raise_for_status()
                resumed = response.status_code == httpx.codes.PARTIAL_CONTENT
                with partial.open("ab" if resumed else "wb") as fh:
                    for chunk in response.iter_bytes(CHUNK_SIZE):
                        fh.write(chunk)
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                exc.response.status_code >= 500 or exc.response.status_code == 429
            )
            if not retryable or attempt == max_attempts:
                raise DownloadError(f"failed to download {remote.url}: {exc}") from exc
            wait = min(60.0, backoff_seconds * 2 ** (attempt - 1))
            logger.warning("Download of %s interrupted (%s); retrying in %.0fs", remote.filename, exc, wait)
            time.sleep(wait)

    try:
        verify_checksum(partial, remote)
    except DownloadError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(dest)
    logger.info("Downloaded %s", dest.name)
    return dest
