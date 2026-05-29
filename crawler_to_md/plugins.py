"""
Entry-point-based plugin architecture for crawler-to-md.

This module defines the four pipeline-stage protocols — :class:`Fetcher`,
:class:`Filter`, :class:`Processor` and :class:`Formatter` — together with a
defensive :class:`PluginRegistry` that discovers implementations through Python
`entry points <https://packaging.python.org/en/latest/specifications/entry-points/>`_.

Design goals
------------
* **Zero behaviour change.** First-party implementations *wrap* the proven
  :class:`~crawler_to_md.export_manager.ExportManager` and
  :class:`~crawler_to_md.scraper.Scraper` logic rather than reimplementing it,
  so re-expressing a feature through the registry produces byte-identical
  output.
* **Always available.** Each group ships built-in first-party implementations
  that the registry exposes even before the distribution metadata is refreshed.
  Installed entry points (declared in ``pyproject.toml`` and contributed by
  third parties) are merged on top, so discovery never depends on install
  timing.
* **Defensive discovery.** Entry-point resolution tolerates zero installed
  plugins, never raises at import time, skips individual broken plugins with a
  warning, and caches its results.

Entry-point groups
-------------------
* ``crawler_to_md.formatters`` → :class:`Formatter`
* ``crawler_to_md.filters`` → :class:`Filter`
* ``crawler_to_md.processors`` → :class:`Processor`
* ``crawler_to_md.fetchers`` → :class:`Fetcher`
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Mapping of short group key (used throughout the API) to the fully-qualified
# entry-point group name declared in ``pyproject.toml``.
GROUPS = MappingProxyType(
    {
        "formatters": "crawler_to_md.formatters",
        "filters": "crawler_to_md.filters",
        "processors": "crawler_to_md.processors",
        "fetchers": "crawler_to_md.fetchers",
    }
)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class Formatter(Protocol):
    """
    Render the crawled corpus into an on-disk export.

    A formatter is the unit of the ``crawler_to_md.formatters`` group. It is
    handed the live :class:`~crawler_to_md.export_manager.ExportManager` (which
    owns the database connection and run title) and an output path, and is free
    to write one or more files.

    Attributes
    ----------
    name : str
        Stable, unique identifier used to look the formatter up in the registry
        and to declare its entry point.
    """

    name: str

    def export(self, manager: Any, output_path: str, **options: Any) -> Any:
        """
        Write the corpus to ``output_path``.

        Parameters
        ----------
        manager : crawler_to_md.export_manager.ExportManager
            The export manager providing the database accessor and run title.
        output_path : str
            Destination path or folder, depending on the formatter.
        **options : Any
            Formatter-specific keyword options (e.g. ``base_url``,
            ``frontmatter``, ``chunk_size``).

        Returns
        -------
        Any
            Whatever the underlying export produces (often ``None`` or a path).
        """
        ...


@runtime_checkable
class Filter(Protocol):
    """
    Decide whether a discovered URL belongs in the crawl frontier.

    A filter is the unit of the ``crawler_to_md.filters`` group.

    Attributes
    ----------
    name : str
        Stable, unique identifier used for registry lookup and entry points.
    """

    name: str

    def is_allowed(self, url: str) -> bool:
        """
        Return whether ``url`` should be crawled.

        Parameters
        ----------
        url : str
            The candidate URL.

        Returns
        -------
        bool
            ``True`` if the URL passes the filter, ``False`` to drop it.
        """
        ...


@runtime_checkable
class Processor(Protocol):
    """
    Transform a page's HTML before Markdown conversion.

    A processor is the unit of the ``crawler_to_md.processors`` group.

    Attributes
    ----------
    name : str
        Stable, unique identifier used for registry lookup and entry points.
    """

    name: str

    def process(self, html: str, url: str) -> str:
        """
        Return the transformed HTML for ``url``.

        Parameters
        ----------
        html : str
            The raw HTML of the page.
        url : str
            The source URL (available for context-aware processing).

        Returns
        -------
        str
            The (possibly) transformed HTML.
        """
        ...


@runtime_checkable
class Fetcher(Protocol):
    """
    Retrieve a URL and return a response-like object.

    A fetcher is the unit of the ``crawler_to_md.fetchers`` group. The returned
    object is expected to expose the small ``requests``/``httpx`` response
    surface consumed by the crawl loop (``status_code``, ``headers``, ``text``,
    ``content``).

    Attributes
    ----------
    name : str
        Stable, unique identifier used for registry lookup and entry points.
    """

    name: str

    def fetch(self, url: str) -> Any:
        """
        Fetch ``url`` and return a response-like object.

        Parameters
        ----------
        url : str
            The URL to fetch.

        Returns
        -------
        Any
            A response-like object, or ``None`` on failure.
        """
        ...


# ---------------------------------------------------------------------------
# First-party formatters (thin wrappers over ExportManager methods)
# ---------------------------------------------------------------------------


class MarkdownFormatter:
    """Formatter delegating to :meth:`ExportManager.export_to_markdown`."""

    name = "markdown"

    def export(self, manager: Any, output_path: str, **options: Any) -> Any:
        """Write the concatenated Markdown file to ``output_path``."""
        return manager.export_to_markdown(output_path)


class JsonFormatter:
    """Formatter delegating to :meth:`ExportManager.export_to_json`."""

    name = "json"

    def export(self, manager: Any, output_path: str, **options: Any) -> Any:
        """Write the JSON corpus file to ``output_path``."""
        return manager.export_to_json(output_path)


class JsonlFormatter:
    """Formatter delegating to :meth:`ExportManager.export_to_jsonl`."""

    name = "jsonl"

    def export(self, manager: Any, output_path: str, **options: Any) -> Any:
        """Write the JSON Lines corpus file to ``output_path``."""
        return manager.export_to_jsonl(output_path)


class LlmsFormatter:
    """Formatter delegating to :meth:`ExportManager.export_to_llms`."""

    name = "llms"

    def export(self, manager: Any, output_path: str, **options: Any) -> Any:
        """Write ``llms.txt`` / ``llms-full.txt`` into the ``output_path`` folder."""
        return manager.export_to_llms(output_path)


class IndividualMarkdownFormatter:
    """Formatter delegating to :meth:`ExportManager.export_individual_markdown`."""

    name = "individual"

    def export(self, manager: Any, output_path: str, **options: Any) -> Any:
        """
        Write each page as an individual Markdown file under ``output_path``.

        Recognised options: ``base_url`` (str or ``None``) and ``frontmatter``
        (bool, default ``True``).
        """
        return manager.export_individual_markdown(
            output_path,
            base_url=options.get("base_url"),
            frontmatter=options.get("frontmatter", True),
        )


class ChunksFormatter:
    """Formatter delegating to :meth:`ExportManager.export_chunks_jsonl`."""

    name = "chunks"

    def export(self, manager: Any, output_path: str, **options: Any) -> Any:
        """
        Write token-aware RAG chunks as JSON Lines to ``output_path``.

        Recognised options: ``chunk_size`` (int, required ``> 0``) and
        ``chunk_overlap`` (int, default ``0``).
        """
        return manager.export_chunks_jsonl(
            output_path,
            options.get("chunk_size", 0),
            options.get("chunk_overlap", 0),
        )


class VectorsFormatter:
    """Formatter delegating to :meth:`ExportManager.export_to_vectors`."""

    name = "vectors"

    def export(self, manager: Any, output_path: str, **options: Any) -> Any:
        """
        Write a Parquet vector export to ``output_path``.

        Recognised options: ``chunk_size`` (int, default ``0``) and
        ``chunk_overlap`` (int, default ``0``).
        """
        return manager.export_to_vectors(
            output_path,
            options.get("chunk_size", 0),
            options.get("chunk_overlap", 0),
        )


# ---------------------------------------------------------------------------
# First-party filter / processor / fetcher
# ---------------------------------------------------------------------------


class UrlPatternFilter:
    """
    Include/exclude URL filter mirroring :meth:`Scraper.is_valid_link`.

    The canonical form of each URL is compared so that equivalent URLs
    (differing only by default port, tracking parameters, query order, ...)
    are filtered identically to the crawl loop.

    Parameters
    ----------
    base_url : str or None, optional
        If set, a URL must canonically start with the canonical base URL.
    include_patterns : list[str] or None, optional
        If non-empty, a URL must contain at least one of these substrings.
    exclude_patterns : list[str] or None, optional
        A URL containing any of these substrings is rejected.
    """

    name = "url-pattern"

    def __init__(self, base_url=None, include_patterns=None, exclude_patterns=None):
        self.base_url = base_url
        self.include_patterns = list(include_patterns or [])
        self.exclude_patterns = list(exclude_patterns or [])

    @classmethod
    def from_scraper(cls, scraper: Any) -> "UrlPatternFilter":
        """
        Build a filter from a configured :class:`Scraper`.

        Parameters
        ----------
        scraper : crawler_to_md.scraper.Scraper
            The scraper whose ``base_url`` and include/exclude patterns are
            mirrored.

        Returns
        -------
        UrlPatternFilter
            A filter producing the same verdicts as ``scraper.is_valid_link``.
        """
        return cls(
            base_url=scraper.base_url,
            include_patterns=scraper.include_url_patterns,
            exclude_patterns=scraper.exclude_patterns,
        )

    def is_allowed(self, url: str) -> bool:
        """Return whether ``url`` passes the include/exclude rules."""
        from . import utils

        canonical = utils.canonicalize_url(url)
        if self.base_url and not canonical.startswith(
            utils.canonicalize_url(self.base_url)
        ):
            return False
        if self.include_patterns and not any(
            pattern in canonical for pattern in self.include_patterns
        ):
            return False
        for pattern in self.exclude_patterns:
            if pattern in canonical:
                return False
        return True


class NoOpProcessor:
    """
    Pass-through processor that returns the HTML unchanged.

    Serves as the safe default first-party processor: it imposes no
    transformation, so wiring it into the pipeline cannot alter behaviour.
    """

    name = "noop"

    def process(self, html: str, url: str) -> str:
        """Return ``html`` unmodified."""
        return html


class RequestsFetcher:
    """
    Fetcher wrapping a ``requests`` session (or an existing scraper).

    Parameters
    ----------
    session : requests.Session or None, optional
        The session used to issue GET requests. A fresh session is created when
        omitted.
    timeout : float, optional
        Per-request timeout in seconds. Defaults to ``15``.
    """

    name = "requests"

    def __init__(self, session=None, timeout=15):
        self._session = session
        self.timeout = timeout

    @property
    def session(self):
        """Return the underlying session, creating one lazily if needed."""
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    @classmethod
    def from_scraper(cls, scraper: Any) -> "RequestsFetcher":
        """
        Build a fetcher that delegates to a scraper's retrying GET.

        Parameters
        ----------
        scraper : crawler_to_md.scraper.Scraper
            The scraper whose ``_get_with_retry`` (retry/backoff, timeout,
            headers/auth) is reused verbatim.

        Returns
        -------
        RequestsFetcher
            A fetcher whose :meth:`fetch` calls ``scraper._get_with_retry``.
        """
        fetcher = cls(session=scraper.session, timeout=scraper.timeout)
        fetcher._scraper = scraper
        return fetcher

    def fetch(self, url: str) -> Any:
        """
        Fetch ``url`` and return the response.

        When built via :meth:`from_scraper`, delegates to the scraper's
        retry-aware GET; otherwise issues a single GET with the session.
        """
        scraper = getattr(self, "_scraper", None)
        if scraper is not None:
            return scraper._get_with_retry(url)
        return self.session.get(url, timeout=self.timeout)


# Built-in first-party implementations, keyed by group then by ``name``. These
# are always available through the registry; installed entry points are merged
# on top so discovery never depends on the distribution metadata being fresh.
_BUILTINS: dict[str, dict[str, Any]] = {
    "formatters": {
        cls.name: cls
        for cls in (
            MarkdownFormatter,
            JsonFormatter,
            JsonlFormatter,
            LlmsFormatter,
            IndividualMarkdownFormatter,
            ChunksFormatter,
            VectorsFormatter,
        )
    },
    "filters": {UrlPatternFilter.name: UrlPatternFilter},
    "processors": {NoOpProcessor.name: NoOpProcessor},
    "fetchers": {RequestsFetcher.name: RequestsFetcher},
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class PluginRegistry:
    """
    Discover and cache pipeline plugins from built-ins and entry points.

    For each group the registry exposes the built-in first-party
    implementations merged with any entry-point-contributed plugins. Discovery
    is defensive: a missing distribution, an absent group, or an individual
    plugin that fails to import never raises — it is logged and skipped.
    Results are cached per group until :meth:`clear_cache` is called.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    def clear_cache(self) -> None:
        """Drop all cached discovery results (forces a fresh re-scan)."""
        self._cache.clear()

    @staticmethod
    def _load_entry_points(group_path: str) -> dict[str, Any]:
        """
        Load every entry point in ``group_path`` defensively.

        Parameters
        ----------
        group_path : str
            Fully-qualified entry-point group name.

        Returns
        -------
        dict[str, Any]
            Mapping of entry-point name to the loaded object. Broken plugins
            are skipped with a warning; a missing group yields an empty dict.
        """
        result: dict[str, Any] = {}
        try:
            discovered = entry_points(group=group_path)
        except Exception as exc:  # pragma: no cover - importlib edge cases
            logger.warning("Entry-point discovery failed for %s: %s", group_path, exc)
            return result
        for ep in discovered:
            try:
                result[ep.name] = ep.load()
            except Exception as exc:
                logger.warning(
                    "Skipping plugin %r in group %s: %s", ep.name, group_path, exc
                )
        return result

    def discover(self, group: str, *, refresh: bool = False) -> dict[str, Any]:
        """
        Return all plugins for ``group`` (built-ins merged with entry points).

        Parameters
        ----------
        group : str
            Short group key (one of :data:`GROUPS`, e.g. ``"formatters"``).
        refresh : bool, optional
            When ``True``, bypass and rebuild the cache for this group.

        Returns
        -------
        dict[str, Any]
            Mapping of plugin name to the loaded object/class. Entry points
            override built-ins of the same name.

        Raises
        ------
        KeyError
            If ``group`` is not a recognised group key.
        """
        if group not in GROUPS:
            raise KeyError(f"Unknown plugin group: {group!r}")
        if refresh or group not in self._cache:
            merged = dict(_BUILTINS.get(group, {}))
            merged.update(self._load_entry_points(GROUPS[group]))
            self._cache[group] = merged
        return dict(self._cache[group])

    def names(self, group: str) -> list[str]:
        """
        Return the sorted plugin names available for ``group``.

        Parameters
        ----------
        group : str
            Short group key.

        Returns
        -------
        list[str]
            Sorted plugin names.
        """
        return sorted(self.discover(group))

    def get(self, group: str, name: str) -> Any:
        """
        Return the plugin object/class registered under ``name`` in ``group``.

        Parameters
        ----------
        group : str
            Short group key.
        name : str
            Plugin name.

        Returns
        -------
        Any
            The loaded plugin object/class, or ``None`` if no such plugin
            exists.
        """
        return self.discover(group).get(name)

    def create(self, group: str, name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Return a ready-to-use plugin instance for ``name`` in ``group``.

        Classes are instantiated with ``*args``/``**kwargs``; objects that are
        already instances are returned as-is.

        Parameters
        ----------
        group : str
            Short group key.
        name : str
            Plugin name.
        *args, **kwargs : Any
            Constructor arguments forwarded when the plugin is a class.

        Returns
        -------
        Any
            A plugin instance.

        Raises
        ------
        KeyError
            If no plugin named ``name`` exists in ``group``.
        """
        obj = self.get(group, name)
        if obj is None:
            raise KeyError(f"No {group} plugin named {name!r}")
        return obj(*args, **kwargs) if isinstance(obj, type) else obj


# Process-wide default registry. Importing this module never triggers discovery
# (the registry scans lazily on first use), so import stays side-effect free.
registry = PluginRegistry()


def get_registry() -> PluginRegistry:
    """
    Return the process-wide default :class:`PluginRegistry`.

    Returns
    -------
    PluginRegistry
        The shared registry instance.
    """
    return registry
