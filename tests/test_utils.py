import pytest
from src import utils


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
