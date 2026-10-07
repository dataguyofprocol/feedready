import os
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

ASSETS = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.expanduser("~/Library/Fonts")
CARDS = [
    ("B, but darker", "edits toward B, shows you v1"),
    ("warmer", "next version, only warmer"),
    ("too much", "pulls the last move back"),
    ("back to v2", "picks up from the saved v2"),
    ("show me all versions", "every version on one board"),
    ("ship it", "full-res JPEG, no GPS"),
]
W, CW, CH, GX, GY = 880, 280, 112, 20, 20


class Face:
    def __init__(self, name):
        path = os.path.join(FONTS, name)
        blob = hb.Blob.from_file_path(path)
        self.hb = hb.Font(hb.Face(blob))
        self.tt = TTFont(path)
        self.glyphs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        self.upem = self.tt["head"].unitsPerEm

    def shape(self, s, size, tracking=0.0):
        buf = hb.Buffer()
        buf.add_str(s)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": True})
        k = size / self.upem
        out, x = [], 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], x + pos.x_offset * k))
            x += pos.x_advance * k + tracking
        return out, x - tracking

    def path(self, s, size, x0, y0, tracking=0.0, anchor="start"):
        glyphs, width = self.shape(s, size, tracking)
        if anchor == "middle":
            x0 -= width / 2
        elif anchor == "end":
            x0 -= width
        k = size / self.upem
        pen = SVGPathPen(self.glyphs, ntos=r)
        for name, gx in glyphs:
            self.glyphs[name].draw(TransformPen(pen, (k, 0, 0, -k, x0 + gx, y0)))
        return pen.getCommands(), width


def r(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


REG = Face("Geist-Regular.ttf")
MED = Face("Geist-Medium.ttf")


def main():
    h = 2 * CH + GY
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}">',
        "<style>.card{fill:#F6EFE6}.reply{fill:#4A443F}.you{fill:#F2643C}.youtxt{fill:#fff}.who{fill:#9A918A}.arrow{stroke:#C9BFB5}"
        "@media (prefers-color-scheme: dark){.card{fill:#24211F}.reply{fill:#D3CBC3}.who{fill:#8A827B}.arrow{stroke:#4A4541}}</style>",
    ]
    for i, (you, reply) in enumerate(CARDS):
        x, y = (i % 3) * (CW + GX), (i // 3) * (CH + GY)
        _, tw = MED.shape(you, 15)
        bw = tw + 32
        bx = x + CW - 20 - bw
        who, _ = MED.path("YOU", 10.5, x + CW - 20, y + 24, tracking=0.8, anchor="end")
        bubble, _ = MED.path(you, 15, bx + bw / 2, y + 53.5, anchor="middle")
        text, _ = REG.path(reply, 15, x + 44, y + 95)
        out += [
            f'<rect class="card" x="{x}" y="{y}" width="{CW}" height="{CH}" rx="18"/>',
            f'<path class="who" d="{who}"/>',
            f'<rect class="you" x="{r(bx)}" y="{y + 32}" width="{r(bw)}" height="32" rx="16"/>',
            f'<path class="youtxt" d="{bubble}"/>',
            f'<path class="arrow" d="M{x + 22} {y + 70}v14q0 6 6 6h8" fill="none" stroke-width="2" stroke-linecap="round"/>',
            f'<path class="reply" d="{text}"/>',
        ]
    out.append("</svg>")
    with open(os.path.join(ASSETS, "art", "talk.svg"), "w") as f:
        f.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
