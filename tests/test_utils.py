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
