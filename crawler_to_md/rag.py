"""
Token accounting and RAG-oriented text chunking helpers.

This module isolates the optional ``tiktoken`` dependency so that the core
package stays importable without it. Token-aware chunking (used by the RAG
chunk export) requires the ``rag`` extra and fails with a clear, actionable
message when it is missing. Token *estimation* degrades gracefully to a
cheap word-based heuristic when ``tiktoken`` is unavailable, which keeps the
run summary useful for bare installations.
"""

import logging

logger = logging.getLogger(__name__)

# Default tiktoken encoding. ``cl100k_base`` is shared by the GPT-3.5/4 family
# and is a sensible, model-agnostic default for token accounting.
DEFAULT_ENCODING = "cl100k_base"

# Heuristic ratio of tokens per whitespace-delimited word, used only when
# ``tiktoken`` is not installed. Deliberately conservative and clearly labelled
# wherever it surfaces so callers never mistake it for an exact count.
_WORD_TO_TOKEN_RATIO = 1.3

# Actionable error shown when a tiktoken-only feature is used without the extra.
RAG_MISSING_MESSAGE = (
    "Token-aware chunking requires the optional 'rag' extra. "
    "Install it with: pip install crawler-to-md[rag]"
)


def _load_tiktoken():
    """
    Import :mod:`tiktoken`, raising a clear error if the extra is missing.

    Returns
    -------
    module
        The imported :mod:`tiktoken` module.

    Raises
    ------
    ImportError
        If :mod:`tiktoken` is not installed, with a message telling the user
        to install the ``rag`` extra.
    """
    try:
        import tiktoken
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise ImportError(RAG_MISSING_MESSAGE) from exc
    return tiktoken


def get_encoder(encoding_name=DEFAULT_ENCODING):
    """
    Return a tiktoken encoder for ``encoding_name``.

    Parameters
    ----------
    encoding_name : str, optional
        Name of the tiktoken encoding to load. Defaults to
        :data:`DEFAULT_ENCODING`.

    Returns
    -------
    tiktoken.Encoding
        The requested encoder.

    Raises
    ------
    ImportError
        If the ``rag`` extra (tiktoken) is not installed.
    """
    tiktoken = _load_tiktoken()
    return tiktoken.get_encoding(encoding_name)


def count_tokens(text, encoder=None):
    """
    Count tokens in ``text`` exactly using tiktoken.

    Parameters
    ----------
    text : str or None
        The text to tokenize. ``None`` is treated as an empty string.
    encoder : tiktoken.Encoding, optional
        A pre-built encoder to reuse. When omitted, the default encoder is
        created on demand.

    Returns
    -------
    int
        The number of tokens in ``text``.

    Raises
    ------
    ImportError
        If the ``rag`` extra (tiktoken) is not installed.
    """
    encoder = encoder or get_encoder()
    return len(encoder.encode(text or ""))


def estimate_tokens(text):
    """
    Estimate the token count of ``text``, degrading gracefully.

    Uses tiktoken for an exact count when available; otherwise falls back to a
    cheap word-based heuristic so the run summary remains useful on bare
    installations.

    Parameters
    ----------
    text : str or None
        The text to measure. ``None`` is treated as an empty string.

    Returns
    -------
    tuple[int, str]
        A ``(count, method)`` pair where ``method`` is ``"tiktoken"`` for an
        exact count or ``"word-estimate"`` for the heuristic fallback.
    """
    text = text or ""
    try:
        encoder = get_encoder()
    except ImportError:
        words = len(text.split())
        return int(round(words * _WORD_TO_TOKEN_RATIO)), "word-estimate"
    return len(encoder.encode(text)), "tiktoken"


def chunk_text(text, chunk_size, chunk_overlap=0, encoder=None):
    """
    Split ``text`` into token-aware, optionally overlapping chunks.

    Parameters
    ----------
    text : str or None
        The text to split. ``None`` is treated as an empty string.
    chunk_size : int
        Maximum number of tokens per chunk. Values ``<= 0`` disable chunking
        and yield an empty list.
    chunk_overlap : int, optional
        Number of tokens shared between consecutive chunks. Clamped to the
        range ``[0, chunk_size - 1]`` so the window always advances.
    encoder : tiktoken.Encoding, optional
        A pre-built encoder to reuse. When omitted, the default encoder is
        created on demand.

    Returns
    -------
    list[tuple[str, int]]
        A list of ``(chunk_text, token_count)`` pairs in document order.

    Raises
    ------
    ImportError
        If the ``rag`` extra (tiktoken) is not installed.
    """
    if chunk_size <= 0:
        return []

    encoder = encoder or get_encoder()
    tokens = encoder.encode(text or "")
    if not tokens:
        return []

    overlap = max(0, min(chunk_overlap, chunk_size - 1))
    step = chunk_size - overlap

    chunks = []
    start = 0
    total = len(tokens)
    while start < total:
        window = tokens[start : start + chunk_size]
        chunks.append((encoder.decode(window), len(window)))
        start += step
    return chunks
