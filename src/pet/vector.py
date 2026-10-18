"""Tiny anti-aliased vector canvas built on numpy signed-distance fields.

Every primitive rasterises an analytic coverage mask, but only inside its own
bounding box (float32), which keeps the cost proportional to the shape rather
than the canvas. That matters here because the character is assembled from
several hundred primitives per frame.
"""
from __future__ import annotations

import numpy as np

SS = 4  # supersample factor for the whole sprite


class Canvas:
    """RGBA canvas in "design units"; internally rendered at SSx resolution."""

    def __init__(self, width: float, height: float, ss: int = SS):
        self.w = float(width)
        self.h = float(height)
        self.ss = int(ss)
        self.pw = int(round(self.w * self.ss))
        self.ph = int(round(self.h * self.ss))
        self.rgba = np.zeros((self.ph, self.pw, 4), dtype=np.float32)

    # ------------------------------------------------------------------ helpers
    def _bbox(self, x0, y0, x1, y1, pad=1.0):
        """Design-unit bbox -> integer pixel slice, clamped to the canvas."""
        ss = self.ss
        ix0 = max(0, int(np.floor((min(x0, x1) - pad) * ss)))
        iy0 = max(0, int(np.floor((min(y0, y1) - pad) * ss)))
        ix1 = min(self.pw, int(np.ceil((max(x0, x1) + pad) * ss)))
        iy1 = min(self.ph, int(np.ceil((max(y0, y1) + pad) * ss)))
        if ix1 <= ix0 or iy1 <= iy0:
            return None
        return ix0, iy0, ix1, iy1

    def _grid(self, box):
        ss = self.ss
        ix0, iy0, ix1, iy1 = box
        xs = ((np.arange(ix0, ix1, dtype=np.float32) + 0.5) / ss).reshape(1, -1)
        ys = ((np.arange(iy0, iy1, dtype=np.float32) + 0.5) / ss).reshape(-1, 1)
        return xs, ys

    def _paint(self, box, cov: np.ndarray, color, alpha: float = 1.0) -> None:
        if cov is None:
            return
        np.clip(cov, 0.0, 1.0, out=cov)
        if alpha != 1.0:
            cov *= float(alpha)
        if cov.max() <= 0.0015:
            return
        ix0, iy0, ix1, iy1 = box
        col = np.asarray(color, dtype=np.float32)
        a = cov * (col[3] / 255.0)
        src = col[:3] / 255.0
        dst = self.rgba[iy0:iy1, ix0:ix1]
        dst_a = dst[..., 3]
        out_a = a + dst_a * (1.0 - a)
        np.maximum(out_a, 1e-6, out=out_a)
        for ch in range(3):
            dst[..., ch] = (src[ch] * a + dst[..., ch] * dst_a * (1.0 - a)) / out_a
        dst[..., 3] = out_a

    def _feather(self, soft: float = 0.0) -> float:
        return (1.15 if soft <= 0 else float(soft)) / self.ss

    @staticmethod
    def _cov(d: np.ndarray, feather: float) -> np.ndarray:
        return 0.5 - d / max(feather, 1e-6)

    # ------------------------------------------------------------------ shapes
    def ellipse(self, cx, cy, rx, ry, color, soft=0.0, alpha=1.0, rot=0.0):
        pad = self._feather(soft) * 2.0 + 0.5
        rr = max(rx, ry) + 2.0
        box = self._bbox(cx - rr, cy - rr, cx + rr, cy + rr, pad)
        if box is None:
            return self
        X, Y = self._grid(box)
        dx = X - cx
        dy = Y - cy
        if rot:
            c, s = np.cos(-rot), np.sin(-rot)
            dx, dy = dx * c - dy * s, dx * s + dy * c
        k = np.float32(max(rx, 1e-6) / max(ry, 1e-6))
        d = (np.sqrt((dx * k) ** 2 + dy**2) - rx) / max(k, 1e-6)
        self._paint(box, self._cov(d, self._feather(soft)), color, alpha)
        return self

    def circle(self, cx, cy, r, color, soft=0.0, alpha=1.0):
        return self.ellipse(cx, cy, r, r, color, soft, alpha)

    def capsule(self, p0, p1, r0, color, r1=None, soft=0.0, alpha=1.0):
        r1 = r0 if r1 is None else r1
        ax, ay = float(p0[0]), float(p0[1])
        bx, by = float(p1[0]), float(p1[1])
        rmax = max(r0, r1)
        pad = self._feather(soft) * 2.0 + 0.5
        box = self._bbox(min(ax, bx) - rmax, min(ay, by) - rmax,
                         max(ax, bx) + rmax, max(ay, by) + rmax, pad)
        if box is None:
            return self
        X, Y = self._grid(box)
        px = X - ax
        py = Y - ay
        bax, bay = bx - ax, by - ay
        L2 = bax * bax + bay * bay
        t = np.clip((px * bax + py * bay) / max(L2, 1e-9), 0.0, 1.0)
        cx = ax + bax * t
        cy = ay + bay * t
        r = r0 + (r1 - r0) * t
        d = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2) - r
        self._paint(box, self._cov(d, self._feather(soft)), color, alpha)
        return self

    def polygon(self, pts, color, soft=0.0, alpha=1.0):
        pts = np.asarray(pts, dtype=np.float64)
        pad = self._feather(soft) * 2.0 + 0.5
        box = self._bbox(pts[:, 0].min(), pts[:, 1].min(),
                         pts[:, 0].max(), pts[:, 1].max(), pad)
        if box is None:
            return self
        X, Y = self._grid(box)
        X = np.broadcast_to(X, (Y.shape[0], X.shape[1]))
        Y = np.broadcast_to(Y, X.shape)
        n = len(pts)
        dist = np.full(X.shape, np.inf, dtype=np.float32)
        inside = np.zeros(X.shape, dtype=bool)
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            ex, ey = bx - ax, by - ay
            wx = X - ax
            wy = Y - ay
            L2 = ex * ex + ey * ey
            t = np.clip((wx * ex + wy * ey) / max(L2, 1e-9), 0.0, 1.0).astype(np.float32)
            dx = wx - ex * t
            dy = wy - ey * t
            np.minimum(dist, np.sqrt(dx * dx + dy * dy), out=dist)
            cond = (ay > Y) != (by > Y)
            if cond.any():
                denom = ey if abs(ey) > 1e-9 else 1e-9
                xin = ax + (Y - ay) / denom * ex
                inside ^= cond & (X < xin)
        d = np.where(inside, -dist, dist).astype(np.float32)
        self._paint(box, self._cov(d, self._feather(soft)), color, alpha)
        return self

    @staticmethod
    def star_points(cx, cy, r, inner=0.42, points=4, rot=0.0):
        pts = []
        for i in range(points * 2):
            ang = rot + i * np.pi / points
            rad = r if i % 2 == 0 else r * inner
            pts.append((cx + np.cos(ang) * rad, cy + np.sin(ang) * rad))
        return pts

    def star(self, cx, cy, r, color, inner=0.42, points=4, rot=0.0, soft=0.0, alpha=1.0):
        pts = self.star_points(cx, cy, r, inner=inner, points=points, rot=rot)
        return self.polygon(pts, color, soft, alpha)

    def crescent(self, cx, cy, r, color, bite=0.55, bite_dy=-0.42, bite_dx=0.30,
                 soft=0.0, alpha=1.0):
        """Moon crescent: a disc with an offset disc subtracted."""
        bx = cx + r * bite_dx
        by = cy + r * bite_dy
        rb = r * bite
        pad = self._feather(soft) * 2.0 + 0.5
        box = self._bbox(min(cx - r, bx - rb), min(cy - r, by - rb),
                         max(cx + r, bx + rb), max(cy + r, by + rb), pad)
        if box is None:
            return self
        X, Y = self._grid(box)
        d = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2) - r
        d2 = np.sqrt((X - bx) ** 2 + (Y - by) ** 2) - rb
        d = np.maximum(d, -d2)
        self._paint(box, self._cov(d, self._feather(soft)), color, alpha)
        return self

    def blend(self, other: "Canvas", alpha=1.0):
        src = other.rgba
        a = src[..., 3] * float(alpha)
        if a.max() <= 0.0015:
            return self
        dst = self.rgba
        dst_a = dst[..., 3]
        out_a = a + dst_a * (1.0 - a)
        np.maximum(out_a, 1e-6, out_a)
        for ch in range(3):
            dst[..., ch] = (src[..., ch] * a + dst[..., ch] * dst_a * (1.0 - a)) / out_a
        dst[..., 3] = out_a
        return self

    # ------------------------------------------------------------------ output
    def to_pil(self):
        from PIL import Image

        arr = np.clip(self.rgba, 0.0, 1.0)
        rgb = (arr[..., :3] * 255.0 + 0.5).astype(np.uint8)
        a = (arr[..., 3] * 255.0 + 0.5).astype(np.uint8)
        img = Image.fromarray(np.dstack([rgb, a]), mode="RGBA")
        return img.resize((int(round(self.w)), int(round(self.h))), Image.LANCZOS)
