# Copyright 2010-2021 CDPedistas (see AUTHORS.txt)
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
# For further info, check  http://code.google.com/p/cdpedia/

"""Download the whole wikipedia."""

import io
import collections
import datetime
import functools
import gzip
import json
import logging
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config
from src import utiles
from src.armado import to3dirs

logger = logging.getLogger(__name__)

WIKI = 'http://{language}.wikipedia.org'

HISTORY_BASE = (
    'http://%(lang)s.wikipedia.org/w/api.php?action=query&prop=revisions'
    '&format=json&rvprop=ids|timestamp|user|userid'
    '&rvlimit=%(limit)d&titles=%(title)s'
)
REVISION_URL = (
    'http://%(lang)s.wikipedia.org/w/index.php?'
    'title=%(title)s&oldid=%(revno)s'
)

REQUEST_HEADERS = {
    'Accept-encoding': 'gzip',
    'User-Agent': "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:77.0) Gecko/20100101 Firefox/77.0",
}

DataURLs = collections.namedtuple("DataURLs", "url temp_dir disk_name basename")


class ScraperError(Exception):
    """Base class for all scraper errors."""
    def __init__(self, msg, *msg_args):
        super().__init__(msg)
        self.msg_args = msg_args


class PageHaveNoRevisionsError(ScraperError):
    """Error to indicate that a page has no history revisions."""


class FetchingError(ScraperError):
    """Error while fetching a web page."""


class BadHTMLError(ScraperError):
    """Error in the HTML format."""


def get_data_urls(listado_nombres, dest_dir, language, test_limit=None):
    """Get a list of DataURLs to download (verifying which are already downloaded)."""
    logger.info('Generando DataURLs')
    wiki_base = WIKI.format(language=language)

    temp_dir = dest_dir + ".tmp"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    data_urls_list = []
    previous_count = 0

    with open(listado_nombres, 'rt', encoding='utf-8') as fh:
        for line in fh:
            if test_limit is not None:
                test_limit -= 1
                if test_limit <= 0:
                    break
            line = line.strip()
            if line == "page_title":
                continue
            basename = line.strip()
            three_dirs, filename = to3dirs.get_path_file(basename)
            path = os.path.join(dest_dir, three_dirs)
            disk_name = os.path.join(path, filename)
            if os.path.exists(disk_name):
                previous_count += 1
                continue

            if not os.path.exists(path):
                os.makedirs(path)
            quoted_url = urllib.parse.quote(basename)
            # Skip wikipedia automatic redirect
            url = "{}/w/index.php?title={}&redirect=no".format(wiki_base, quoted_url)
            data = DataURLs(url=url, temp_dir=temp_dir, disk_name=disk_name, basename=basename)
            data_urls_list.append(data)

        return (previous_count, data_urls_list)


def fetch_html(url):
    """Fetch an url following redirects and retrying on some errors.

    It considers HTTP 404 the only one error to not retry. Note that it also retries on non-HTTP
    errors (for example, after getting information on a 200 response, but failing to uncompress
    it properly).
    """
    # seconds to sleep before each retrial (starting from the end)
    retries = [5, 1, .3]
    while True:
        try:
            req = urllib.request.Request(url, headers=REQUEST_HEADERS)
            resp = urllib.request.urlopen(req, timeout=60)
            compressedstream = io.BytesIO(resp.read())
            gzipper = gzip.GzipFile(fileobj=compressedstream)
            html = gzipper.read().decode('utf-8')
            return html

        except Exception as err:
            if isinstance(err, urllib.error.HTTPError) and err.code == 404:
                raise FetchingError("Failed with HTTPError 404 on url %r", url)
            if not retries:
                raise FetchingError("Giving up retries after %r on url %r", err, url)
            time.sleep(retries.pop())


class WikipediaArticleHistoryItem(object):
    def __init__(self, user_registered, page_rev_id, date):
        self.user_registered = user_registered
        self.page_rev_id = page_rev_id
        self.date = date

    @classmethod
    def FromJSON(cls, jsonitem):
        user_registered = jsonitem.get('userid', 0) != 0
        page_rev_id = str(jsonitem['revid'])
        tstamp = jsonitem['timestamp']
        date = datetime.datetime.strptime(tstamp, "%Y-%m-%dT%H:%M:%SZ")
        return cls(user_registered, page_rev_id, date)

    def __str__(self):
        return '<rev: regist %s id %r %r>' % (self.user_registered,
                                              self.page_rev_id, self.date)


