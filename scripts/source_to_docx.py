#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成《源代码文档》（.docx）——把项目源码逐字收录，每页最多 50 行代码。

特点：
  * 连续流式分页：除最后一页外每页恰好 50 行代码，不浪费版面；
  * 每行带 4 位文件内行号；文件边界用「▸ 路径 第 a–b 行」标注；
  * 统一封面、编制说明、按模块的文件目录、页眉页脚页码；
  * 逐字保真：不改写代码，仅把制表符按 4 空格展示，超长行由 Word 自动折行；
  * `--check` 回读 docx，逐行比对源码并统计每一页的实际代码行数。

用法（仓库根目录）：
    backend/.venv/Scripts/python.exe scripts/source_to_docx.py
    backend/.venv/Scripts/python.exe scripts/source_to_docx.py --check

依赖：python-docx（已在 backend/.venv 中）；无网络、无外部服务依赖。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from md_to_docx import (
    ACCENT, BLUE, BORDER, DARK, FILL_CODE, FILL_HEAD, FILL_QUOTE, FONT_BODY,
    FONT_CODE, FONT_HEAD, MUTED, NAVY, add_field, mark_header_row,
    set_cell_border, set_cell_margins, set_paragraph_border, set_run_font,
    set_shading,
)

LINES_PER_PAGE = 50
CODE_SIZE = 7.5
LINE_PT = 9
OUT_NAME = "07-源代码文档.docx"

# 按模块组织，顺序即正文顺序。只收录手写源码 / 配置 / 脚本。
GROUPS: list[tuple[str, list[str]]] = [
    ("一、后端服务 · Python / FastAPI", [
        "backend/app/main.py",
        "backend/app/db.py",
        "backend/app/models.py",
        "backend/app/schemas.py",
        "backend/app/core/config.py",
        "backend/app/core/security.py",
        "backend/app/api/deps.py",
        "backend/app/api/auth.py",
        "backend/app/api/kb.py",
        "backend/app/api/documents.py",
        "backend/app/api/chat.py",
        "backend/app/services/text.py",
        "backend/app/services/embeddings.py",
        "backend/app/services/ingest.py",
        "backend/app/services/retrieval.py",
        "backend/app/services/llm.py",
        "backend/requirements.txt",
        "backend/.env.example",
    ]),
    ("二、后端脚本与自动化测试", [
        "backend/scripts/make_seed_db.py",
        "backend/scripts/reindex_all.py",
        "backend/scripts/prepare-backend.bat",
        "backend/scripts/smoke_test.py",
        "backend/tests/test_all.py",
    ]),
    ("三、前端 · React / TypeScript", [
        "frontend/index.html",
        "frontend/package.json",
        "frontend/tsconfig.json",
        "frontend/vite.config.ts",
        "frontend/src/main.tsx",
        "frontend/src/App.tsx",
        "frontend/src/vite-env.d.ts",
        "frontend/src/api.ts",
        "frontend/src/types.ts",
        "frontend/src/pages/Login.tsx",
        "frontend/src/pages/Workspace.tsx",
        "frontend/src/components/DocPanel.tsx",
        "frontend/src/components/ChatPanel.tsx",
        "frontend/src/index.css",
    ]),
    ("四、桌面端 · Rust / Tauri / 安装包脚本", [
        "src-tauri/Cargo.toml",
        "src-tauri/build.rs",
        "src-tauri/src/main.rs",
        "src-tauri/tauri.conf.json",
        "src-tauri/capabilities/default.json",
        "src-tauri/windows/hooks.nsh",
        "src-tauri/windows/uninstall-cleanup.ps1",
        "src-tauri/nsis/setup.nsi",
        "src-tauri/nsis/build-setup.cmd",
        "src-tauri/gen_icon.py",
    ]),
    ("五、工程配置、CI 与工具脚本", [
        ".github/workflows/ci.yml",
        ".gitignore",
        "demo-files/gen_demo_files.py",
        "scripts/md_to_docx.py",
        "scripts/source_to_docx.py",
    ]),
]

