"""
Water colour from Sentinel-2: hue angle and the Forel-Ule scale.

The Forel-Ule (FU) scale is the 21 coloured vials limnologists have held up
against lakes since the 1890s: FU 1 is deep indigo, FU 21 is cola brown.
Van der Woerd & Wernand (2015, 2018) showed how to get the same number from a
satellite: weight the visible bands into CIE X, Y, Z, take the hue angle of
the colour around the white point, correct it for the sensor's coarse bands,
and look the angle up on the FU scale.

Coefficients for Sentinel-2 MSI (bands 443, 490, 560, 665, 705 nm), the
polynomial corrections for S2A and S2B, and the FU transition angles are the
ones used in ESA's SNAP toolbox (opttbx-fu-operator, FuAlgo.java and
Instrument.java) and in ACOLITE (VanderWoerd/hue_angle.txt), which agree.
"""
from __future__ import annotations

import math

X = (11.756, 6.423, 53.696, 32.028, 0.529)
Y = (1.744, 22.289, 65.702, 16.808, 0.192)
Z = (62.696, 31.101, 1.778, 0.015, 0.000)
POLY = {
    "S2A": (-68.76, 495.18, -1315.60, 1547.60, -748.36, 113.25),
    "S2B": (-70.78, 510.49, -1360.3, 1608.6, -785.63, 121.34),
}
POLY["S2C"] = POLY["S2B"]          # as in ACOLITE: S2C uses the S2B correction
HUE_MIN, HUE_MAX = 45.0, 234.0
FU_TRANSITIONS = (232.0, 227.168, 220.977, 209.994, 190.779, 163.084, 132.999,
                  109.054, 94.037, 83.346, 74.572, 67.957, 62.186, 56.435,
                  50.665, 45.129, 39.769, 34.906, 30.439, 26.337, 22.741, 19.0, 19.0)


def chromaticity(r443, r490, r560, r665, r705):
    bands = (r443, r490, r560, r665, r705)
    x3 = sum(b * c for b, c in zip(bands, X))
    y3 = sum(b * c for b, c in zip(bands, Y))
    z3 = sum(b * c for b, c in zip(bands, Z))
    d = x3 + y3 + z3
    if not d or d <= 0:
        return None
    return x3 / d, y3 / d, y3


def hue_angle(r443, r490, r560, r665, r705, sat: str = "S2A"):
    """Corrected hue angle in degrees (higher = bluer), or None."""
    c = chromaticity(r443, r490, r560, r665, r705)
    if c is None:
        return None
    x, y, _ = c
    h = math.degrees(math.atan2(y - 1 / 3, x - 1 / 3)) % 360
    if h < HUE_MIN or h > HUE_MAX:
        return None
    a = h / 100
    p = POLY.get(sat[:3].upper(), POLY["S2A"])
    corr = p[0] * a**5 + p[1] * a**4 + p[2] * a**3 + p[3] * a**2 + p[4] * a + p[5]
    return h + corr


def forel_ule(alpha):
    if alpha is None or alpha != alpha:
        return None
    for i, t in enumerate(FU_TRANSITIONS):
        if alpha > t:
            return max(i, 1)
    return 21


def swatch(r443, r490, r560, r665, r705) -> str | None:
    """An sRGB hex colour for the water's chromaticity, at a fixed brightness."""
    c = chromaticity(r443, r490, r560, r665, r705)
    if c is None:
        return None
    x, y, _ = c
    if y <= 0:
        return None
    Yl = 0.35
    Xc, Zc = x * Yl / y, (1 - x - y) * Yl / y
    rgb = (3.2406 * Xc - 1.5372 * Yl - 0.4986 * Zc,
           -0.9689 * Xc + 1.8758 * Yl + 0.0415 * Zc,
           0.0557 * Xc - 0.2040 * Yl + 1.0570 * Zc)
    m = max(rgb)
    if m > 1:
        rgb = tuple(v / m for v in rgb)

    def g(v):
        v = min(max(v, 0.0), 1.0)
        return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return "#" + "".join(f"{round(g(v) * 255):02x}" for v in rgb)


def reading(med: dict, sat: str = "2A") -> dict:
    """Hue angle, FU, swatch and NDCI from median band reflectances (B01..B05).

    Very clear water can sit a hair below zero in the red and red-edge bands after
    atmospheric correction; those are clipped to a tiny positive value rather than
    throwing the scene away. Blue and green must be clearly positive."""
    out = {"hue": None, "fu": None, "swatch": None, "ndci": None}
    b1, b2, b3, b4, b5 = (med.get(k) for k in ("B01", "B02", "B03", "B04", "B05"))
    vals = (b1, b2, b3, b4, b5)
    if any(v is None or v != v for v in vals):
        return out
    # Over small, dark lakes in deep terrain the standard atmospheric correction
    # (Sen2Cor) can drive the blue and green bands to zero or below. There's no
    # colour left to read then, so the scene is skipped rather than guessed at.
    # (Subtracting the SWIR band as an offset was tried and made summer-to-summer
    # readings noisier on every lake with good data, so it isn't done.)
    if b2 <= 0.001 or b3 <= 0.001:
        return out
    eps = 1e-4
    b1, b4, b5 = max(b1, eps), max(b4, eps), max(b5, eps)
    s = "S2" + str(sat)[-1:].upper()
    a = hue_angle(b1, b2, b3, b4, b5, s)
    out["hue"] = round(a, 2) if a is not None else None
    out["fu"] = forel_ule(a)
    out["swatch"] = swatch(b1, b2, b3, b4, b5)
    # NDCI needs some red and red-edge light to work with; in the clearest lakes
    # both are essentially zero and the index is just noise, so it's left blank.
    out["ndci"] = round((b5 - b4) / (b5 + b4), 4) if (b4 + b5) > 0.002 else None
    return out


if __name__ == "__main__":
    # sanity: clear blue, green and brown water
    for name, r in {"clear blue": (0.020, 0.018, 0.010, 0.002, 0.001),
                    "green": (0.010, 0.012, 0.020, 0.008, 0.010),
                    "brown": (0.004, 0.006, 0.015, 0.018, 0.020)}.items():
        a = hue_angle(*r)
        print(f"{name:10s} hue {a and round(a, 1)}  FU {forel_ule(a)}  {swatch(*r)}")
