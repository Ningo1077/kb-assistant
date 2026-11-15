# -*- coding: utf-8 -*-
"""生成 Tauri 应用图标（纯 stdlib，无 Pillow）。产出 32x32.png / 128x128.png / icon.ico"""
import struct, zlib, os

def png_chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

def write_png(path, size, pixels):
    # pixels: list of rows, each row list of (r,g,b,a)
    raw = b"".join(b"\x00" + b"".join(struct.pack("BBBB", *px) for px in row) for row in pixels)
    data = b"\x89PNG\r\n\x1a\n"
    data += png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    data += png_chunk(b"IDAT", zlib.compress(raw, 9))
    data += png_chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(data)

def render(size):
    s = size
    px = [[(0, 0, 0, 0) for _ in range(s)] for _ in range(s)]
    r_in = s * 0.20  # 圆角半径
    for y in range(s):
        for x in range(s):
            # 圆角矩形范围
            cx = min(x, s - 1 - x); cy = min(y, s - 1 - y)
            if cx < r_in and cy < r_in and (cx - r_in) ** 2 + (cy - r_in) ** 2 > r_in ** 2:
                continue
            # 深蓝 -> 亮蓝 对角渐变
            t = (x + y) / (2 * s)
            r = int(41 + (66 - 41) * t)
            g = int(98 + (133 - 98) * t)
            b = int(255 + (244 - 255) * t)
            # 白色对话气泡（上 62% 区域圆角矩形 + 左下尾巴）
            bx0, bx1 = s * 0.18, s * 0.82
            by0, by1 = s * 0.20, s * 0.60
            br = s * 0.08
            in_bubble = False
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                dx = min(x - bx0, bx1 - x); dy = min(y - by0, by1 - y)
                if dx >= br or dy >= br or (dx - br) ** 2 + (dy - br) ** 2 <= br ** 2:
                    in_bubble = True
            # 尾巴：气泡左下角向下的三角形
            if by1 <= y <= s * 0.74:
                width = (s * 0.74 - y) / (s * 0.14) * s * 0.14 + s * 0.05
                if bx0 + s * 0.02 <= x <= bx0 + s * 0.02 + width:
                    in_bubble = True
            # 三个点
            if not in_bubble and by0 <= y <= by1:
                pcy = (by0 + by1) / 2
                for i, px_x in enumerate((0.34, 0.50, 0.66)):
                    pr = s * 0.045
                    cxp = s * px_x
                    if (x - cxp) ** 2 + (y - pcy) ** 2 <= pr ** 2:
                        r, g, b = 255, 255, 255
                        in_bubble = True
                        break
            if in_bubble:
                px[y][x] = (255, 255, 255, 255)
            else:
                px[y][x] = (r, g, b, 255)
    return px

out = os.path.dirname(os.path.abspath(__file__))
for size, name in ((32, "32x32.png"), (128, "128x128.png"), (256, "128x128@2x.png"), (256, "icon.png")):
    write_png(os.path.join(out, name), size, render(size))

# icon.ico：打包 256px PNG 条目（Vista+ 支持 PNG 编码的 ICO）
png = open(os.path.join(out, "icon.png"), "rb").read()
ico = struct.pack("<HHH", 0, 1, 1)
ico += struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
ico += png
open(os.path.join(out, "icon.ico"), "wb").write(ico)
print("icons generated in", out)
