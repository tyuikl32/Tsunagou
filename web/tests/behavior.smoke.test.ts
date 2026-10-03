/* 前端结构冒烟 —— web/tests/behavior.smoke.test.ts
 * ----------------------------------------------------------------------------
 * 为什么有这一份：这一轮踩到的两个 bug 都不是"逻辑算错了"，而是**结构**错了 ——
 *
 *   1) 总路径的行从 `.taskFlow > .inner > .item` 少了一层 `.inner`，于是点击行用的
 *      选择器（两级 `>`）再也匹配不上 —— 行点不开；
 *   2) 「任务验收情况」的结果格把标签和几行说明当**兄弟节点**摆进那个宽 200px 的
 *      flex 行容器，于是一格被挤成竖排、文字全糊：多行内容必须套 `.colu-t`。
 *   3) 左栏项目卡片少了一个闭合 `</div>`，浏览器把后面的卡片全嵌进第一张里；
 *      选中态用的是后代选择器，于是"点一张，下面一片跟着高亮"（同名只是个巧合）。
 *
 * 这两类只有把真页面、真 DOM 拉起来才拦得住，所以这里用 jsdom 载入仓库里**真正的**
 * index.html + console.config.js + behavior.js，然后断言结构，而不是断言字符串。
 *
 * 这一份**不联调后端**（那是 tools/dev/console_smoke.py 的活）：所有请求都让它失败，
 * 因为"没有后端时整页也要能画出来"本身就是要守住的行为。
 * ------------------------------------------------------------------------- */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { JSDOM } from "jsdom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const WEB_ROOT = new URL("../", import.meta.url);

function readWeb(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, WEB_ROOT)), "utf8");
}

type ConsoleApi = {
  ready: boolean;
  dispatch: (type: string, payload?: unknown) => { ok: boolean; error?: string };
  config: { get: () => Record<string, unknown> };
  stopPolling?: () => void;
};

let dom: JSDOM;
let page: Document;
let api: ConsoleApi;

