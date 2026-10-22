"""For each hinge list ALL nearby thin panels, regardless of distance."""
import math
import sys
from pathlib import Path
import numpy as np
from pygltflib import GLTF2

GLB = Path(__file__).parent / "src" / "assets" / "models" / "PSL-AS.glb"
gltf = GLTF2().load(str(GLB))

parents = {}
for pi, p in enumerate(gltf.nodes):
    for ci in (p.children or []):
        parents[ci] = pi


def node_world_matrix(idx):
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


def mesh_world_bbox(node_idx):
    node = gltf.nodes[node_idx]
    if node.mesh is None:
        return None
    M = node_world_matrix(node_idx)
    mesh = gltf.meshes[node.mesh]
    mins = np.array([math.inf] * 3)
    maxs = np.array([-math.inf] * 3)
    for prim in mesh.primitives:
        acc = gltf.accessors[prim.attributes.POSITION]
        if acc.min is None or acc.max is None:
            continue
        for cx in (acc.min[0], acc.max[0]):
            for cy in (acc.min[1], acc.max[1]):
                for cz in (acc.min[2], acc.max[2]):
                    v = M @ np.array([cx, cy, cz, 1.0])
                    mins = np.minimum(mins, v[:3])
                    maxs = np.maximum(maxs, v[:3])
    if not np.all(np.isfinite(mins)):
        return None
    return mins, maxs


hinges = {}
for ni, n in enumerate(gltf.nodes):
    if n.name and n.name.startswith("KLT-180-AS:"):
        try:
            idx = int(n.name.split(":")[1])
        except Exception:
            continue
        M = node_world_matrix(ni)
        hinges[idx] = (M @ np.array([0, 0, 0, 1.0]))[:3]

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
    # door-sized panels (thin AND upright)
    if dims[0] > 0.15:
        continue
    if dims[1] < 0.30:
        continue
    if dims[2] < 0.50:
        continue
    if size[1] < 0.50:
        continue
    panels.append({
        "node": ni,
        "centre": (mins + maxs) / 2,
        "min": mins,
        "max": maxs,
        "size": size,
    })

print(f"{len(hinges)} hinges, {len(panels)} candidate panels\n")
for idx in sorted(hinges):
    hp = hinges[idx]
    print(f"=== Door {idx}: hinge @ x={hp[0]:+.3f} y={hp[1]:+.3f} z={hp[2]:+.3f}")
    cands = []
    for p in panels:
        dy = hp[1] - p["centre"][1]
        dx = max(0.0, p["min"][0] - hp[0], hp[0] - p["max"][0])
        dz = max(0.0, p["min"][2] - hp[2], hp[2] - p["max"][2])
        dxz = math.sqrt(dx * dx + dz * dz)
        cands.append((dxz, dy, p))
    # ignore Y window
    cands = [c for c in cands if -0.1 <= c[1] <= 1.5]
    cands.sort(key=lambda c: c[0])
    for dxz, dy, p in cands[:8]:
        sx, sy, sz = p["size"]
        cx, cy, cz = p["centre"]
        print(f"   dxz={dxz:.3f} dy={dy:+.3f} size=({sx:.2f},{sy:.2f},{sz:.2f}) ctr=({cx:+.2f},{cy:+.2f},{cz:+.2f}) node={p['node']}")
    print()

print("\n--- ALL candidate panels (centre + size) ---")
for p in panels:
    sx, sy, sz = p["size"]
    cx, cy, cz = p["centre"]
    print(f"node={p['node']:4d}  ctr=({cx:+.2f},{cy:+.2f},{cz:+.2f})  size=({sx:.2f},{sy:.2f},{sz:.2f})")