class WikipediaArticle(object):
    """Represent a wikipedia page.

    It should know how to retrive the asociated history page and any revision.
    """
    HISTORY_CLASS = WikipediaArticleHistoryItem

    def __init__(self, language, url, basename):
        self.language = language
        self.url = url
        self.basename = basename
        self.quoted_basename = urllib.parse.quote(basename).replace(' ', '_')
        self._history = None
        self.history_size = 6

    def __str__(self):
        return '<wp: %s>' % self.basename

    @property
    def history_url(self):
        url = HISTORY_BASE % dict(lang=self.language, limit=self.history_size,
                                  title=self.quoted_basename)
        return url

    def get_revision_url(self, revision=None):
        """
        Return the revision url when revision is provided, elsewhere the basic
        url for the page
        """
        if revision is None:
            return self.url
        url = REVISION_URL % dict(lang=self.language, title=self.quoted_basename, revno=revision)
        return url

    def get_history(self, size=6):
        if self._history is None or size != self.history_size:
            self.history_size = size
            self._history = fetch_html(self.history_url)
        return self._history

    def iter_history_json(self, json_rev_history):
        pages = json_rev_history['query'].get('pages')
        if pages is None:
            raise PageHaveNoRevisionsError("Page without history")

        assert len(pages) == 1
        (pageid,) = pages.keys()
        if pageid == '-1':
            # page deleted / moved / whatever but not now..
            raise PageHaveNoRevisionsError("Bad value for pageid")

        revisions = pages[pageid].get("revisions")
        if not revisions:
            # None, or there but empty
            # page deleted / moved / whatever but not now..
            raise PageHaveNoRevisionsError("No revisions found")

        for idx, item in enumerate(revisions):
            yield idx, self.HISTORY_CLASS.FromJSON(item)

    def search_valid_version(self, acceptance_days=7, _show_debug_info=False):
        """Search for a "good-enough" version of the page wanted.

        Where good-enough means:

         * Page version is commited by a registered user (being it
           human or bot).

         * Page version is commited by an unregistered user and stayed
           alive longer than 'acceptance_days'.

        Return None if no version page was found.

        For more info, check issue #124 at:
            http://code.google.com/p/cdpedia/issues/detail?id=124
        """
        self.acceptance_delta = datetime.timedelta(acceptance_days)
        idx, hist = self.iterate_history()
        if idx != 0:
            logger.debug("Possible vandalism (idx=%d) in %r", idx, self.basename)
        return self.get_revision_url(hist.page_rev_id)

    def iterate_history(self):
        prev_date = datetime.datetime.now()

        for history_size in [6, 100]:
            history = self.get_history(size=history_size)
            json_rev_history = json.loads(history)

            for idx, hist in self.iter_history_json(json_rev_history):
                if self.validate_revision(hist, prev_date):
                    return (idx, hist)
                prev_date = hist.date

        return (idx, hist)

    def validate_revision(self, hist_item, prev_date):
        # if the user is registered, it's enough for us! (even if it's a bot)
        if hist_item.user_registered:
            return True
        # if it's not registered, check for how long this version lasted
        if hist_item.date + self.acceptance_delta < prev_date:
            return True
        return False


class CSSLinkExtractor:
    """Extract raw CSS links from HTML source code."""

    def __init__(self):
        # pattern for extracting css links from html
        regex = r"/w/load.php\?.*?only=styles&amp;skin=vector"
        self._findlinks = re.compile(regex).findall

        # lock for writing to same file from different threads
        self._lock = threading.Lock()

    def setup(self, language_dump_dir):
        """Load previous data and set output file handler."""
        # extracted links will be saved in each language's dump directory
        cssdir = os.path.join(language_dump_dir, config.CSS_DIRNAME)
        links_file = os.path.join(cssdir, config.CSS_LINKS_FILENAME)
        # load previously collected links if any
        try:
            self._fh = open(links_file, 'r+t', encoding='utf-8')
            self.links = {line.strip() for line in self._fh}
        except FileNotFoundError:
            self._fh = open(links_file, 'wt', encoding='utf-8')
            self.links = set()

    def collect(self, html):
        """Find all css links in HTML string and save new ones to file."""
        new_links = set(self._findlinks(html)) - self.links
        if new_links:
            self.links.update(new_links)
            # as html head is discarded after this extraction,
            # dump new links as soon as found to avoid data loss
            with self._lock:
                self._fh.write('\n'.join(new_links) + '\n')
                self._fh.flush()

    def close(self):
        """Close output file handler."""
        self._fh.close()


