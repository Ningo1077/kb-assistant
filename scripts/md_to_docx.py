#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown -> Word (.docx) 批量高保真转换脚本（kb-assistant 交付文档专用）。

设计目标：只做「格式转换」，不改写任何一个字的正文内容。
支持：多级标题、表格（表头样式/重复表头）、围栏代码块（含 Mermaid 源码）、
      有序/无序/任务列表、引用块、水平线、行内粗体/斜体/删除线/行内代码/超链接、
      统一封面、静态目录、页眉页脚与页码、中英文混排字体。

用法（仓库根目录）：
    backend/.venv/Scripts/python.exe scripts/md_to_docx.py
    backend/.venv/Scripts/python.exe scripts/md_to_docx.py --check   # 只校验已有产物

依赖：python-docx（已在 backend/.venv 中）；无网络、无外部服务依赖。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# ----------------------------------------------------------------------------
# 全局排版常量
# ----------------------------------------------------------------------------
FONT_BODY = "等线"
FONT_HEAD = "微软雅黑"
FONT_CODE = "Consolas"
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
BLUE = RGBColor(0x2E, 0x5C, 0x8A)
DARK = RGBColor(0x22, 0x2B, 0x35)
MUTED = RGBColor(0x6B, 0x72, 0x80)
CODE_COLOR = RGBColor(0x1F, 0x29, 0x37)
FILL_CODE = "F3F5F7"
FILL_QUOTE = "F5F8FC"
FILL_HEAD = "DCE7F2"
FILL_ALT = "FAFBFC"
BORDER = "C9D4E0"
ACCENT = "2E5C8A"

# 源文件 -> Word 文件名。所有 Word 产物统一放在 docs/word/ 下。
SOURCES: list[tuple[str, str, str]] = [
    ("docs/00-交付物清单与全过程索引.md", "00-交付物清单与全过程索引.docx", "全过程索引"),
    ("docs/01-系统概要与详细设计说明书.md", "01-系统概要与详细设计说明书.docx", "设计说明书"),
    ("docs/02-UI原型设计说明书.md", "02-UI原型设计说明书.docx", "原型设计说明书"),
    ("docs/03-测试报告.md", "03-测试报告.docx", "测试报告"),
    ("docs/04-部署手册.md", "04-部署手册.docx", "部署手册"),
    ("docs/05-使用说明书.md", "05-使用说明书.docx", "使用说明书"),
    ("docs/技术选型与需求分析.md", "技术选型与需求分析.docx", "需求分析（完整版）"),
    ("docs/技术选型与需求分析-精简版.md", "技术选型与需求分析-精简版.docx", "需求分析（精简版）"),
    ("docs/作业要求对照-技术选型与需求分析填写稿.md", "作业要求对照-技术选型与需求分析填写稿.docx", "作业对照填写稿"),
    ("README.md", "README-项目总览.docx", "项目总览 / 入口"),
    ("backend/README.md", "README-后端说明.docx", "后端说明"),
]

# 链接必须最先匹配：链接文字里常含 `行内代码`，否则会先被 code 分支切断，
# 导致 Word 中出现原始的 [`xxx`](url) 语法文本。
INLINE_RE = re.compile(
    r"(?P<link>\[[^\]]+?\]\([^)]+?\))"
    r"|(?P<bold>\*\*[^*]+?\*\*)"
    r"|(?P<code>`[^`]+?`)"
    r"|(?P<strike>~~[^~]+?~~)"
    r"|(?P<italic>\*[^*\n]+?\*)"
)
LINK_RE = re.compile(r"^\[(?P<text>[^\]]+)\]\((?P<url>[^)]+)\)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")
LIST_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>[-*+]|\d+[.)])\s+(?P<text>.*)$")
TASK_RE = re.compile(r"^\[(?P<flag>[ xX])\]\s*(?P<text>.*)$")
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*)$")
HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


# ----------------------------------------------------------------------------
# 低层 OOXML / 排版辅助
# ----------------------------------------------------------------------------
def set_run_font(run, size=None, bold=None, color=None, font=None, italic=None):
    """同时设置 ascii/hAnsi/eastAsia 字体，避免中文回退到默认字体。"""
    ascii_font = font or FONT_BODY
    ea_font = FONT_BODY if font == FONT_CODE else (font or FONT_BODY)
    run.font.name = ascii_font
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rFonts.set(qn(attr), ascii_font)
    rFonts.set(qn("w:eastAsia"), ea_font)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    return run


