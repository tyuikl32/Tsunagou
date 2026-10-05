"""Frontend copy out, and the edited copy back in.

The page's Chinese lives inside string literals scattered across ``web/index.html``,
``web/assets/js/*.js`` and ``web/assets/css/*.css``. Somebody who wants to reword it
should not have to hunt through those files, and should not have to escape anything.

``extract`` writes every literal that contains Chinese into one plain-text file, one
entry per line, with the runtime expressions that sit between the literal parts written
as ``<...>`` placeholders::

    web/assets/js/behavior.js#37 = 项目「<project.name>」的<role>：

``apply`` writes the text back into exactly the spans it came from. The expressions are
never touched, so a round trip with an unedited file is byte-for-byte identical — which
is also how this tool is verified.

Refusals rather than guesses, because a silent mis-write here is worse than an error:

* an entry must keep the same number of ``<...>`` placeholders as the source has
  expressions, and the same order;
* entries are matched by file and by position in that file, so lines may be left out
  (they stay as they are) but never reordered;
* a literal the tool cannot place back is reported, never guessed;
* ``extract`` refuses to overwrite an existing copy file unless ``--force`` is given
  (the old one is backed up first) — overwriting it would throw away hand edits.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_COPY = REPOSITORY / "tsunagou.lang"
HAN = re.compile(r"[\u4e00-\u9fff]")
HTML_SOURCES = ("web/index.html",)
JS_GLOBS = ("web/assets/js/*.js",)
CSS_GLOBS = ("web/assets/css/*.css",)
HTML_ATTRIBUTES = ("placeholder", "title", "alt", "aria-label", "value")
#: Generated, never hand-edited copy.
SKIP_NAMES = {"console.config.js"}


@dataclass
class Entry:
    """One editable piece of copy, and where it came from."""

    path: str
    #: ``js``, ``css`` or ``html``: decides what has to be escaped when writing back.
    kind: str
    #: ``'``, ``"`` or a backtick: what the span is delimited by.
    quote: str
    #: The literal spans that carry the text, in source order. ``'a' + expr + 'b'`` has
    #: two; a template literal has one per literal part.
    spans: list[tuple[int, int]]
    #: The literal parts as they appear in the file.
    parts: list[str]
    #: Source text of each expression between the parts (one fewer than the parts).
    between: list[str] = field(default_factory=list)
    #: Whitespace that surrounded the text in the file (HTML 缩进), put back on write.
    pad: tuple[str, str] = ("", "")

    def text(self) -> str:
        pieces = [self.parts[0] if self.parts else ""]
        for expression, part in zip(self.between, self.parts[1:], strict=False):
            pieces.append(f"<{_describe(expression)}>")
            pieces.append(part)
        return "".join(pieces)


def _describe(expression: str) -> str:
    """A readable placeholder name for whatever the code interpolates.

    Only characters the placeholder syntax allows: an expression such as
    ``Math.round(left/60)`` would otherwise produce a marker the reader (and this tool)
    could not tell apart from markup.
    """

    cleaned = re.sub(r"[\s<>\"'=/]+", "", expression)[:60]
    return cleaned or "值"


def _read(path: Path) -> str:
    """Read without newline translation: CRLF must survive the round trip.

    ``Path.read_text`` turns ``\\r\\n`` into ``\\n``, which both moves every span after the
    first line and makes a write-back silently convert the whole file to LF.
    """

    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _files(root: Path) -> list[Path]:
    found = [root / name for name in HTML_SOURCES]
    for pattern in (*JS_GLOBS, *CSS_GLOBS):
        found.extend(sorted(root.glob(pattern)))
    return [path for path in found if path.is_file() and path.name not in SKIP_NAMES]


def _skip_js(source: str, index: int) -> int | None:
    """Where a comment ends, if one starts here (``None`` = not a comment)."""

    if source.startswith("//", index):
        end = source.find("\n", index)
        return len(source) if end < 0 else end
    if source.startswith("/*", index):
        end = source.find("*/", index + 2)
        return len(source) if end < 0 else end + 2
    return None


def _literal_end(source: str, start: int, quote: str) -> int:
    """The index just past a string or template literal that starts at ``start``."""

    index, size = start + 1, len(source)
    while index < size:
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == quote:
            return index + 1
        if quote == "`" and source[index] == "$" and source[index + 1 : index + 2] == "{":
            depth, index = 1, index + 2
            while index < size and depth:
                depth += (source[index] == "{") - (source[index] == "}")
                index += 1
            continue
        index += 1
    return size


def _template_parts(source: str, start: int, end: int) -> tuple[list[str], list[str], list[tuple[int, int]]]:
    """Literal parts, expressions, and each part's span, for a template literal."""

    parts: list[str] = [""]
    expressions: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = start + 1
    piece_start = cursor
    index = start + 1
    while index < end - 1:
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == "$" and source[index + 1 : index + 2] == "{":
            spans.append((piece_start, index))
            parts[-1] = source[piece_start:index]
            depth, stop = 1, index + 2
            while stop < end - 1 and depth:
                depth += (source[stop] == "{") - (source[stop] == "}")
                stop += 1
            expressions.append(source[index + 2 : stop - 1])
            parts.append("")
            index = piece_start = stop
            continue
        index += 1
    spans.append((piece_start, end - 1))
    parts[-1] = source[piece_start : end - 1]
    return parts, expressions, spans


