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


import pytest

from src.armado import easy_index
from src.armado import sqlite_index
from src.armado.cdpindex import tokenize
from src.armado.sqlite_index import IndexEntry


def get_ie(title):
    """Creates an index_entry object with default values."""
    return IndexEntry(rtype=IndexEntry.TYPE_ORIG_ARTICLE,
                      title=title.strip(),
                      link=title.strip(),
                      score=0)


def to_idx_data(titles, function):
    """Generate a list of data prepared for create index."""
    return [(tokenize(ttl), 0, function(ttl), set()) for ttl in titles]


@pytest.fixture(params=[easy_index.Index, sqlite_index.Index])
def create_index(request, tmpdir):
    """Create an index with given info in a temp dir, load it and return built index."""

    def f(info):
        # Create the index with the parametrized engine
        engine = request.param
        if engine is sqlite_index.Index:
            setattr(engine, "search", engine.partial_search)
        engine.create(str(tmpdir), info)

        # Load the index and give it to use
        index = engine(str(tmpdir))
        return index

    yield f


# --- Test the .items method.


def test_items_nothing(create_index):
    """Nothing in the index."""
    with pytest.raises(ValueError) as _:
        create_index([])


def test_one_item(create_index):
    """Only one item."""
    idx = create_index(to_idx_data(["ala blanca"], get_ie))
    values = idx.values()
    # assert DataSet("A") == values
    assert list(values) == [get_ie("ala blanca")]


def test_several_items(create_index):
    """Several items stored."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    values = idx.values()
    assert set(values) == {get_ie('ala blanca'), get_ie('conejo blanco'), get_ie('conejo negro')}
    assert set(idx.keys()) == {"ala", "blanca", "blanco", "conejo", "negro"}


# --- Test the .random method.


def test_random_one_item(create_index):
    """Only one item."""
    idx = create_index(to_idx_data(["ala blanca"], get_ie))
    value = idx.random()
    assert value == get_ie("ala blanca")


def test_random_several_values(create_index):
    """Several values stored."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    value = list([idx.random()])[0]
    assert value in {get_ie('ala blanca'), get_ie('conejo blanco'), get_ie('conejo negro')}

# --- Test the "in" functionality.


def test_infunc_one_item(create_index):
    """Only one item."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    assert "ala" in idx
    assert "bote" not in idx

# --- Test the .search method.


def test_search_failed(create_index):
    """Several items stored."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    res = list(idx.search(["botero"]))
    assert res == []


def test_search_unicode(create_index):
    """Several items stored."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    res1 = list(idx.search(["Alá"]))
    res2 = list(idx.search(["ála"]))
    assert res1 == res2


def test_search(create_index):
    """Several items stored."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    res = list(idx.search(["ala"]))
    assert res == [get_ie("ala blanca")]


def test_several_results(create_index):
    """Several results for one key stored."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    # items = [a for a in idx.search(["conejo"])]
    res = idx.search(["conejo"])
    assert set(res) == {get_ie('conejo blanco'), get_ie('conejo negro')}


def test_several_keys(create_index):
    """Several item stored."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    # items = [a for a in idx.search(["conejo"])]
    res = idx.search(["conejo", "negro"])
    assert set(res) == {get_ie('conejo negro')}


def test_many_results(create_index):
    """Test with many pages of results."""
    data = """\
        blanca ojeda;
        coneja blanca;
        gradaciones entre los colores de blanca;
        conejo blanca;
        caja blanca;
        limpieza de blanca;
        blanca casa;
        es blanca la paloma;
        Blanca gómez;
        recuerdos de blanca;
        blanca
    """.split(';')
    idx = create_index(to_idx_data(data, get_ie))
    assert len(data) == len([v for v in idx.values()])
    res = list(idx.search(["blanca"]))
    assert len(res) == len(data)


def test_search_prefix(create_index):
    """Match its prefix."""
    idx = create_index(to_idx_data(["ala blanca", "conejo blanco", "conejo negro"], get_ie))
    res = idx.partial_search(["blanc"])
    assert set(res) == {get_ie('ala blanca'), get_ie('conejo blanco')}
    res = idx.partial_search(["zz"])
    assert list(res) == []


def test_search_several_values(create_index):
    """Several values stored."""
    data = ["aaa", "abc", "bcd", "abd", "bbd"]
    idx = create_index(to_idx_data(data, get_ie))
    res = idx.partial_search(["a"])
    assert set(res) == {get_ie("aaa"), get_ie("abc"), get_ie("abd")}
    res = idx.partial_search(["b"])
    assert set(res) == {get_ie("abc"), get_ie("abd"), get_ie("bcd"), get_ie("bbd")}
    res = idx.partial_search(["c"])
    assert set(res) == {get_ie("abc"), get_ie("bcd")}
    res = idx.partial_search(["d"])
    assert set(res) == {get_ie("bcd"), get_ie("abd"), get_ie("bbd")}
    res = idx.partial_search(["o"])
    assert set(res) == set()


def test_search_and(create_index):
    """Check that AND is applied."""
    data = ["aaa", "abc", "bcd", "abd", "bbd"]
    idx = create_index(to_idx_data(data, get_ie))
    res = idx.partial_search(["a", "b"])
    assert set(res) == {get_ie("abc"), get_ie("abd")}
    res = idx.partial_search(["b", "c"])
    assert set(res) == {get_ie("abc"), get_ie("bcd")}
    res = idx.partial_search(["a", "o"])
    assert set(res) == set()
