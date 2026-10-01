from accordance.kb.ordering import natural_key


def test_natural_key_orders_numeric_segments_as_ints():
    ids = ["2-10", "2-2", "2-1", "101-1", "303-3"]
    assert sorted(ids, key=natural_key) == ["2-1", "2-2", "2-10", "101-1", "303-3"]
