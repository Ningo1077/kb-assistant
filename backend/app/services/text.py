"""文档解析与分块。不依赖 LangChain，逻辑全部可解释。"""

import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".txt", ".csv"}
MAX_FILE_BYTES = 20 * 1024 * 1024

_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;\n])")
_PAGE_NO = re.compile(r"^[-—\s]*\d{1,4}[-—\s]*$")
_PAGE_LABEL = re.compile(r"^第\s*\d+\s*页(\s*[/／共]?\s*\d*\s*页?)?$")
_BULLET = re.compile(r"^([一二三四五六七八九十]+[、.]|\d+[.、)]|[（(]\d+[）)]|[-*•]|#+)")
_CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class Segment:
    page_no: int
    text: str


@dataclass
class ChunkPiece:
    content: str
    page_no: int
    index: int


def _looks_like_heading(line: str) -> bool:
    if _BULLET.match(line):
        return True
    # 短行且没有任何句读，多半是小标题，不能和正文接在一起
    return len(line) <= 20 and not re.search(r"[。，、；：.!?,;:]$", line)


def clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ").replace("\xa0", " ")
    lines: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            lines.append("")
            continue
        # 去掉孤立页码与「第 x 页」这类页脚，它们会污染向量
        if _PAGE_NO.match(line) or _PAGE_LABEL.match(line):
            continue
        lines.append(line)

    merged: list[str] = []
    buf = ""
    for line in lines:
        if not line:
            if buf:
                merged.append(buf)
                buf = ""
            merged.append("")
            continue
        can_merge = (
            buf
            and not _looks_like_heading(buf)
            and not _looks_like_heading(line)
            and not re.search(r"[。！？；：.!?;:]$", buf)
        )
        if can_merge:
            buf += line  # PDF 硬换行把一句话切断，接回去
        else:
            if buf:
                merged.append(buf)
            buf = line
    if buf:
        merged.append(buf)

    out = "\n".join(merged)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def parse_document(path: Path) -> list[Segment]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"不支持的文件类型：{suffix or '未知'}")

    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    return [Segment(page_no=1, text=clean_text(_read_text(path)))]


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "gb18030", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _parse_pdf(path: Path) -> list[Segment]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    segments: list[Segment] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:  # 个别损坏页不阻断整篇
            raw = ""
        text = clean_text(raw)
        if text:
            segments.append(Segment(page_no=i, text=text))
    if not segments:
        raise ValueError("PDF 中未提取到文本（可能是扫描件，需 OCR）")
    return segments


def _parse_docx(path: Path) -> list[Segment]:
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:  # 表格按行拼成文本，避免整表丢失（简单处理）
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                paragraphs.append(" | ".join(cells))
    text = clean_text("\n".join(paragraphs))
    if not text:
        raise ValueError("文档内容为空")
    return [Segment(page_no=1, text=text)]


def _split_units(text: str) -> list[str]:
    """按段落 → 句子切分。段落之间用换行连接，避免分块后段落粘成一坨。"""
    units: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        first_in_para = True
        for sentence in _SENT_SPLIT.split(para):
            sentence = sentence.strip()
            if not sentence:
                continue
            prefix = "\n" if (first_in_para and units) else ""
            while len(sentence) > 600:  # 超长句强制切，防止单块爆表
                units.append(prefix + sentence[:600])
                sentence = sentence[600:]
                prefix = ""
            if sentence:
                units.append(prefix + sentence)
            first_in_para = False
    return units


def chunk_segments(segments: list[Segment], size: int = 800, overlap: int = 120) -> list[ChunkPiece]:
    """按句子边界打包，块与块之间保留 overlap 字符，防止语义被截断。"""
    pieces: list[ChunkPiece] = []
    for seg in segments:
        buf = ""
        for unit in _split_units(seg.text):
            if buf and len(buf) + len(unit) > size:
                pieces.append(ChunkPiece(content=buf.strip(), page_no=seg.page_no, index=len(pieces)))
                tail = ""
                for piece_unit in reversed(_split_units(buf)):
                    if len(tail) + len(piece_unit) > overlap:
                        break
                    tail = piece_unit + tail
                buf = tail
            buf += unit
        if buf.strip():
            pieces.append(ChunkPiece(content=buf.strip(), page_no=seg.page_no, index=len(pieces)))

    # 短于 30 字的块（多半是残句）并回上一块
    merged: list[ChunkPiece] = []
    for piece in pieces:
        if merged and len(piece.content) < 30:
            prev = merged[-1]
            merged[-1] = ChunkPiece(
                content=f"{prev.content}\n{piece.content}", page_no=prev.page_no, index=prev.index
            )
        else:
            merged.append(piece)
    for i, piece in enumerate(merged):
        piece.index = i
    return merged
