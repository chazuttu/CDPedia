# Copyright 2020 CDPedistas (see AUTHORS.txt)
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3, as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For further info, check  https://github.com/PyAr/CDPedia/

import urllib.parse

import pytest

import config
from src.scraping.css import re_resource_url, scrap_css, _CSSScraper


@pytest.mark.parametrize('url', (
    'https://foo.bar/baz',
    '//foo.bar/baz',
    '/foo.bar/baz',
    '"/foo.bar(baz)"',
    '"/foo"bar"(baz)"',
    '/foo(bar)baz'
    '/foo/bar/baz.png?1234',
))
def test_re_resource_url(url):
    """Match external resources URLs in CSS files."""
    css = '#p-lang {{background: transparent url({}) no-repeat center top;}}'.format(url)
    assert re_resource_url.search(css).group(1) == url


def test_scrap_css(mocker):
    """Call appropriate methods for downloading and joining."""
    css_scraper = mocker.Mock()
    mocker.patch('src.scraping.css._CSSScraper', css_scraper)
    scrap_css(cssdir='foo')
    assert css_scraper.mock_calls[-1] == mocker.call().download_all()
    # TODO: test joining


class TestCSSScraper:
    """Test for the CSS scraper."""

    @pytest.fixture
    def scraper(self, mocker, tmp_path):
        """CSS scraper instance with minimal params."""
        mocker.patch('config.URL_WIKIPEDIA', 'http://xy.wiki.org/')
        tmp_path.joinpath(config.CSS_LINKS_FILENAME).touch()
        return _CSSScraper(str(tmp_path))

    def test_download_all(self, mocker, scraper):
        """Donwload CSS and resources."""
        pool = mocker.Mock()
        mocker.patch('src.utiles.pooled_exec', pool)
        scraper.download_all()
        # check required calls where made
        calls = pool.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == scraper._download_css
        assert calls[1][0][0] == scraper._download_resource

    @pytest.mark.parametrize('module_exists', (True, False))
    def test_load_modules_info(self, mocker, tmp_path, scraper, module_exists):
        """Load css module info."""
        name = 'foo.bar'
        mocker.patch.object(scraper, '_module_names', lambda: {name})
        mocker.patch.object(scraper, '_collect_resources_info')
        filepath = tmp_path / name
        if module_exists:
            filepath.touch()
        scraper._load_modules_info()
        # check expected module info
        module = scraper.modules.get(name)
        assert module is not None
        assert name in module['url']
        assert module['filepath'] == str(filepath)
        assert module['exists'] == module_exists

    def test_module_names(self, tmp_path, scraper):
        """Extract module names from raw urls in file."""
        links = (
            'wiki.com/foo?a=b&modules=first.module&c=d\n'
            'wiki.com/foo?n=r&modules=first.module|second.module&x=y\n'
            'wiki.com/foo?f=g&modules=foo.bar,baz&h=i\n'
        )
        tmp_path.joinpath(config.CSS_LINKS_FILENAME).write_text(links)
        names = scraper._module_names()
        assert names == {'first.module', 'second.module', 'foo.bar', 'foo.baz'}

    def test_build_css_url(self, scraper):
        """Build URL for downloading a css module."""
        module_name = 'foo.bar_baz'
        url = urllib.parse.urlparse(scraper._css_url(module_name))
        assert url.netloc == 'xy.wiki.org'
        assert url.path == '/w/load.php'
        query_params = {'modules': module_name, **scraper.params}
        for k, v in query_params.items():
            assert '{}={}'.format(k, v) in url.query

    def test_collect_resources_info(self, scraper):
        """Extract multiple resources links from css."""
        css = 'foo url(link1) bar url(link2) baz'
        scraper._collect_resources_info(css)
        assert scraper.resources.keys() == {'link1', 'link2'}

    @pytest.mark.parametrize('urls', (
        ('"foo/bar.baz"', 'foo/bar.baz'),
        ('//foo/bar.baz', 'http://foo/bar.baz'),
        ('"//foo/bar.baz"', 'http://foo/bar.baz'),
        ('"/foo/bar.baz"', 'http://xy.wiki.org/foo/bar.baz'),
        ('/foo/bar.baz', 'http://xy.wiki.org/foo/bar.baz'),
        ('foo/bar.baz', 'foo/bar.baz'),
        ('http://foo/bar.baz', 'http://foo/bar.baz'),
    ))
    def test_collect_resources_info_url(self, mocker, scraper, urls):
        """Extract different kind of raw links and construct correct resource full URL."""
        url_raw, url_expected = urls
        mocker.patch.object(scraper, '_safe_resource_name', lambda _: 'foo')
        css = 'background: lightblue url({}) no-repeat fixed center;'.format(url_raw)
        scraper._collect_resources_info(css)
        assert scraper.resources[url_raw]['url'] == url_expected

    @pytest.mark.parametrize('url_name', (
        ('https://foo/bar/fooボ.ico', 'foo.ico'),
        ('http://foo/bar/foo.png?1234', 'foo.png'),
        ('http://foo/bar/%23foóo%2A.jpg', '#foo*.jpg'),
    ))
    def test_safe_resource_name(self, scraper, url_name):
        url, name_expected = url_name
        assert scraper._safe_resource_name(url) == name_expected

    @pytest.mark.parametrize('decode_resp', (True, False))
    def test_download(self, mocker, scraper, decode_resp):
        """Get correct kind of response from generic '_download' function."""
        asset = b'foo'
        resp_expected = 'foo' if decode_resp else b'foo'
        # mock url fetching
        headers = mocker.Mock(get_content_charset=lambda: 'utf-8')
        resp = mocker.Mock(read=lambda: asset, headers=headers)
        mocker.patch('urllib.request.urlopen', lambda req: resp)

        resp = scraper._download('http://spam', decode=decode_resp)
        assert resp == resp_expected

    def test_download_css(self, mocker, tmp_path, scraper):
        """Donwload and save a css module."""
        filepath = tmp_path / 'foo.bar'
        mocker.patch.object(scraper, '_download', return_value='text')
        item = {'url': 'url', 'filepath': str(filepath)}
        assert not filepath.exists()
        scraper._download_css(item)
        assert item['exists']
        assert filepath.read_text() == 'text'

    def test_download_resource(self, mocker, tmp_path, scraper):
        """Download and save a css resource."""
        filepath = tmp_path / 'foo.png'
        mocker.patch.object(scraper, '_download', return_value=b'content')
        item = {'url': 'url', 'filepath': str(filepath)}
        assert not filepath.exists()
        scraper._download_resource(item)
        assert item['exists']
        assert filepath.read_bytes() == b'content'
