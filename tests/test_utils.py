import pytest

from crawler_to_md import utils


def test_randomstring_to_filename():
    assert utils.randomstring_to_filename('Hello World!') == 'Hello_World'


def test_url_to_filename():
    result = utils.url_to_filename('https://example.com/path/index.html')
    assert result == 'example_com_path_index_html'


def test_url_dirname():
    assert utils.url_dirname('https://example.com/path/page') == 'https://example.com/path/'
    assert utils.url_dirname('https://example.com/path/page/') == 'https://example.com/path/page/'


def test_deduplicate_list():
    assert utils.deduplicate_list([1, 2, 2, 3, 1]) == [1, 2, 3]


def test_randomstring_special_chars():
    assert utils.randomstring_to_filename('a!@ b$c#') == 'a_bc'


def test_url_to_filename_invalid():
    with pytest.raises(ValueError):
        utils.url_to_filename(123)


def test_canonicalize_url_collapses_variants():
    """Equivalent URLs (port/utm/query-order/fragment) collapse to one key."""
    a = utils.canonicalize_url('http://Example.com:80/Path?utm_source=x&b=2&a=1#frag')
    b = utils.canonicalize_url('http://example.com/Path?a=1&b=2')
    assert a == b == 'http://example.com/Path?a=1&b=2'


def test_canonicalize_url_root_trailing_slash():
    """An empty root path and an explicit '/' root collapse to the same URL."""
    assert utils.canonicalize_url('http://example.com') == utils.canonicalize_url(
        'http://example.com/'
    )
    assert utils.canonicalize_url('http://example.com') == 'http://example.com/'


def test_canonicalize_url_strips_default_https_port():
    """The redundant default HTTPS port (443) is removed."""
    assert utils.canonicalize_url('https://Example.com:443/') == 'https://example.com/'


def test_canonicalize_url_drops_tracking_params_preserves_case():
    """Tracking params are dropped while meaningful path case is preserved."""
    result = utils.canonicalize_url('https://example.com/Docs?fbclid=zzz&gclid=q')
    assert result == 'https://example.com/Docs'


def test_canonicalize_url_non_default_port_preserved():
    """A non-default port is kept (only 80/443 defaults are stripped)."""
    assert utils.canonicalize_url('http://example.com:8080/x') == (
        'http://example.com:8080/x'
    )
