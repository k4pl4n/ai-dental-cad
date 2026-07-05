"""Layer 2a — Rendering pipeline. (DEV_PLAN Step 2, SPEC Appendix A)

Five views. Not three. Not seven. Five.
1024×1024 PNG, ambient + one directional light from above.

Primary renderer: Open3D OffscreenRenderer (headless-safe, used on Railway).
Fallback: matplotlib trisurf on a decimated mesh — lower fidelity but keeps
the pipeline alive anywhere (PLAN Part 6: rendering failure → degrade, flag).
"""
from __future__ import annotations

import logging
import os

import numpy as np
import trimesh

log = logging.getLogger(__name__)

RESOLUTION = 1024
VIEW_NAMES = ["occlusal", "buccal_right", "buccal_left", "anterior", "diagonal"]


def _camera_positions(mesh: trimesh.Trimesh) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """(eye, look_at) per view, relative to arch centroid. SPEC Appendix A."""
    c = mesh.vertices.mean(axis=0)
    ext = mesh.bounding_box.extents
    longest = float(max(ext))
    d = 1.5 * longest
    width_d = 1.5 * float(ext[0])
    depth_d = 1.5 * float(ext[1])

    # diagonal: 30° elevation, 15° from midline, in front of the arch
    el, az = np.radians(30), np.radians(15)
    diag = c + d * np.array([np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)])

    return {
        "occlusal":     (c + np.array([0, 0, d]), c),
        "buccal_right": (c + np.array([width_d, 0, 0]), c),
        "buccal_left":  (c + np.array([-width_d, 0, 0]), c),
        "anterior":     (c + np.array([0, depth_d, 0]), c),
        "diagonal":     (diag, c),
    }


# ------------------------------------------------------------- Open3D path

def _render_open3d(mesh: trimesh.Trimesh, out_dir: str) -> list[str]:
    import open3d as o3d
    from open3d.visualization import rendering

    o3 = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(mesh.vertices),
        o3d.utility.Vector3iVector(mesh.faces),
    )
    o3.compute_vertex_normals()

    renderer = rendering.OffscreenRenderer(RESOLUTION, RESOLUTION)
    mat = rendering.MaterialRecord()
    mat.shader = "defaultLit"
    mat.base_color = [0.92, 0.90, 0.86, 1.0]        # tooth-like neutral
    renderer.scene.add_geometry("arch", o3, mat)
    renderer.scene.scene.set_sun_light([0.0, 0.3, -1.0], [1.0, 1.0, 1.0], 90000)
    renderer.scene.scene.enable_sun_light(True)
    renderer.scene.set_background([1, 1, 1, 1])

    paths = []
    for name, (eye, target) in _camera_positions(mesh).items():
        up = [0, 1, 0] if name == "occlusal" else [0, 0, 1]
        renderer.setup_camera(45.0, target.astype(np.float32),
                              eye.astype(np.float32), np.array(up, dtype=np.float32))
        img = renderer.render_to_image()
        p = os.path.join(out_dir, f"{name}.png")
        o3d.io.write_image(p, img)
        paths.append(p)
    return paths


# --------------------------------------------------------- matplotlib path

def _render_matplotlib(mesh: trimesh.Trimesh, out_dir: str) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    m = mesh
    if len(m.faces) > 15_000:                        # decimate hard: plot speed + memory
        try:
            m = m.simplify_quadric_decimation(face_count=15_000)
        except Exception:                            # fallback: vertex subsampling
            keep = np.random.default_rng(0).choice(
                len(m.faces), 15_000, replace=False)
            m = trimesh.Trimesh(m.vertices, m.faces[keep])
            m.remove_unreferenced_vertices()

    v, f = m.vertices, m.faces
    c = v.mean(axis=0)

    view_angles = {                                  # (elev, azim) equivalents
        "occlusal":     (90, -90),
        "buccal_right": (0, 0),
        "buccal_left":  (0, 180),
        "anterior":     (0, 90),
        "diagonal":     (30, 75),
    }
    paths = []
    for name, (elev, azim) in view_angles.items():
        fig = plt.figure(figsize=(RESOLUTION / 100, RESOLUTION / 100), dpi=100)
        ax = fig.add_subplot(111, projection="3d")
        ax.plot_trisurf(v[:, 0], v[:, 1], f, v[:, 2],
                        color=(0.92, 0.90, 0.86), edgecolor="none",
                        shade=True, antialiased=False)
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        r = max(m.bounding_box.extents) * 0.6
        ax.set_xlim(c[0] - r, c[0] + r)
        ax.set_ylim(c[1] - r, c[1] + r)
        ax.set_zlim(c[2] - r, c[2] + r)
        ax.set_box_aspect((1, 1, 1))
        p = os.path.join(out_dir, f"{name}.png")
        fig.savefig(p, bbox_inches="tight", pad_inches=0, facecolor="white")
        plt.close(fig)
        paths.append(p)
    return paths


# ------------------------------------------------------------------ entry

def render_five_views(mesh_path: str, out_dir: str) -> tuple[list[str], str]:
    """Returns ([png paths in VIEW_NAMES order], renderer_used).
    Raises RenderingError only if BOTH renderers fail."""
    os.makedirs(out_dir, exist_ok=True)
    mesh = trimesh.load(mesh_path, force="mesh")
    try:
        return _render_open3d(mesh, out_dir), "open3d"
    except Exception as e:
        log.warning("Open3D renderer unavailable (%s); falling back to matplotlib", e)
    try:
        return _render_matplotlib(mesh, out_dir), "matplotlib_fallback"
    except Exception as e:
        raise RenderingError(f"All renderers failed: {e}") from e


class RenderingError(Exception):
    pass