EXCLUDED = [
    "frontend/package-lock.json（npm 自动生成，2070 行依赖锁定 JSON，仓库中保留）",
    "src-tauri/gen/schemas/*.json（Tauri 自动生成的 ACL / 平台 schema）",
    "backend/data/**（运行时数据库、上传文档与用户数据）",
    "docs/**、README.md、backend/README.md、LICENSE（文档与许可已单独交付）",
    "demo-files/ 下的 PDF / DOCX / CSV / TXT / MD（虚构演示数据，非源码）",
    "frontend/dist/、frontend/node_modules/、backend/.venv/、src-tauri/target/（构建与依赖产物）",
]


def load_records(root: Path):
    """返回 (逐行记录, 文件清单)。记录 = (模块, 相对路径, 文件内行号, 代码文本)。"""
    records, manifest = [], []
    for group, paths in GROUPS:
        for rel in paths:
            p = root / rel
            if not p.exists():
                print(f"  WARN missing source: {rel}")
                continue
            lines = p.read_text(encoding="utf-8-sig").splitlines()
            manifest.append({
                "group": group,
                "path": rel,
                "lines": len(lines),
                "max_len": max((len(x) for x in lines), default=0),
            })
            for i, line in enumerate(lines, 1):
                # 制表符按 4 空格展示（唯一的内容变换，已在编制说明中声明）
                records.append((group, rel, i, line.replace("\t", "    ")))
    return records, manifest


def build_pages(records, per_page=LINES_PER_PAGE):
    """连续流式分页：每页 <= per_page 行。

    若最后一页只剩极少行（<= 9 行），把全部页均衡成 per_page-1 / per_page 行，
    避免出现「一整页只有两三行代码」的空页，同时仍严格不超过上限。
    """
    total = len(records)
    if total == 0:
        return []
    full, rem = divmod(total, per_page)
    if rem == 0:
        sizes = [per_page] * full
    elif rem <= 9 and full >= 1:
        count = full + 1
        base, extra = divmod(total, count)
        sizes = [base + (1 if i < extra else 0) for i in range(count)]
    else:
        sizes = [per_page] * full + [rem]
    pages, pos = [], 0
    for size in sizes:
        pages.append(records[pos:pos + size])
        pos += size
    return pages


def split_segments(block):
    """把一个代码页按连续的文件边界切段（生成与校验共用）。"""
    segments: list[tuple[tuple[str, str], list]] = []
    for rec in block:
        key = (rec[0], rec[1])
        if segments and segments[-1][0] == key:
            segments[-1][1].append(rec)
        else:
            segments.append((key, [rec]))
    return segments


def make_style(doc, name, size, font, color, bold=False, line_pt=None, ea=None):
    st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    st.font.name = font
    st.font.size = Pt(size)
    st.font.bold = bold
    st.font.color.rgb = color
    rPr = st.element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        from docx.oxml import OxmlElement
        rf = OxmlElement("w:rFonts")
        rPr.insert(0, rf)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rf.set(qn(attr), font)
    rf.set(qn("w:eastAsia"), ea or font)
    pf = st.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.widow_control = False
    if line_pt:
        pf.line_spacing = Pt(line_pt)  # 固定行距，保证 50 行稳定落在一页
    return st


def setup(doc):
    normal = doc.styles["Normal"]
    normal.font.name = FONT_BODY
    normal.font.size = Pt(10)
    normal.font.color.rgb = DARK
    rPr = normal.element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        from docx.oxml import OxmlElement
        rf = OxmlElement("w:rFonts")
        rPr.insert(0, rf)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rf.set(qn(attr), FONT_BODY)
    rf.set(qn("w:eastAsia"), FONT_BODY)
    normal.paragraph_format.line_spacing = 1.3
    normal.paragraph_format.space_after = Pt(5)

    for lvl, size in ((1, 15), (2, 12)):
        st = doc.styles[f"Heading {lvl}"]
        st.font.name = FONT_HEAD
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = NAVY
        st.paragraph_format.space_before = Pt(10)
        st.paragraph_format.space_after = Pt(5)
        srPr = st.element.get_or_add_rPr()
        srf = srPr.find(qn("w:rFonts"))
        if srf is None:
            from docx.oxml import OxmlElement
            srf = OxmlElement("w:rFonts")
            srPr.insert(0, srf)
        srf.set(qn("w:eastAsia"), FONT_HEAD)

    make_style(doc, "SrcPageTitle", 8.5, FONT_HEAD, NAVY, bold=True, line_pt=12)
    make_style(doc, "SrcFileLabel", 7.2, FONT_HEAD, BLUE, bold=True, line_pt=10)
    make_style(doc, "CodeBlock", CODE_SIZE, FONT_CODE, RGBColor(0x1F, 0x29, 0x37),
               line_pt=LINE_PT, ea=FONT_BODY)

    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(1.7)
    sec.bottom_margin = Cm(1.6)
    sec.left_margin = Cm(1.8)
    sec.right_margin = Cm(1.6)
    sec.header_distance = Cm(0.8)
    sec.footer_distance = Cm(0.8)
    sec.different_first_page_header_footer = True

    hdr = sec.header.paragraphs[0]
    hdr.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = hdr.add_run("kb-assistant · 源代码文档")
    set_run_font(r, size=8, color=MUTED)
    r = hdr.add_run(f"    |    每页最多 {LINES_PER_PAGE} 行代码 · 逐字收录")
    set_run_font(r, size=8, color=MUTED)
    set_paragraph_border(hdr, side="bottom", color=BORDER, size=4, space=4)

    ftr = sec.footer.paragraphs[0]
    ftr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for item in ("第 ", "PAGE", " 页 / 共 ", "NUMPAGES", " 页"):
        if item in ("PAGE", "NUMPAGES"):
            add_field(ftr, item, size=8.5)
        else:
            r = ftr.add_run(item)
            set_run_font(r, size=8.5, color=MUTED)