def set_shading(obj, fill):
    """给段落或单元格加底纹（按 OOXML 元素顺序插入，兼容 Word/WPS 严格解析）。"""
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    if hasattr(obj, "_tc"):
        pr = obj._tc.get_or_add_tcPr()
        pr.insert_element_before(shd, "w:noWrap", "w:tcMar", "w:textDirection",
                                 "w:vAlign", "w:hideMark")
    else:
        pr = obj._p.get_or_add_pPr()
        pr.insert_element_before(shd, "w:tabs", "w:spacing", "w:ind",
                                 "w:jc", "w:rPr", "w:sectPr")
    return shd


def set_paragraph_border(p, side="left", color=ACCENT, size=18, space=8):
    pPr = p._p.get_or_add_pPr()
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        pBdr = OxmlElement("w:pBdr")
        pPr.insert_element_before(pBdr, "w:shd", "w:tabs", "w:spacing",
                                  "w:ind", "w:jc", "w:rPr", "w:sectPr")
    el = OxmlElement(f"w:{side}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size))
    el.set(qn("w:space"), str(space))
    el.set(qn("w:color"), color)
    pBdr.append(el)


def set_cell_border(cell, color=BORDER, size=4):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcPr.insert_element_before(borders, "w:shd", "w:noWrap", "w:tcMar",
                                   "w:textDirection", "w:vAlign", "w:hideMark")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(size))
        el.set(qn("w:color"), color)
        borders.append(el)


def set_cell_margins(cell, top=60, start=90, bottom=60, end=90):
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    # 用 w:left / w:right 而非 w:start / w:end，兼容 Word 2007 与 WPS
    for tag, val in (("top", top), ("left", start), ("bottom", bottom), ("right", end)):
        el = OxmlElement(f"w:{tag}")
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tcPr.insert_element_before(mar, "w:textDirection", "w:vAlign", "w:hideMark")


def mark_header_row(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.insert_element_before(el, "w:tblCellSpacing", "w:jc", "w:hidden")


def add_field(paragraph, instr, size=9):
    """插入 PAGE / NUMPAGES 域，并写入缓存结果，未更新域时也能显示占位数字。"""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    r = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size * 2)))
    rPr.append(sz)
    r.append(rPr)
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    paragraph._p.append(fld)
    return fld


