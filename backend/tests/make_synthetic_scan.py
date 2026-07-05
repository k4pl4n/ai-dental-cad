"""Generate a synthetic upper-arch intraoral scan for pipeline testing.

Not anatomically correct — but it has the right gross geometry: a horseshoe
ridge with 14 tooth-like bumps (two sites left as gaps), a filled palate
(so upper-arch detection fires), 30k+ vertices, and realistic dimensions
(~55mm wide, ~48mm deep).
"""
import os
import sys

import numpy as np
import trimesh


def make_arch(out_path: str) -> None:
    rng = np.random.default_rng(7)

    # parabolic arch centreline
    half_w, depth = 27.0, 46.0
    xs = np.linspace(-half_w, half_w, 400)
    ys = depth * (1 - (xs / half_w) ** 2) - depth * 0.5   # anterior at +y

    parts = []

    # ridge: tube of spheres along the centreline
    for x, y in zip(xs[::6], ys[::6]):
        s = trimesh.creation.icosphere(subdivisions=2, radius=4.5)
        s.apply_translation([x, y, 0])
        parts.append(s)

    # palate: dome filling the centre (upper-arch signature)
    palate = trimesh.creation.icosphere(subdivisions=3, radius=20.0)
    palate.apply_scale([1.0, 1.0, 0.25])
    palate.apply_translation([0, -4.0, -1.5])
    parts.append(palate)

    # teeth: bumps along the arch; skip index 4 (a "missing" premolar site)
    tooth_ts = np.linspace(0.04, 0.96, 14)
    for i, t in enumerate(tooth_ts):
        if i == 4:
            continue                                       # edentulous gap
        x = -half_w + 2 * half_w * t
        y = depth * (1 - (x / half_w) ** 2) - depth * 0.5
        anterior = abs(x) < 10
        h = 6.0 if not anterior else 4.0                   # worn anteriors: shorter
        tooth = trimesh.creation.capsule(radius=3.4 if not anterior else 2.6, height=h)
        tooth.apply_translation([x, y, 4.0 + h / 2])
        parts.append(tooth)

    mesh = trimesh.util.concatenate(parts)

    # scan-like surface noise + densify to intraoral vertex counts
    while len(mesh.vertices) < 30000:
        mesh = mesh.subdivide()
    mesh.vertices += rng.normal(0, 0.02, mesh.vertices.shape)

    # random rotation — ingestion must normalise it back
    r = trimesh.transformations.rotation_matrix(np.radians(31), [0.3, 1.0, 0.2])
    mesh.apply_transform(r)

    mesh.export(out_path)
    print(f"synthetic scan: {len(mesh.vertices):,} vertices → {out_path}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "synthetic_upper.stl"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    make_arch(out)
