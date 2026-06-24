"""
Convert README.md and SPEC_*.md to PDF using reportlab + STSong-Light CID font.
Usage: python export_docs.py
"""
import re
import os
import glob
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, Preformatted)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# ── Font setup ──────────────────────────────────────────────────────────────
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
F = 'STSong-Light'

# Windows TTF override for better rendering locally
for _fp in ['C:/Windows/Fonts/msjh.ttc', 'C:/Windows/Fonts/kaiu.ttf']:
    if os.path.exists(_fp):
        try:
            from reportlab.pdfbase.ttfonts import TTFont
            pdfmetrics.registerFont(TTFont('CJK', _fp))
            F = 'CJK'
            break
        except Exception:
            pass

# ── Styles ───────────────────────────────────────────────────────────────────
def S(name, **kw):
    kw.setdefault('fontName', F)
    kw.setdefault('leading', kw.get('fontSize', 10) * 1.5)
    return ParagraphStyle(name, **kw)

STYLES = {
    'h1':    S('h1',    fontSize=18, spaceBefore=14, spaceAfter=8,
                        textColor=colors.HexColor('#1a1a2e'), borderPadding=(0,0,4,0)),
    'h2':    S('h2',    fontSize=14, spaceBefore=12, spaceAfter=6,
                        textColor=colors.HexColor('#16213e')),
    'h3':    S('h3',    fontSize=11, spaceBefore=8,  spaceAfter=4,
                        textColor=colors.HexColor('#0f3460')),
    'body':  S('body',  fontSize=9,  spaceAfter=4),
    'bq':    S('bq',    fontSize=9,  spaceAfter=4,  leftIndent=18,
                        textColor=colors.HexColor('#555555')),
    'code':  S('code',  fontName='Courier', fontSize=8, spaceAfter=2,
                        leftIndent=12, leading=13),
    'li':    S('li',    fontSize=9,  spaceAfter=2,  leftIndent=16),
    'li2':   S('li2',   fontSize=9,  spaceAfter=2,  leftIndent=28),
}

TBL_HEADER = colors.HexColor('#4472C4')
TBL_STRIPE = colors.HexColor('#EBF0FA')
TBL_GRID   = colors.HexColor('#CCCCCC')


def escape(text):
    """Escape special XML/HTML chars for Paragraph."""
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))


def inline(text):
    """Convert inline markdown (bold, code, link) to reportlab XML."""
    text = escape(text)
    # bold **...**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # code `...`
    text = re.sub(r'`([^`]+)`', r'<font name="Courier" size="8">\1</font>', text)
    # italic *...*
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # strip markdown links [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    return text


def parse_table(lines):
    """Parse GFM table lines into a list-of-lists."""
    rows = []
    for line in lines:
        if re.match(r'\s*\|?[-:| ]+\|?\s*$', line):
            continue  # separator row
        cells = [c.strip() for c in re.split(r'(?<!\\)\|', line) if c.strip()]
        if cells:
            rows.append(cells)
    return rows


