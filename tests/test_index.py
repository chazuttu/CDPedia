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


import shutil
import tempfile
import logging
import pytest

from src.armado import easy_index
from src.armado import compressed_index
from src.armado import sqlite_index


def decomp(data):
    """To write docset in a compact way.

    Ej: 'my title/2;second title/4'
    """
    docs = [n.strip().split("/") for n in data.split(";")]
    docs = [(n[0], int(n[1])) for n in docs]
    return docs


def abrev(result):
    """Cut auto generated html title in 0 position."""
    result = list(result)
    if not result:
        return result
    return [tuple(r[1:3]) for r in result]


class DataSet:
    """Creates data lists to put in the index."""
    fixtures = {}

    @classmethod
    def add_fixture(cls, key, data):
        docs = decomp(data)
        info = [(n[0].lower().split(" "), n[1], (None, n[0])) for n in docs]
        cls.fixtures[key] = info

    def __init__(self, key):
        self.name = key
        self.info = []
        if key in self.fixtures:
            self.info = self.fixtures[key]

    def __eq__(self, other):
        return self.info == other

    def __repr__(self):
        return "Fixture %s: %r" % (self.name, self.info)


def test_auxiliary():
    DataSet.add_fixture("one", "ala blanca/3")
    assert DataSet("one") == [(['ala', 'blanca'], 3, (None, 'ala blanca'))]
    r = [["A/l/a/Ala_Blanca", "ala blanca", 3],
         ["A/l/a/Ala", "ala", 8]]
    s = "ala blanca/3; ala/8"
    assert abrev(r) == decomp(s)


DataSet.add_fixture("A", "ala blanca/3")
DataSet.add_fixture("B", "ala blanca/3; conejo blanco/5; conejo negro/6")
data = """\
        aaa/4;
        abc/4;
        bcd/4;
        abd/4;
        bbd/4
    """
DataSet.add_fixture("E", data)


@pytest.fixture(params=[compressed_index.Index, easy_index.Index, sqlite_index.Index])
def create_index(request):
    """Create an index with given info in a temp dir, load it and return built index."""
    tempdir = tempfile.mkdtemp()

    def f(info):
        # Create the index with the parametrized engine
        engine = request.param
        engine.create(tempdir, info)

        # Load the index and give it to use
        index = engine(tempdir)
        return index

    try:
        yield f
    finally:
        shutil.rmtree(tempdir)


@pytest.fixture(params=[compressed_index.Index, easy_index.Index, sqlite_index.Index])
def get_engine(request):
    """Provide temp dirs and index engines to the tests."""
    tempdir = tempfile.mkdtemp()
    engine = request.param
    try:
        yield lambda: (tempdir, engine)
    finally:
        shutil.rmtree(tempdir)


# --- Test the .items method.


def test_items_nothing(create_index):
    """Nothing in the index."""
    with pytest.raises(ValueError) as _:
        create_index([])


def test_one_item(create_index):
    """Only one item."""
    idx = create_index(DataSet("A").info)
    values = idx.values()
    assert abrev(values) == decomp("ala blanca/3")


def test_several_items(create_index):
    """Several items stored."""
    idx = create_index(DataSet("B").info)
    values = sorted(idx.values())
    assert abrev(values) == decomp("ala blanca/3; conejo blanco/5; conejo negro/6")
    tokens = sorted([str(k) for k in idx.keys()])
    assert tokens == ["ala", "blanca", "blanco", "conejo", "negro"]

# --- Test the .random method.


def test_random_one_item(create_index):
    """Only one item."""
    idx = create_index(DataSet("A").info)
    value = idx.random()
    assert abrev([value]) == decomp("ala blanca/3")


def test_random_several_values(create_index):
    """Several values stored."""
    idx = create_index(DataSet("B").info)
    value = abrev([idx.random()])
    assert value[0] in decomp("ala blanca/3; conejo blanco/5; conejo negro/6")

# --- Test the "in" functionality.


def test_infunc_one_item(create_index):
    """Only one item."""
    idx = create_index(DataSet("B").info)
    assert "ala" in idx
    assert "bote" not in idx

# --- Test the .search method.


def test_search_failed(create_index):
    """Several items stored."""
    idx = create_index(DataSet("B").info)
    res = searchidx(idx, ["botero"])
    assert abrev(res) == []


def test_search_unicode(create_index):
    """Several items stored."""
    idx = create_index(DataSet("B").info)
    res1 = searchidx(idx, ["Alá"])
    res2 = searchidx(idx, ["ála"])
    assert res1 == res2


def test_search(create_index):
    """Several items stored."""
    idx = create_index(DataSet("B").info)
    res = searchidx(idx, ["ala"])
    assert abrev(res) == decomp("ala blanca/3")


def test_several_results(caplog, create_index):
    """Several results for one key stored."""
    caplog.set_level(logging.INFO)
    idx = create_index(DataSet("B").info)
    # items = [a for a in idx.search(["conejo"])]
    res = searchidx(idx, ["conejo"])
    assert set(abrev(res)) == set(decomp("conejo negro/6; conejo blanco/5"))


def test_several_keys(caplog, create_index):
    """Several item stored."""
    caplog.set_level(logging.INFO)
    idx = create_index(DataSet("B").info)
    # items = [a for a in idx.search(["conejo"])]
    res = searchidx(idx, ["conejo", "negro"])
    assert abrev(res) == decomp("conejo negro/6")


def test_many_results(caplog, create_index):
    """Test with many pages of results."""
    caplog.set_level(logging.INFO)
    data = """\
        blanca ojeda/9000;
        coneja blanca/9000;
        gradaciones entre los colores de blanca/9000;
        conejo blanca/9000;
        caja blanca/9000;
        limpieza de blanca/9000;
        blanca casa/9000;
        es blanca la paloma/9000;
        Blanca gómez/9000;
        recuerdos de blanca/9000;
        blanca/9000
    """
    DataSet.add_fixture("D", data)
    idx = create_index(DataSet("D").info)
    assert len(DataSet("D").info) == len([v for v in idx.values()])
    res = searchidx(idx, ["blanca"])
    assert len(res) == len(DataSet("D").info)


def searchidx(idx, keys):
    res = list(idx.search(keys))
    return res


def test_search_prefix(create_index):
    """Match its prefix."""
    idx = create_index(DataSet("B").info)
    res = idx.search(["blanc"])
    assert set(abrev(res)) == set(decomp("conejo blanco/5; ala blanca/3"))
    res = idx.search(["zz"])
    assert list(res) == []


def test_search_several_values(create_index):
    """Several values stored."""
    idx = create_index(DataSet("E").info)
    res = idx.search(["a"])
    assert set(abrev(res)) == set(decomp("aaa/4;abc/4;abd/4"))
    res = idx.search(["b"])
    assert set(abrev(res)) == set(decomp("abc/4;abd/4;bcd/4;bbd/4"))
    res = idx.search(["c"])
    assert set(abrev(res)) == set(decomp("abc/4;bcd/4"))
    res = idx.search(["d"])
    assert set(abrev(res)) == set(decomp("bcd/4;abd/4;bbd/4"))
    res = idx.search(["o"])
    assert set(abrev(res)) == set()


def test_search_and(create_index):
    """Check that AND is applied."""
    idx = create_index(DataSet("E").info)
    res = idx.search(["a", "b"])
    assert set(abrev(res)) == set(decomp("abc/4;abd/4"))
    res = idx.search(["b", "c"])
    assert set(abrev(res)) == set(decomp("abc/4;bcd/4"))
    res = idx.search(["a", "o"])