# single instance for collecting css links from different threads
css_link_extractor = CSSLinkExtractor()

regex = (
    r'(<h1 id="firstHeading" class="firstHeading" >.+</h1>)'
    r'(.+)\s*<div class="printfooter">')
capture = re.compile(regex, re.MULTILINE | re.DOTALL).search


def get_html(url, basename):
    html = fetch_html(url)

    # ok, downloaded the html, let's check that it complies with some rules
    if "</html>" not in html:
        raise BadHTMLError("Broken HTML after downloading {!r}".format(url))

    found = capture(html)
    if not found:
        # unknown html format
        raise BadHTMLError("HTML file from  {!r} has an unknown format".format(url))
    stripped_html = "\n".join(found.groups())

    # collect css links here as html head is not saved
    css_link_extractor.collect(html)

    return stripped_html


def obtener_link_200_siguientes(html):
    links = re.findall('<a href="([^"]+)[^>]+>200 siguientes</a>', html)
    if links == []:
        return
    return '%s%s' % (WIKI, links[0])


def reemplazar_links_paginado(html, n):
    ''' Reemplaza lar urls anteriores y siguientes

        En el caso de la primera no encontrará el link 'anterior', no hay problema
        con llamar esta función
    '''

    def reemplazo(m):
        pre, link, post = m.groups()
        idx = '"' if (n == 2 and delta == -1) else '_%d"' % (n + delta)
        return '<a href="/wiki/' + link.replace('_', ' ') + idx + post

    # Reemplazo el link 'siguiente'
    delta = 1
    html = re.sub(r'(<a href="/w/index.php\?title=)(?P<link>[^&]+)[^>]+(>200 siguientes</a>)',
                  reemplazo, html)

    # Reemplazo el link 'anterior'
    delta = -1
    return re.sub(r'(<a href="/w/index.php\?title=)(?P<link>[^&]+)[^>]+(>200 previas</a>)',
                  reemplazo, html)


def get_temp_file(temp_dir):
    return tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8', suffix='.html',
                                       prefix='scrap-', dir=temp_dir, delete=False, )


def save_htmls(data_url):
    """Save the article to a temporary file.

    If it is a category, process pagination and save all pages.
    """
    html = get_html(str(data_url.url), data_url.basename)
    temp_file = get_temp_file(data_url.temp_dir)

    if "Categoría" not in data_url.basename:
        # normal case, not Categories or any paginated stuff
        temp_file.write(html)
        temp_file.close()
        return [(temp_file, data_url.disk_name)]

    # we have categories
    n = 1
    temporales = []
    while True:
        if n == 1:
            temporales.append((temp_file, data_url.disk_name))
        else:
            temporales.append((temp_file, data_url.disk_name + '_%d' % n))

        # encontrar el link tomando url
        prox_url = obtener_link_200_siguientes(html)

        html = reemplazar_links_paginado(html, n)
        temp_file.write(html)
        temp_file.close()

        if not prox_url:
            return temporales

        html = get_html(prox_url.replace('&amp;', '&'), data_url.basename)
        temp_file = get_temp_file(data_url.temp_dir)
        n += 1


def fetch(language, data_url):
    """Fetch a wikipedia page (that can be paginated)."""
    page = WikipediaArticle(language, data_url.url, data_url.basename)
    url = page.search_valid_version()
    data_url = data_url._replace(url=url)

    # save the htmls with the (maybe changed) url and all the data
    temporales = save_htmls(data_url)

    # transform temp data into final files
    for temp_file, disk_name in temporales:
        os.rename(temp_file.name, disk_name.encode("utf-8"))


def main(articles_path, language, dest_dir, test_limit=None, pool_size=20):
    """Main entry point.

    Params:
    - articles_path: the path to the file with the list of articles to download
    - language: the language of the Wikipedia to use (e.g.: 'es')
    - dest_dir: the destination directory to put the downloaded articles (may take tens of GBs)
    - test_limit: a limit to how many articles download (optional, defaults to all)
    - pool_size: how many concurrent downloaders use (optional, defaults to 20)
    """
    # setup css link extractor before scraping
    css_link_extractor.setup(language_dump_dir=os.path.dirname(dest_dir))

    previous_count, payloads = get_data_urls(articles_path, dest_dir, language, test_limit)

    func = functools.partial(fetch, language)
    utiles.pooled_exec(func, previous_count, payloads, pool_size, known_errors=[ScraperError])

    css_link_extractor.close()
