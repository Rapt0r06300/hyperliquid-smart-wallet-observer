from hl_observer.arbitrage.triangular_graph import TriangularEdge, build_triangular_cycles


def test_triangular_graph_builds_cycle():
    cycles = build_triangular_cycles(
        [
            TriangularEdge("A", "B", 2),
            TriangularEdge("B", "C", 3),
            TriangularEdge("C", "A", 0.2),
        ]
    )
    assert cycles