#: A ``/`` right after one of these can only start a regular expression, never divide.
_REGEX_AFTER = set("(,=:[!&|?{};+-*%^~<>")


def _skip_regex(source: str, index: int, previous: str) -> int | None:
    """Where a regular-expression literal ends, if one starts at ``index``.

    ``esc()`` in behavior.js contains ``/"/g`` and ``/'/g``. Without this, the quote
    inside such a regex opens a phantom string that runs on for thousands of
    characters and swallows every real literal in between -- those come back looking
    multi-line, get dropped, and their Chinese never reaches the copy file. Worse, the
    entries that *do* survive are renumbered whenever anything before them changes, so
    adding a comment silently invalidates every ``path#n`` in tsunagou.lang.

    Returns ``None`` when the ``/`` is really a division.
    """

    if previous and previous not in _REGEX_AFTER:
        return None
    cursor, size = index + 1, len(source)
    in_class = False
    while cursor < size:
        char = source[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "\n":
            return None  # 换行了还没收尾：那是除号，不是正则
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            cursor += 1
            while cursor < size and source[cursor].isalpha():
                cursor += 1
            return cursor
        cursor += 1
    return None


def _js_entries(source: str, relative: str) -> list[Entry]:
    """String literals with Chinese, runs of them joined across ``+`` expressions."""

    literals: list[tuple[int, int, str]] = []
    index, size = 0, len(source)
    previous = ""  # 最近一个"有意义的"字符：判断 '/' 是正则还是除号
    while index < size:
        skipped = _skip_js(source, index)
        if skipped is not None:
            index = skipped
            continue
        char = source[index]
        if char in "'\"`":
            end = _literal_end(source, index, char)
            literals.append((index, end, char))
            index = end
            previous = char
            continue
        if char == "/":
            regex_end = _skip_regex(source, index, previous)
            if regex_end is not None:
                index = regex_end
                previous = "/"
                continue
        if not char.isspace():
            previous = char
        index += 1

    entries: list[Entry] = []
    position = 0
    while position < len(literals):
        start, end, quote = literals[position]
        if quote == "`":
            parts, expressions, spans = _template_parts(source, start, end)
            if any(HAN.search(part) for part in parts):
                if any(TAG.search(part) for part in parts):
                    for span, part in zip(spans, parts, strict=True):
                        entries.extend(_tagged_entries(relative, "js", quote, span, part))
                else:
                    entries.append(Entry(relative, "js", quote, spans, parts, expressions))
            position += 1
            continue
        run = [literals[position]]
        between: list[str] = []
        cursor = position
        while cursor + 1 < len(literals) and literals[cursor + 1][2] != "`":
            gap = source[literals[cursor][1] : literals[cursor + 1][0]]
            joined = re.fullmatch(r"\s*\+\s*(.*?)\s*\+\s*", gap, re.S)
            plain = re.fullmatch(r"\s*\+\s*", gap)
            if joined is None and plain is None:
                break
            run.append(literals[cursor + 1])
            between.append(joined.group(1) if joined is not None else "")
            cursor += 1
        bodies = [source[item[0] + 1 : item[1] - 1] for item in run]
        if any(HAN.search(body) for body in bodies):
            spans = [(item[0] + 1, item[1] - 1) for item in run]
            if any(TAG.search(body) for body in bodies):
                # 拼串拼出来的页面：只把标签之间的中文抽出来，标签和变量一个都别动。
                for span, body in zip(spans, bodies, strict=True):
                    if TAG.search(body):
                        entries.extend(_tagged_entries(relative, "js", quote, span, body))
                    elif HAN.search(body):
                        # 同一段拼串里既有标签又有**纯文本**（`… + '">' + '选项 ' + …`）：
                        # 纯文本那段没有标签可依，上面那条会把它整个丢掉 —— 可它是给人看的字。
                        text = body.strip()
                        if text:
                            head = body.index(text)
                            start = span[0] + head
                            entries.append(Entry(relative, "js", quote, [(start, start + len(text))], [text]))
            else:
                entries.append(Entry(relative, "js", quote, spans, bodies, between))
        position = cursor + 1
    return entries


def _html_entries(source: str, relative: str) -> list[Entry]:
    """Text between tags, plus the few attributes a person reads."""

    entries: list[Entry] = []
    for match in re.finditer(r">([^<>]+)<", source):
        body = match.group(1)
        if not HAN.search(body):
            continue
        text = body.strip()
        if not text:
            continue
        head = body.index(text)
        pad = (body[:head], body[head + len(text) :])
        # 整个文本节点都算这一条的跨度：缩进也算进来，写回时原样带出去，不去动版式。
        entries.append(Entry(
            relative, "html", "", [(match.start(1), match.start(1) + len(body))], [text], pad=pad,
        ))
    attributes = "|".join(HTML_ATTRIBUTES)
    for match in re.finditer(rf'\b(?:{attributes})\s*=\s*"([^"]*)"', source):
        value = match.group(1)
        if HAN.search(value):
            start = match.start(1)
            entries.append(Entry(relative, "html", "", [(start, start + len(value))], [value]))
    return sorted(entries, key=lambda entry: entry.spans[0][0])


def _css_entries(source: str, relative: str) -> list[Entry]:
    """``content: "…"`` — where several of the page's labels actually live."""

    entries: list[Entry] = []
    for match in re.finditer(r'content\s*:\s*(["\'])((?:[^"\'\\]|\\.)*)\1', source):
        value = match.group(2)
        if HAN.search(value):
            start = match.start(2)
            entries.append(Entry(relative, "css", match.group(1), [(start, start + len(value))], [value]))
    return entries


def _one_line(parts: list[str]) -> bool:
    """Whether this entry fits the file's one-line-per-entry shape.

    A literal that really spans lines (a template holding a paragraph) would break the
    format, and inventing an escape for it would make the round trip lossy. Those few
    are skipped and counted instead, so the tool never silently mangles them.
    """

    return not any("\n" in part or "\r" in part for part in parts)


def collect(root: Path) -> tuple[list[Entry], dict[str, str]]:
    """Every editable entry in file order, plus each file's original text."""

    entries: list[Entry] = []
    originals: dict[str, str] = {}
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        originals[relative] = _read(path)
        if relative.endswith(".html"):
            found = _html_entries(originals[relative], relative)
        elif relative.endswith(".css"):
            found = _css_entries(originals[relative], relative)
        else:
            found = _js_entries(originals[relative], relative)
        for entry in found:
            if _one_line(entry.parts):
                entries.append(entry)
            else:
                SKIPPED.append(f"{relative}:{entry.spans[0][0]}")
    return entries, originals


#: Literals left out because they span lines (reported by ``extract``, never guessed).
SKIPPED: list[str] = []


HEADER = """# 前端文案（网页上会给用户看的字都在这里）
#
# 怎么改：只改等号右边。变量写成 <描述>，例如：请打开 <Agent软件>
#   · 一行一条；以 # 开头的行是注释；**不要调换顺序**；
#   · 只列你要改的那几行也行 —— 没列出来的一律保持原样（回填时会报出条数）；
#   · 一行里的 <...> 是代码里的取值（Agent 名字、项目名这类）。**个数与顺序不要动**，
#     名字本身可以改成更顺口的说法（例如把 <host.label> 改成 <宿主名称>）；
#   · 改完交给 AI 换回去，或者自己跑：
#       uv run --no-sync python tools/dev/web_copy.py check   # 先看会不会出问题
#       uv run --no-sync python tools/dev/web_copy.py apply   # 真的写回代码
#
# 等号左边的 id 是回填用的地址，别改。重抽（extract）会覆盖这个文件，所以它默认拒绝，
# 要重抽必须显式 --force，且旧文件先备份成同名 .bak。
"""


def write_copy(entries: list[Entry], target: Path) -> None:
    lines = [HEADER]
    current = ""
    for index, entry in enumerate(entries):
        if entry.path != current:
            current = entry.path
            lines.append(f"\n# ---- {current} ----")
        lines.append(f"{entry.path}#{index} = {entry.text()}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def read_copy(target: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    # utf-8-sig: 记事本这类编辑器保存时会加 BOM，那一个字节不该让整个文件读不了。
    for line in target.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(" = ")
        if not separator:
            raise SystemExit(f"这一行没有 ' = '：{line!r}")
        values[key.strip()] = value
    return values


#: A placeholder as the copy file spells it: ``<描述>`` with no spaces, quotes, ``=`` or
#: ``/`` in it, so that markup the copy legitimately contains (``<div class="t">``,
#: ``</p>``) can never be mistaken for a variable.
MARKER = re.compile(r"<[^<>\s\"'=/]+>")
#: An HTML tag inside a JavaScript string: those literals contribute the words *between*
#: tags, never the markup (see ``_tagged_entries``).
TAG = re.compile(r"<[a-zA-Z/][^<>]*>")


def _tagged_entries(relative: str, kind: str, quote: str, span: tuple[int, int], body: str) -> list[Entry]:
    """The readable words inside a piece of markup, as separate entries.

    A page built by string concatenation keeps its sentence inside a tag soup. Showing
    the whole soup as one line would be honest but useless to the person editing it, so
    each run of text between tags becomes its own line and the tags stay where they are.
    """

    entries: list[Entry] = []
    for match in re.finditer(r">([^<>]+)<", body):
        text = match.group(1)
        if not HAN.search(text):
            continue
        stripped = text.strip()
        if not stripped:
            continue
        head = text.index(stripped)
        start = span[0] + match.start(1) + head
        entries.append(Entry(
            relative, kind, quote, [(start, start + len(stripped))], [stripped],
            pad=(text[:head], text[head + len(stripped) :]),
        ))
    return entries


def _pair_warnings(before: str, after: str) -> list[str]:
    """Warn when one entry's quotation marks came back unpaired.

    ``「」`` and ``“”`` get swapped by hand a lot, and dropping the opening bracket is
    easy to miss — the line still reads fine, it just starts with a closing quote.

    Only fires when the entry *was* balanced before: separated fragments legitimately
    hold one half each (``请在“`` in one entry, ``”下打开`` in the next), and those were
    never balanced on their own. Swapping ``「」`` for ``“”`` inside one entry stays
    quiet too, because the result is balanced again.
    """

    pairs = (("\u201c", "\u201d"), ("\u300c", "\u300d"), ("\u2018", "\u2019"))
    if not any(before.count(opener) and before.count(opener) == before.count(closer) for opener, closer in pairs):
        return []
    notes: list[str] = []
    for opener, closer in pairs:
        opened, closed = after.count(opener), after.count(closer)
        if opened != closed:
            notes.append(f"{opener}{closer} 单着了（改后 {opened}/{closed} 个）")
    return notes


def _escape(text: str, entry: Entry) -> str:
    """Escape only what the entry's own syntax needs.

    HTML text takes no escaping at all (a path like ``D:\\work\\副本`` must stay exactly
    as it was written), CSS only its quote, and JavaScript both its backslash and its
    delimiter — doubling backslashes in markup is how a path grows an extra one.
    """

    if entry.kind == "html":
        return text
    if entry.kind == "css":
        return text.replace(entry.quote, "\\" + entry.quote)
    text = text.replace("\\", "\\\\")
    if entry.quote == "`":
        return text.replace("`", "\\`").replace("${", "\\${")
    return text.replace(entry.quote, "\\" + entry.quote)


def apply(root: Path, target: Path, *, check: bool) -> int:
    entries, originals = collect(root)
    wanted = read_copy(target)
    updated = dict(originals)
    #: How far each file has already grown or shrunk: entries are applied in source
    #: order, so every later span needs the running difference (reset per file, not per
    #: entry — that mistake writes text on top of the tags).
    shifts: dict[str, int] = {}
    problems: list[str] = []
    untouched: list[str] = []
    warnings: list[str] = []
    for index, entry in enumerate(entries):
        key = f"{entry.path}#{index}"
        if key not in wanted:
            # 只列改过的那几行也可以：没列出来的一律保持原样（数量会报出来）。
            untouched.append(key)
            continue
        text = wanted[key]
        if "\n" in text:
            problems.append(f"{key}：文案里不能有换行")
            continue
        if not entry.between:
            # 没有变量的条目原样写回：网页文案里本来就有 `<div class="t">` 这类标记，
            # 不去猜哪个尖括号是变量，就不会猜错。
            pieces = [text]
        else:
            markers = MARKER.findall(text)
            if len(markers) != len(entry.between):
                problems.append(
                    f"{key}：变量个数不对（文案里 {len(markers)} 个，代码里 {len(entry.between)} 个）"
                )
                continue
            pieces = MARKER.split(text)
        if len(pieces) != len(entry.spans):
            problems.append(f"{key}：变量的位置不合法")
            continue
        for note in _pair_warnings(entry.text(), text):
            warnings.append(f"{key}：{note}")
        if entry.pad != ("", ""):
            # HTML 文本节点：把原来的缩进原样放回去（改的是字，不是版式）。
            pieces = [entry.pad[0] + pieces[0]]
            pieces[-1] = pieces[-1] + entry.pad[1]
        source = updated[entry.path]
        shift = shifts.get(entry.path, 0)
        for (start, end), part in zip(entry.spans, pieces, strict=True):
            written = _escape(part, entry)
            source = source[: start + shift] + written + source[end + shift :]
            shift += len(written) - (end - start)
        updated[entry.path] = source
        shifts[entry.path] = shift
    if problems:
        for problem in problems:
            print(f"  拒绝：{problem}")
        return 2
    changed = [name for name, text in updated.items() if text != originals[name]]
    if not check:
        for name in changed:
            # 原样写：读的时候没有翻译换行，所以字符串里带的就是这个文件自己的换行
            # （behavior.js 是 CRLF、index.html 是 LF），再翻译一次会写出 \r\r\n。
            (root / name).write_text(updated[name], encoding="utf-8", newline="")
    print(f"  {'待写回' if check else '已写回'} {len(changed)} 个文件；文案共 {len(entries)} 条")
    if untouched:
        print(f"  没列出来的 {len(untouched)} 条保持原样（例如 {untouched[0]}）")
    if warnings:
        print(f"  ⚠ 有 {len(warnings)} 条看起来少了配对符号（照样写进去了，自己确认一下）：")
        for note in warnings[:8]:
            print(f"    {note}")
    for name in changed:
        print(f"    {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("extract", "apply", "check"))
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--copy", type=Path, default=DEFAULT_COPY)
    parser.add_argument(
        "--force", action="store_true",
        help="允许 extract 覆盖已存在的文案文件（会先备份成 <名字>.bak）",
    )
    args = parser.parse_args(argv)
    if args.action == "extract":
        if args.copy.is_file() and not args.force:
            # 覆盖就等于把人工改的字扔掉。这件事发生过一次，所以这里必须挡一下：
            # 想重抽就显式 --force，而且旧文件先留一份 .bak。
            raise SystemExit(
                f"文案文件已存在：{args.copy}\n"
                "  extract 会重写它（人工改过的字就没了）。确认要重抽就加 --force，"
                "旧文件会先备份成同名 .bak。"
            )
        entries, _ = collect(args.root)
        if args.copy.is_file():
            args.copy.replace(args.copy.with_name(args.copy.name + ".bak"))
        write_copy(entries, args.copy)
        print(f"  写出 {len(entries)} 条到 {args.copy}")
        if SKIPPED:
            print(f"  跨行的没抽（保持一行一条）：{len(SKIPPED)} 条 → " + "、".join(SKIPPED[:6]))
        return 0
    if not args.copy.is_file():
        raise SystemExit(f"文案文件不存在：{args.copy}（先跑 extract）")
    return apply(args.root, args.copy, check=args.action == "check")


if __name__ == "__main__":
    raise SystemExit(main())
