from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MeshNode:
    tag: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class MeshSnapshot:
    nodes: tuple[MeshNode, ...]
    elem_tags: tuple[int, ...]
    elem_nodes_flat: tuple[int, ...]  # 4 * n_elem
    """요소별 CalculiX ELSET 이름. None 이면 단일 EALL."""
    elem_elset: tuple[str, ...] | None = None

    @classmethod
    def from_gmsh_session(cls, *, tet_element_type: int = 4) -> MeshSnapshot:
        """Gmsh 초기화·체적 메쉬 생성 직후 호출. C3D4(타입 4)만."""
        import gmsh  # noqa: PLC0415 — 런타임(도커/워커)에만 필요, 단위 테스트는 gmsh 없이 동작

        node_tags, coord, _ = gmsh.model.mesh.getNodes()
        if len(node_tags) == 0:
            raise RuntimeError("Gmsh: 노드가 없습니다.")
        tags_list = [int(t) for t in node_tags]
        c = [float(x) for x in coord]
        nodes: list[MeshNode] = []
        for i, t in enumerate(tags_list):
            b = 3 * i
            nodes.append(MeshNode(t, c[b], c[b + 1], c[b + 2]))

        elem_types, elem_tags_arr, node_tags_el = gmsh.model.mesh.getElements(dim=3)
        out_tags: list[int] = []
        out_nodes: list[int] = []
        for etype, tags, nodes_block in zip(elem_types, elem_tags_arr, node_tags_el):
            if int(etype) != tet_element_type:
                continue
            n_elem = len(tags)
            for e in range(n_elem):
                out_tags.append(int(tags[e]))
                base = 4 * e
                out_nodes.extend(
                    [
                        int(nodes_block[base]),
                        int(nodes_block[base + 1]),
                        int(nodes_block[base + 2]),
                        int(nodes_block[base + 3]),
                    ]
                )
        if not out_tags:
            raise RuntimeError("Gmsh: 3D 선형 사면체가 없습니다.")
        return cls(
            nodes=tuple(nodes),
            elem_tags=tuple(out_tags),
            elem_nodes_flat=tuple(out_nodes),
            elem_elset=None,
        )