def add_hyperlink(paragraph, text, url, size=None):
    """插入真正可点击的 Word 超链接（相对路径也可）。"""
    try:
        rid = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    except Exception:
        r = paragraph.add_run(text)
        set_run_font(r, size=size, color=BLUE)
        return
    hl = OxmlElement("w:hyperlink")
    hl.set(qn("r:id"), rid)
    r = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rFonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        rFonts.set(qn(attr), FONT_BODY)
    rPr.append(rFonts)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "2E5C8A")
    rPr.append(color)
    if size:
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(int(size * 2)))
        rPr.append(sz)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)
    r.append(rPr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    hl.append(r)
    paragraph._p.append(hl)


def strip_md(text):
    """提取 Markdown 片段的纯显示文本，用于回读校验与链接文字。

    反引号内的内容按字面保留（例如 `**加粗**` 在 Word 里就该显示 **加粗**），
    只剥离反引号外的强调标记；因此先用占位符把行内代码整体保护起来。
    """
    codes: list[str] = []

    def hold(m):
        codes.append(m.group(0)[1:-1])
        return f"\x00CODE{len(codes) - 1}\x00"

    text = re.sub(r"`[^`]+`", hold, text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"\*\*|~~", "", text)
    text = re.sub(r"\x00CODE(\d+)\x00", lambda m: codes[int(m.group(1))], text)
    return text.replace(r"\|", "|").strip()


# ----------------------------------------------------------------------------
# 链接重映射：让 Word 里的相对链接仍指向仓库内的正确文件
# ----------------------------------------------------------------------------
class Converter:
    def __init__(self, root: Path, out_dir: Path, src_rel: str, out_name: str):
        self.root = root
        self.out_dir = out_dir
        self.src_rel = src_rel
        self.src_path = root / src_rel
        self.out_name = out_name
        self.stats = {
            "headings": 0,
            "paragraphs": 0,
            "tables": 0,
            "table_rows": 0,
            "code_blocks": 0,
            "code_lines": 0,
            "list_items": 0,
            "quotes": 0,
            "links": 0,
            "source_lines": 0,
            "source_chars": 0,
        }
        self.toc: list[tuple[int, str]] = []
        self.link_map: dict[str, str] = {}
        for src, out, _ in SOURCES:
            self.link_map[Path(src).as_posix()] = out

    def remap(self, url: str) -> str:
        url = url.strip()
        if url.startswith(("http://", "https://", "mailto:", "#")):
            return url
        path_part = url.split("#")[0]
        anchor = url[len(path_part):]
        if not path_part:
            return url
        # 解析为仓库内相对路径
        base = self.src_path.parent
        candidate = (base / path_part).resolve()
        try:
            rel = candidate.relative_to(self.root).as_posix()
        except ValueError:
            return url
        if rel in self.link_map:
            return "./" + self.link_map[rel] + anchor
        # 目标不在 Word 目录内 -> 相对 docs/word/ 的路径
        try:
            rel_from_word = os.path.relpath(candidate, self.out_dir).replace("\\", "/")
        except ValueError:
            rel_from_word = rel
        return rel_from_word + anchor

    # ---------------- 行内格式 ----------------
    def add_inline(self, p, text, size=None, base_bold=False, code_context=False):
        """把一行 Markdown 行内语法写入段落。"""
        pos = 0
        for m in INLINE_RE.finditer(text):
            if m.start() > pos:
                self._text_run(p, text[pos:m.start()], size, base_bold)
            token = m.group(0)
            kind = m.lastgroup
            if kind == "bold":
                # 粗体内部可能还有 `行内代码` 或 [链接]()，必须递归解析，
                # 否则 Word 里会留下反引号与 [...](...) 原始语法。
                self.add_inline(p, token[2:-2], size, base_bold=True)
            elif kind == "italic":
                self.add_inline(p, token[1:-1], size, base_bold)
            elif kind == "strike":
                self.add_inline(p, token[2:-2], size, base_bold)
            elif kind == "code":
                r = p.add_run(token[1:-1])
                set_run_font(r, size=(size or 10.5) - 0.5, font=FONT_CODE, color=RGBColor(0xB0, 0x3A, 0x2E))
            elif kind == "link":
                lm = LINK_RE.match(token)
                if lm:
                    self.stats["links"] += 1
                    add_hyperlink(p, strip_md(lm.group("text")), self.remap(lm.group("url")), size=size)
                else:
                    self._text_run(p, token, size, base_bold)
            pos = m.end()
        if pos < len(text):
            self._text_run(p, text[pos:], size, base_bold)

    def _text_run(self, p, text, size=None, bold=False):
        r = p.add_run(text)
        set_run_font(r, size=size, bold=bold or None, color=DARK)
        return r

    # ---------------- 块元素 ----------------
    def prescan_toc(self, lines):
        """正文写入前先扫描标题，目录页因此可以正确地放在封面之后。"""
        self.toc = []
        in_code = False
        for ln in lines:
            s = ln.strip()
            if s.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            hm = HEADING_RE.match(s)
            if hm and len(hm.group("hashes")) <= 2:
                self.toc.append((len(hm.group("hashes")), strip_md(hm.group("text"))))

    def add_heading(self, doc, level, text):
        self.stats["headings"] += 1
        p = doc.add_paragraph(style=f"Heading {min(level, 4)}")
        p.paragraph_format.keep_with_next = True
        self.add_inline(p, text)
        for r in p.runs:
            r.font.name = FONT_HEAD
            r.font.bold = True
            r.font.color.rgb = NAVY if level <= 2 else BLUE
            r.font.size = Pt({1: 19, 2: 15, 3: 12.5, 4: 11}[min(level, 4)])
            rPr = r._element.get_or_add_rPr()
            rf = rPr.find(qn("w:rFonts"))
            if rf is not None:
                rf.set(qn("w:eastAsia"), FONT_HEAD)
        if level == 1:
            set_paragraph_border(p, side="bottom", color=ACCENT, size=10, space=6)
        return p

    def add_code_block(self, doc, lang, lines):
        self.stats["code_blocks"] += 1
        self.stats["code_lines"] += len(lines)
        label = "图示源码 · Mermaid" if lang.lower() == "mermaid" else f"代码 · {lang or 'text'}"
        cap = doc.add_paragraph()
        cap.paragraph_format.space_after = Pt(2)
        cap.paragraph_format.keep_with_next = True
        r = cap.add_run(label)
        set_run_font(r, size=8.5, color=MUTED, font=FONT_CODE)
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.25)
        p.paragraph_format.right_indent = Cm(0.1)
        p.paragraph_format.space_after = Pt(9)
        p.paragraph_format.line_spacing = 1.15
        set_shading(p, FILL_CODE)
        set_paragraph_border(p, side="left", color=BORDER, size=14, space=6)
        for idx, line in enumerate(lines):
            r = p.add_run(line.replace("\t", "    "))
            set_run_font(r, size=8.8, font=FONT_CODE, color=CODE_COLOR)
            if idx < len(lines) - 1:
                r.add_break()
        return p

    def add_table(self, doc, header, rows):
        self.stats["tables"] += 1
        self.stats["table_rows"] += len(rows) + 1
        cols = len(header)
        table = doc.add_table(rows=1, cols=cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        try:
            table.style = "Table Grid"
        except KeyError:
            pass
        for j, cell_text in enumerate(header):
            cell = table.rows[0].cells[j]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_shading(cell, FILL_HEAD)
            set_cell_border(cell)
            set_cell_margins(cell)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.1
            self.add_inline(p, cell_text, size=9, base_bold=True)
            for r in p.runs:
                r.font.bold = True
                r.font.size = Pt(9)
        mark_header_row(table.rows[0])
        for i, row in enumerate(rows):
            cells = table.add_row().cells
            for j in range(cols):
                cell = cells[j]
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                set_cell_border(cell)
                set_cell_margins(cell)
                if i % 2 == 1:
                    set_shading(cell, FILL_ALT)
                p = cell.paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.1
                self.add_inline(p, row[j] if j < len(row) else "", size=9)
        tail = doc.add_paragraph()
        tail.paragraph_format.space_after = Pt(2)
        tail.paragraph_format.line_spacing = 0.5
        return table

    def add_list_item(self, doc, indent, marker, text):
        self.stats["list_items"] += 1
        ordered = bool(re.match(r"\d+[.)]$", marker))
        tm = TASK_RE.match(text)
        if tm:
            p = doc.add_paragraph(style="List Bullet")
            r = p.add_run("☑ " if tm.group("flag").lower() == "x" else "☐ ")
            set_run_font(r, size=10.5, color=BLUE)
            self.add_inline(p, tm.group("text"))
        elif ordered:
            p = doc.add_paragraph(style="List Number")
            self.add_inline(p, text)
        else:
            p = doc.add_paragraph(style="List Bullet")
            self.add_inline(p, text)
        level = min(len(indent) // 2, 3)
        p.paragraph_format.left_indent = Cm(0.75 + 0.6 * level)
        p.paragraph_format.first_line_indent = Cm(-0.35)
        p.paragraph_format.space_after = Pt(2)
        return p

    def add_quote(self, doc, lines):
        self.stats["quotes"] += 1
        for line in lines:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.space_after = Pt(3)
            set_shading(p, FILL_QUOTE)
            set_paragraph_border(p, side="left", color=ACCENT, size=16, space=8)
            self.add_inline(p, line, size=10)
            for r in p.runs:
                r.font.color.rgb = RGBColor(0x3C, 0x4A, 0x5A)
        return

    def add_hr(self, doc):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(8)
        set_paragraph_border(p, side="bottom", color=BORDER, size=6, space=1)
        return p

    # ---------------- 文档骨架 ----------------
    def setup_styles(self, doc):
        normal = doc.styles["Normal"]
        normal.font.name = FONT_BODY
        normal.font.size = Pt(10.5)
        normal.font.color.rgb = DARK
        rPr = normal.element.get_or_add_rPr()
        rf = rPr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rPr.insert(0, rf)
        for attr in ("w:ascii", "w:hAnsi", "w:cs"):
            rf.set(qn(attr), FONT_BODY)
        rf.set(qn("w:eastAsia"), FONT_BODY)
        normal.paragraph_format.line_spacing = 1.35
        normal.paragraph_format.space_after = Pt(6)
        for lvl in range(1, 5):
            st = doc.styles[f"Heading {lvl}"]
            st.font.name = FONT_HEAD
            st.font.color.rgb = NAVY if lvl <= 2 else BLUE
            st.font.bold = True
            st.font.size = Pt({1: 19, 2: 15, 3: 12.5, 4: 11}[lvl])
            st.paragraph_format.space_before = Pt({1: 16, 2: 12, 3: 9, 4: 7}[lvl])
            st.paragraph_format.space_after = Pt(5)
            st.paragraph_format.keep_with_next = True
            srPr = st.element.get_or_add_rPr()
            srf = srPr.find(qn("w:rFonts"))
            if srf is None:
                srf = OxmlElement("w:rFonts")
                srPr.insert(0, srf)
            srf.set(qn("w:eastAsia"), FONT_HEAD)

    def setup_page(self, doc, doc_title):
        sec = doc.sections[0]
        sec.page_width = Cm(21.0)
        sec.page_height = Cm(29.7)
        sec.top_margin = Cm(2.2)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin = Cm(2.3)
        sec.right_margin = Cm(2.1)
        sec.header_distance = Cm(1.0)
        sec.footer_distance = Cm(1.0)
        sec.different_first_page_header_footer = True

        hdr = sec.header.paragraphs[0]
        hdr.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = hdr.add_run("私有文档知识库问答助手 · kb-assistant")
        set_run_font(r, size=8.5, color=MUTED)
        r2 = hdr.add_run("    |    " + doc_title)
        set_run_font(r2, size=8.5, color=MUTED)
        set_paragraph_border(hdr, side="bottom", color=BORDER, size=4, space=4)

        ftr = sec.footer.paragraphs[0]
        ftr.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = ftr.add_run("第 ")
        set_run_font(r, size=9, color=MUTED)
        add_field(ftr, "PAGE", size=9)
        r = ftr.add_run(" 页 / 共 ")
        set_run_font(r, size=9, color=MUTED)
        add_field(ftr, "NUMPAGES", size=9)
        r = ftr.add_run(" 页")
        set_run_font(r, size=9, color=MUTED)

    def add_cover(self, doc, doc_title, doc_type, src_rel):
        for _ in range(4):
            doc.add_paragraph()
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("私有文档知识库问答助手")
        set_run_font(r, size=15, color=MUTED, font=FONT_HEAD)
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(26)
        r = p.add_run(doc_title)
        set_run_font(r, size=30, bold=True, color=NAVY, font=FONT_HEAD)
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(10)
        r = p.add_run(doc_type)
        set_run_font(r, size=13, color=BLUE, font=FONT_HEAD)
        set_paragraph_border(p, side="bottom", color=ACCENT, size=12, space=12)

        info = doc.add_table(rows=4, cols=2)
        info.alignment = WD_TABLE_ALIGNMENT.CENTER
        info.autofit = True
        labels = [
            ("项目", "kb-assistant · 私有文档知识库问答助手（个人作品）"),
            ("版本", "v1.0.0"),
            ("编制日期", dt.date.today().isoformat()),
            ("源文件", src_rel + "（Markdown 可编辑源文件）"),
        ]
        for i, (k, v) in enumerate(labels):
            for j, txt in enumerate((k, v)):
                cell = info.cell(i, j)
                set_cell_margins(cell, top=80, bottom=80)
                cp = cell.paragraphs[0]
                cp.paragraph_format.space_after = Pt(0)
                rr = cp.add_run(txt)
                set_run_font(rr, size=10, bold=(j == 0), color=MUTED if j == 0 else DARK)
        for _ in range(2):
            doc.add_paragraph()
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("本文件由 Markdown 源文件自动转换生成，正文内容与源文件一致；"
                      "表格、代码块与链接均按原结构保留。")
        set_run_font(r, size=9, color=MUTED)
        doc.add_page_break()

    def add_toc(self, doc, doc_title):
        entries = [(lv, t) for lv, t in self.toc if not (lv == 1 and t == doc_title)]
        if len(entries) < 3:
            return
        p = doc.add_paragraph()
        r = p.add_run("目  录")
        set_run_font(r, size=20, bold=True, color=NAVY, font=FONT_HEAD)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(16)
        for lv, text in entries:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.4 + 0.65 * (lv - 1))
            p.paragraph_format.space_after = Pt(3)
            if lv == 1:
                r = p.add_run("■ ")
                set_run_font(r, size=9.5, color=BLUE)
            r = p.add_run(text)
            set_run_font(r, size=10.5 if lv == 1 else 9.8, bold=(lv == 1),
                         color=NAVY if lv == 1 else DARK)
        doc.add_page_break()

    # ---------------- 主转换 ----------------
    def convert(self) -> dict:
        md = self.src_path.read_text(encoding="utf-8")
        lines = md.splitlines()
        self.stats["source_lines"] = len(lines)
        self.stats["source_chars"] = len(md)
        doc_title = ""
        for ln in lines:
            hm = HEADING_RE.match(ln.strip())
            if hm and len(hm.group("hashes")) == 1:
                doc_title = re.sub(r"[*`\[\]]", "", hm.group("text")).strip()
                break
        doc_title = doc_title or Path(self.out_name).stem
        doc_type = next(t for s, o, t in SOURCES if s == self.src_rel)

        doc = Document()
        self.setup_styles(doc)
        self.setup_page(doc, self.out_name.replace(".docx", ""))
        doc.core_properties.title = doc_title
        doc.core_properties.subject = "kb-assistant 项目交付文档"
        doc.core_properties.author = "Ningo1077"
        doc.core_properties.keywords = "kb-assistant; RAG; 交付文档; " + doc_type
        doc.core_properties.comments = "由 " + self.src_rel + " 自动转换，正文未改写"
        self.add_cover(doc, doc_title, doc_type, self.src_rel)
        self.prescan_toc(lines)
        self.add_toc(doc, doc_title)

        i = 0
        n = len(lines)
        para_buf: list[str] = []

        def flush_para():
            nonlocal para_buf
            if not para_buf:
                return
            text = " ".join(x.strip() for x in para_buf).strip()
            para_buf = []
            if not text:
                return
            self.stats["paragraphs"] += 1
            p = doc.add_paragraph()
            self.add_inline(p, text)

        while i < n:
            raw = lines[i]
            line = raw.rstrip()
            stripped = line.strip()

            if not stripped:
                flush_para()
                i += 1
                continue

            # 围栏代码块
            if stripped.startswith("```"):
                flush_para()
                lang = stripped[3:].strip()
                body = []
                i += 1
                while i < n and not lines[i].strip().startswith("```"):
                    body.append(lines[i])
                    i += 1
                i += 1  # 跳过结束围栏
                self.add_code_block(doc, lang, body)
                continue

            # 标题
            hm = HEADING_RE.match(stripped)
            if hm:
                flush_para()
                self.add_heading(doc, len(hm.group("hashes")), hm.group("text").strip())
                i += 1
                continue

            # 水平线
            if HR_RE.match(stripped):
                flush_para()
                self.add_hr(doc)
                i += 1
                continue

            # 表格（表头行 + 分隔行）
            if stripped.startswith("|") and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]) and "-" in lines[i + 1]:
                flush_para()
                def split_cells(s):
                    s = s.strip()
                    if s.startswith("|"):
                        s = s[1:]
                    if s.endswith("|"):
                        s = s[:-1]
                    return [c.strip().replace(r"\|", "|") for c in re.split(r"(?<!\\)\|", s)]
                header = split_cells(stripped)
                i += 2
                rows = []
                while i < n and lines[i].strip().startswith("|"):
                    row = split_cells(lines[i].strip())
                    rows.append(row + [""] * (len(header) - len(row)) if len(row) < len(header) else row[:len(header)])
                    i += 1
                self.add_table(doc, header, rows)
                continue

            # 引用块
            if stripped.startswith(">"):
                flush_para()
                quotes = []
                while i < n and lines[i].strip().startswith(">"):
                    quotes.append(re.sub(r"^\s*>\s?", "", lines[i].strip()))
                    i += 1
                self.add_quote(doc, quotes)
                continue

            # 列表项
            lm = LIST_RE.match(raw)
            if lm and not stripped.startswith("|"):
                flush_para()
                self.add_list_item(doc, lm.group("indent"), lm.group("marker"), lm.group("text").strip())
                i += 1
                continue

            # 普通段落（合并软换行）
            para_buf.append(stripped)
            i += 1

        flush_para()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.out_dir / self.out_name
        doc.save(out_path)
        self.stats["output"] = str(out_path.relative_to(self.root)).replace("\\", "/")
        self.stats["docx_bytes"] = out_path.stat().st_size
        return self.stats

