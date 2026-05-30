import json
import os
import tempfile

from crawler_to_md.database_manager import DatabaseManager
from crawler_to_md.export_manager import ExportManager


def create_populated_db(tmpdir):
    db_path = os.path.join(tmpdir, 'db.sqlite')
    db = DatabaseManager(db_path)
    db.insert_link('http://example.com')
    db.mark_link_visited('http://example.com')
    db.insert_page(
        'http://example.com', '# Title\nParagraph', json.dumps({'author': 'John'})
    )
    return db


def test_export_markdown_and_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = create_populated_db(tmpdir)
        exporter = ExportManager(db, title='My Title')
        md_path = os.path.join(tmpdir, 'out.md')
        json_path = os.path.join(tmpdir, 'out.json')

        exporter.export_to_markdown(md_path)
        exporter.export_to_json(json_path)

        assert os.path.exists(md_path)
        assert os.path.exists(json_path)

        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert content.startswith('# My Title')
            assert '## Title' in content
            assert 'URL: http://example.com' in content

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert data[0]['url'] == 'http://example.com'
            assert 'Title' in data[0]['content']
            assert data[0]['metadata']['author'] == 'John'


def test_adjust_headers_and_cleanup():
    db = DatabaseManager(':memory:')
    exporter = ExportManager(db, title='T')
    content = '# H1\n## H2'
    adjusted = exporter._adjust_headers(content, level_increment=1)
    assert '## H1' in adjusted
    assert '### H2' in adjusted
    cleaned = exporter._cleanup_markdown('A\n\n\nB')
    assert cleaned == 'A\n\nB'


def test_concatenate_markdown_filters_metadata():
    db = DatabaseManager(':memory:')
    db.insert_page('http://a', '# T1', json.dumps({'keep': 'x'}))
    db.insert_page('http://b', '# T2', json.dumps({'drop': None}))
    exporter = ExportManager(db, title='Head')
    result = exporter._concatenate_markdown(db.get_all_pages())
    assert result.startswith('# Head')
    assert 'URL: http://a' in result and 'T1' in result
    assert 'keep: x' in result
    assert 'drop:' not in result


def test_export_individual_markdown(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    db = DatabaseManager(str(db_path))
    db.insert_page('http://example.com/path/page', '# P', '{}')
    exporter = ExportManager(db)
    output_folder = exporter.export_individual_markdown(str(tmp_path))
    expected = tmp_path / 'files' / 'example.com' / 'path' / 'page.md'
    assert expected.exists()
    assert output_folder == str(tmp_path / 'files')


def test_adjust_headers_upper_limit():
    db = DatabaseManager(':memory:')
    exporter = ExportManager(db)
    content = '###### H6\n####### H7'
    adjusted = exporter._adjust_headers(content, level_increment=1)
    lines = [line for line in adjusted.split('\n') if line.startswith('#')]
    # both lines should not exceed 6 hashes
    assert all(len(line.split()[0]) <= 6 for line in lines)


def test_concatenate_skips_none_content():
    db = DatabaseManager(':memory:')
    db.insert_page('http://a', None, '{}')
    db.insert_page('http://b', '# T', '{}')
    exporter = ExportManager(db, title='Top')
    content = exporter._concatenate_markdown(db.get_all_pages())
    assert 'URL: http://a' not in content
    assert 'URL: http://b' in content


def test_concatenate_markdown_multipage_single_cleanup():
    """
    Multi-page concatenation must run ``_cleanup_markdown`` exactly once.

    The cleanup pass previously ran inside the per-page loop (O(n^2)); it now
    runs a single time after the loop. This test asserts both that the cleanup
    is invoked exactly once regardless of page count and that the resulting
    document is correct (no runs of 3+ newlines, all pages present and ordered).
    """
    db = DatabaseManager(':memory:')
    # Content with deliberate excessive blank lines to exercise cleanup.
    db.insert_page('http://a', '# A\n\n\n\nAlpha', json.dumps({'k': 'va'}))
    db.insert_page('http://b', '# B\n\n\n\nBravo', json.dumps({'k': 'vb'}))
    db.insert_page('http://c', '# C\n\n\n\nCharlie', json.dumps({'k': 'vc'}))
    exporter = ExportManager(db, title='Head')

    call_count = {'n': 0}
    original_cleanup = exporter._cleanup_markdown

    def counting_cleanup(content):
        """Wrap the real cleanup to count how many times it runs."""
        call_count['n'] += 1
        return original_cleanup(content)

    exporter._cleanup_markdown = counting_cleanup
    result = exporter._concatenate_markdown(db.get_all_pages())

    # Single cleanup pass, not one per page.
    assert call_count['n'] == 1

    # Output correctness: title, every page, no excessive newline runs.
    assert result.startswith('# Head')
    for url, marker in (
        ('http://a', 'Alpha'),
        ('http://b', 'Bravo'),
        ('http://c', 'Charlie'),
    ):
        assert f'URL: {url}' in result
        assert marker in result
    assert '\n\n\n' not in result
    # Pages preserved in insertion order.
    assert result.index('Alpha') < result.index('Bravo') < result.index('Charlie')


def test_export_to_json_skips_none(tmp_path):
    db = DatabaseManager(':memory:')
    db.insert_page('http://a', None, '{}')
    db.insert_page('http://b', '# T', '{}')
    exporter = ExportManager(db)
    json_path = tmp_path / 'out.json'
    exporter.export_to_json(str(json_path))
    data = json.load(open(json_path, 'r', encoding='utf-8'))
    assert len(data) == 1 and data[0]['url'] == 'http://b'
