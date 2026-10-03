"""远端自报的机器名：只是**显示**，不是权限。

跨机器导入时（`agent import --machine`），那台机器的桥会在入席时把名字放在 `descriptor_ref`
里带上来；协调中心把它记在 Agent 上，名单出口原样公布，页面据此画「远端 · 机器名」。

这里要守住两件事：
* 本机接入从来不报这个名 —— 没有它，页面就不画那个标记（"没有"是有意义的值）；
* 它只是入席者**说自己是谁**，所以既不能影响状态/角色，也不能因为乱填就把入席弄失败。
"""

from __future__ import annotations

from typing import Any

from tests.unit.test_trace_audit import Runtime
from tests.unit.test_trace_audit import runtime as runtime  # noqa: F401  (夹具按名字取用)


def _enroll(runtime: Runtime, conversation: str, *, descriptor: Any = None) -> dict[str, Any]:
    identity = {
        "installation_id": conversation,
        "conversation_evidence": {"conversation_id": conversation},
    }
    ticket = runtime.call("agent.ticket.create.user", identity)["secret"]
    payload = {**identity, "probe_payload": {"baseline": {}}}
    if descriptor is not None:
        payload["descriptor_ref"] = descriptor
    return runtime.call("agent.enroll", payload, ticket=ticket)


def _row(runtime: Runtime, agent_id: str) -> dict[str, Any]:
    endpoint = runtime.endpoint("/api/v1/projects/{project_id}/agents")
    return next(item for item in endpoint(runtime.project_id)["items"] if item["agent_id"] == agent_id)


def test_a_remote_names_its_machine_and_the_roster_says_so(runtime: Runtime) -> None:
    receipt = _enroll(runtime, "远端会话", descriptor="工位-七")

    row = _row(runtime, receipt["agent_id"])

    assert row["machine"] == "工位-七"
    # 报了个名字什么都不换：角色还是 worker，会话该缺的东西照样缺（这里基线是空的，
    # 所以它仍在 provisioning —— 名字不是准入证据）。
    assert row["role"] == "worker" and row["status"] == "provisioning"


def test_a_local_enrollment_has_no_machine_at_all(runtime: Runtime) -> None:
    """本机接入没有这一项 —— 页面正是靠"没有"来判断不需要画远端标记。"""

    receipt = _enroll(runtime, "本机会话")

    assert "machine" not in _row(runtime, receipt["agent_id"])


def test_a_useless_descriptor_is_ignored_rather_than_failing_the_enrollment(runtime: Runtime) -> None:
    """乱填不该让入席失败：它只是显示用，拿不准就当没报。"""

    for index, descriptor in enumerate(("", "   ", {"machine": "工位-七"}, {"no_machine": "x"},
                                      ["工位-七"], 42, None)):
        receipt = _enroll(runtime, f"第{index}个会话", descriptor=descriptor)
        row = _row(runtime, receipt["agent_id"])
        assert row["role"] == "worker", "入席本身照常成立"
        if isinstance(descriptor, dict) and descriptor.get("machine"):
            assert row["machine"] == "工位-七", "对象形式里的机器名要认得"
        else:
            assert "machine" not in row or row["machine"] == "", f"{descriptor!r} 不该变成一个名字"

    named = _enroll(runtime, "清理空白", descriptor="  工位-八  ")
    assert _row(runtime, named["agent_id"])["machine"] == "工位-八"


def test_a_name_that_is_too_long_is_cut_short_not_dropped(runtime: Runtime) -> None:
    """名字是"这台机器是不是远端"的信号（D191 的拒绝就靠它），所以超长要截短，不能丢掉 ——
    丢掉等于把一台远端当成本机，它就能接文件任务了。换行/制表符只是抹掉，不是整条不认。"""

    long_name = _enroll(runtime, "超长名字", descriptor="x" * 200)
    assert _row(runtime, long_name["agent_id"])["machine"] == "x" * 64
    messy = _enroll(runtime, "带换行", descriptor="两行\r\n名字")
    assert _row(runtime, messy["agent_id"])["machine"] == "两行名字"


def test_a_declared_code_copy_is_recorded_and_published(runtime: Runtime) -> None:
    """报了副本的远端：位置与基线都记下来、都公布出去 —— 主机据此把工作区指过去（D192）。"""

    receipt = _enroll(runtime, "带副本的远端", descriptor={
        "machine": "工位-七", "copy": {"path": "D:/work/copy", "baseline": "main"},
    })

    row = _row(runtime, receipt["agent_id"])

    assert row["machine"] == "工位-七"
    assert row["copy_path"] == "D:/work/copy" and row["copy_baseline"] == "main"


def test_only_the_declared_pieces_travel(runtime: Runtime) -> None:
    """没报的就不出现：本机接入既没有机器名也没有副本；只报副本时不冒充"远端"。"""

    local = _enroll(runtime, "本机会话")
    copied = _enroll(runtime, "只报了副本", descriptor={"copy": {"path": "D:/work/copy"}})

    assert "machine" not in _row(runtime, local["agent_id"])
    assert "copy_path" not in _row(runtime, local["agent_id"])
    assert "machine" not in _row(runtime, copied["agent_id"])
    assert _row(runtime, copied["agent_id"])["copy_path"] == "D:/work/copy"