def verify(root: Path, out_dir: Path, src_rel: str, out_name: str) -> dict:
    """回读 docx，校验结构完整性与正文覆盖率。"""
    from docx import Document as _Doc
    p = out_dir / out_name
    result = {"src": src_rel, "docx": p.name, "ok": False}
    if not p.exists():
        result["error"] = "missing"
        return result
    try:
        d = _Doc(p)
    except Exception as e:
        result["error"] = f"unreadable: {e}"
        return result
    # 按段落拼接所有 w:t（含 w:hyperlink 内的文字、表格单元格、页眉外的全部正文），
    # 这样跨 run 的一整行文本仍能作为连续子串被检出。
    text = "\n".join(
        "".join(t.text or "" for t in el.iter(qn("w:t")))
        for el in d.element.body.iter(qn("w:p"))
    )
    md = (root / src_rel).read_text(encoding="utf-8")
    # 逐行抽样：标题文本、表格首列、代码块行、正文/引用/列表行都要能在 docx 文本中找到
    heads, cells, body = [], [], []
    in_code = False
    for l in md.splitlines():
        s = l.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            if len(s) > 3:
                body.append(("code", s.replace("\t", "    ")))
            continue
        hm = HEADING_RE.match(s)
        if hm:
            h = strip_md(hm.group("text"))
            if h:
                heads.append(h)
            continue
        if s.startswith("|"):
            if not TABLE_SEP_RE.match(s):
                first = strip_md(s.strip("|").split("|")[0])
                if len(first) > 1 and not re.fullmatch(r"[-:\s]+", first):
                    cells.append(first)
            continue
        if not s or HR_RE.match(s):
            continue
        if s.startswith(">"):
            val = strip_md(re.sub(r"^>\s?", "", s))
        else:
            lm = LIST_RE.match(l)
            if lm:
                tm = TASK_RE.match(lm.group("text"))
                val = strip_md(tm.group("text") if tm else lm.group("text"))
            else:
                val = strip_md(s)
        if len(val) > 3:
            body.append(("body", val))
    missing = [h for h in heads if h not in text]
    cell_missing = [c for c in cells if c not in text]
    body_missing = [(k, v) for k, v in body if v not in text][:5]
    result.update({
        "ok": not missing and not cell_missing and not body_missing,
        "paragraphs": len(d.paragraphs),
        "tables": len(d.tables),
        "sections": len(d.sections),
        "chars": len(text),
        "headings": len(heads),
        "headings_missing": missing[:5],
        "table_cells_checked": len(cells),
        "table_cells_missing": cell_missing[:5],
        "body_lines_checked": len(body),
        "body_lines_missing": body_missing,
        "bytes": p.stat().st_size,
    })
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="仓库根目录（默认：脚本上级目录）")
    ap.add_argument("--out-dir", default="docs/word")
    ap.add_argument("--check", action="store_true", help="只校验已有 docx，不重新生成")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    out_dir = (root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.check:
        results = [verify(root, out_dir, s, o) for s, o, _ in SOURCES]
        print(json.dumps({"mode": "check", "results": results}, ensure_ascii=False, indent=2))
        ok = all(r["ok"] for r in results)
        print("CHECK_RESULT=" + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1

    print(f"[md_to_docx] root={root}")
    print(f"[md_to_docx] output={out_dir}")
    print(f"[md_to_docx] files={len(SOURCES)}")
    all_stats = []
    for src, out, kind in SOURCES:
        src_path = root / src
        if not src_path.exists():
            print(f"  MISSING SOURCE: {src}")
            continue
        conv = Converter(root, out_dir, src, out)
        st = conv.convert()
        all_stats.append(st)
        print(f"  OK  {src} -> docs/word/{out}  "
              f"[ headings={st['headings']} tables={st['tables']} "
              f"code_blocks={st['code_blocks']} paragraphs={st['paragraphs']} "
              f"links={st['links']} bytes={st['docx_bytes']} ]")
    print(f"[md_to_docx] converted={len(all_stats)}")
    print("[md_to_docx] verifying ...")
    results = [verify(root, out_dir, s, o) for s, o, _ in SOURCES]
    for r in results:
        flag = "OK " if r["ok"] else "BAD"
        print(f"  {flag} {r['docx']}: paragraphs={r.get('paragraphs')} "
              f"tables={r.get('tables')} body_lines={r.get('body_lines_checked')} "
              f"missing[head={len(r.get('headings_missing', []))}, "
              f"cell={len(r.get('table_cells_missing', []))}, "
              f"body={len(r.get('body_lines_missing', []))}] bytes={r.get('bytes')}")
    ok = all(r["ok"] for r in results) and len(all_stats) == len(SOURCES)
    print("CONVERT_RESULT=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