def build_table(rows):
    """Return a reportlab Table flowable from rows."""
    if not rows:
        return None
    col_count = max(len(r) for r in rows)
    # pad rows
    data = []
    for r in rows:
        row = [Paragraph(inline(c), STYLES['body']) for c in r]
        while len(row) < col_count:
            row.append(Paragraph('', STYLES['body']))
        data.append(row)

    col_w = (A4[0] - 40*mm) / col_count
    t = Table(data, colWidths=[col_w] * col_count, repeatRows=1)
    style = [
        ('FONTNAME',   (0, 0), (-1, -1), F),
        ('FONTSIZE',   (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0),  TBL_HEADER),
        ('TEXTCOLOR',  (0, 0), (-1, 0),  colors.white),
        ('GRID',       (0, 0), (-1, -1), 0.4, TBL_GRID),
        ('ALIGN',      (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(('BACKGROUND', (0, i), (-1, i), TBL_STRIPE))
    t.setStyle(TableStyle(style))
    return t


def md_to_story(md_text):
    """Convert markdown text to a list of reportlab flowables."""
    story = []
    lines = md_text.splitlines()
    i = 0
    in_code = False
    code_buf = []
    table_buf = []

    def flush_table():
        if table_buf:
            t = build_table(parse_table(table_buf))
            if t:
                story.append(t)
                story.append(Spacer(1, 4))
            table_buf.clear()

    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ────────────────────────────────────────────
        if line.strip().startswith('```'):
            flush_table()
            if in_code:
                if code_buf:
                    story.append(Preformatted('\n'.join(code_buf),
                                              STYLES['code'],
                                              maxLineLength=90))
                    story.append(Spacer(1, 4))
                code_buf.clear()
                in_code = False
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # ── Table ─────────────────────────────────────────────────────────
        if '|' in line:
            table_buf.append(line)
            i += 1
            continue
        else:
            flush_table()

        stripped = line.strip()

        # ── Blank line ────────────────────────────────────────────────────
        if not stripped:
            story.append(Spacer(1, 4))
            i += 1
            continue

        # ── Horizontal rule ───────────────────────────────────────────────
        if re.match(r'^---+$', stripped):
            story.append(HRFlowable(width='100%', thickness=0.5,
                                    color=colors.HexColor('#AAAAAA'),
                                    spaceAfter=4))
            i += 1
            continue

        # ── Headings ──────────────────────────────────────────────────────
        m = re.match(r'^(#{1,3})\s+(.*)', stripped)
        if m:
            level = len(m.group(1))
            text  = inline(m.group(2))
            key   = f'h{level}'
            story.append(Paragraph(text, STYLES.get(key, STYLES['h3'])))
            if level == 1:
                story.append(HRFlowable(width='100%', thickness=1,
                                        color=TBL_HEADER, spaceAfter=6))
            i += 1
            continue

        # ── Blockquote ────────────────────────────────────────────────────
        if stripped.startswith('>'):
            text = inline(stripped.lstrip('> ').strip())
            story.append(Paragraph(f'<i>{text}</i>', STYLES['bq']))
            i += 1
            continue

        # ── Bullet list (- or *) ─────────────────────────────────────────
        m2 = re.match(r'^(\s*)([-*])\s+(.*)', line)
        if m2:
            indent = len(m2.group(1))
            text   = inline(m2.group(3))
            sty    = STYLES['li2'] if indent >= 2 else STYLES['li']
            bullet = '•'
            story.append(Paragraph(f'{bullet} {text}', sty))
            i += 1
            continue

        # ── Numbered list ────────────────────────────────────────────────
        m3 = re.match(r'^\d+\.\s+(.*)', stripped)
        if m3:
            text = inline(m3.group(1))
            story.append(Paragraph(f'• {text}', STYLES['li']))
            i += 1
            continue

        # ── Normal paragraph ─────────────────────────────────────────────
        story.append(Paragraph(inline(stripped), STYLES['body']))
        i += 1

    flush_table()
    return story


def convert(md_path, pdf_path):
    with open(md_path, encoding='utf-8') as f:
        md_text = f.read()

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm,  bottomMargin=20*mm,
    )
    story = md_to_story(md_text)
    doc.build(story)
    print(f'  ✅  {os.path.basename(pdf_path)}')


if __name__ == '__main__':
    base = os.path.dirname(os.path.abspath(__file__))

    targets = [
        ('README.md',                    'README.pdf'),
        ('SPEC_員工日報系統_v0.4.md',   'SPEC_員工日報系統_v0.4.pdf'),
    ]

    print('匯出 PDF 中...')
    for md_name, pdf_name in targets:
        md_path  = os.path.join(base, md_name)
        pdf_path = os.path.join(base, pdf_name)
        if os.path.exists(md_path):
            convert(md_path, pdf_path)
        else:
            print(f'  ⚠  找不到 {md_name}，跳過')

    print('完成。')
