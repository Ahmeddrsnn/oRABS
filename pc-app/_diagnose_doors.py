"""Diagnose: for each KLT-180-AS hinge, report nearby thin panel candidates.

Mimics the spatial query in viewer.js but prints per-hinge results so we
can see why some doors stay grey.
"""
import math
import sys
from pathlib import Path

from pygltflib import GLTF2

GLB = Path(__file__).parent / "src" / "assets" / "models" / "PSL-AS.glb"

gltf = GLTF2().load(str(GLB))


def node_world_matrix(idx, parents):
    """Compose world matrix by walking up the parent chain."""
    import numpy as np
    M = np.eye(4)
    chain = []
    cur = idx
    while cur is not None:
        chain.append(cur)
        cur = parents.get(cur)
    for n_idx in reversed(chain):
        node = gltf.nodes[n_idx]
        T = np.eye(4)
        if node.matrix:
            T = np.array(node.matrix, dtype=float).reshape(4, 4).T
        else:
            if node.translation:
                T[:3, 3] = node.translation
            if node.rotation:
                qx, qy, qz, qw = node.rotation
                R = np.array([
                    [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw), 0],
                    [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw), 0],
                    [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy), 0],
                    [0, 0, 0, 1],
                ])
                T = T @ R
            if node.scale:
                S = np.diag([*node.scale, 1.0])
                T = T @ S
        M = M @ T
    return M


def main():
    import numpy as np

    parents = {}
    for pi, p in enumerate(gltf.nodes):
        for ci in (p.children or []):
            parents[ci] = pi

    # Build a list of all meshes with their world bbox (approx — use node
    # translation only, ignoring mesh-vertex bounds for speed; this is enough
    # to know the OVERALL position).  For accurate bbox we'd need to load
    # vertex data — skipping that for this quick diagnose.
    # Instead use mesh.primitives bounds from accessors.
    def mesh_world_bbox(node_idx):
        node = gltf.nodes[node_idx]
        if node.mesh is None:
            return None
        M = node_world_matrix(node_idx, parents)
        mesh = gltf.meshes[node.mesh]
        mins = np.array([math.inf] * 3)
        maxs = np.array([-math.inf] * 3)
        for prim in mesh.primitives:
            acc = gltf.accessors[prim.attributes.POSITION]
            if acc.min is None or acc.max is None:
                continue
            corners = [
                (acc.min[0], acc.min[1], acc.min[2]),
                (acc.min[0], acc.min[1], acc.max[2]),
                (acc.min[0], acc.max[1], acc.min[2]),
                (acc.min[0], acc.max[1], acc.max[2]),
                (acc.max[0], acc.min[1], acc.min[2]),
                (acc.max[0], acc.min[1], acc.max[2]),
                (acc.max[0], acc.max[1], acc.min[2]),
                (acc.max[0], acc.max[1], acc.max[2]),
            ]
            for cx, cy, cz in corners:
                v = M @ np.array([cx, cy, cz, 1.0])
                mins = np.minimum(mins, v[:3])
                maxs = np.maximum(maxs, v[:3])
        if not np.all(np.isfinite(mins)):
            return None
        return mins, maxs

    # Find hinge world positions
    hinges = {}
    for ni, n in enumerate(gltf.nodes):
        name = n.name or ""
        if name.startswith("KLT-180-AS:"):
            try:
                idx = int(name.split(":")[1])
            except Exception:
                continue
            M = node_world_matrix(ni, parents)
            world = M @ np.array([0, 0, 0, 1.0])
            hinges[idx] = world[:3]

    # Find candidate panels (thin, door-sized)
    panels = []
    for ni, n in enumerate(gltf.nodes):
        if n.mesh is None:
            continue
        bb = mesh_world_bbox(ni)
        if bb is None:
            continue
        mins, maxs = bb
        size = maxs - mins
        dims = sorted(size)
        if dims[0] > 0.15 or dims[1] < 0.30 or dims[2] < 0.50:
            continue
        panels.append({
            "node": ni,
            "name": n.name or f"<node{ni}>",
            "centre": (mins + maxs) / 2,
            "min": mins,
            "max": maxs,
            "size": size,
            "sizeY": size[1],
        })

    print(f"Found {len(hinges)} hinges and {len(panels)} door-sized panels")
    print()
    for idx in sorted(hinges):
        hp = hinges[idx]
        print(f"=== Door {idx}: hinge @ x={hp[0]:.3f} y={hp[1]:.3f} z={hp[2]:.3f}")
        cands = []
        for p in panels:
            dy = hp[1] - p["centre"][1]
            dx = max(0.0, p["min"][0] - hp[0], hp[0] - p["max"][0])
            dz = max(0.0, p["min"][2] - hp[2], hp[2] - p["max"][2])
            dxz = math.sqrt(dx * dx + dz * dz)
            cands.append((dxz, dy, p))
        cands.sort(key=lambda c: c[0])
        for dxz, dy, p in cands[:4]:
            sx, sy, sz = p["size"]
            print(f"   dxz={dxz:.3f}  dy={dy:+.3f}  size=({sx:.2f},{sy:.2f},{sz:.2f})  node={p['node']:3d} {p['name']!r}")
        print()


if __name__ == "__main__":
    sys.exit(main() or 0)
