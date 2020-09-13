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
"""
Creates a sqlite_index from a existing compressed_index
"""

import pathlib
import logging
import pickle
import re
import os
import sys
from collections import defaultdict
from logging.handlers import RotatingFileHandler
from bz2 import BZ2File as CompressedFile
sys.path.append(os.path.abspath(os.curdir))

import config   # NOQA import after fixing path
from src.armado import to3dirs  # NOQA import after fixing path
from src.armado.sqlite_index import Index as IndexSQL  # NOQA import after fixing path
from src.armado.cdpindex import normalize_words  # NOQA import after fixing path

logger = logging.getLogger()
handler = logging.StreamHandler()
logger.addHandler(handler)
formatter = logging.Formatter("%(asctime)s  %(name)-20s %(levelname)-8s %(message)s")
handler.setFormatter(formatter)
logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)
handler = RotatingFileHandler("cdpetron.log")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger = logging.getLogger("index")

WORDS = re.compile(r"\w+", re.UNICODE)
PATH_IDX = pathlib.Path("./idx")
PATH_COMP = PATH_IDX.joinpath("old")


def walk():
    # see how many id files we have
    for fn in os.listdir(PATH_COMP):
        if fn.startswith("compindex-") and fn.endswith(".ids.bz2"):
            yield str(PATH_COMP.joinpath(fn))


def decomp(fname):
    """Decompress a file and return a dict."""
    fh = CompressedFile(fname, "rb")
    # encoding needed for compatibility w/ py2 cPickle
    idx = pickle.load(fh, encoding="latin1")
    fh.close()
    return idx


def cycle():
    """Loop & open every file and yield every value inside."""
    for fname in walk():
        idx = decomp(fname)
        # print(fname, len(idx))
        print("!", end="", flush=True)
        for n_doc, value in idx.items():
            html, title, ptje, redir, primtext = value
            words = list(WORDS.findall(normalize_words(title)))
            yield words, ptje, (html, title, redir, primtext)


def cycle_filtered():
    allreadyseen = set()
    repeated = null_title = 0
    for words, ptje, data in cycle():
        hash_data = hash(data)
        if hash_data not in allreadyseen:
            allreadyseen.add(hash_data)
            if data[1]:
                yield words, ptje, data
            else:
                null_title += 1
        else:
            repeated += 1
    print("null_title", null_title, "  repeated", repeated)



def media_words():
    words_lenght = defaultdict(int)
    with open("long_titles.txt", "w") as fh:
        for words, ptje, data in cycle():
            lenght = len(words)
            words_lenght[lenght] += 1
            if lenght > 15:
                fh.write(' '.join(words) + "\n")
    keys = list(words_lenght.keys())
    keys.sort()
    for k in keys:
        print(k, words_lenght[k])


def test_cycle():
    """See what is bringing."""
    for n_doc, value in enumerate(cycle()):
        print(value)
        if n_doc > 5:
            break


def main():
    help = """Creates a new sqlite index from the compressed index information.

    Sqlite index path: '%s'    Legacy compressed index path: '%s'""" % (PATH_IDX, PATH_COMP)
    print(help)
    sqlitepath = PATH_IDX.joinpath("index.sqlite")
    if sqlitepath.exists():
        sqlitepath.unlink()
        print("Database index %s was removed" % sqlitepath)
    IndexSQL.create(str(PATH_IDX), cycle_filtered())


if __name__ == "__main__":
    # media_words()
    main()