def add_cover(doc, stats):
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("私有文档知识库问答助手 · kb-assistant")
    set_run_font(r, size=13, color=MUTED, font=FONT_HEAD)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(24)
    r = p.add_run("源 代 码 文 档")
    set_run_font(r, size=32, bold=True, color=NAVY, font=FONT_HEAD)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"逐字收录 · 带行号 · 每页最多 {LINES_PER_PAGE} 行代码")
    set_run_font(r, size=12, color=BLUE, font=FONT_HEAD)
    set_paragraph_border(p, side="bottom", color=ACCENT, size=12, space=12)

    table = doc.add_table(rows=6, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    rows = [
        ("收录文件", f'{stats["files"]} 个（5 个模块）'),
        ("源码总行数", f'{stats["lines"]:,} 行'),
        ("代码页数", f'{stats["pages"]} 页（各页 {stats["min_page_lines"]}–{LINES_PER_PAGE} 行，上限 {LINES_PER_PAGE} 行）'),
        ("最长单行", f'{stats["max_len"]} 字符（不截断，由 Word 自动折行）'),
        ("版本 / 编制日期", f'v1.0.0 / {dt.date.today().isoformat()}'),
        ("生成方式", "scripts/source_to_docx.py（python-docx，本地无网络依赖）"),
    ]
    for i, (k, v) in enumerate(rows):
        for j, txt in enumerate((k, v)):
            cell = table.cell(i, j)
            set_cell_margins(cell, top=70, bottom=70)
            cp = cell.paragraphs[0]
            cp.paragraph_format.space_after = Pt(0)
            rr = cp.add_run(txt)
            set_run_font(rr, size=9.5, bold=(j == 0), color=MUTED if j == 0 else DARK)
    doc.add_page_break()


def add_front_matter(doc, manifest, pages, stats):
    doc.add_heading("一、编制说明", level=1)
    notes = [
        "收录范围：后端 FastAPI 服务、后端脚本与自动化测试、React / TypeScript 前端、Tauri / Rust 桌面端与安装包脚本、CI 与工程配置，共 5 个模块。"
        "每个文件的路径、行数与所在代码页见下一节文件目录。",
        "逐字保真：代码不做任何改写或省略；唯一的展示层变换是把制表符按 4 个空格展开，其余字符、缩进、空行与注释均保持原样。"
        "超长行不截断，由 Word 按页宽自动折行。",
        f"分页规则：正文采用连续流式分页，每页最多 {LINES_PER_PAGE} 行代码（本次各页 {stats['min_page_lines']}–{LINES_PER_PAGE} 行，"
        f"末页 {stats['last_page_lines']} 行）；末页不足 10 行时自动把最后若干页均衡为 49–50 行，避免整页空白。"
        "每页顶部的「〔代码页 X / 共 Y〕」标注代码页编号与全局行范围；文件边界用「▸ 路径 第 a–b 行」单独标出，"
        "因此一页内可能包含多个短文件。",
        "行号：每行前的 4 位数字是该文件内的行号，便于与仓库源码逐行对照；空行同样编号。",
        "页码说明：页脚是 Word 实际页码；页标题与文件目录里的「代码页 X」是正文逻辑页编号（从 001 开始），"
        "两者相差封面、编制说明与文件目录所占页数，按目录查找源码时以「代码页」编号为准。",
        "复现命令：backend/.venv/Scripts/python.exe scripts/source_to_docx.py（重新生成）；"
        "加 --check 回读校验逐行一致性与每页行数。生成日志见 docs/evidence/07-源代码文档生成.log。",
    ]
    for n in notes:
        p = doc.add_paragraph(n)
        p.paragraph_format.space_after = Pt(5)

    doc.add_heading("排除项（非手写源码或另有交付）", level=2)
    for item in EXCLUDED:
        p = doc.add_paragraph(item, style="List Bullet")
        p.paragraph_format.space_after = Pt(2)

    doc.add_heading("二、文件目录", level=1)
    # 文件 -> 代码页范围
    file_pages: dict[str, list[int]] = {}
    for idx, block in enumerate(pages, 1):
        for rec in block:
            file_pages.setdefault(rec[1], []).append(idx)

    for group, _paths in GROUPS:
        doc.add_heading(group, level=2)
        items = [m for m in manifest if m["group"] == group]
        table = doc.add_table(rows=1, cols=3)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        try:
            table.style = "Table Grid"
        except KeyError:
            pass
        for j, txt in enumerate(("文件路径", "行数", "代码页")):
            cell = table.rows[0].cells[j]
            set_shading(cell, FILL_HEAD)
            set_cell_border(cell)
            set_cell_margins(cell)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(txt)
            set_run_font(r, size=8, bold=True, color=NAVY)
        mark_header_row(table.rows[0])
        for m in items:
            cells = table.add_row().cells
            fp = file_pages.get(m["path"], [])
            span = f"第 {min(fp)}–{max(fp)} 页" if fp else "—"
            for j, txt in enumerate((m["path"], str(m["lines"]), span)):
                cell = cells[j]
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                set_cell_border(cell)
                set_cell_margins(cell)
                p = cell.paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                r = p.add_run(txt)
                set_run_font(r, size=7.8, font=FONT_CODE if j == 0 else FONT_BODY,
                             color=DARK)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)


