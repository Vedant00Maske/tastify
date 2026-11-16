"""Vectorized (pyarrow) twins of the backend's matching-key functions.

Mapping tens of millions of listens and canonical rows in pure Python would take hours, so these
compute the same keys as `app.domains.catalogue.normalization.matching_key`/`clean_title` and
`app.domains.catalogue.writer.track_matching_key` column-at-a-time. tests/test_keys.py checks that
both implementations agree.
"""

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

# Same patterns as app.domains.catalogue.normalization, in RE2 syntax with case-insensitivity.
_FEATURING = r"(?i)\s*[(\[]\s*(?:feat\.?|ft\.?|featuring)\s+[^)\]]*[)\]]"
_REMASTER = (
    r"(?i)\s*(?:-\s*|[(\[]\s*)(?:\d{4}\s+)?(?:digital(?:ly)?\s+)?remaster(?:ed)?"
    r"(?:\s+\d{4})?(?:\s+version)?\s*[)\]]?\s*$"
)
_NOT_LETTER_OR_NUMBER = r"[^\p{L}\p{N}]+"
_FINAL_SIGMA, _SIGMA = chr(0x03C2), chr(0x03C3)


def matching_key(values: Any) -> pa.ChunkedArray | pa.Array:
    decomposed = pc.utf8_normalize(values, form="NFKD")
    lowered = pc.replace_substring(pc.utf8_lower(decomposed), pattern=_FINAL_SIGMA, replacement=_SIGMA)
    alnum = pc.replace_substring_regex(lowered, pattern=_NOT_LETTER_OR_NUMBER, replacement="")
    key = pc.utf8_normalize(alnum, form="NFC")
    # Symbol-only names keep their lower-cased symbols (same rule as the Python version).
    symbols = pc.utf8_trim_whitespace(
        pc.replace_substring(
            pc.utf8_lower(pc.utf8_normalize(values, form="NFKC")),
            pattern=_FINAL_SIGMA,
            replacement=_SIGMA,
        )
    )
    return pc.if_else(pc.equal(key, ""), symbols, key)


def clean_title(values: Any) -> pa.ChunkedArray | pa.Array:
    without_featuring = pc.replace_substring_regex(values, pattern=_FEATURING, replacement="")
    cleaned = pc.utf8_trim_whitespace(
        pc.replace_substring_regex(without_featuring, pattern=_REMASTER, replacement="")
    )
    return pc.if_else(pc.equal(cleaned, ""), pc.utf8_trim_whitespace(values), cleaned)


def track_matching_key(artists: Any, titles: Any) -> pa.ChunkedArray | pa.Array:
    return pc.binary_join_element_wise(
        matching_key(artists), matching_key(clean_title(titles)), "|"
    )
