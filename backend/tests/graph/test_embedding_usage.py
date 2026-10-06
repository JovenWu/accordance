import inspect

from accordance.graph.nodes import index_node


def test_index_node_accepts_conn_param():
    params = list(inspect.signature(index_node).parameters)
    assert params[:3] == ["state", "store", "conn"]