def add_code_pages(doc, pages):
    total = len(pages)
    global_idx = 0
    for idx, block in enumerate(pages, 1):
        start = global_idx + 1
        end = global_idx + len(block)
        global_idx = end
        title = doc.add_paragraph(style="SrcPageTitle")
        title.paragraph_format.page_break_before = True
        r = title.add_run(f"〔代码页 {idx:03d} / 共 {total:03d}〕  ")
        set_run_font(r, size=8.5, bold=True, color=NAVY, font=FONT_HEAD)
        r = title.add_run(f"全局行 {start:05d}–{end:05d}")
        set_run_font(r, size=8.5, color=MUTED, font=FONT_CODE)
        set_paragraph_border(title, side="bottom", color=ACCENT, size=6, space=4)

        for (group, rel), seg in split_segments(block):
            label = doc.add_paragraph(style="SrcFileLabel")
            label.paragraph_format.keep_with_next = True
            r = label.add_run(f"▸ {rel}    第 {seg[0][2]}–{seg[-1][2]} 行")
            set_run_font(r, size=7.2, bold=True, color=BLUE, font=FONT_HEAD)

            cb = doc.add_paragraph(style="CodeBlock")
            set_shading(cb, FILL_CODE)
            set_paragraph_border(cb, side="left", color=BORDER, size=10, space=5)
            for k, (_g, _rel, lineno, text) in enumerate(seg):
                r = cb.add_run(f"{lineno:04d} | {text}")
                set_run_font(r, size=CODE_SIZE, font=FONT_CODE,
                             color=RGBColor(0x1F, 0x29, 0x37))
                if k < len(seg) - 1:
                    r.add_break()