beforeAll(() => {
  dom = new JSDOM(readWeb("index.html"), {
    url: "http://127.0.0.1:55862/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const win = dom.window as unknown as Window & typeof globalThis;
  /* 页面一进来就会拉数据。这一份不联调后端，所以每个请求都直接失败 ——
     空状态必须画得出来，不许整页崩掉。*/
  (win as unknown as { fetch: unknown }).fetch = () =>
    Promise.reject(new Error("smoke: no backend"));
  win.eval(readWeb("console.config.js"));
  win.eval(readWeb("assets/js/behavior.js"));
  page = win.document;
  api = (win as unknown as { Tsunagou: ConsoleApi }).Tsunagou;
});

afterAll(() => {
  api?.stopPolling?.();
  dom?.window.close();
});

describe("控制台页面（web/）结构冒烟", () => {
  it("页面能起来，而且 demo 开关已经彻底不在了", () => {
    expect(api.ready).toBe(true);
    expect(typeof api.dispatch).toBe("function");
    const snapshot = api.config.get();
    expect(snapshot).not.toHaveProperty("mode");
    expect(snapshot).not.toHaveProperty("demo");
  });

  it("index.html 不再引用演示后端，也不再认识离线数据集", () => {
    const html = readWeb("index.html");
    expect(html).not.toContain("mock-backend");
    expect(html).toContain("./console.config.js");
    expect(html).toContain("./assets/js/behavior.js");
  });

  it("仓库里那份 console.config.js 只写 baseUrl / poll_ms", () => {
    const provided = (dom.window as unknown as { TSUNAGOU_CONSOLE_CONFIG: Record<string, unknown> })
      .TSUNAGOU_CONSOLE_CONFIG;
    expect(Object.keys(provided).sort()).toEqual(["baseUrl", "poll_ms"]);
  });

  it("同名的多个协作里，左栏卡片互为兄弟、选中只会点亮一张", () => {
    /* 卡片若少一个闭合标签，浏览器会把它们互相嵌套：` .projItemSelected .inner .title `
       是后代选择器，于是选中上面那张会把**它里面所有卡片**的标题一起点亮。名字相同
       只是让人更容易注意到，真正的错因是结构。这里断言结构，不断言字符串。*/
    const card = (id: string) => ({
      id,
      name: "main",
      status: "working",
      statusText: "进行中",
      time: "daemon 运行中",
    });
    const result = api.dispatch("project.list", [card("p-1"), card("p-2"), card("p-3")]);
    expect(result.ok).toBe(true);

    const rail = page.querySelector("#projList");
    expect(rail).not.toBeNull();
    expect(rail!.querySelectorAll(".projItem")).toHaveLength(3);
    // 卡片不能落在另一张卡片里面。
    expect(rail!.querySelectorAll(".projItem .projItem")).toHaveLength(0);

    const first = rail!.querySelector(".projItem");
    expect(first).not.toBeNull();
    first!.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));

    expect(rail!.querySelectorAll(".projItemSelected")).toHaveLength(1);
    // 点亮的是"那一张"的标题：嵌套时这里会数出 3。
    expect(rail!.querySelectorAll(".projItemSelected .title")).toHaveLength(1);
  });

  it("总路径的行仍然是 .taskFlow > .inner > .item（两级选择器点得开的前提）", () => {
    const result = api.dispatch("timeline.list", [
      {
        era: "第一阶段",
        items: [
          {
            id: "row-1",
            time: "09-29 12:00",
            actor: { ref: "a-1", name: "熊猫" },
            task: "接口对齐",
            action: "提交结果",
          },
          {
            id: "row-2",
            time: "09-29 12:30",
            actor: { ref: "a-2", name: "海豚" },
            task: "接口对齐",
            action: "打回",
          },
        ],
      },
    ]);
    expect(result.ok).toBe(true);

    const pane = page.querySelector("#pane-path");
    expect(pane).not.toBeNull();
    const rows = pane!.querySelectorAll(".taskFlow > .inner > .item");
    expect(rows).toHaveLength(2);
    // 行不能直接挂在 .taskFlow 下：点击用的是两级 '>'，少一层就点不开。
    expect(pane!.querySelectorAll(".taskFlow > .item")).toHaveLength(0);
    // 点击处理器靠 data-row-id 认行，没有它就等于行是死的。
    expect([...rows].map((row) => row.getAttribute("data-row-id"))).toEqual(["row-1", "row-2"]);
  });

  /* 总路径的三列以前直接印机器话（`task.begin`、`session/`、`runtime`），人读不动。
     现在原始 token 走中间层词表（GET /console/glossary）：命令名、引用前缀、操作人
     各查一次表；表里没有的**原样印**，不许猜。*/
  it("总路径三列走中间层词表，表里没有的原样印", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/glossary", {
        version: 5,
        domains: {
          command_kind: { "task.begin": "开工", "user_decision.resolve": "用户已决定" },
          ref_kind: { task: "任务", session: "会话", ticket: "接入码", decision: "用户决定" },
          actor_kind: { runtime: "后台" },
          denial_reason: { resource_conflict: "资源被占用" },
          event_reason: { user_decision: "用户决定" },
        },
      }],
      ["/history", { items: [
        {
          event_id: "e-1", action: "task.begin", actor_ref: "worker2",
          subject_ref: "task/b71c0d3e-4a5f-4c6d-8e7f-000000000000",
          occurred_at: "2026-10-02T10:16:52.000Z",
        },
        {
          event_id: "e-2", action: "command.task.begin.denied", actor_ref: "runtime",
          subject_ref: "session/", reason_code: "resource_conflict:file:src/x.py",
          occurred_at: "2026-10-02T10:16:53.000Z",
        },
        {
          event_id: "e-3", action: "some.new.thing", actor_ref: "ticket/0",
          subject_ref: "ticket/0", occurred_at: "2026-10-02T10:16:54.000Z",
        },
        {
          event_id: "e-4", action: "user_decision.resolve", actor_ref: "user_control",
          subject_ref: "decision", reason_code: "user_decision",
          occurred_at: "2026-10-02T10:16:55.000Z",
        },
      ] }],
    ];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const hit = replies.filter((pair) => path.indexOf(pair[0]) >= 0)[0];
      const body = hit ? hit[1] : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    /* 词表先到（启动时就拉了），再拉历史 —— 顺序与真页面一致。*/
    await win.Tsunagou.refresh(["glossary"]);
    await win.Tsunagou.refresh(["timeline"]);

    const rows = [...page.querySelectorAll("#pane-path .taskFlow > .inner > .item")];
    expect(rows).toHaveLength(4);
    const rowText = (index: number): string => rows[index]!.textContent ?? "";

    // ① 命令名 → 中文；`task/<id>` → 「任务 + 短号」；没登记的 Agent 名字原样留着。
    expect(rowText(0)).toContain("开工");
    expect(rowText(0)).toContain("任务 b71c0d3e");
    expect(rowText(0)).toContain("worker2");

    // ② 账本里的被拒条目：剥掉 command./.denied 之后查表，再补原因码。
    expect(rowText(1)).toContain("后台");
    expect(rowText(1)).toContain("会话");
    expect(rowText(1)).toContain("开工（被拒）");
    expect(rowText(1)).toContain("资源被占用");

    // ③ 表里没有的：原样印，并让前缀词汇把 `ticket/0` 说成人话。
    expect(rowText(2)).toContain("some.new.thing");
    expect(rowText(2)).toContain("接入码 0");

    // ④ 括注里的 `user_decision` 不是拒绝码，走 event_reason 那张表；
    //    任务列的 `decision` 也靠 ref_kind 说成人话。
    expect(rowText(3)).toContain("用户已决定（用户决定）");
    expect(rowText(3)).toContain("用户决定");
  });

  /* 「冲突与协商 → Agent 间协商」那张表的收发两侧，以前是把 id 直接截 8 个字符，
     于是 `user_control` 在页面上写成 user_con。现在与总路径共用同一套"这是谁"：
     名单里的 Agent 用昵称，用户/后台这类主体走中间层词表。*/
  it("消息表的收发两侧把 user_control 说成「用户」", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/glossary", {
        version: 5,
        domains: { actor_kind: { user_control: "用户" }, ref_kind: { ticket: "接入码" } },
      }],
      ["/console/views/collaboration", { sources: {
        agents: { items: [{ agent_id: "a-1", status: "active", role: "worker" }] },
        messages: { items: [
          {
            message_id: "m-1", sender_agent_id: "user_control", recipient_agent_id: "a-1",
            summary: "用户已裁决：确认：按此目标执行", status: "none", obligations: [],
          },
          {
            message_id: "m-2", sender_agent_id: "a-1", recipient_agent_id: "user_control",
            summary: "有结果待评审", status: "pending", obligations: [{ status: "open" }],
          },
        ] },
      } }],
    ];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const hit = replies.filter((pair) => path.indexOf(pair[0]) >= 0)[0];
      const body = hit ? hit[1] : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    await win.Tsunagou.refresh(["glossary"]);
    await win.Tsunagou.refresh(["conflicts"]);

    const block = page.querySelector("#block-conflict");
    expect(block).not.toBeNull();
    const shown = block!.textContent ?? "";
    expect(shown).toContain("用户");
    expect(shown).not.toContain("user_con");
    // 后端自己发的通知也已经是中文（模板改了源头，不是页面替换正文）。
    expect(shown).toContain("有结果待评审");
  });

  it("「验收结果」格里的多行内容套在 .colu-t 里（200px 宽的格子靠它竖排）", () => {
    api.dispatch("checkpoint.list", { latest: [], history: [] });
    const result = api.dispatch("acceptance.data", {
      proposal: {},
      taskResults: [
        {
          agent: { name: "熊猫", icon: "" },
          task: "接口对齐",
          result: "已提交 sha256:1234abcd",
          reviewed: true,
          decision: "changes_requested",
          round: 1,
          reviewer: "海豚",
          reason: "缺一组边界用例",
        },
        {
          agent: { name: "海豚", icon: "" },
          task: "接口对齐",
          result: "还没提交",
          reviewed: false,
          decision: "",
          round: 0,
          reviewer: "",
          reason: "",
        },
      ],
    });
    expect(result.ok).toBe(true);

    const cells = page.querySelectorAll("#pane-acceptance .colu-t");
    expect(cells).toHaveLength(2);

    // 第一格：主行是那个判定标签，后面几行是次要信息 —— 全部在同一个 .colu-t 里。
    const first = cells[0];
    expect(first.querySelector(".citem1 .tagZ")).not.toBeNull();
    expect([...first.children].map((node) => node.className.split(" ")[0])).toEqual([
      "citem1",
      "citem2",
      "citem2",
      "citem2",
    ]);
    // 而它所在的那一格（.colu-m）里除了这个 .colu-t，不许再直接摆别的块。
    const cell = first.parentElement!;
    expect([...cell.children]).toHaveLength(1);
    expect(cell.children[0]).toBe(first);

    // 没验收过的那一格不许给出绿色标签（那等于替后端宣布一个它没说的结论）。
    expect(cells[1].querySelector(".tagZOK")).toBeNull();
    expect(cells[1].textContent).toContain("还没验收");
  });

  it("style.css 里 .colu-t 仍然是竖排（多行格子的样式契约）", () => {
    expect(readWeb("assets/css/style.css")).toMatch(/\.colu-t\s*\{[^}]*flex-direction:\s*column/);
  });

  /* 2026-09-30：胶囊写**昵称**、说明写**后端代号**、图标跟**厂商**走。
     这里连后端形状一起过一遍（不联调后端，只把 fetch 换成应答表）——
     名字/图标是渲染时按 agent_id 从用户档案现算的，改坏任何一半这张卡就残。*/
  it("Agent 卡片：胶囊=昵称、说明=后端代号、图标=厂商（厂商未知时不冒充 DeepSeek）", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", {
        version: 1, nickname: "", theme: "",
        agents: { "a-1": { nickname: "熊猫", vendor: "Codex" } },
      }],
      ["/projects/p-1/agents", {
        items: [
          { agent_id: "a-1", role: "worker", status: "active" },
          { agent_id: "a-2", role: "worker", status: "active" },
        ],
        main_agent_id: "a-1",
      }],
    ];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const hit = replies.filter((pair) => path.indexOf(pair[0]) >= 0)[0];
      const body = hit ? hit[1] : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    await win.Tsunagou.refresh(["agents", "settings"]);

    const cards = page.querySelectorAll("#pane-agents .boxerbox > .item");
    expect(cards).toHaveLength(2);
    const descOf = (card: Element): Element => {
      const title = [...card.querySelectorAll(".title")].find((node) => node.textContent === "说明");
      expect(title).toBeDefined();
      return title!.nextElementSibling!;
    };

    // 档案里有昵称与厂商：胶囊写昵称，说明写得下后端代号，图标是那家的 logo。
    const named = cards[0]!;
    expect(named.querySelector(".listfieldbox .item .right")!.textContent).toBe("熊猫");
    expect(descOf(named).textContent).toBe("后端代号：a-1");
    expect(named.querySelector(".listfieldbox .item img")!.getAttribute("src")).toMatch(/codex-[ld]\.png/);

    // 档案里什么都没有：胶囊退回代号（不能是个没字的胶囊），
    // 厂商未知时摆 Tsunagou 自己的小标 —— 拿 DeepSeek 冒充会让人以为项目里真有个 DeepSeek。
    const unnamed = cards[1]!;
    expect(unnamed.querySelector(".listfieldbox .item .right")!.textContent).toBe("a-2");
    expect(descOf(unnamed).textContent).toBe("后端代号：a-2");
    expect(unnamed.querySelector(".listfieldbox .item img")!.getAttribute("src")).toMatch(/logo-little-[ld]\.png/);
  });

  /* 左栏项目卡片上那个主 Agent 胶囊走的是同一条"按 agent_id 从档案现算"的路。
     它以前是照着 agentIconFor 的默认值画的，而那个默认值是 DeepSeek 的鲸鱼图标 ——
     于是"厂商还不知道"在界面上长得像"这个 Agent 是 DeepSeek 的"。
     未知一律摆 Tsunagou 自己的小标，这条用例把两种取值都钉住。*/
  it("左栏主 Agent 的图标：厂商已知用厂商 logo，未知摆 Tsunagou 小标", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/api/v1/projects", {
        items: [{
          project_id: "p-1", name: "示例协作", lifecycle: "active", available: true,
          main_agent_id: "a-1", agents: [{ agent_id: "a-1", status: "active", role: "main" }],
        }],
      }],
    ];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const hit = replies.filter((pair) => path.indexOf(pair[0]) >= 0)[0];
      const body = hit ? hit[1] : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    /* 档案先回来，再画项目卡：卡片上的厂商是渲染那一刻从档案里按 id 取的。*/
    await win.Tsunagou.refresh(["settings"]);
    await win.Tsunagou.refresh(["projects"]);
    const chip = (): Element | null => page.querySelector("#projList .projItem .mainAgent img");
    expect(chip()).not.toBeNull();
    expect(chip()!.getAttribute("src")).toMatch(/logo-little-[ld]\.png/);

    // 档案里给了厂商：同一个位置换成那家的 logo，不再是"未知"。
    replies[0] = ["/console/profile", {
      version: 1, nickname: "", theme: "", agents: { "a-1": { vendor: "Codex" } },
    }];
    await win.Tsunagou.refresh(["settings"]);
    await win.Tsunagou.refresh(["projects"]);
    expect(chip()!.getAttribute("src")).toMatch(/codex-[ld]\.png/);
  });

  /* 已确认完工（lifecycle=completed）的协作必须离开"进行中的协作"那一组。
     控制台没有归档入口，分组若只认 archived，卡片会写着"已完成"却永远混在上面那一组。*/
  it("确认完工的协作归到「已完成的协作」组，状态文字与分组同一个判据", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/api/v1/projects", {
        items: [
          { project_id: "p-1", name: "还在进行", lifecycle: "active", available: true, main_agent_id: "a-1" },
          { project_id: "p-2", name: "已经完工", lifecycle: "completed", available: true, main_agent_id: "a-1" },
        ],
      }],
    ];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const hit = replies.filter((pair) => path.indexOf(pair[0]) >= 0)[0];
      const body = hit ? hit[1] : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    await win.Tsunagou.refresh(["settings"]);
    await win.Tsunagou.refresh(["projects"]);

    const rail = page.querySelector("#projList")!;
    const layout = [...rail.children].map((node) => node.classList.contains("wkTitle")
      ? node.textContent!.trim()
      : node.getAttribute("data-project-id"));
    expect(layout).toEqual(["进行中的协作", "p-1", "已完成的协作", "p-2"]);
    expect(rail.querySelector('.projItem[data-project-id="p-2"] .right p')!.textContent).toBe("已完成");
  });

  /* ---- 确认完工之后：只能在做项目时用的入口该消失 -------------------------
     判据只有一处：项目自己那份 project.json 里的 lifecycle（中间层随项目列表给过来，
     所以 daemon 停着也判得出来）。清理类动作不受影响：改昵称、删除、校验存档点、
     重试存档 —— 那些恰恰是收尾之后还要做的事。*/

  async function projectWith(lifecycle: string, stamp?: string): Promise<{
    win: { Tsunagou: { state: { set: (path: string, value: unknown) => void }; refresh: (keys?: string[]) => Promise<unknown>; dispatch: (type: string, payload?: unknown) => { ok: boolean } } };
  }> {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
        dispatch: (type: string, payload?: unknown) => { ok: boolean };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      /* 更具体的路径要排在前面：匹配是"包含即算"，`/api/v1/projects` 会先吃掉
         `/api/v1/projects/p-1/agents`（于是一个项目行被当成了一个 Agent）。*/
      ["/projects/p-1/agents", {
        items: [
          { agent_id: "a-1", role: "main", status: "active" },
          { agent_id: "a-2", role: "worker", status: "active" },
        ],
        main_agent_id: "a-1",
      }],
      ["/console/views/acceptance", {
        sources: {
          overview: { project_id: "p-1", name: "协作", lifecycle },
          tasks: [], agents: [], results: [], reviews: [], decisions: [],
        },
        missing: {},
        ...(stamp ? { history: { overview: stamp, tasks: stamp } } : {}),
      }],
      ["/api/v1/projects", {
        items: [{ project_id: "p-1", name: "协作", lifecycle, available: true, main_agent_id: "a-1" }],
      }],
    ];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const hit = replies.filter((pair) => path.indexOf(pair[0]) >= 0)[0];
      const body = hit ? hit[1] : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    await win.Tsunagou.refresh(["settings", "projects", "agents"]);
    return { win };
  }

  async function acceptanceFrom(
    win: { Tsunagou: { refresh: (keys?: string[]) => Promise<unknown>; dispatch: (type: string, payload?: unknown) => { ok: boolean } } },
  ): Promise<void> {
    /* 这一屏走真路径（refresh → 形状转换 → 渲染）：`history` 是**中间层**在回答里加的
       标记，直接 dispatch 原始 payload 会绕过那次转换，测的就不是真行为了。*/
    win.Tsunagou.dispatch("checkpoint.list", { latest: [], history: [] });
    await win.Tsunagou.refresh(["acceptance"]);
  }

  it("确认完工之后：接入 Agent / 立即存档 / 设为主 Agent 都不再画", async () => {
    const { win } = await projectWith("completed");
    await acceptanceFrom(win);

    expect(page.querySelector("#pane-agents .itemAdd")).toBeNull();
    expect(page.querySelector("#pane-agents")!.textContent).not.toContain("设为主 Agent");
    expect(page.querySelector("#pane-acceptance")!.textContent).not.toContain("立即存档");
    // 清理类动作留着：改昵称、删除一个 Agent 与"项目是否完工"无关。
    expect(page.querySelector("#pane-agents")!.textContent).toContain("修改");
  });

  it("还在进行的协作：这些入口照旧都在（同一条判据的另一半）", async () => {
    const { win } = await projectWith("active");
    await acceptanceFrom(win);

    expect(page.querySelector("#pane-agents .itemAdd")).not.toBeNull();
    expect(page.querySelector("#pane-agents")!.textContent).toContain("设为主 Agent");
    expect(page.querySelector("#pane-acceptance")!.textContent).toContain("立即存档");
  });

  it("daemon 停了但有记录：左栏卡片说得出上次记录到什么时候", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: { refresh: (keys?: string[]) => Promise<unknown> };
    };
    const body = {
      items: [{
        project_id: "p-1", name: "已经收尾", lifecycle: "completed", available: true,
        main_agent_id: "a-1", daemon: { url: "http://127.0.0.1:1" },
        history: { captured_at: "2026-10-03T06:14:00.000Z", sources: 6 },
      }],
    };
    win.fetch = () => Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)),
    });
    await win.Tsunagou.refresh(["projects"]);

    const card = page.querySelector('.projItem[data-project-id="p-1"]')!;
    // 端点文件还在、进程已经没了 —— 中间层如实说"无响应"，并补上"上次记录"。
    expect(card.textContent).toContain("daemon 无响应");
    expect(card.textContent).toContain("上次记录（记录到 2026-10-03 06:14）");
  });

  it("这一屏是从记录里拿的：面板上写明记录时刻，不装作现在", async () => {
    const { win } = await projectWith("completed", "2026-10-03T06:15:00.000Z");
    await acceptanceFrom(win);

    const pane = page.querySelector("#pane-acceptance")!;
    // 抬头是「上次记录」，正文写清记录到什么时候、以及 daemon 已经不在。
    expect(pane.textContent).toContain("上次记录");
    expect(pane.textContent).toContain("记录到 2026-10-03 06:15");
    expect(pane.textContent).toContain("daemon 已经不在");
  });

  /* 子 Agent 头像一行最多 3 个，多出来的用 `+N` 说明——N 是**没摆出来的**数量。
     以前 N 写的是总数：2 个成员会画成"2 个头像 +2"，看起来像有 4 个。*/
  it("子 Agent 头像最多 3 个，`+N` 只数没摆出来的那些", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const others = (count: number): Record<string, unknown>[] =>
      Array.from({ length: count }, (_, index) => ({
        agent_id: "a-" + index, status: "active", role: "worker",
      }));
    let members: Record<string, unknown>[] = [];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const body = path.indexOf("/console/profile") >= 0
        ? { version: 1, nickname: "", theme: "", agents: {} }
        : path.indexOf("/api/v1/projects") >= 0
          ? { items: [{
              project_id: "p-1", name: "示例协作", lifecycle: "active", available: true,
              main_agent_id: "a-main", agents: members,
            }] }
          : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    const cardFaces = (): { icons: number; plus: string } => {
      const row = page.querySelector('#projList .projItem .anotherAgent')!;
      return {
        icons: row.querySelectorAll("img").length,
        plus: row.querySelector(".plus")?.textContent ?? "",
      };
    };

    members = others(6);
    await win.Tsunagou.refresh(["settings"]);
    await win.Tsunagou.refresh(["projects"]);
    expect(cardFaces()).toEqual({ icons: 3, plus: "3" });

    // 刚好 3 个：全摆出来，没有 `+N`。
    members = others(3);
    await win.Tsunagou.refresh(["projects"]);
    expect(cardFaces()).toEqual({ icons: 3, plus: "" });

    // 2 个：以前这里会写"+2"（总数），现在什么都不加。
    members = others(2);
    await win.Tsunagou.refresh(["projects"]);
    expect(cardFaces()).toEqual({ icons: 2, plus: "" });
  });

  /* 2026-10-02：Agent 的「网络接入」标记（跨机器协作）——
     **本机接入的 Agent 什么都不画**（连右侧那个 <i> 图标都不出现），
     只有中间层说它是从网络接进来的才画「网络在线 / 网络离线」。
     中间层有两条通道，这里都要认：接口带 `network`/`online` 字段（随刷新到），
     以及运行时推送（dispatch `agent.network` / app.setAgentNetwork）。
     主 Agent 必须在 daemon 所在机器上 —— 它永远不算网络接入。*/
  it("网络接入标记：本机不画；接口字段与运行时推送都认，主 Agent 永远不算", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        dispatch: (type: string, payload?: unknown) => { ok: boolean };
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/projects/p-1/agents", {
        items: [
          { agent_id: "a-1", role: "main", status: "active" },
          { agent_id: "a-2", role: "worker", status: "active" },
          { agent_id: "a-3", role: "worker", status: "active", network: true, online: true },
          { agent_id: "a-4", role: "worker", status: "active", network: true },
        ],
        main_agent_id: "a-1",
      }],
    ];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const hit = replies.filter((pair) => path.indexOf(pair[0]) >= 0)[0];
      const body = hit ? hit[1] : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    await win.Tsunagou.refresh(["agents", "settings"]);

    const cards = () => [...page.querySelectorAll("#pane-agents .boxerbox > .item")];
    const badge = (index: number) => cards()[index]!.querySelector(".header .right");
    expect(cards()).toHaveLength(4);

    // 本机接入（主 Agent、以及中间层没表态的子 Agent）：连图标都不许出现。
    expect(badge(0)).toBeNull();
    expect(cards()[0]!.querySelector(".header")!.textContent).toBe("main");
    expect(badge(1)).toBeNull();

    // 中间层说是网络接入：在线/离线由 online 决定，图标在文字右侧。
    expect(badge(2)!.textContent).toBe("网络在线");
    expect(badge(2)!.querySelector("i.fa-solid.fa-circle-nodes")).not.toBeNull();
    expect(badge(3)!.textContent).toBe("网络离线");

    // 运行时推送：改的是同一个徽标，不用等下一次刷新。
    expect(win.Tsunagou.dispatch("agent.network", { agent_id: "a-2", online: true }).ok).toBe(true);
    expect(badge(1)!.textContent).toBe("网络在线");
    expect(win.Tsunagou.dispatch("agent.network", { agent_id: "a-2", online: false }).ok).toBe(true);
    expect(badge(1)!.textContent).toBe("网络离线");
    // 主 Agent 必须在 daemon 所在机器上：中间层推了也不画。
    expect(win.Tsunagou.dispatch("agent.network", { agent_id: "a-1", online: true }).ok).toBe(true);
    expect(badge(0)).toBeNull();
    // 撤回 → 回到本机（不画）。
    expect(win.Tsunagou.dispatch("agent.network.clear", { agent_id: "a-2" }).ok).toBe(true);
    expect(badge(1)).toBeNull();
  });

  /* 2026-10-03：远端**自报**的机器名跟着一起显示 —— 名单里要能看出是哪台机器。
     名字是"入席者说自己是谁"，不是系统认证出来的，所以它只影响这一句话。*/
  it("远端自报的机器名写在同一个标记里，本机接入仍然什么都不画", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/projects/p-1/agents", {
        items: [
          { agent_id: "a-1", role: "main", status: "active" },
          { agent_id: "a-2", role: "worker", status: "active", machine: "工位-七", online: true },
          { agent_id: "a-3", role: "worker", status: "active", machine: "NAS" },
        ],
        main_agent_id: "a-1",
      }],
    ];
    win.fetch = (url: string) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      const hit = replies.filter((pair) => path.indexOf(pair[0]) >= 0)[0];
      const body = hit ? hit[1] : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };
    win.Tsunagou.state.set("currentProjectId", "p-1");
    await win.Tsunagou.refresh(["agents", "settings"]);

    const cards = () => [...page.querySelectorAll("#pane-agents .boxerbox > .item")];
    const badge = (index: number) => cards()[index]!.querySelector(".header .right");
    /* 有机器名 = 远端：在线与否照旧由 online 说，名字跟在后面。*/
    expect(badge(1)!.textContent).toBe("网络在线 · 工位-七");
    expect(badge(1)!.querySelector("i.fa-solid.fa-circle-nodes")).not.toBeNull();
    expect(badge(2)!.textContent).toBe("网络离线 · NAS");
    /* 本机接入没有这一项 —— 连标记都不出现。*/
    expect(badge(0)).toBeNull();
  });

  /* 2026-10-03：Agent 详细窗口里的两行"跨机器才出现"—— 在哪台机器、这台机器做不到什么。
     唤醒是本机机制（主机叫不醒别的机器上的窗口），文件任务按 D191 直接拒绝。
     本机接入的 Agent 连标题都不出现，所以那个窗口和加这个功能之前一模一样。*/
  it("详细窗口：远端多出「在哪台机器 / 这台机器的限制」两行，本机接入不出现", () => {
    const win = dom.window as unknown as {
      Tsunagou: {
        state: { set: (path: string, value: unknown) => void };
        app: { openAgentInfo: (id: string) => boolean };
      };
    };
    const shown = (id: string) => {
      const node = page.querySelector<HTMLElement>("#" + id);
      return Boolean(node && node.style.display !== "none");
    };
    /* 名单窗口的行（中间层归一化后的样子）：一个本机、一个远端（没报副本）、一个远端（报了副本）。
       本机那一个用没被别的用例推过状态的 id —— 推来的网络状态会盖过数据里的。*/
    win.Tsunagou.state.set("agentsWindow", [
      { id: "p-1/a-7", agent_id: "a-7", project: "示例", task: "", network: false, online: false, machine: "" },
      { id: "p-1/a-2", agent_id: "a-2", project: "示例", task: "", network: true, online: true, machine: "工位-七" },
      { id: "p-1/a-3", agent_id: "a-3", project: "示例", task: "", network: true, online: true,
        machine: "NAS", copy_path: "D:\\work\\副本", copy_baseline: "main" },
    ]);

    win.Tsunagou.app.openAgentInfo("p-1/a-2");
    expect(shown("agentInfoMachineTitle")).toBe(true);
    expect(page.querySelector("#agentInfoMachine")?.textContent).toBe("工位-七");
    expect(shown("agentInfoCopyTitle")).toBe(false);
    expect(shown("agentInfoLimitsTitle")).toBe(true);
    expect(page.querySelector("#agentInfoLimits")?.textContent).toContain("叫不醒它");
    expect(page.querySelector("#agentInfoLimits")?.textContent).toContain("没报代码副本");

    /* 报了副本的远端：多一行"代码副本"，限制那句也跟着变（文件活能做，但证据是自报的）。*/
    win.Tsunagou.app.openAgentInfo("p-1/a-3");
    expect(shown("agentInfoCopyTitle")).toBe(true);
    expect(page.querySelector("#agentInfoCopy")?.textContent).toBe("D:\\work\\副本（main）");
    expect(page.querySelector("#agentInfoLimits")?.textContent).toContain("自报");

    win.Tsunagou.app.openAgentInfo("p-1/a-7");
    expect(shown("agentInfoMachineTitle")).toBe(false);
    expect(shown("agentInfoMachine")).toBe(false);
    expect(shown("agentInfoCopyTitle")).toBe(false);
    expect(shown("agentInfoCopy")).toBe(false);
    expect(shown("agentInfoLimitsTitle")).toBe(false);
    expect(shown("agentInfoLimits")).toBe(false);
  });

  it("DAG：有节点但彼此没依赖时，不再往画布上摆一块会压住节点的 .empty", () => {
    const dag = (dom.window as unknown as {
      Tsunagou: { dag: { setData: (sources: unknown) => unknown; render: () => unknown } };
    }).Tsunagou.dag;
    dag.setData({
      tasks: { items: [
        { task_id: "t-1", title: "协商接口并实现", status: "running", current_attempt_id: "at-1" },
        { task_id: "t-2", title: "写回归测试", status: "running", current_attempt_id: "at-2" },
      ] },
      attempts: { items: [
        { attempt_id: "at-1", task_id: "t-1", owner_agent_id: "a-1", status: "running" },
        { attempt_id: "at-2", task_id: "t-2", owner_agent_id: "a-2", status: "running" },
      ] },
      agents: { items: [{ agent_id: "a-1", role: "worker" }, { agent_id: "a-2", role: "worker" }] },
    });
    dag.render();

    const canvas = page.querySelector("#canvas")!;
    expect(canvas.querySelectorAll(".node")).toHaveLength(2);
    /* 节点是绝对定位的，.empty 是流转内的块 —— 两者同时存在就会叠字
       （曾经那句「都是独立任务」正好压在第一个节点上）。那句话改由通知说。*/
    expect(canvas.querySelector(".empty")).toBeNull();
  });

  /* 2026-10-01：项目目标不再由建项目时的向导收集。
     它是用户与主 Agent 谈定、**用户确认过**的一条决定（kind=project.objective，
     见 docs/decisions/2026-10-01-objective-from-dialogue.md）：主 Agent 提，用户在
     「待用户决定」里答，答完之后界面才把它当目标显示；没确认过就显示项目记录里那句
     （后端写的占位）。计划（coordination.plan）的抬头故意不算数 —— 那是"这一批任务
     要干什么"，换个阶段就会变，不能冒充整个项目的目标。*/
  it("新建协作向导第 1 步只问名字，目标不由向导收集", () => {
    const step1 = page.querySelector("#newXz1");
    expect(step1).not.toBeNull();
    // 只剩"名字"一个框；那个问目标的框连它的说明文字一起撤掉了。
    expect(step1!.querySelectorAll("input")).toHaveLength(1);
    expect(readWeb("index.html")).not.toContain("这次协作的目标");

    // 收集出来的草稿里不再有 objective 这个键：留个永远为空的字段只会又骗人一次。
    const collected = (dom.window as unknown as {
      Tsunagou: { ui: { wizard: { collect: () => Record<string, unknown> } } };
    }).Tsunagou.ui.wizard.collect();
    expect(collected).toHaveProperty("name");
    expect(collected).not.toHaveProperty("objective");
  });

  it("主视图的目标只用「用户确认过」的那条决定，没有就回落到项目记录里那句", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const overview = (decisions: unknown[]) => ({
      project_id: "p-1",
      view: "overview",
      missing: {},
      sources: {
        overview: {
          project_id: "p-1", name: "示例协作", objective: "待主 Agent 与用户确认",
          lifecycle: "active", policy_revision: 1, roots: [], repositories: [],
        },
        agents: { items: [] },
        tasks: { items: [] },
        cognition: { reports: [] },
        checkpoints: { items: [] },
        decisions: { items: decisions },
      },
    });
    const serve = (payload: unknown) => {
      win.fetch = () =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(payload),
          text: () => Promise.resolve(JSON.stringify(payload)),
        });
    };
    const shown = () => page.querySelector("#pane-overview .textArea")!.textContent;

    win.Tsunagou.state.set("currentProjectId", "p-1");

    // ① 只是"待用户决定"，还没人答：显示项目记录里那句，不拿没确认的话冒充目标。
    serve(overview([
      { decision_id: "d-1", kind: "project.objective", status: "pending", summary: "还没人答的那句" },
    ]));
    await win.Tsunagou.refresh(["project"]);
    expect(shown()).toBe("待主 Agent 与用户确认");

    // ② 用户答过：主视图写的就是那句目标本身。
    serve(overview([
      { decision_id: "d-1", kind: "project.objective", status: "resolved", summary: "让两个 Agent 对齐 API" },
    ]));
    await win.Tsunagou.refresh(["project"]);
    expect(shown()).toBe("让两个 Agent 对齐 API");

    // ③ 确认过两次：取最后一条（最新的那版理解），不是最早那条。
    serve(overview([
      { decision_id: "d-1", kind: "project.objective", status: "resolved", summary: "旧的理解" },
      { decision_id: "d-2", kind: "project.objective", status: "resolved", summary: "新的理解" },
    ]));
    await win.Tsunagou.refresh(["project"]);
    expect(shown()).toBe("新的理解");

    // ④ 别的 kind 不算数：重大设计决定被确认了也不等于项目目标。
    serve(overview([
      { decision_id: "d-3", kind: "design.change", status: "resolved", summary: "换个方案" },
    ]));
    await win.Tsunagou.refresh(["project"]);
    expect(shown()).toBe("待主 Agent 与用户确认");
  });

});

