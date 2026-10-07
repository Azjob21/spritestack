"""
Helpers for stack-oriented 3D workflows:
- Primitive stack generation (cube, pyramid, prism, cylinder)
- Texture PNG mapping onto existing stack layers
- OBJ/MTL export from layered voxel data
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPolygon


def create_primitive_stack(shape: str, width: int, height: int, depth: int) -> list[QImage]:
    """Create a list of ARGB layers representing a primitive volume."""
    shape = (shape or "").lower().strip()
    if shape not in {"cube", "pyramid", "prism", "cylinder"}:
        raise ValueError(f"Unsupported primitive shape: {shape}")

    layers: list[QImage] = []
    margin = max(1, min(width, height) // 8)
    base_color = QColor(240, 240, 240, 255)

    for z in range(depth):
        img = QImage(width, height, QImage.Format_ARGB32)
        img.fill(Qt.transparent)

        p = QPainter(img)
        p.setPen(Qt.NoPen)
        p.setBrush(base_color)

        if shape == "cube":
            p.drawRect(margin, margin, max(1, width - margin * 2), max(1, height - margin * 2))

        elif shape == "pyramid":
            t = 1.0 - (z / max(1, depth - 1))
            scale = max(0.1, t)
            bw = max(1, int((width - margin * 2) * scale))
            bh = max(1, int((height - margin * 2) * scale))
            ox = (width - bw) // 2
            oy = (height - bh) // 2
            p.drawRect(ox, oy, bw, bh)

        elif shape == "prism":
            bw = max(3, width - margin * 2)
            bh = max(3, height - margin * 2)
            ox = (width - bw) // 2
            oy = (height - bh) // 2
            tri = QPolygon([
                QPoint(ox + bw // 2, oy),
                QPoint(ox, oy + bh),
                QPoint(ox + bw, oy + bh),
            ])
            p.drawPolygon(tri)

        elif shape == "cylinder":
            p.drawEllipse(margin, margin, max(1, width - margin * 2), max(1, height - margin * 2))

        p.end()
        layers.append(img)

    return layers


def apply_texture_to_layers(
    layers: list[QImage],
    texture: QImage,
    map_mode: str = "bands",
    tile_x: int = 1,
    tile_y: int = 1,
    offset_x: int = 0,
    offset_y: int = 0,
    strength: int = 100,
) -> list[QImage]:
    """
    Map a PNG texture onto each layer.
    map_mode:
      - "bands": texture split vertically into N bands (N = layers)
      - "full":  full texture repeated on every layer
    """
    if not layers:
        return []
    if texture.isNull():
        raise ValueError("Texture image is invalid.")

    n = len(layers)
    map_mode = (map_mode or "bands").strip().lower()
    if map_mode not in {"bands", "full"}:
        map_mode = "bands"
    tile_x = max(1, int(tile_x))
    tile_y = max(1, int(tile_y))
    strength = max(0, min(100, int(strength)))
    t = strength / 100.0
    out: list[QImage] = []

    for i, layer in enumerate(layers):
        if layer is None or layer.isNull():
            out.append(layer.copy() if layer else QImage())
            continue

        mapped = QImage(layer.width(), layer.height(), QImage.Format_ARGB32)
        mapped.fill(Qt.transparent)

        if map_mode == "bands":
            band_y0 = int(i * texture.height() / n)
            band_y1 = int((i + 1) * texture.height() / n)
            src_tex = texture.copy(0, band_y0, texture.width(), max(1, band_y1 - band_y0))
        else:
            src_tex = texture

        for y in range(layer.height()):
            for x in range(layer.width()):
                src = layer.pixelColor(x, y)
                if src.alpha() <= 0:
                    continue

                # Repeat and offset texture sampling.
                u = ((x + offset_x) / max(1, layer.width())) * tile_x
                v = ((y + offset_y) / max(1, layer.height())) * tile_y
                tx = int(u * src_tex.width()) % max(1, src_tex.width())
                ty = int(v * src_tex.height()) % max(1, src_tex.height())
                tex = src_tex.pixelColor(tx, ty)

                # Strength = 100 -> full texture, 0 -> keep original layer colour.
                r = int(src.red() * (1.0 - t) + tex.red() * t)
                g = int(src.green() * (1.0 - t) + tex.green() * t)
                b = int(src.blue() * (1.0 - t) + tex.blue() * t)
                mapped.setPixelColor(x, y, QColor(r, g, b, src.alpha()))

        out.append(mapped)

    return out


def export_stack_to_obj_mtl(
    layers: list[QImage],
    obj_path: str,
    alpha_threshold: int = 10,
    voxel_size: float = 1.0,
    layer_height: float = 1.0,
) -> tuple[str, str, str]:
    """
    Export visible voxels from layered images as OBJ/MTL + texture atlas PNG.
    Returns (obj_path, mtl_path, texture_path).
    """
    if not layers:
        raise ValueError("No layers to export.")

    first = next((l for l in layers if l and not l.isNull()), None)
    if first is None:
        raise ValueError("No valid layers to export.")

    w, h = first.width(), first.height()
    depth = len(layers)

    base = os.path.splitext(obj_path)[0]
    basename = os.path.basename(base)
    mtl_path = base + ".mtl"
    tex_path = base + "_albedo.png"
    mtl_name = os.path.basename(mtl_path)
    tex_name = os.path.basename(tex_path)

    # Build atlas (stacked vertically by layer index).
    atlas_h = h * depth
    atlas = QImage(w, atlas_h, QImage.Format_ARGB32)
    atlas.fill(Qt.transparent)
    ap = QPainter(atlas)
    for z, layer in enumerate(layers):
        if layer and not layer.isNull():
            ap.drawImage(0, z * h, layer)
    ap.end()
    if not atlas.save(tex_path, "PNG"):
        raise RuntimeError(f"Failed to save texture atlas: {tex_path}")

    voxels = set()
    uv_by_voxel = {}
    for z, layer in enumerate(layers):
        if layer is None or layer.isNull():
            continue
        for y in range(h):
            for x in range(w):
                c = layer.pixelColor(x, y)
                if c.alpha() >= alpha_threshold:
                    voxels.add((x, y, z))
                    u = (x + 0.5) / w
                    v = 1.0 - ((z * h + y + 0.5) / atlas_h)
                    uv_by_voxel[(x, y, z)] = (u, v)

    if not voxels:
        raise ValueError("No opaque voxels found in current stack.")

    def has_voxel(x, y, z):
        return (x, y, z) in voxels

    v_lines = []
    vt_lines = []
    f_lines = []
    vt_index_by_voxel = {}
    v_index = 1
    vt_index = 1

    for v in sorted(voxels):
        uv = uv_by_voxel[v]
        vt_index_by_voxel[v] = vt_index
        vt_lines.append(f"vt {uv[0]:.8f} {uv[1]:.8f}")
        vt_index += 1

    def add_face(verts, tex_idx):
        nonlocal v_index
        for vx, vy, vz in verts:
            v_lines.append(f"v {vx:.6f} {vy:.6f} {vz:.6f}")
        f_lines.append(
            f"f {v_index}/{tex_idx} {v_index + 1}/{tex_idx} {v_index + 2}/{tex_idx} {v_index + 3}/{tex_idx}"
        )
        v_index += 4

    for x, y, z in sorted(voxels):
        x0 = x * voxel_size
        x1 = (x + 1) * voxel_size
        y0 = (h - y - 1) * voxel_size
        y1 = (h - y) * voxel_size
        z0 = z * layer_height
        z1 = (z + 1) * layer_height

        tidx = vt_index_by_voxel[(x, y, z)]

        if not has_voxel(x, y, z + 1):  # front (+Z)
            add_face([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], tidx)
        if not has_voxel(x, y, z - 1):  # back (-Z)
            add_face([(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)], tidx)
        if not has_voxel(x + 1, y, z):  # right (+X)
            add_face([(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)], tidx)
        if not has_voxel(x - 1, y, z):  # left (-X)
            add_face([(x0, y0, z1), (x0, y0, z0), (x0, y1, z0), (x0, y1, z1)], tidx)
        if not has_voxel(x, y - 1, z):  # top (+Y in image-space)
            add_face([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], tidx)
        if not has_voxel(x, y + 1, z):  # bottom (-Y in image-space)
            add_face([(x0, y0, z1), (x1, y0, z1), (x1, y0, z0), (x0, y0, z0)], tidx)

    with open(mtl_path, "w", encoding="utf-8", newline="\n") as mf:
        mf.write("newmtl stack_material\n")
        mf.write("Ka 1.000 1.000 1.000\n")
        mf.write("Kd 1.000 1.000 1.000\n")
        mf.write("Ks 0.000 0.000 0.000\n")
        mf.write("d 1.000\n")
        mf.write("illum 1\n")
        mf.write(f"map_Kd {tex_name}\n")

    with open(obj_path, "w", encoding="utf-8", newline="\n") as of:
        of.write(f"# Generated by SpriteStack Studio\n")
        of.write(f"mtllib {mtl_name}\n")
        of.write(f"o {basename}\n")
        for line in v_lines:
            of.write(line + "\n")
        for line in vt_lines:
            of.write(line + "\n")
        of.write("usemtl stack_material\n")
        for line in f_lines:
            of.write(line + "\n")

    return obj_path, mtl_path, tex_path
