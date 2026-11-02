"""A minimal .xlsx writer (docs/PLAN.md §4-38): sheets of text and numbers, no styles, no extra
package. Numbers are written with repr() so they read back exactly; text as inline strings."""

import math
from pathlib import Path
import re
import zipfile
from xml.sax.saxutils import escape


def _column(k: int) -> str:
    name = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        name = chr(65 + r) + name
    return name


def _cell(ref: str, value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return f'<c r="{ref}"><v>{repr(float(value)) if isinstance(value, float) else value}</v></c>'
    text = escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value)))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def write(path: Path, sheets: list[tuple[str, list[list]]]) -> Path:
    """Write sheets [(name, rows)] to `path` (each row a list of str/int/float/None)."""
    names = [re.sub(r"[\[\]:*?/\\]", "_", n)[:31] or f"Sheet{i + 1}" for i, (n, _) in enumerate(sheets)]
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(sheets)))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook {ns} xmlns:r="{rel}"><sheets>'
                   + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                             for i, n in enumerate(names))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="{rel}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(len(sheets)))
                   + "</Relationships>")
        for i, (_, rows) in enumerate(sheets):
            body = "".join(f'<row r="{r + 1}">' + "".join(_cell(f"{_column(c)}{r + 1}", v) for c, v in enumerate(row))
                           + "</row>" for r, row in enumerate(rows))
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml",
                       f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {ns}><sheetData>{body}</sheetData></worksheet>')
    return path


def read(path: Path) -> dict[str, list[list]]:
    """Read back what `write` wrote (tests): {sheet name: rows}, numbers as float."""
    import xml.etree.ElementTree as ET

    m = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    out = {}
    with zipfile.ZipFile(path) as z:
        sheets = ET.fromstring(z.read("xl/workbook.xml")).iter(f"{m}sheet")
        for i, s in enumerate(sheets):
            rows = []
            for row in ET.fromstring(z.read(f"xl/worksheets/sheet{i + 1}.xml")).iter(f"{m}row"):
                cells = {}
                for c in row:
                    col = re.match(r"[A-Z]+", c.get("r")).group()
                    k = 0
                    for ch in col:
                        k = k * 26 + ord(ch) - 64
                    cells[k - 1] = (c.find(f"{m}is/{m}t").text or "") if c.get("t") == "inlineStr" else float(c.find(f"{m}v").text)
                rows.append([cells.get(k) for k in range(max(cells) + 1)] if cells else [])
            out[s.get("name")] = rows
    return out
