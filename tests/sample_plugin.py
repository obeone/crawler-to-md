"""
In-repo example of a third-party-style plugin.

This module is *not* part of the distributed package; it exists so the test
suite can register a custom :class:`~crawler_to_md.plugins.Formatter` through a
fake entry point and exercise it end-to-end, proving that external plugins work
without modifying the core code.
"""


class SampleFormatter:
    """
    Minimal third-party-style formatter that writes a URL listing.

    It reads the crawled pages straight from the export manager's database and
    writes one ``"<url>"`` line per stored page, prefixed by a banner, to prove
    a registry-discovered formatter has full access to the corpus.
    """

    name = "sample"

    def export(self, manager, output_path, **options):
        """
        Write a banner plus one line per page URL to ``output_path``.

        Parameters
        ----------
        manager : crawler_to_md.export_manager.ExportManager
            The export manager owning the database connection.
        output_path : str
            Destination text file.
        **options
            Ignored; accepted for protocol compatibility.

        Returns
        -------
        int
            The number of page URLs written.
        """
        pages = manager.db_manager.get_all_pages()
        lines = ["# sample-plugin export"]
        lines.extend(url for url, _content, _metadata in pages)
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return len(pages)