def generate(root: Path, out_dir: Path, per_page: int):
    records, manifest = load_records(root)
    pages = build_pages(records, per_page)
    stats = {
        "files": len(manifest),
        "lines": len(records),
        "pages": len(pages),
        "last_page_lines": len(pages[-1]) if pages else 0,
        "min_page_lines": min((len(b) for b in pages), default=0),
        "max_len": max((len(r[3]) for r in records), default=0),
    }
    doc = Document()
    setup(doc)
    doc.core_properties.title = "源代码文档 · 私有文档知识库问答助手"
    doc.core_properties.subject = f"逐字收录源码，每页最多 {per_page} 行"
    doc.core_properties.author = "Ningo1077"
    doc.core_properties.comments = "由 scripts/source_to_docx.py 生成，代码未改写"
    add_cover(doc, stats)
    add_front_matter(doc, manifest, pages, stats)
    add_code_pages(doc, pages)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUT_NAME
    doc.save(out_path)
    print(f"[source_to_docx] files={stats['files']} lines={stats['lines']} "
          f"code_pages={stats['pages']} lines_per_page={per_page} "
          f"last_page={stats['last_page_lines']} max_line={stats['max_len']}")
    print(f"[source_to_docx] output={out_path.relative_to(root).as_posix()} "
          f"bytes={out_path.stat().st_size}")
    return stats


def check(root: Path, out_dir: Path, per_page: int) -> bool:
    from docx import Document as _Doc
    path = out_dir / OUT_NAME
    if not path.exists():
        print("CHECK_RESULT=FAIL (missing docx)")
        return False
    records, manifest = load_records(root)
    pages = build_pages(records, per_page)
    with zipfile.ZipFile(path) as z:
        zip_ok = z.testzip() is None

    d = _Doc(path)
    page_counts, doc_lines = [], []
    cur = None
    for p in d.paragraphs:
        style = p.style.name
        if style == "SrcPageTitle":
            if cur is not None:
                page_counts.append(cur)
            cur = 0
        elif style == "CodeBlock" and cur is not None:
            cur += len(p._p.findall(".//" + qn("w:br"))) + 1
            for line in p.text.split("\n"):
                m = re.match(r"^\d{4} \| (.*)$", line)
                if m:
                    doc_lines.append(m.group(1))
    if cur is not None:
        page_counts.append(cur)

    src_lines = [r[3] for r in records]
    identical = doc_lines == src_lines
    expected_counts = [len(b) for b in pages]
    counts_ok = page_counts == expected_counts and all(0 < c <= per_page for c in page_counts)
    print(f"[check] zip={zip_ok} files={len(manifest)} source_lines={len(src_lines)} "
          f"docx_lines={len(doc_lines)} code_pages={len(page_counts)}")
    print(f"[check] page_lines min={min(page_counts, default=0)} "
          f"max={max(page_counts, default=0)} expected_pages={len(pages)} "
          f"matches_plan={page_counts == expected_counts} counts_ok={counts_ok}")
    print(f"[check] byte-for-byte identical={identical}")
    if not identical:
        for i, (a, b) in enumerate(zip(src_lines, doc_lines)):
            if a != b:
                print(f"  first diff at source line {i + 1}: {a[:100]!r} != {b[:100]!r}")
                break

    # 版式估算：确认每个代码页的 50 行 + 文件标签 + 长行折行不会溢出 A4 正文区
    heights = []
    for block in pages:
        h = 12.0  # 代码页标题
        for _key, seg in split_segments(block):
            h += 10.0  # 文件标签
            for rec in seg:
                visual_rows = max(1, -(-(7 + len(rec[3])) // 105))  # 7 = "NNNN | "
                h += visual_rows * LINE_PT
        heights.append(h)
    avail_pt = (29.7 - 1.7 - 1.6) * 28.3465
    height_ok = bool(heights) and max(heights) <= avail_pt
    print(f"[check] estimated max code-page height={max(heights, default=0):.0f}pt / "
          f"available={avail_pt:.0f}pt fit_on_one_page={height_ok}")

    ok = zip_ok and identical and counts_ok and height_ok
    print("CHECK_RESULT=" + ("PASS" if ok else "FAIL"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--out-dir", default="docs/word")
    ap.add_argument("--lines-per-page", type=int, default=LINES_PER_PAGE)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    out_dir = (root / args.out_dir).resolve()
    if args.lines_per_page < 1 or args.lines_per_page > 50:
        print("lines-per-page 必须在 1~50 之间（本交付要求每页 <= 50 行）")
        return 2
    if args.check:
        return 0 if check(root, out_dir, args.lines_per_page) else 1
    generate(root, out_dir, args.lines_per_page)
    return 0 if check(root, out_dir, args.lines_per_page) else 1


if __name__ == "__main__":
    sys.exit(main())
