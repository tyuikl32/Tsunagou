"""文案文件与页面之间必须逐字节往返：改字要生效，没改的不能被动。

前端文案抽出来给人改（``文案.txt``），再由同一个工具写回 ``web/``。这里钉三件事：
仓库里那份文案与页面是一致的（``check`` 说不需要改）、改过一行确实写进代码、变量个数不对
时**拒绝**而不是猜。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


def _tool():
    """Load ``tools/dev/web_copy.py`` by path (it is a script, not an importable package).

    It has to be registered in ``sys.modules`` first: a dataclass inside looks itself up
    there while the module is still executing.
    """

    spec = importlib.util.spec_from_file_location("web_copy", REPOSITORY / "tools" / "dev" / "web_copy.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["web_copy"] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_copy_file_still_matches_the_page() -> None:
    """仓库里那份 文案.txt 与 web/ 下的代码一致 —— 不一致就说明有人只改了一边。"""

    tool = _tool()
    assert tool.main(["check"]) == 0


def test_writing_preserves_the_files_own_line_endings(tmp_path: Path) -> None:
    """改一个字不能把整份文件的换行换掉（behavior.js 是 CRLF，index.html 是 LF）。

    ``Path.read_text`` 会把 CRLF 归一化成 ``\\n``，所以只比字符串是看不出这件事的 ——
    这里比字节，往返前后必须一模一样。
    """

    script = tmp_path / "web" / "assets" / "js" / "crlf.js"
    script.parent.mkdir(parents=True)
    before = "const a = '请打开 Codex';\r\nconst b = '别的字';\r\n".encode()
    script.write_bytes(before)
    copy = tmp_path / "文案.txt"
    tool = _tool()

    assert tool.main(["extract", "--root", str(tmp_path), "--copy", str(copy)]) == 0
    copy.write_text(
        copy.read_text(encoding="utf-8").replace("请打开 Codex", "请打开你的 Agent"),
        encoding="utf-8", newline="",
    )
    assert tool.main(["apply", "--root", str(tmp_path), "--copy", str(copy)]) == 0

    assert script.read_bytes() == "const a = '请打开你的 Agent';\r\nconst b = '别的字';\r\n".encode()


def test_an_untouched_page_is_left_byte_for_byte_alone(tmp_path: Path) -> None:
    """没人改的往返必须一个字节都不动（这是这个工具唯一的安全保证）。"""

    script = tmp_path / "web" / "assets" / "js" / "mixed.js"
    script.parent.mkdir(parents=True)
    original = "const a = '请打开 ' + host.label + ' 再继续';\r\nconst b = '已完成';\r\n".encode()
    script.write_bytes(original)
    copy = tmp_path / "文案.txt"
    tool = _tool()

    assert tool.main(["extract", "--root", str(tmp_path), "--copy", str(copy)]) == 0
    assert tool.main(["check", "--root", str(tmp_path), "--copy", str(copy)]) == 0
    assert tool.main(["apply", "--root", str(tmp_path), "--copy", str(copy)]) == 0
    assert script.read_bytes() == original


def test_an_edited_line_is_written_back_into_its_own_span(tmp_path: Path) -> None:
    script = tmp_path / "web" / "assets" / "js" / "probe.js"
    script.parent.mkdir(parents=True)
    script.write_text("const a = '请打开 Codex 桌面版';\nconst b = '别的字';\n", encoding="utf-8")
    copy = tmp_path / "文案.txt"
    tool = _tool()

    assert tool.main(["extract", "--root", str(tmp_path), "--copy", str(copy)]) == 0
    assert "请打开 Codex 桌面版" in copy.read_text(encoding="utf-8")

    copy.write_text(
        copy.read_text(encoding="utf-8").replace("请打开 Codex 桌面版", "请打开你的 Agent 软件"),
        encoding="utf-8",
    )
    assert tool.main(["apply", "--root", str(tmp_path), "--copy", str(copy)]) == 0

    assert script.read_text(encoding="utf-8") == "const a = '请打开你的 Agent 软件';\nconst b = '别的字';\n"


def test_a_variable_survives_the_round_trip_and_is_shown_as_a_placeholder(tmp_path: Path) -> None:
    script = tmp_path / "web" / "assets" / "js" / "probe.js"
    script.parent.mkdir(parents=True)
    script.write_text("const a = '请打开 ' + host.label + ' 再继续';\n", encoding="utf-8")
    copy = tmp_path / "文案.txt"
    tool = _tool()

    assert tool.main(["extract", "--root", str(tmp_path), "--copy", str(copy)]) == 0
    line = [item for item in copy.read_text(encoding="utf-8").splitlines() if "probe.js#" in item][0]
    assert line.endswith("= 请打开 <host.label> 再继续")

    copy.write_text(
        copy.read_text(encoding="utf-8").replace("<host.label>", "<Agent软件>")
        .replace("请打开", "先去打开").replace("再继续", "再回来"),
        encoding="utf-8",
    )
    assert tool.main(["apply", "--root", str(tmp_path), "--copy", str(copy)]) == 0

    assert script.read_text(encoding="utf-8") == "const a = '先去打开 ' + host.label + ' 再回来';\n"


def test_a_changed_number_of_variables_is_refused(tmp_path: Path) -> None:
    """少写或多写一个 ``<...>`` 就停下来，绝不猜怎么拼 —— 猜错会静默改坏页面。"""

    script = tmp_path / "web" / "assets" / "js" / "probe.js"
    script.parent.mkdir(parents=True)
    script.write_text("const a = '请打开 ' + host.label + ' 再继续';\n", encoding="utf-8")
    copy = tmp_path / "文案.txt"
    tool = _tool()
    assert tool.main(["extract", "--root", str(tmp_path), "--copy", str(copy)]) == 0

    copy.write_text(
        copy.read_text(encoding="utf-8").replace("<host.label>", "那个软件"), encoding="utf-8",
    )
    assert tool.main(["apply", "--root", str(tmp_path), "--copy", str(copy)]) == 2
    assert script.read_text(encoding="utf-8") == "const a = '请打开 ' + host.label + ' 再继续';\n"


def test_a_half_dropped_quote_pair_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """整条里成对的引号被改成只剩一半时要说出来（分段文案不在此列）。"""

    script = tmp_path / "web" / "assets" / "js" / "probe.js"
    script.parent.mkdir(parents=True)
    script.write_text("const a = '「' + name + '」会被删掉';\n", encoding="utf-8")
    copy = tmp_path / "文案.txt"
    tool = _tool()
    assert tool.main(["extract", "--root", str(tmp_path), "--copy", str(copy)]) == 0

    copy.write_text(
        copy.read_text(encoding="utf-8").replace("「<name>」", "<name>”"), encoding="utf-8", newline="",
    )
    capsys.readouterr()
    assert tool.main(["check", "--root", str(tmp_path), "--copy", str(copy)]) == 0

    assert "单着了" in capsys.readouterr().out


def test_a_byte_order_mark_does_not_break_the_file(tmp_path: Path) -> None:
    """记事本保存会加 BOM：那一个字节不该让整份文案读不了。"""

    script = tmp_path / "web" / "assets" / "js" / "probe.js"
    script.parent.mkdir(parents=True)
    script.write_text("const a = '请打开 Codex';\n", encoding="utf-8")
    copy = tmp_path / "文案.txt"
    tool = _tool()
    assert tool.main(["extract", "--root", str(tmp_path), "--copy", str(copy)]) == 0

    body = copy.read_text(encoding="utf-8")
    copy.write_bytes(b"\xef\xbb\xbf" + body.replace("请打开 Codex", "请打开你的 Agent").encode())
    assert tool.main(["apply", "--root", str(tmp_path), "--copy", str(copy)]) == 0

    assert script.read_text(encoding="utf-8") == "const a = '请打开你的 Agent';\n"


@pytest.mark.parametrize("path", ["web/index.html", "web/assets/js/behavior.js"])
def test_the_page_sources_are_covered(path: str) -> None:
    tool = _tool()
    entries, _ = tool.collect(REPOSITORY)
    assert any(entry.path == path for entry in entries), f"{path} 里应该抽得出文案"
