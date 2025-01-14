#!/usr/bin/env python

# Copyright 2008-2021 CDPedistas (see AUTHORS.txt)
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

import functools
import gettext
import itertools
import logging
import os
import posixpath
import tarfile
import tempfile
import urllib.parse
from datetime import datetime
from mimetypes import guess_type

from werkzeug.wrappers import Request, Response
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, NotFound, InternalServerError
from werkzeug.utils import redirect
from jinja2 import Environment, FileSystemLoader

import config
from . import utils
from .destacados import Destacados
from src.armado import cdpindex
from src.armado.cdpindex import normalize_words
from src.armado import compresor
from src.armado import to3dirs
from .test_infra import load_test_infra_data
from .utils import TemplateManager

ARTICLES_BASE_URL = "wiki"
SEARCH_CACHE_SIZE = 100

logger = logging.getLogger(__name__)


class ArticleNotFound(HTTPException):
    code = 404

    def __init__(self, article_name, original_link, description=None):
        HTTPException.__init__(self, description)
        self.article_name = article_name
        self.original_link = original_link


class CDPedia:

    def __init__(self, watchdog=None, verbose=False):
        self.watchdog = watchdog
        self.verbose = verbose

        self.art_mngr = compresor.ArticleManager(verbose=verbose)

        # Configure template engine (jinja)
        template_path = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(loader=FileSystemLoader(template_path),
                                     extensions=['jinja2.ext.i18n'],
                                     autoescape=False)
        self.jinja_env.globals["watchdog"] = True if watchdog else False
        self.jinja_env.globals["date"] = self.get_creation_date()
        self.jinja_env.globals["version"] = config.VERSION
        self.jinja_env.globals["language"] = config.LANGUAGE
        # translation config set as environment variable at init time
        translations = gettext.translation("core", 'locale')
        self.jinja_env.install_gettext_translations(translations)

        self.template_manager = TemplateManager(template_path)
        self.img_mngr = compresor.ImageManager(verbose=verbose)
        self.featured_mngr = Destacados(self.art_mngr, debug=False)

        self.index = cdpindex.IndexInterface(config.DIR_INDICE)
        self.index.start()

        self.tmpdir = os.path.join(tempfile.gettempdir(), "cdpedia")
        self.url_map = Map([
            Rule('/', endpoint='main_page'),
            Rule('/%s/<path:name>' % ARTICLES_BASE_URL, endpoint='article'),
            Rule('/al_azar', endpoint='random'),
            Rule('/search', endpoint='search', methods=['POST']),
            Rule('/search/<path:key>', endpoint='search_results'),
            Rule('/images/<path:name>', endpoint='image'),
            Rule('/institucional/<path:path>', endpoint='institutional'),
            Rule('/watchdog/update', endpoint='watchdog_update'),
            Rule('/tutorial', endpoint='tutorial'),
            Rule('/favicon.ico', endpoint='favicon'),
            Rule('/test_infra', endpoint='test_infra')
        ])
        self._tutorial_ready = False
        self._test_infra_data = None
        self.docs_dirname = None  # root directory of tar archive

    def get_creation_date(self):
        _path = os.path.join(config.DIR_ASSETS, 'dynamic', 'start_date.txt')
        with open(_path, 'rt', encoding='utf-8') as f:
            date = f.read().strip()
        creation_date = datetime.strptime(date, "%Y%m%d")
        return creation_date

    def on_main_page(self, request):
        featured_data = self.featured_mngr.get_destacado()
        if featured_data is None:
            portal_name = config.PORTAL_PAGE
            return self.on_article(request, portal_name)
        else:
            link, title, first_paragraphs = featured_data
            featured = {"link": link, "title": title, "first_paragraphs": first_paragraphs}
            return self.render_template('main_page.html', title="Portada", featured=featured)

    def on_article(self, request, name):
        orig_link = utils.get_orig_link(name)
        # compressed article name contains special filesystem chars quoted
        filename = to3dirs.to_filename(name)
        try:
            data = self.art_mngr.get_item(filename)
        except Exception as err:
            raise InternalServerError("Error interno al buscar contenido: %s" % err)

        if data is None:
            raise ArticleNotFound(name, orig_link)

        return self.render_template('article.html',
                                    article_name=name,
                                    orig_link=orig_link,
                                    article=data,
                                    )

    def on_test_infra(self, request):
        if self._test_infra_data is None:
            try:
                data = load_test_infra_data()
            except FileNotFoundError:
                # won't launch test infra if data file doesn't exist
                raise NotFound()
            if not data:
                raise InternalServerError("No pages to test")
            self._test_infra_data = itertools.cycle(data)

        item_data = next(self._test_infra_data)
        article = self.art_mngr.get_item(item_data['article_name'])
        if article is None:
            article = 'Article Not Found'
        return self.render_template('test_infra.html', article=article, **item_data)

    def on_image(self, request, name):
        try:
            normpath = posixpath.normpath(name)
            asset_data = self.img_mngr.get_item(normpath)
        except Exception as err:
            msg = "Error interno al buscar imagen: %s" % err
            raise InternalServerError(msg)
        if asset_data is None:
            logger.warning("No pudimos encontrar %r", name)
            try:
                width, _, height = request.args["s"].partition('-')
                width = int(width)
                height = int(height)
            except Exception:
                raise InternalServerError("Error al generar imagen")
            # image not included, return fallback picture of same dimensions
            show_text = width > 90 and height > 30
            img_template = self.jinja_env.get_template('no_image.svg')
            img = img_template.render(width=width, height=height, show_text=show_text)
            return Response(img, mimetype='image/svg+xml')
        type_ = guess_type(name)[0]
        return Response(asset_data, mimetype=type_)

    def on_favicon(self, request):
        asset_file = os.path.join(config.DIR_ASSETS, 'static', 'misc', 'favicon.ico')
        with open(asset_file, 'rb') as f:
            asset_data = f.read()
        type_ = guess_type(asset_file)[0]
        return Response(asset_data, mimetype=type_)

    def on_institutional(self, request, path):
        path = os.path.join("institucional", path)
        asset_file = os.path.join(config.DIR_ASSETS, path)
        if os.path.isdir(asset_file):
            logger.warning("%r es un directorio", asset_file)
            raise NotFound()
        if not os.path.exists(asset_file):
            logger.warning("No pudimos encontrar %r", asset_file)
            raise NotFound()

        # all unicode
        data = open(asset_file, "rt", encoding="utf-8").read()
        title = utils.get_title_from_data(data)

        p = self.render_template('institucional.html', title=title, asset=data)
        return p

    def on_random(self, request):
        """Redirect to a random article."""
        idx_entry = self.index.get_random()
        link = "%s/%s" % (ARTICLES_BASE_URL, to3dirs.from_path(idx_entry.link))
        return redirect(urllib.parse.quote(link.encode("utf-8")))

    @functools.lru_cache(SEARCH_CACHE_SIZE)
    def _search(self, search_string):
        """Really do the search."""
        search_string_norm = normalize_words(search_string)
        words = search_string_norm.split()
        results = list(self.index.search(words))

        # remove 3 dirs from link and add the proper base url
        for result in results:
            result.link = "wiki/{}".format(
                urllib.parse.quote(to3dirs.from_path(result.link), safe=()))

        return results

    def on_search(self, request):
        """Search he received keywords in the POST request in the index."""
        search_string = request.form.get("keywords", '')
        search_string = urllib.parse.unquote_plus(search_string)
        if not search_string:
            return redirect("/")

        results = self._search(search_string)
        return self.render_template('search.html', search_string=search_string, results=results)

    def on_tutorial(self, request):
        tmpdir = os.path.join(self.tmpdir)
        if not self._tutorial_ready:
            if not self.docs_dirname or not os.path.exists(
                    os.path.join(tmpdir, self.docs_dirname)):
                tar = tarfile.open(
                    os.path.join(config.DIR_ASSETS, config.PYTHON_DOCS_FILENAME), mode="r:bz2")
                self.docs_dirname = tar.next().name
                tar.extractall(tmpdir)
                tar.close()
            self._tutorial_ready = True
        asset = "/cmp/{}/tutorial/index.html".format(self.docs_dirname)
        return self.render_template('compressed_asset.html',
                                    server_mode=config.SERVER_MODE,
                                    asset_url=asset,
                                    asset_name="Tutorial de python")

    def on_watchdog_update(self, request):
        self.watchdog.update()
        seconds = str(int(config.BROWSER_WD_SECONDS * 0.85))
        html = (
            "<html><head><meta http-equiv='refresh' content='%s'></head><body></body></html>" % (
                seconds,))
        resp = Response(html, mimetype="text/html")
        return resp

    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        return Response(t.render(context), mimetype='text/html')

    def dispatch_request(self, request):
        adapter = self.url_map.bind_to_environ(request.environ)
        try:
            endpoint, values = adapter.match()
            return getattr(self, 'on_' + endpoint)(request, **values)
        except ArticleNotFound as err:
            response = self.render_template(
                "404.html", article_name=err.article_name, original_link=err.original_link)
            response.status_code = 404
            return response
        except InternalServerError as err:
            response = self.render_template("500.html", message=err.description)
            response.status_code = 500
            return response
        except HTTPException as err:
            return err

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)


def create_app(watchdog, verbose=False, with_static=True, with_debugger=True,
               use_evalex=True):
    from werkzeug.middleware.shared_data import SharedDataMiddleware
    from werkzeug.debug import DebuggedApplication
    app = CDPedia(watchdog, verbose=verbose)
    if with_static:
        paths = [("/" + path, os.path.join(config.DIR_ASSETS, path))
                 for path in config.ALL_ASSETS]
        paths += [('/cmp', app.tmpdir)]
        app.wsgi_app = SharedDataMiddleware(app.wsgi_app, dict(paths))
    if with_debugger:
        app.wsgi_app = DebuggedApplication(app.wsgi_app, use_evalex)
    return app


if __name__ == '__main__':
    from werkzeug.serving import run_simple

    app = create_app()
    run_simple('127.0.0.1', 8000, app, use_debugger=True, use_reloader=False,
               threaded=True)
