"""Bounded Markdown table projection, derived only from the cited source bytes.

No arithmetic, unit conversion or inferred headers. Unsupported/ambiguous markup
has no projection; the original evidence remains available for other checks.
"""

import re


def _cell(value: str) -> str | None:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<sup>\s*\((\d+)\)\s*</sup>", r"(注\1)", value, flags=re.I)
    value = value.replace("**", "").strip()
    # Delimiters inside a cell could turn one bound row into independent claims.
    if any(c in value for c in "<>|\n。；;") or len(value) > 400:
        return None
    return value


def table_source_statements(content: str) -> list[str]:
    if len(content) > 100_000 or re.search(r"仅限|如果|(?:^|[，。])若|除非|不适用|适用条件", content):
        return []
    lines = content.splitlines()
    heading = period = ""
    statements: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#"):
            heading = _cell(line.lstrip("# ")) or ""
            period = ""
        elif line.startswith("截至") and len(line) < 100 and "期间" in line:
            period = _cell(line) or ""
        if not line.startswith("|") or i + 1 >= len(lines):
            i += 1
            continue
        headers = [_cell(c) for c in line.strip("|").split("|")]
        separators = lines[i + 1].strip().strip("|").split("|")
        if (
            not heading
            or not 2 <= len(headers) <= 12
            or any(not h for h in headers)
            or len(separators) != len(headers)
            or not all(re.fullmatch(r"\s*:?-{3,}:?\s*", s) for s in separators)
            or len(set(headers)) != len(headers)
        ):
            i += 1
            continue
        i += 2
        while i < len(lines) and lines[i].strip().startswith("|"):
            cells = [_cell(c) for c in lines[i].strip().strip("|").split("|")]
            i += 1
            if len(cells) != len(headers) or any(c is None or not c for c in cells):
                continue
            bound = f"{heading}（{period + '，' if period else ''}{headers[0]}）{cells[0]}"
            bound += "，" + "，".join(
                f"{h}：{c}" for h, c in zip(headers[1:], cells[1:], strict=True)
            )
            # Referenced notes must be present and travel with the whole row.
            notes = []
            for ref in sorted(set(re.findall(r"\(注(\d+)\)", bound))):
                matches = {n.strip() for n in lines if re.match(rf"\s*注\s*[:：]\s*\({ref}\)", n)}
                if len(matches) != 1:
                    break
                note = next(iter(matches))
                cleaned = _cell(note.rstrip("。"))
                if not cleaned:
                    break
                notes.append(cleaned)
            else:
                statements.append(bound + ("，" + "，".join(notes) if notes else "") + "。")
            if len(statements) >= 128:
                return statements
    return statements
