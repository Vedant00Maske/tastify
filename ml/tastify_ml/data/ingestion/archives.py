"""Streaming access to members of (zstd-compressed) tar archives without extracting them to disk."""

import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import zstandard


@contextmanager
def open_tar_stream(path: Path) -> Iterator[tarfile.TarFile]:
    """Open a .tar or .tar.zst archive for sequential (streaming) reading."""
    with path.open("rb") as raw:
        if path.name.endswith(".zst"):
            with zstandard.ZstdDecompressor().stream_reader(raw) as decompressed:
                with tarfile.open(fileobj=decompressed, mode="r|") as tar:
                    yield tar
        else:
            with tarfile.open(fileobj=raw, mode="r|") as tar:
                yield tar


def iter_members(path: Path) -> Iterator[tuple[str, IO[bytes]]]:
    """Yield (member name, file object) for each regular file, in archive order.

    Members must be consumed before advancing: the archive is read sequentially.
    """
    with open_tar_stream(path) as tar:
        for member in tar:
            if member.isfile():
                handle = tar.extractfile(member)
                if handle is not None:
                    yield member.name, handle