type EnrollmentApi = ConsoleApi & {
  state: { set: (path: string, value: unknown) => void; get: (path: string) => unknown };
  ui: {
    wizard: { go: (n: number) => number; next: () => Promise<unknown>; current: () => number };
    window: { isOpen: (id: string) => boolean };
    choosebox: { setValue: (id: string, value: string, options: { silent: boolean }) => void };
  };
  notify: { loadingEnd: () => boolean; cancelWaiting: () => Promise<boolean> };
  dialog: { confirm: () => Promise<boolean> };
  actions: { addSubAgent: (payload: Record<string, unknown>) => Promise<unknown> };
  app: { confirmNetworkInvite: () => boolean; cancelNetworkInvite: () => boolean };
};

describe("控制台接入等待与取消", () => {
  let enrollmentDom: JSDOM;
  let enrollmentApi: EnrollmentApi;
  let enrollmentPage: Document;
  let prepareBody: Record<string, unknown>;
  let statusBody: Record<string, unknown>;
  let observeBody: Record<string, unknown>;
  let cancelBody: Record<string, unknown>;
  let cancelStatus: number;
  let prepareStatus: number;
  let prepareGate: Promise<void> | undefined;
  let cancelGate: Promise<void> | undefined;
  let calls: Array<{ url: string; body: Record<string, unknown> }>;
  const projectPath = "E:/Tsunagou/projects/示例协作";
  const text = () => enrollmentPage.querySelector("#loadW .textW")?.textContent ?? "";
  /* 顶部那一句话提示（notify.info / notify.error 都写这里） */
  const tip = () => enrollmentPage.querySelector("#AnnounceMent2 .aText")?.textContent ?? "";

  async function loadPage(current: Record<string, unknown> = { status: "none" }, remembered = "") {
    enrollmentDom = new JSDOM(readWeb("index.html"), {
      url: "http://127.0.0.1:55862/?poll_ms=0", runScripts: "outside-only", pretendToBeVisual: true,
    });
    const win = enrollmentDom.window;
    if (remembered) win.localStorage.setItem("tsunagou.console.lastProject", remembered);
    win.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown> });
      let body: unknown = {};
      let status = 200;
      if (url.includes("agents:prepare")) { await prepareGate; body = prepareBody; status = prepareStatus; }
      else if (url.includes(":cancel")) { await cancelGate; body = cancelBody; status = cancelStatus; }
      else if (url.includes("enrollments:observe")) body = observeBody;
      else if (url.endsWith("/enrollments/current")) body = current;
      else if (url.includes("/enrollments/")) body = statusBody;
      else if (url.includes("/projects?agents=1")) body = { items: [
        { project_id: "p-1", name: "示例协作", path: projectPath, available: true },
        { project_id: "p-2", name: "另一个协作", path: "E:/Other", available: true },
      ] };
      return { ok: status < 400, status, text: async () => JSON.stringify(body) } as Response;
    }) as typeof fetch;
    win.eval(readWeb("console.config.js"));
    win.eval(readWeb("assets/js/behavior.js"));
    enrollmentPage = win.document;
    enrollmentApi = (win as unknown as { Tsunagou: EnrollmentApi }).Tsunagou;
    /* jsdom 不排版；只替换可见性判断，真实窗口开关仍由页面代码执行。*/
    enrollmentApi.ui.window.isOpen = (id) => {
      const node = enrollmentPage.getElementById(id);
      return Boolean(node && node.style.display && node.style.display !== "none");
    };
    await vi.advanceTimersByTimeAsync(0);
  }

  beforeEach(async () => {
    vi.useFakeTimers();
    prepareBody = {
      status: "prepared", enrollment_id: "e-1", profile: "p",
      host_registration: { status: "deferred" },
    };
    statusBody = { status: "waiting", phase: "pending", enrollment_id: "e-1" };
    observeBody = { status: "waiting", adapter: "deepseek" };
    cancelBody = { status: "cancelled", note: "已取消这次待接入申请" };
    cancelStatus = 200;
    prepareStatus = 200;
    prepareGate = undefined;
    cancelGate = undefined;
    calls = [];
    await loadPage();
    enrollmentApi.dispatch("project.list", [
      { id: "p-1", name: "示例协作", path: projectPath, available: true },
    ]);
    enrollmentApi.state.set("hosts", [
      { adapter: "codex", label: "Codex", mode: "console" },
      { adapter: "opencode", label: "OpenCode", mode: "console" },
    ]);
    enrollmentApi.state.set("currentProjectId", "p-1");
    enrollmentApi.state.set("wizard.project", { id: "p-1", name: "示例协作" });
    enrollmentApi.ui.wizard.go(2);
    (enrollmentPage.querySelector("#newXz2 input") as HTMLInputElement).value = "熊猫";
  });

  afterEach(() => {
    enrollmentApi.stopPolling?.();
    enrollmentDom.window.close();
    vi.useRealTimers();
  });

  it("Codex deferred 等待一句话接入，只有 arrived 才完成主 Agent 向导", async () => {
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(text()).toContain("请接入 Tsunagou");
    expect(text()).not.toContain(projectPath);
    expect(text()).not.toContain("主 Agent 身份");
    expect(calls.find((call) => call.url.includes("agents:prepare"))?.body.role).toBe("main");
    await vi.advanceTimersByTimeAsync(2000);
    expect(enrollmentApi.ui.wizard.current()).toBe(2);
    expect(enrollmentApi.state.get("wizard.main")).toBeNull();
    statusBody = { status: "arrived", enrollment_id: "e-1", agent_id: "a-own", role: "main" };
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
    expect(enrollmentApi.state.get("wizard.main")).toMatchObject({ agent_id: "a-own", status: "arrived" });
  });

  it.each(["pending", "connecting", "enrolled", "failed"])("%s 阶段使用后端说明，不自行承诺就绪", async (phase) => {
    const note = "本次阶段：" + phase + "；请在原对话按接入结果继续。";
    statusBody = {
      status: "waiting", phase, enrollment_id: "e-1", note,
      pending: { agent_id: "a-own", role: "worker", session_status: "degraded" },
    };
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(2000);
    expect(text()).toBe(note);
    expect(enrollmentApi.ui.wizard.current()).toBe(2);
    enrollmentApi.notify.loadingEnd();
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
  });

  it("OpenCode 保留项目目录和宿主加载提示", async () => {
    prepareBody.host_registration = { status: "registered" };
    enrollmentApi.ui.choosebox.setValue("newXz2Vendor", "OpenCode", { silent: true });
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(text()).toContain(projectPath);
    expect(text()).toContain("OpenCode");
    expect(text()).toContain("打开/重载");
    enrollmentApi.notify.loadingEnd();
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
  });

  it("OpenCode 等待时照抄中间层给的会话名，页面不自己编", async () => {
    prepareBody.host_registration = { status: "registered" };
    prepareBody.next = "在这个项目里用会话名 ses_p 打开 OpenCode（opencode --session ses_p），reload 一次。";
    enrollmentApi.ui.choosebox.setValue("newXz2Vendor", "OpenCode", { silent: true });
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(text()).toContain("ses_p");
    expect(text()).not.toContain("打开/重载");
    enrollmentApi.notify.loadingEnd();
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
  });

  /* 「位置＝网络」这条路：主机签一张邀请，人把它交给另一台机器；确认后才开始等席位。
     编号那一格只在"网络 + 会话名自己说了算的厂商"（Codex / DeepSeek Harness）出现 ——
     OpenCode 的会话名由主机起，所以不用问。*/
  it("网络接入：要编号、给邀请、确认后等席位，OpenCode 不需要编号", async () => {
    const field = () => enrollmentPage.querySelector<HTMLElement>("#addSubAgentAddr");
    const place = () => enrollmentPage.querySelector<HTMLElement>("#addSubAgent .choosebox.TOG0");
    const vendor = () => enrollmentPage.querySelector<HTMLElement>("#addSubAgent .choosebox.TOG1");
    const shown = (node: HTMLElement | null) => Boolean(node && node.style.display !== "none");
    /* 让"选择框变了"这件事真的发生：silent 会吞掉 choosebox:change。*/
    const choose = (id: string, value: string) => {
      enrollmentApi.ui.choosebox.setValue(id, value, { silent: false });
    };

    choose("addSubAgentVendor", "Codex");
    choose("addSubAgentPlace", "网络");
    expect(shown(field())).toBe(true);
    expect(field()?.querySelector("input")?.getAttribute("placeholder")).toBe("网络 Agent 编号");
    expect(shown(place())).toBe(true);
    expect(enrollmentPage.querySelector("#addSubAgent .choosebox.TOG1")?.textContent).toContain("Codex");

    /* OpenCode：名字我们起，不需要编号这一格 */
    choose("addSubAgentVendor", "OpenCode");
    expect(shown(field())).toBe(false);
    /* 本机接入：更不需要 */
    choose("addSubAgentVendor", "Codex");
    choose("addSubAgentPlace", "本机");
    expect(shown(field())).toBe(false);

    /* 回到网络 + Codex，走一遍：确定 → 邀请窗口 → 开始等待 → 席位出现 */
    choose("addSubAgentPlace", "网络");
    expect(shown(field())).toBe(true);
    prepareBody = {
      status: "invited", invite: "tsunagou-invite-v1:AAAA", enrollment_id: "e-net",
      expires_in_seconds: 600, expires_at: "2026-10-02T14:10:00.000Z",
      url: "http://10.0.0.5:2810", conversation_id: "thread-abc",
    };
    const done = enrollmentApi.actions.addSubAgent({
      name: "小三", vendor: "Codex", place: "network", number: "thread-abc",
    });
    await vi.advanceTimersByTimeAsync(0);

    const prepared = calls.filter((call) => call.url.includes("agents:prepare"));
    expect(prepared).toHaveLength(1);
    expect(prepared[0]!.body).toMatchObject({
      vendor: "codex", place: "network", conversation_id: "thread-abc", role: "worker",
    });
    /* 邀请摆在一个窗口里，内容原样放在只读输入框里等人复制 */
    expect(enrollmentApi.ui.window.isOpen("netInvite")).toBe(true);
    const inviteInput = enrollmentPage.querySelector<HTMLInputElement>("#netInvite .textbox2 input");
    expect(inviteInput?.value).toBe("tsunagou-invite-v1:AAAA");
    expect(inviteInput?.hasAttribute("readonly")).toBe(true);

    /* 确认（人已把内容转交）→ 加载框 → 席位出现。
       jsdom 不跑行内 onclick，所以直接调那个动作（页面上是按钮，行为一致）。*/
    expect(enrollmentApi.app.confirmNetworkInvite()).toBe(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(enrollmentApi.ui.window.isOpen("netInvite")).toBe(false);
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(true);
    expect(text()).toContain("交给");

    /* 等待是每 2 秒问一次中间层"名单里出现它了吗"（与其它等待同一套） */
    await vi.advanceTimersByTimeAsync(2000);
    const asked = calls.filter((call) => call.url.includes("enrollments:observe"));
    expect(asked.length).toBeGreaterThanOrEqual(1);
    expect(decodeURIComponent(asked[0]!.url)).toContain("enrollment_id=e-net");
    observeBody = { status: "arrived", adapter: "codex", agent: { agent_id: "a-net" } };
    await vi.advanceTimersByTimeAsync(2000);
    await done;
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
    expect(enrollmentApi.ui.window.isOpen("addSubAgent")).toBe(false);
    expect(vendor()).not.toBeNull();
  });

  it("网络接入点「取消」：邀请作废（撤掉那条申请），不进等待", async () => {
    enrollmentApi.state.set("hosts", [
      { adapter: "codex", label: "Codex", mode: "console" },
    ]);
    prepareBody = {
      status: "invited", invite: "tsunagou-invite-v1:BBBB", enrollment_id: "e-cancel",
      expires_in_seconds: 600, expires_at: "2026-10-02T14:10:00.000Z", url: "http://10.0.0.5:2810",
    };
    const done = enrollmentApi.actions.addSubAgent({
      name: "小三", vendor: "Codex", place: "network", number: "thread-abc",
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(enrollmentApi.ui.window.isOpen("netInvite")).toBe(true);

    enrollmentApi.app.cancelNetworkInvite();
    await vi.advanceTimersByTimeAsync(0);
    await done;

    const cancelled = calls.filter((call) => call.url.includes(":cancel"));
    expect(cancelled).toHaveLength(1);
    expect(decodeURIComponent(cancelled[0]!.url)).toContain("e-cancel");
    expect(enrollmentApi.ui.window.isOpen("netInvite")).toBe(false);
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
  });

  /* 宿主自己在聊天里接入的那一种（DeepSeek Harness）：控制台不签票，但**必须把
     "谁要接哪个项目、什么角色"记在机器上** —— 那条聊天里说"请接入 Tsunagou"时只有自己的
     会话 id 和工作目录，工作目录常常不是协调仓库。然后开同一块遮罩等名单里出现它，
     判断在中间层（它拿接入材料当证据），页面不数人头。*/
  it("宿主自己接入的厂商：先记下接哪个项目，再开等待遮罩等它出现在名单里", async () => {
    enrollmentApi.state.set("hosts", [
      { adapter: "deepseek", label: "DeepSeek Harness", mode: "in_host", note: "在 DeepSeek Harness 自己的桌面聊天里接入。" },
      { adapter: "claudecode", label: "Claude Code", mode: "unsupported", note: "Claude Code 的 MCP 注册还没实现。" },
    ]);
    enrollmentApi.ui.choosebox.setValue("newXz2Vendor", "DeepSeek Harness", { silent: true });
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    /* 先写记录：那条聊天靠它才查得到项目与角色（命令只能是 prepare 这条写门） */
    const prepared = calls.filter((call) => call.url.includes("agents:prepare"));
    expect(prepared).toHaveLength(1);
    expect(prepared[0]!.body).toMatchObject({ vendor: "deepseek", role: "main" });
    /* 遮罩上是中间层那句指路（页面不自己编步骤）+ 项目目录 + 这次的身份 + "正在等待" */
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(true);
    expect(text()).toContain("自己的桌面聊天里接入");
    expect(text()).toContain(projectPath);
    expect(text()).toContain("正在等待它出现");
    /* 身份必须写出来：那条聊天把它交给 tsunagou_connect 的 role */
    expect(text()).toContain("以主 Agent 身份接入");
    await vi.advanceTimersByTimeAsync(2000);
    const asked = calls.filter((call) => call.url.includes("enrollments:observe"));
    expect(asked).toHaveLength(1);
    expect(decodeURIComponent(asked[0]!.url)).toContain("adapter=deepseek");
    expect(decodeURIComponent(asked[0]!.url)).toContain("enrollment_id=e-1");
    /* 中间层说"连上了但角色不对"：照它的话说，并且身份照旧带上，不报成功 */
    observeBody = {
      status: "waiting",
      note: "有个席位连上了，但它的角色是子 Agent，不是这次申请的主 Agent。",
    };
    await vi.advanceTimersByTimeAsync(2000);
    expect(text()).toContain("角色是子 Agent");
    expect(text()).toContain("以主 Agent 身份接入");
    expect(enrollmentApi.ui.wizard.current()).toBe(2);
    /* 中间层说到了：遮罩收起、主 Agent 落到第 3 步 */
    observeBody = { status: "arrived", adapter: "deepseek", agent: { agent_id: "a-own" } };
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
    expect(enrollmentApi.state.get("wizard.main")).toMatchObject({ agent_id: "a-own", status: "arrived" });
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
  });

  it("宿主自己接入时点「取消」撤掉刚记下的那条申请，并停止等待", async () => {
    enrollmentApi.state.set("hosts", [
      { adapter: "deepseek", label: "DeepSeek Harness", mode: "in_host", note: "在它自己的聊天里接入。" },
    ]);
    enrollmentApi.ui.choosebox.setValue("newXz2Vendor", "DeepSeek Harness", { silent: true });
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    enrollmentApi.dialog.confirm = async () => true;
    expect(await enrollmentApi.notify.cancelWaiting()).toBe(true);
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    /* 没有票要作废，但记录得撤：那条聊天可能正靠它找项目 */
    const cancelled = calls.filter((call) => call.url.includes(":cancel"));
    expect(cancelled).toHaveLength(1);
    expect(decodeURIComponent(cancelled[0]!.url)).toContain("e-1");
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
    expect(tip()).toContain("已撤掉");
  });

  it("还没做的厂商点了下一步只给一句话，绝不发准备请求", async () => {
    enrollmentApi.state.set("hosts", [
      { adapter: "deepseek", label: "DeepSeek Harness", mode: "in_host", note: "在 DeepSeek Harness 自己的桌面聊天里接入。" },
      { adapter: "claudecode", label: "Claude Code", mode: "unsupported", note: "Claude Code 的 MCP 注册还没实现。" },
    ]);
    enrollmentApi.ui.choosebox.setValue("newXz2Vendor", "Claude Code", { silent: true });
    await enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(tip()).toContain("还没实现");
    expect(calls.filter((call) => call.url.includes("agents:prepare"))).toHaveLength(0);
    expect(enrollmentApi.ui.wizard.current()).toBe(2);
  });

  it("拒绝确认保留取消入口，确认后以服务端 cancelled 为准", async () => {
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    enrollmentApi.dialog.confirm = async () => false;
    expect(await enrollmentApi.notify.cancelWaiting()).toBe(false);
    expect(calls.filter((call) => call.url.includes(":cancel"))).toHaveLength(0);
    enrollmentApi.dialog.confirm = async () => true;
    expect(await enrollmentApi.notify.cancelWaiting()).toBe(true);
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(calls.filter((call) => call.url.includes(":cancel"))).toHaveLength(1);
    expect(enrollmentApi.ui.wizard.current()).toBe(2);
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
  });

  it("取消被 409 拒绝时继续等待，不把已认领申请报成已取消", async () => {
    cancelStatus = 409;
    cancelBody = { detail: { code: "enrollment_already_claimed", message: "原会话已经开始接入，不能取消" } };
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    enrollmentApi.dialog.confirm = async () => true;
    await enrollmentApi.notify.cancelWaiting();
    await vi.advanceTimersByTimeAsync(0);
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(true);
    expect(text()).not.toContain("已取消");
    expect(text()).toContain("已经开始接入");
    statusBody = { status: "arrived", enrollment_id: "e-1", agent_id: "a-own", role: "main" };
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
    expect(enrollmentApi.state.get("wizard.main")).toMatchObject({ status: "arrived" });
  });

  it("准备尚未返回时取消，取得申请编号后真正向后端取消", async () => {
    let releasePrepare!: () => void;
    prepareGate = new Promise<void>((resolve) => { releasePrepare = resolve; });
    const pending = enrollmentApi.ui.wizard.next();
    enrollmentApi.dialog.confirm = async () => true;
    await enrollmentApi.notify.cancelWaiting();
    await vi.advanceTimersByTimeAsync(0);
    expect(calls.filter((call) => call.url.includes(":cancel"))).toHaveLength(0);
    releasePrepare();
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(calls.filter((call) => call.url.includes("e-1:cancel"))).toHaveLength(1);
    expect(enrollmentApi.ui.wizard.current()).toBe(2);
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
  });

  it("到达后才返回的取消拒绝不重新打开等待遮罩", async () => {
    let releaseCancel!: () => void;
    cancelGate = new Promise<void>((resolve) => { releaseCancel = resolve; });
    cancelStatus = 409;
    cancelBody = { detail: { code: "enrollment_already_arrived" } };
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    enrollmentApi.dialog.confirm = async () => true;
    await enrollmentApi.notify.cancelWaiting();
    statusBody = { status: "arrived", enrollment_id: "e-1", agent_id: "a-own", role: "main" };
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
    releaseCancel();
    await vi.advanceTimersByTimeAsync(0);
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
  });

  it.each(["原来的名字", ""])("重复准备保留原昵称 %j，不用重试表单覆盖", async (nickname) => {
    prepareBody.nickname = nickname;
    const pending = enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    statusBody = { status: "arrived", enrollment_id: "e-1", agent_id: "a-own", role: "main" };
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(enrollmentApi.state.get("wizard.main")).toMatchObject({ name: nickname });
    const profileSave = calls.find((call) => call.url.endsWith("/console/profile") && call.body.agents);
    expect(profileSave?.body.agents).toMatchObject({ "a-own": { nickname } });
  });

  it("其他项目或角色的申请冲突说明原选择，不完成当前向导", async () => {
    prepareStatus = 409;
    prepareBody = { detail: {
      code: "enrollment_already_pending", enrollment: { project_id: "p-2", role: "worker", enrollment_id: "e-other" },
      note: "请先处理原申请，已认领时在原聊天继续完成。",
    } };
    await enrollmentApi.ui.wizard.next();
    expect(enrollmentPage.querySelector("#AnnounceMent2 .aText")?.textContent).toContain("p-2");
    expect(enrollmentPage.querySelector("#AnnounceMent2 .aText")?.textContent).toContain("子 Agent");
    expect(enrollmentPage.querySelector("#AnnounceMent2 .aText")?.textContent).toContain("原聊天继续");
    expect(enrollmentApi.ui.wizard.current()).toBe(2);
    expect(calls.some((call) => call.url.includes("e-other"))).toBe(false);
  });

  it.each(["p-1", "p-2"])("刷新恢复待接入申请，保留当前选择 %s 且不推进旧向导", async (remembered) => {
    enrollmentDom.window.close();
    calls = [];
    await loadPage({
      status: "waiting", enrollment_id: "e-1", project_id: "p-1", role: "main", nickname: "熊猫", phase: "pending",
      note: "请接入 Tsunagou。",
    }, remembered);
    expect(calls.some((call) => call.url.endsWith("/enrollments/current"))).toBe(true);
    expect(calls.some((call) => call.url.includes("agents:prepare"))).toBe(false);
    expect(text()).toContain("示例协作");
    expect(text()).toContain("主 Agent");
    expect(enrollmentApi.state.get("currentProjectId")).toBe(remembered);
    expect(enrollmentApi.ui.wizard.current()).toBe(1);
    calls = [];
    statusBody = { status: "arrived", enrollment_id: "e-1", project_id: "p-1", agent_id: "a-own", role: "main" };
    await vi.advanceTimersByTimeAsync(2000);
    expect(enrollmentApi.state.get("currentProjectId")).toBe(remembered);
    expect(enrollmentApi.ui.wizard.current()).toBe(1);
    expect(enrollmentApi.state.get("wizard.main")).toBeNull();
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
    expect(calls.some((call) => call.url.includes("/projects/" + remembered + "/agents"))).toBe(remembered === "p-1");
  });

  it("刷新恢复后可以取消未认领申请，无需重新准备或重新打开向导", async () => {
    enrollmentDom.window.close();
    calls = [];
    await loadPage({
      status: "waiting", enrollment_id: "e-1", project_id: "p-1", role: "main", nickname: "熊猫", phase: "pending",
    }, "p-1");
    enrollmentApi.dialog.confirm = async () => true;
    await enrollmentApi.notify.cancelWaiting();
    await vi.advanceTimersByTimeAsync(2000);
    expect(calls.filter((call) => call.url.includes("e-1:cancel"))).toHaveLength(1);
    expect(calls.some((call) => call.url.includes("agents:prepare"))).toBe(false);
    expect(enrollmentApi.ui.wizard.current()).toBe(1);
    expect(enrollmentApi.ui.window.isOpen("loadW")).toBe(false);
  });

  /* 测试同事报的那个 bug 就落在这条路上：刷新之后，一条 DeepSeek Harness 的申请被当成
     Codex 的申请去等（写死 adapter/label），到达到时还会把它的厂商记成 Codex —— 于是
     页面上这个 Agent 从此一直显示成另一家的图标。这里钉住"按申请自己的宿主说话"。
     等待本身由中间层那条"没有回执就按名单判定"的路负责翻绿，这一条只管页面这半边。*/
  it("刷新恢复一条宿主自己接入的申请：按它自己的宿主等，到达时厂商也记它自己那家", async () => {
    enrollmentDom.window.close();
    calls = [];
    await loadPage({
      status: "waiting", phase: "pending", enrollment_id: "e-7", project_id: "p-1",
      role: "worker", nickname: "远端小三", vendor: "deepseek", label: "DeepSeek Harness",
    }, "p-1");
    await vi.advanceTimersByTimeAsync(0);
    expect(calls.some((call) => call.url.includes("agents:prepare"))).toBe(false);
    await vi.advanceTimersByTimeAsync(2000);
    expect(calls.some((call) => call.url.includes("/enrollments/e-7"))).toBe(true);
    statusBody = { status: "arrived", enrollment_id: "e-7", agent_id: "a-dsh", role: "worker" };
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(0);
    /* 档案写入门与读取是同一个 URL，所以按**载荷**认那一次写入（`api.post` 会把 `patch`
       那层拆掉，落到后端的就是 `{agents: …}`）。*/
    const wrote = calls
      .map((call) => call.body as { agents?: Record<string, { vendor?: string }> })
      .filter((body) => Boolean(body?.agents?.["a-dsh"]));
    expect(wrote).toHaveLength(1);
    expect(wrote[0]!.agents!["a-dsh"]!.vendor).toBe("DeepSeek Harness");
  });
});
