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
      time: "服务运行中",
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
            summary: "有结果待验收", status: "pending", obligations: [{ status: "open" }],
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
    expect(shown).toContain("有结果待验收");
  });

  /* 2026-10-04 用户要求：消息表最左边加一栏时间，并按时间排序（新的在上）。*/
  it("消息表最左边是时间，且按时间倒序", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const message = (id: string, summary: string, createdAt: string) => ({
      message_id: id, sender_agent_id: "a-1", recipient_agent_id: "user_control",
      summary: summary, status: "none", obligations: [], created_at: createdAt,
    });
    const replies: [string, unknown][] = [
      ["/console/views/collaboration", { sources: {
        agents: { items: [{ agent_id: "a-1", status: "active", role: "worker" }] },
        // 故意乱序给进来：排序是页面的事，不能指望后端按时间给。
        messages: { items: [
          message("m-old", "最早的一条", "2026-10-04T02:00:00.000Z"),
          message("m-new", "最新的一条", "2026-10-04T04:00:00.000Z"),
          message("m-mid", "中间那条", "2026-10-04T03:00:00.000Z"),
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
    await win.Tsunagou.refresh(["conflicts"]);

    const rows = [...page.querySelectorAll("#block-conflict [data-row-id]")]
      .filter((node) => String(node.getAttribute("data-row-id")).indexOf("m-") === 0);
    expect(rows.map((node) => node.getAttribute("data-row-id")))
      .toEqual(["m-new", "m-mid", "m-old"]);
    // 最左边那一格是时间（本地时区，页面统一的颗粒度里带"月日"）。
    expect(rows[0]!.querySelector(".colu-m")!.textContent).toContain("月");
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
    /* 左栏结构：两组各自「标题（带本组自己的放大镜与齿轮）→ 本组搜索条 → 本组卡片 →
       本组那句空文案」，全都画在 #projList 里；空文案借 `.emptybox`，**自己不带字**
       —— 那句话由 CSS 的 ::before 填，两组共用同一句（2026-10-04 用户选定的口径）。
       本组有卡片时那句空文案只是被 display:none 藏着 —— 元素一直在，才能按组切换显隐。*/
    const label = (node: Element) => node.classList.contains("wkTitle")
      ? `${node.getAttribute("data-proj-group")}:${node.textContent!.trim()}`
      : (node.classList.contains("searchBar")
        ? `搜索条(${node.getAttribute("data-proj-group")})`
        : (node.hasAttribute("data-proj-blank")
          ? `没有协作(${node.getAttribute("data-proj-blank")})`
          : node.getAttribute("data-project-id")));
    expect(page.querySelector("#projHead")).toBeNull();
    expect([...rail.children].map(label)).toEqual([
      "active:进行中的协作", "搜索条(active)", "p-1", "没有协作(active)",
      "done:已完成的协作", "搜索条(done)", "p-2", "没有协作(done)",
    ]);
    // 每张卡片自己带着分组属性；卡片外面**没有**多包一层容器（那会把卡片样式弄没）。
    expect([...rail.querySelectorAll(".projItem")].map((node) => node.getAttribute("data-proj-group")))
      .toEqual(["active", "done"]);
    expect(rail.querySelectorAll(".projItem .projItem")).toHaveLength(0);
    // 两组各自的放大镜与齿轮都在（顺序就是那一组标题右边的两个键）。
    expect([...rail.querySelectorAll(".wkTbtn")].map((node) => node.getAttribute("data-tg-role")))
      .toEqual(["project-search", "project-sort", "project-search", "project-sort"]);
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
    // 端点文件还在、进程已经没了。这一份是**已完工**的协作：它的 daemon 是完工确认成功后
    // 按设计退出的（自动关闭、把端口让出来），所以文案说"已退出"而不是"无响应"——
    // 后者是故障的说法，把正常收尾说成故障会让人以为出了问题。并补上"上次记录"。
    expect(card.textContent).toContain("服务已退出（完工后自动关闭）");
    expect(card.textContent).not.toContain("服务无响应");
    expect(card.textContent).toContain("上次记录（记录到 2026-10-03 06:14）");
  });

  it("还没完工的协作、daemon 却没了：这才叫服务无响应", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: { refresh: (keys?: string[]) => Promise<unknown> };
    };
    const body = {
      items: [{
        project_id: "p-2", name: "还在进行", lifecycle: "active", available: true,
        main_agent_id: "a-1", daemon: { url: "http://127.0.0.1:1" },
        history: { captured_at: "2026-10-03T06:14:00.000Z", sources: 6 },
      }],
    };
    win.fetch = () => Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)),
    });
    await win.Tsunagou.refresh(["projects"]);

    const card = page.querySelector('.projItem[data-project-id="p-2"]')!;
    // 没完工就没了 = 真的没响应，这一句必须留着，别被上一条改宽了。
    expect(card.textContent).toContain("服务无响应");
    expect(card.textContent).not.toContain("服务已退出");
  });

  it("这一屏是从记录里拿的：面板上写明记录时刻，不装作现在", async () => {
    const { win } = await projectWith("completed", "2026-10-03T06:15:00.000Z");
    await acceptanceFrom(win);

    const pane = page.querySelector("#pane-acceptance")!;
    // 抬头是「上次记录」，正文写清记录到什么时候、以及 daemon 已经不在。
    expect(pane.textContent).toContain("上次记录");
    expect(pane.textContent).toContain("记录到 2026-10-03 06:15");
    expect(pane.textContent).toContain("服务已经不在");
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
     只有中间层说它是从网络接进来的才画这个标记；写出来的那句是**会话状态**
     （就绪/降级中/已结束 —— 2026-10-04 起取代了"网络在线/网络离线"，
     因为协议里没有心跳，谁也不知道对端机器还在不在）。
     中间层有两条通道，这里都要认：接口带 `network` 字段（随刷新到），
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
      /* 词表这一份是给页面别处的机械替换用的（角色/状态词）。徽标本身不看它了 ——
         徽标现在只认心跳算出来的 online。*/
      ["/console/glossary", { version: 2, domains: {
        session_status: { ready: "就绪", degraded: "降级中", ended: "已结束" },
      } }],
      ["/projects/p-1/agents", {
        items: [
          { agent_id: "a-1", role: "main", status: "active" },
          { agent_id: "a-2", role: "worker", status: "active", session_status: "ended" },
          /* 会话 ready 但没有**任何心跳证据** → 离线：ready 只说明"这个座位还能干活"，
             不是"那台机器还在"（用户 2026-10-04 定的口径，也是远端关机后立刻显示离线的原因）。*/
          { agent_id: "a-3", role: "worker", status: "active", network: true,
            session_status: "ready" },
          /* 心跳说它在，才是在线。*/
          { agent_id: "a-4", role: "worker", status: "active", network: true,
            session_status: "ready", online: true },
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
    await win.Tsunagou.refresh(["agents", "settings", "glossary"]);

    const cards = () => [...page.querySelectorAll("#pane-agents .boxerbox > .item")];
    const badge = (index: number) => cards()[index]!.querySelector(".header .right");
    expect(cards()).toHaveLength(4);

    // 本机接入（主 Agent、以及中间层没表态的子 Agent）：连图标都不许出现。
    expect(badge(0)).toBeNull();
    expect(cards()[0]!.querySelector(".header")!.textContent).toBe("main");
    expect(badge(1)).toBeNull();

    // 中间层说是网络接入：卡面上只有机器状态（在线/离线）——机器名不在这儿（放不下）。
    expect(badge(2)!.textContent).toBe("离线");   // 会话 ready，但没有任何心跳证据
    expect(badge(2)!.querySelector("i.fa-solid.fa-circle-nodes")).not.toBeNull();
    expect(badge(3)!.textContent).toBe("在线");   // 心跳说它在
    expect(badge(3)!.textContent).not.toContain("ready");

    // 运行时推送：能把一个本机 Agent 标成网络接入，也能顺带说它的机器状态。
    expect(win.Tsunagou.dispatch("agent.network", { agent_id: "a-2", online: true }).ok).toBe(true);
    expect(badge(1)!.textContent).toBe("在线");   // 推来的 online 优先
    expect(win.Tsunagou.dispatch("agent.network",
      { agent_id: "a-2", network: true, online: false }).ok).toBe(true);
    expect(badge(1)!.textContent).toBe("离线");
    // 主 Agent 必须在 daemon 所在机器上：中间层推了也不画。
    expect(win.Tsunagou.dispatch("agent.network", { agent_id: "a-1", online: true }).ok).toBe(true);
    expect(badge(0)).toBeNull();
    // 撤回 → 回到本机（不画）。
    expect(win.Tsunagou.dispatch("agent.network.clear", { agent_id: "a-2" }).ok).toBe(true);
    expect(badge(1)).toBeNull();
  });

  /* 2026-10-04：卡面上只写机器状态（在线/离线）—— 机器名放不下，写了会把别的字挤掉；
     它放进**详细信息窗口**的「在哪台机器」那一行。名字是"入席者说自己是谁"，
     不是系统认证出来的，所以它只影响那一行。*/
  it("卡面只写在线/离线；机器名在详细信息窗口里，本机接入什么都不画", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
        app: { openAgentInfo: (id: string) => boolean };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/projects/p-1/agents", {
        items: [
          { agent_id: "a-1", role: "main", status: "active" },
          { agent_id: "a-2", role: "worker", status: "active", project_id: "p-1",
            machine: "工位-七", session_status: "ready", online: true },
          { agent_id: "a-3", role: "worker", status: "active", project_id: "p-1",
            machine: "NAS", session_status: "ended" },
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
    /* 有机器名 = 远端：卡面上只有机器状态，机器名不在那儿。*/
    expect(badge(1)!.textContent).toBe("在线");
    expect(badge(1)!.textContent).not.toContain("工位-七");
    expect(badge(2)!.textContent).toBe("离线");
    expect(badge(2)!.textContent).not.toContain("NAS");
    /* 本机接入没有这一项 —— 连标记都不出现。*/
    expect(badge(0)).toBeNull();

    /* 机器名在详细信息窗口的「在哪台机器」那一行。*/
    win.Tsunagou.app.openAgentInfo("p-1/a-2");
    expect(page.querySelector("#agentInfoMachine")!.textContent).toBe("工位-七");
  });

  /* 2026-10-04 用户要求：主 Agent 排在 Agent 列表最前面 —— 它是这个协作的调度者，
     混在子 Agent 里得翻着找。后端给的顺序里它可能在后面，所以排序在前端做，
     其余保持后端原顺序。*/
  it("Agent 列表把主 Agent 排最前，其余保持后端顺序", async () => {
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
          { agent_id: "b-1", role: "worker", status: "active" },
          { agent_id: "b-2", role: "worker", status: "active" },
          { agent_id: "a-1", role: "main", status: "active" },
          { agent_id: "b-3", role: "worker", status: "active" },
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

    const order = [...page.querySelectorAll("#pane-agents .boxerbox > .item")]
      .map((node) => node.getAttribute("data-agent-id"));
    expect(order.slice(0, 4)).toEqual(["a-1", "b-1", "b-2", "b-3"]);
  });

  /* 2026-10-04 用户实测：自动重画会把滚动位置清掉 —— 正读到一半就被拉回顶部。
     这里把"重画把滚动归零"这件事在请求里做掉（jsdom 没有布局，不这么做就测不到），
     刷新结束时那个位置必须回来。*/
  it("刷新前后把滚动位置放回去，读到一半不会被拉回顶部", async () => {
    const win = dom.window as unknown as {
      fetch: (url: string) => Promise<unknown>;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/console/projects", { items: [] }],
    ];
    const answer = (url: string) => {
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
    const host = page.getElementById("projList")!;
    host.scrollTop = 120;
    win.fetch = (url: string) => {
      // 模拟"重画把容器内容换掉"：滚动被浏览器归零。
      host.scrollTop = 0;
      return answer(url);
    };

    await win.Tsunagou.refresh(["projects"]);

    expect(host.scrollTop).toBe(120);
  });

  /* 2026-10-04 用户实测复现的那一屏：**总路径 → 线性时间图**。
     render.timeline 把整页拼成 html 后 fill(pane, html)，于是 `.taskFlow > .inner`
     （真正的滚动条在你滚的那个）每次都是**新节点** —— 记"节点自己 + 祖先"救不了它，
     只能按路径在新内容里找回同一个位置。这条测试不需要模拟什么：新节点的 scrollTop
     本来就是 0，所以没有那段逻辑它必然变红。*/
  it("总路径的线性时间图：重画后内层滚动区的位置还在", () => {
    const win = dom.window as unknown as {
      Tsunagou: { render: { timeline: (data: unknown) => unknown } };
    };
    const data = [{
      era: "第一阶段",
      items: [{
        id: "t-1", time: "10月4日 18:21",
        actor: { ref: "daf0f222-687c-4946-a282-6e49256d3279" },
        task: "写 HTML", action: "已提交",
      }],
    }];
    win.Tsunagou.render.timeline(data);

    const inner = () => page.querySelector("#pane-path .taskFlow .inner")!;
    expect(inner()).not.toBeNull();
    inner().scrollTop = 240;

    win.Tsunagou.render.timeline(data);   // 就是每几秒发生一次的那次重画

    expect(inner().scrollTop).toBe(240);
  });

  /* 2026-10-05 用户要求：向导第 1、2 步之间插一步，交代"协作放哪、协调中心怎么对外"。
     这一步必须排在"创建协作"之前 —— 项目一落地，中间层紧接着就把 daemon 起起来了。*/
  it("向导新第 2 步：默认值、跨机器时才要对外地址、创建时把四项一起发给中间层", async () => {
    const win = dom.window as unknown as {
      fetch: (url: string, init?: { body?: string; method?: string }) => Promise<unknown>;
      Tsunagou: {
        ui: {
          wizard: { open: () => boolean; go: (n: number) => number; next: () => Promise<unknown>; current: () => number };
          choosebox: { setValue: (ref: string, value: string, options?: unknown) => boolean };
        };
      };
    };
    const posts: { url: string; body: Record<string, unknown> }[] = [];
    win.fetch = (url: string, init?: { body?: string; method?: string }) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      if (init && init.method === "POST") {
        posts.push({ url: path, body: JSON.parse(String(init.body || "{}")) as Record<string, unknown> });
      }
      const body: Record<string, unknown> = init && init.method === "POST" && path.indexOf("/projects") >= 0
        ? { status: "created", project: { project_id: "p-9", name: "示例协作", objective: "" } }
        : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };

    win.Tsunagou.ui.wizard.open();
    const pane = page.getElementById("newXzSetup")!;
    expect(pane).not.toBeNull();
    const inputs = [...pane.querySelectorAll("input")] as HTMLInputElement[];
    expect(inputs[0]!.getAttribute("placeholder")).toBe("协作根目录（留空则用默认位置）");
    expect(inputs[1]!.value).toBe("2810");
    expect(inputs[2]!.getAttribute("placeholder")).toBe("绑定地址（默认为127.0.0.1）");
    expect(inputs[3]!.getAttribute("placeholder")).toBe("对外地址");
    expect(page.getElementById("newXzSetupAdvertised")!.style.display).toBe("none");

    win.Tsunagou.ui.choosebox.setValue("newXzSetupAccess", "可网络接入");
    expect(page.getElementById("newXzSetupAdvertised")!.style.display).toBe("");

    (page.querySelector("#newXz1 input") as HTMLInputElement).value = "示例协作";
    win.Tsunagou.ui.wizard.next();
    expect(win.Tsunagou.ui.wizard.current()).toBe(2);
    expect(posts).toHaveLength(0);

    await win.Tsunagou.ui.wizard.next();
    expect(win.Tsunagou.ui.wizard.current()).toBe(2);
    expect(posts).toHaveLength(0);

    inputs[0]!.value = "E:\\Tsunagou\\projects\\示例协作";
    inputs[1]!.value = "2820";
    inputs[2]!.value = "192.168.32.1";
    inputs[3]!.value = "http://192.168.32.1:2820";
    await win.Tsunagou.ui.wizard.next();

    const created = posts.filter((item) => item.url.indexOf("/projects") >= 0)[0];
    expect(created).toBeTruthy();
    expect(created!.body).toMatchObject({
      name: "示例协作",
      coordination_root: "E:\\Tsunagou\\projects\\示例协作",
      port: 2820,
      bind_host: "192.168.32.1",
      advertised_url: "http://192.168.32.1:2820",
    });
    expect(win.Tsunagou.ui.wizard.current()).toBe(3);
  });

  /* 跨机器但没写绑定地址时绑 0.0.0.0：只绑回环却对外公布网卡地址，远端一定连不上。
     这一条不能偷偷替用户决定，所以它同时出现在确认页上。*/
  it("向导新第 2 步：跨机器没写绑定地址时绑 0.0.0.0，并在确认页写明", async () => {
    const win = dom.window as unknown as {
      fetch: (url: string, init?: { body?: string; method?: string }) => Promise<unknown>;
      Tsunagou: {
        ui: {
          wizard: { open: () => boolean; next: () => Promise<unknown>; go: (n: number) => number };
          choosebox: { setValue: (ref: string, value: string, options?: unknown) => boolean };
        };
      };
    };
    const posts: Record<string, unknown>[] = [];
    win.fetch = (url: string, init?: { body?: string; method?: string }) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      if (init && init.method === "POST" && path.indexOf("/projects") >= 0) {
        posts.push(JSON.parse(String(init.body || "{}")) as Record<string, unknown>);
      }
      const body = init && init.method === "POST" && path.indexOf("/projects") >= 0
        ? { status: "created", project: { project_id: "p-9", name: "示例协作", objective: "" } }
        : {};
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };

    win.Tsunagou.ui.wizard.open();
    (page.querySelector("#newXz1 input") as HTMLInputElement).value = "示例协作";
    win.Tsunagou.ui.wizard.next();
    win.Tsunagou.ui.choosebox.setValue("newXzSetupAccess", "可网络接入");
    const inputs = [...page.getElementById("newXzSetup")!.querySelectorAll("input")] as HTMLInputElement[];
    inputs[3]!.value = "http://192.168.32.1:2810";
    await win.Tsunagou.ui.wizard.next();

    expect(posts[0]).toMatchObject({ bind_host: "0.0.0.0", advertised_url: "http://192.168.32.1:2810" });
    win.Tsunagou.ui.wizard.go(5);
    const review = page.getElementById("newXz4")!;
    expect(review.textContent).toContain("0.0.0.0:2810");
    expect(review.textContent).toContain("http://192.168.32.1:2810");
  });
  /* 2026-10-04 用户实测：设置窗口的格子会原样显示后端值（旧档案里存的是 `dark`）。
     口径：先归一到界面标签，对不上任何一项就回落**默认项**，不把它当标签用。*/
  it("设置窗口：主题是后端值也显示中文标签，认不出的值回落到默认项", () => {
    const win = dom.window as unknown as {
      Tsunagou: { render: { settings: (data: unknown) => unknown } };
    };
    const label = () => page.querySelector("#uSet1 .choosebox .left")!.textContent!.trim();

    win.Tsunagou.render.settings({ theme: "dark" });
    expect(label()).toBe("深色");
    win.Tsunagou.render.settings({ theme: "light" });
    expect(label()).toBe("浅色");
    win.Tsunagou.render.settings({ theme: "深色" });   // 已经是界面标签也认
    expect(label()).toBe("深色");

    win.Tsunagou.render.settings({ theme: "purple" }); // 认不出的：回落第一项
    expect(label()).toBe("深色");
    expect(label()).not.toContain("purple");
  });

  /* 2026-10-04 用户实测：任务区两个任务的「改动范围」都写成 [object Object] —— 出口给的是
     对象（声明为空就是 `{}`），页面直接把它当文本用了。顺带补上详情页缺的「任务介绍」：
     那段介绍一直在出口里（objective），只是详情没画它。*/
  it("任务区：改动范围写成人话，详情页给出任务介绍", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/console/views/tasks", { sources: {
        agents: { items: [{ agent_id: "a-1", role: "worker", status: "active" }] },
        tasks: { items: [
          { task_id: "t-1", title: "写 HTML", status: "completed", owner_agent_id: "a-1",
            objective: "产出一个纯静态介绍 Microsoft Windows 11 的网页的 HTML 部分。",
            execution_scope: {}, revision: 7, created_at: "2026-10-04T10:19:52.809Z" },
          { task_id: "t-2", title: "写 CSS", status: "running", owner_agent_id: "a-1",
            objective: "产出 CSS 部分。",
            execution_scope: { resources: [{ kind: "path", root_id: "site",
              segments: ["styles.css"], mode: "exclusive_write" }] },
            revision: 3, created_at: "2026-10-04T10:20:00.000Z" },
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
    await win.Tsunagou.refresh(["tasks"]);

    const pane = page.getElementById("pane-tasks")!;
    // 空声明说清"不认领任何路径"，有声明就写出路径与模式 —— 反正不能再是 [object Object]。
    expect(pane.textContent).not.toContain("[object Object]");
    expect(pane.textContent).toContain("不认领任何路径");
    expect(pane.textContent).toContain("site/styles.css");
    expect(pane.textContent).toContain("exclusive_write");

    // 点开那一行 → 详情页多出一行「任务介绍」，内容就是出口那段 objective。
    const row = pane.querySelector('.tablebox .tr[data-row-id="t-1"]')!;
    row.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    const aside = page.getElementById("aside-tasks")!;
    expect(aside.textContent).toContain("任务介绍");
    expect(aside.textContent).toContain("产出一个纯静态介绍 Microsoft Windows 11");
  });

  /* 2026-10-04 用户要求：总路径线性时间图里**主 Agent 的小图标始终是白色** ——
     主 Agent 的胶囊是品牌深蓝底、文字本来就是白的（`.id-mAgent`），深色 logo 在上面
     几乎看不见；子 Agent 是浅底深字，图标必须保持原样（套白滤镜反而看不见）。*/
  it("时间图里主 Agent 的图标变白，子 Agent 的图标不动", () => {
    const win = dom.window as unknown as {
      Tsunagou: {
        render: { timeline: (data: unknown) => unknown };
        state: { set: (path: string, value: unknown) => void };
      };
    };
    win.Tsunagou.state.set("agents", [
      { id: "a-main", isMain: true, name: "总管", icon: "assets/icons/dark.svg" },
      { id: "a-child", isMain: false, name: "小弟", icon: "assets/icons/dark.svg" },
    ]);
    win.Tsunagou.render.timeline([{
      era: "第一阶段",
      items: [
        { id: "t-1", time: "10月4日 18:21", actor: { ref: "a-main" },
          task: "写 HTML", action: "已提交" },
        { id: "t-2", time: "10月4日 18:22", actor: { ref: "a-child" },
          task: "写 CSS", action: "已提交" },
      ],
    }]);

    const chips = [...page.querySelectorAll("#pane-path .itemS")];
    const chipOf = (id: string) =>
      chips.filter((node) => node.getAttribute("data-agent-id") === id)[0]!;

    expect(chipOf("a-main").classList.contains("id-mAgent")).toBe(true);
    expect(chipOf("a-main").querySelector("img")!.getAttribute("style") ?? "")
      .toContain("invert(1)");
    // 子 Agent：出口不动，图标也不许被改。
    expect(chipOf("a-child").querySelector("img")!.getAttribute("style")).toBeNull();
  });

  /* 2026-10-04 用户实测：点 Agent 卡片的「修改」，窗口里「协作名称」空着，
     远端那个也不显示「在哪台机器」。实机形状是关键：中间层的 /projects 只给 project_id
     （**没有 id**），成员只给 agent_id（也没有 id）—— 适配器要负责把 id 补出来，
     窗口才找得到人和协作。这条测试就按实机形状喂。*/
  it("编辑窗口：协作名称与「在哪台机器」都填得上（只有 project_id / agent_id 的实机形状）", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void };
        app: { editAgent: (id: string) => boolean };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/projects?", { items: [{
        project_id: "p-1", name: "跨机器测试", lifecycle: "active", main_agent_id: "a-main",
        path: "E:/Tsunagou/projects/x",
        agents: [{ agent_id: "a-main", role: "main", status: "active" }],
      }] }],
      ["/projects/p-1/agents", { items: [
        { agent_id: "a-main", role: "main", status: "active", session_status: "ready", online: true },
        { agent_id: "a-remote", role: "worker", status: "active", session_status: "ready",
          online: true, machine: "DESKTOP-K03DV8N" },
      ], main_agent_id: "a-main" }],
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
    await win.Tsunagou.refresh(["projects", "agents", "settings"]);

    win.Tsunagou.app.editAgent("a-remote");

    const node = page.getElementById("mgrAgentInfo")!;
    expect([...node.querySelectorAll(".dspText2")][0]!.textContent).toBe("跨机器测试");
    const machine = page.getElementById("agentInfoMachine")!;
    expect(machine.style.display).not.toBe("none");
    expect(machine.textContent).toBe("DESKTOP-K03DV8N");
  });

  /* 同一个窗口的**另一条入口**：跨协作的「Agent 列表」窗口（它不需要先选协作，
     所以那时 state.agents 是空的）。「修改」带的是裸 agent_id，而那份跨协作名单里的 id
     是「协作/Agent」—— 两边对不上时窗口会退化成空壳：昵称照旧有（按 id 从档案现算），
     协作名称、当前任务、在哪台机器全空（2026-10-04 用户实测就是这个现象）。*/
  it("跨协作列表点「修改」：协作名称与「在哪台机器」也要填上", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        refresh: (keys?: string[]) => Promise<unknown>;
        state: { set: (path: string, value: unknown) => void; get: (path: string) => unknown };
        app: { editAgent: (id: string) => boolean };
      };
    };
    const replies: [string, unknown][] = [
      ["/console/profile", { version: 1, nickname: "", theme: "", agents: {} }],
      ["/console/agents", { items: [{
        agent_id: "a-remote", project_id: "p-1", project_name: "跨机器测试", task: "",
        machine: "DESKTOP-K03DV8N", session_status: "ready", online: true,
      }] }],
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
    // 故意不设 currentProjectId：跨协作窗口本来就不要求先选协作。
    await win.Tsunagou.refresh(["agentsWindow", "settings"]);

    /* 页面在整个文件里共用 —— 状态和 DOM 都要先清，否则断言到的是上一个用例的残留，
       测试会"假通过"（我前两版就是这样骗过自己的：同一个协作还选着、字段还留着值）。*/
    win.Tsunagou.state.set("currentProjectId", null);
    win.Tsunagou.state.set("projects", []);
    win.Tsunagou.state.set("project", {});
    win.Tsunagou.state.set("agents", []);
    const node = page.getElementById("mgrAgentInfo")!;
    [...node.querySelectorAll(".dspText2")].forEach((el) => { el.textContent = ""; });
    node.querySelectorAll(".dspText2").forEach((el) => { (el as HTMLElement).style.display = "none"; });
    page.getElementById("agentInfoMachine")!.textContent = "";
    page.getElementById("agentInfoMachine")!.style.display = "none";

    win.Tsunagou.app.editAgent("a-remote");   // 列表窗口那条路传的就是裸 agent_id

    // 前提也要钉住：跨协作名单真的拉到了（否则下面测的就不是"合并字段"而是"没数据"）。
    expect(win.Tsunagou.state.get("agentsWindow")).toHaveLength(1);
    // 适配器那一层先把协作名映射出来（实机的 /console/agents 给的是 project_name）。
    expect((win.Tsunagou.state.get("agentsWindow") as Record<string, unknown>[])[0]!.project)
      .toBe("跨机器测试");
    // 然后是窗口：协作名称那一格（第一个 .dspText2）接到了它。
    expect([...node.querySelectorAll(".dspText2")].map((el) => el.textContent).slice(0, 2))
      .toEqual(["跨机器测试", ""]);
    const machine = page.getElementById("agentInfoMachine")!;
    expect(machine.style.display).not.toBe("none");
    expect(machine.textContent).toBe("DESKTOP-K03DV8N");
  });

  /* 主 Agent 必须和协调中心同一台机器：远端的按钮不画（后端也拒，两道门都要）。*/
  it("设为主 Agent 只给本机 Agent，远端的按钮不画", async () => {
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
          { agent_id: "a-2", role: "worker", status: "active" },
          { agent_id: "a-3", role: "worker", status: "active", machine: "工位-七", online: true },
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

    const cards = [...page.querySelectorAll("#pane-agents .boxerbox > .item")]
      .map((node) => node.textContent ?? "");
    expect(cards).toHaveLength(3);
    expect(cards[0]).not.toContain("设为主 Agent");  /* 已经是主 Agent */
    expect(cards[1]).toContain("设为主 Agent");      /* 本机子 Agent */
    expect(cards[2]).not.toContain("设为主 Agent");  /* 远端子 Agent */
    expect(cards[2]).toMatch(/在线|离线/);          /* 徽标照旧画（写的是机器状态） */
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
    enrollmentApi.ui.wizard.go(3);
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
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
    expect(enrollmentApi.state.get("wizard.main")).toBeNull();
    statusBody = { status: "arrived", enrollment_id: "e-1", agent_id: "a-own", role: "main" };
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(enrollmentApi.ui.wizard.current()).toBe(4);
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
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
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
      expires_in_seconds: 600, expires_at: new Date(Date.now() + 600000).toISOString(),
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
    /* 路由挂在中间层的 /console 下（console/app.py）：漏掉那一段就是 404，页面把一次失败
       当成"还没到"接着问，等待框永远不翻绿 —— 这里钉住整条路径，不再只匹配方法名。*/
    expect(asked[0]!.url).toMatch(/\/api\/v1\/console\/projects\/[^/]+\/enrollments:observe\?/);
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
      expires_in_seconds: 600, expires_at: new Date(Date.now() + 600000).toISOString(), url: "http://10.0.0.5:2810",
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
    /* 钉住整条路径：宿主自己接入这条路问的就是中间层 /console 下那条 observe 路由。*/
    expect(asked[0]!.url).toMatch(/\/api\/v1\/console\/projects\/[^/]+\/enrollments:observe\?/);
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
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
    /* 中间层说到了：遮罩收起、主 Agent 落到第 3 步 */
    observeBody = { status: "arrived", adapter: "deepseek", agent: { agent_id: "a-own" } };
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    expect(enrollmentApi.ui.wizard.current()).toBe(4);
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
    /* 只留**一条**结论，而且以取消接口的答案为准（这里就是后端那句 note）；
       不再另外补一句"这次接入申请已撤掉"—— 两条消息一个说"撤掉了"、另一个说"还在"，
       是待改清单阶段 2 第 3 条要清的矛盾。*/
    expect(tip()).toContain("已取消这次待接入申请");
    expect(tip()).not.toContain("已撤掉");
  });

  it("还没做的厂商点了下一步只给一句话，绝不发准备请求", async () => {
    enrollmentApi.state.set("hosts", [
      { adapter: "deepseek", label: "DeepSeek Harness", mode: "in_host", note: "在 DeepSeek Harness 自己的桌面聊天里接入。" },
      { adapter: "claudecode", label: "Claude Code", mode: "unsupported", note: "Claude Code 的 MCP 注册还没实现。" },
    ]);
    /* 选项文字带着"（待实现）"后缀（人点了也没用），但程序化回填照旧可用，
       所以这条"选了接不了的宿主会报错并停在第 2 步"的路仍然是活的 —— 这里走的就是它。*/
    enrollmentApi.ui.choosebox.setValue("newXz2Vendor", "Claude Code（待实现）", { silent: true });
    await enrollmentApi.ui.wizard.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(tip()).toContain("还没实现");
    expect(calls.filter((call) => call.url.includes("agents:prepare"))).toHaveLength(0);
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
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
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
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
    expect(enrollmentApi.ui.wizard.current()).toBe(4);
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
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
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
    expect(enrollmentApi.ui.wizard.current()).toBe(4);
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
    expect(enrollmentApi.ui.wizard.current()).toBe(3);
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

  /* 测试同事报的那个 bug 就落在这条路上：刷新之后，一条 DeepSeek Harness 的申请被当成     Codex 的申请去等（写死 adapter/label），到达到时还会把它的厂商记成 Codex —— 于是
     页面上这个 Agent 从此一直显示成另一家的图标。这里钉住"按申请自己的宿主说话"。
     等待本身由中间层那条"没有回执就按名单判定"的路负责翻绿，这一条只管页面这半边。*/
  it("刷新恢复一条宿主自己接入的申请：按它自己的宿主等，到达时厂商也记它自己那家", async () => {    enrollmentDom.window.close();
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

  /* 厂商只做三家（Codex / DeepSeek Harness / OpenCode）：ZCode 的图标与选项一并撤掉，
     Claude Code 留着但作为"待实现"——看得见、点不动。程序化回填不受这条限制，所以
     "选了接不了的宿主会报错并停在第 2 步"那条路仍然在（见下面那条 unsupported 用例）。*/
  it("厂商选择框：ZCode 已经不在，Claude Code（待实现）点不动，其他厂商照旧能选", async () => {
    const click = (node: Element) => {
      node.dispatchEvent(new enrollmentDom.window.MouseEvent("click", { bubbles: true }));
    };
    const texts = (panel: Element) =>
      [...panel.querySelectorAll("p")].map((node) => node.textContent ?? "");

    for (const id of ["newXz2Vendor", "addSubAgentVendor"]) {
      const panel = enrollmentPage.getElementById(id)!;
      expect(texts(panel).some((text) => text.includes("ZCode"))).toBe(false);
      const claude = [...panel.querySelectorAll("p")].find((node) => (node.textContent ?? "").includes("Claude"))!;
      expect(claude.textContent).toContain("（待实现）");
      expect(claude.hasAttribute("data-disabled")).toBe(true);
    }

    const box = enrollmentPage.querySelector("#newXz2 .choosebox") as HTMLElement;
    const before = enrollmentApi.ui.choosebox.value(box);
    const claude = [...enrollmentPage.getElementById("newXz2Vendor")!.querySelectorAll("p")]
      .find((node) => (node.textContent ?? "").includes("Claude"))!;
    click(claude);
    expect(enrollmentApi.ui.choosebox.value(box)).toBe(before);

    const opencode = [...enrollmentPage.getElementById("newXz2Vendor")!.querySelectorAll("p")]
      .find((node) => (node.textContent ?? "").includes("OpenCode"))!;
    click(opencode);
    expect(enrollmentApi.ui.choosebox.value(box)).toBe("OpenCode");
  });
});

/* ---- 左栏两组各自独立：搜索 / 排序 -------------------------------------------
   盯的是"两组分家"这件事本身：一组的放大镜、搜索条、齿轮只作用在自己那一组，另一组照旧。
   走真页面 + 真 DOM（runScripts: 'dangerously'）：内联 onclick 也真的被编译过，
   不会拿"事件压根没绑上"当成通过。排序偏好存在 localStorage 里，所以每一条用例自己起一份
   页面（互不串味），也能顺手钉住"按组分开存"与"旧格式能迁移"。*/
describe("左栏两组各自独立（搜索 / 排序）", () => {
  type RailApi = {
    dispatch: (type: string, payload?: unknown) => { ok: boolean };
    stopPolling?: () => void;
    /* 页面那套「失焦即提交」的判据：搜索框必须不在里面（data-tg-commit="manual"） */
    form: { isAutoCommit: (node: Element) => boolean };
  };

  let railDom: JSDOM;
  let railPage: Document;
  let railApi: RailApi;

  const PROJECTS = [
    { id: "a-1", name: "甲组-接口对齐", group: "active", lifecycle: "active", history: { captured_at: "2026-01-01T10:00:00Z" } },
    { id: "a-2", name: "乙组-联调", group: "active", lifecycle: "active", history: { captured_at: "2026-01-02T10:00:00Z" } },
    { id: "a-3", name: "甲组-回归", group: "active", lifecycle: "active", history: { captured_at: "2026-01-03T10:00:00Z" } },
    { id: "d-1", name: "甲组已完工", group: "done", lifecycle: "completed", history: { captured_at: "2026-01-04T10:00:00Z" } },
    { id: "d-2", name: "丙组已完工", group: "done", lifecycle: "completed", history: { captured_at: "2026-01-05T10:00:00Z" } },
  ];

  const rail = () => railPage.querySelector("#projList")!;
  /* 这一组**没有被 display:none 藏起来**的卡片，按 DOM 顺序（也就是这一组自己的排序）。*/
  const visible = (group: string) => [...rail().querySelectorAll(`.projItem[data-proj-group="${group}"]`)]
    .filter((node) => (node as HTMLElement).style.display !== "none")
    .map((node) => node.getAttribute("data-project-id"));
  const all = (group: string) => [...rail().querySelectorAll(`.projItem[data-proj-group="${group}"]`)]
    .map((node) => node.getAttribute("data-project-id"));
  const bar = (group: string) => rail().querySelector(`.searchBar[data-proj-group="${group}"]`) as HTMLElement;
  const blank = (group: string) => rail().querySelector(`[data-proj-blank="${group}"]`) as HTMLElement;
  const titleBtn = (group: string, role: string) =>
    rail().querySelector(`.wkTitle[data-proj-group="${group}"] .wkTbtn[data-tg-role="${role}"]`)!;
  /* 这一组那个分组标题（里面有这一组的放大镜与齿轮） */
  const titleOf = (group: string) => rail().querySelector(`.wkTitle[data-proj-group="${group}"]`) as HTMLElement;
  const click = (node: Element) => node.dispatchEvent(new railDom.window.MouseEvent("click", { bubbles: true }));
  /* 点某一组的齿轮、在菜单里选一项（"按什么排"或"怎么排"） */
  const chooseSort = (group: string, attr: "data-sort-by" | "data-sort-order", value: string) => {
    click(titleBtn(group, "project-sort"));
    click(railPage.querySelector(`#sortMenu .item[${attr}="${value}"]`)!);
  };
  const type = (input: HTMLInputElement, value: string) => {
    input.value = value;
    input.dispatchEvent(new railDom.window.Event("input", { bubbles: true }));
  };
  const inputOf = (group: string) => bar(group).querySelector("input.left") as HTMLInputElement;
  /* 菜单里某一项右边有没有那个对勾 */
  const checked = (attr: string, value: string) => {
    const item = railPage.querySelector(`#sortMenu .item[${attr}="${value}"]`)!;
    return (item.querySelector(".right")?.innerHTML ?? "").includes("fa-check");
  };
  const storedSort = () => JSON.parse(railDom.window.localStorage.getItem("tsunagou.console.projSort") ?? "null");

  /* 页面发过的每一次请求（url + 方法）。测"点一下会不会偷偷发写请求"要看的就是这个：
     没记下来就没法断言"一条都没有"，只能断言"没崩"。默认那一份 fetch 只 reject、
     不留痕迹，所以这里换成会记账的桩。 */
  const sent: Array<{ url: string; method: string }> = [];
  const writes = () => sent.filter((call) => call.method !== "GET");
  /* 空抓的 promise 也要消费掉它的 rejection —— 不消费会在用例里冒出一条没人管的告警。 */
  const quiet = () => { const p = Promise.reject(new Error("smoke: no backend")); p.catch(() => undefined); return p; };

  async function loadRail(seededSort?: unknown) {
    railDom = new JSDOM(readWeb("index.html"), {
      url: "http://127.0.0.1:55862/?poll_ms=0", runScripts: "dangerously", pretendToBeVisual: true,
    });
    const win = railDom.window as unknown as Window & typeof globalThis;
    if (seededSort !== undefined) {
      win.localStorage.setItem("tsunagou.console.projSort", JSON.stringify(seededSort));
    }
    sent.length = 0;
    (win as unknown as { fetch: unknown }).fetch = (input: unknown, init?: { method?: string }) => {
      const url = typeof input === "string" ? input : String((input as { url?: string })?.url ?? input);
      const method = String(init?.method ?? (input as { method?: string })?.method ?? "GET").toUpperCase();
      sent.push({ url, method });
      return quiet();
    };
    win.eval(readWeb("console.config.js"));
    win.eval(readWeb("assets/js/behavior.js"));
    /* behavior.js 是在 readyState 还是 'loading' 时被 eval 的：它把 init 挂在 DOMContentLoaded 上，
       所以要等一个宏任务页面才真的起来（少了这一步，点击委托一个都还没绑）。*/
    await new Promise((resolve) => setTimeout(resolve, 0));
    railPage = win.document;
    railApi = (win as unknown as { Tsunagou: RailApi }).Tsunagou;
    return win;
  }

  beforeEach(() => {
    /* 上面那组用例用过假时钟，这里要真的等 DOMContentLoaded。*/
    vi.useRealTimers();
  });

  afterEach(() => {
    railApi?.stopPolling?.();
    railDom?.window.close();
  });

  it("搜索按组独立：只开本组搜索条、只滤本组卡片，另一组一个都不少", async () => {
    await loadRail();
    railApi.dispatch("project.list", PROJECTS);
    expect(visible("active")).toEqual(["a-3", "a-2", "a-1"]);
    expect(visible("done")).toEqual(["d-2", "d-1"]);
    expect(bar("active").style.display).toBe("none");
    expect(bar("done").style.display).toBe("none");

    // 点【进行中】那组的放大镜：只有这一组的搜索条出来、并拿到焦点。
    click(titleBtn("active", "project-search"));
    expect(bar("active").style.display).toBe("");
    expect(bar("done").style.display).toBe("none");
    expect(railPage.activeElement).toBe(inputOf("active"));

    // 打「甲」：本组只剩两张，另一组连名字里有「甲」的 d-1 也照旧显示。
    type(inputOf("active"), "甲");
    expect(visible("active")).toEqual(["a-3", "a-1"]);
    expect(visible("done")).toEqual(["d-2", "d-1"]);
    expect(all("done")).toHaveLength(2);
    expect(blank("active").style.display).toBe("none");
    expect(blank("done").style.display).toBe("none");

    // 打一个本组谁都不匹配的词：本组那句「没有协作」露出来，另一组照旧。
    type(inputOf("active"), "查无此项");
    expect(visible("active")).toEqual([]);
    expect(blank("active").style.display).toBe("");
    expect(blank("done").style.display).toBe("none");
    expect(visible("done")).toEqual(["d-2", "d-1"]);

    // 点本组的 iconB：只收本组、只清本组，另一组始终没被碰过。
    click(bar("active").querySelector(".iconB")!);
    expect(inputOf("active").value).toBe("");
    expect(bar("active").style.display).toBe("none");
    expect(visible("active")).toEqual(["a-3", "a-2", "a-1"]);
    expect(blank("active").style.display).toBe("none");
    expect(visible("done")).toEqual(["d-2", "d-1"]);
  });

  it("搜索条关闭时不发写请求（失焦即提交不再把搜索词当档案字段）", async () => {
    await loadRail();
    railApi.dispatch("project.list", PROJECTS);
    expect(writes()).toEqual([]);

    // 打开【进行中】的搜索条、打一个字，再点 iconB 关掉：输入框会失焦、随即被移除。
    click(titleBtn("active", "project-search"));
    type(inputOf("active"), "甲");
    // 手动补一次 blur：关搜索条时输入框正在失焦，这条路径不能把搜索词提交出去。
    inputOf("active").dispatchEvent(new railDom.window.Event("blur"));
    click(bar("active").querySelector(".iconB")!);
    expect(inputOf("active").value).toBe("");
    expect(bar("active").style.display).toBe("none");

    // 一条非 GET 的 fetch 都不能有（搜索词不是档案字段，关一次搜索不该写一次档案）。
    expect(writes()).toEqual([]);
    // 真的记了请求才算数（否则上面那条断言可能只是"页面压根没发过任何请求"）。
    expect(sent.every((call) => call.method === "GET")).toBe(true);
    expect(sent.length).toBeGreaterThan(0);
    /* 这条行为断言**拦不住**"把逃生门删掉"：在这份页面里 `isAutoCommitInput` 的
       `inputScope` 回落到 document，而 document 里有 `.buttonbox`，所以搜索框本来
       就不会被 form.watch 装上失焦提交（实测去掉 data-tg-commit 后同样一个写请求都没有）。
       真正钉住"这个框永远不参与失焦提交"的是下面这条，与输入框当前落在哪个容器无关。 */
    expect(inputOf("active").dataset.tgCommit).toBe("manual");
    expect(railApi.form.isAutoCommit(inputOf("active"))).toBe(false);
  });

  it("在搜的那一组把标题让给搜索条，另一组的标题照旧", async () => {
    await loadRail();
    railApi.dispatch("project.list", PROJECTS);
    expect(titleOf("active").style.display).toBe("");
    expect(titleOf("done").style.display).toBe("");

    // 打开【进行中】的搜索条：本组标题收起（放大镜与齿轮就在标题里，让位给搜索条）。
    click(titleBtn("active", "project-search"));
    expect(titleOf("active").style.display).toBe("none");
    expect(titleOf("done").style.display).toBe("");

    // 打字期间同样收着；【已完成】那一组一个都没动 —— 更没被跟着藏。
    type(inputOf("active"), "甲");
    expect(titleOf("active").style.display).toBe("none");
    expect(titleOf("done").style.display).toBe("");
    expect(visible("done")).toEqual(["d-2", "d-1"]);

    // 关掉搜索条、字也清空：本组标题交回 CSS（清成空串，不是写个 display:flex 盖住）。
    click(bar("active").querySelector(".iconB")!);
    expect(titleOf("active").style.display).toBe("");
    expect(titleOf("done").style.display).toBe("");
  });

  it("按名称：order=new 是拼音升序（A→Z），order=old 是降序（Z→A）", async () => {
    await loadRail();
    railApi.dispatch("project.list", PROJECTS);

    // 先切成按名称。【进行中】这一组是：乙组-联调 / 甲组-接口对齐 / 甲组-回归。
    chooseSort("active", "data-sort-by", "name");
    // order 还是默认的 new → 拼音升序 A→Z：甲组-回归（jiǎ）→ 甲组-接口对齐（jiē）→ 乙组-联调（yǐ）。
    expect(visible("active")).toEqual(["a-3", "a-1", "a-2"]);

    // 换成 old → 同一批名字倒过来（Z→A）。菜单上写的就是 A→Z / Z→A，实际顺序要跟它一致。
    chooseSort("active", "data-sort-order", "old");
    expect(visible("active")).toEqual(["a-2", "a-1", "a-3"]);
    // 只是换了顺序，没有藏卡片。
    expect(all("active")).toEqual(visible("active"));
    // 另一组没被这次改动碰到。
    expect(visible("done")).toEqual(["d-2", "d-1"]);
    expect(storedSort()).toEqual({ active: { order: "old", by: "name" }, done: { order: "new", by: "viewed" } });
  });

  it("排序按组独立：改一组不动另一组，对勾跟着打开菜单的那一组，并按组存进本地", async () => {
    await loadRail();
    railApi.dispatch("project.list", PROJECTS);
    const activeBefore = visible("active");
    expect(activeBefore).toEqual(["a-3", "a-2", "a-1"]);
    expect(visible("done")).toEqual(["d-2", "d-1"]);

    // 点【已完成】那组的齿轮：菜单画的是**这一组**的偏好（默认 按查看时间 / 新的在前）。
    click(titleBtn("done", "project-sort"));
    expect((railPage.querySelector("#sortMenu") as HTMLElement).style.display).toBe("flex");
    expect(checked("data-sort-by", "viewed")).toBe(true);
    expect(checked("data-sort-order", "new")).toBe(true);

    click(railPage.querySelector('#sortMenu .item[data-sort-by="created"]')!);
    click(railPage.querySelector('#sortMenu .item[data-sort-order="old"]')!);
    expect(visible("done")).toEqual(["d-1", "d-2"]);   // 按登记时间、旧的在前
    expect(visible("active")).toEqual(activeBefore);   // 进行中那一组一个都没动
    expect(checked("data-sort-by", "created")).toBe(true);
    expect(checked("data-sort-order", "old")).toBe(true);

    // 再点【进行中】那组的齿轮：同一个菜单，对勾立刻换回这一组的偏好。
    click(titleBtn("active", "project-sort"));
    expect(checked("data-sort-by", "viewed")).toBe(true);
    expect(checked("data-sort-order", "new")).toBe(true);
    click(railPage.querySelector('#sortMenu .item[data-sort-by="name"]')!);
    expect(visible("active")).not.toEqual(activeBefore);   // 这一组换了排法
    expect(all("active")).toEqual(visible("active"));       // 换了排法也不是"藏卡片"
    expect(visible("done")).toEqual(["d-1", "d-2"]);        // 完成组仍是它自己那份

    // 存进本地的是按组分开的一份。
    expect(storedSort()).toEqual({ active: { order: "new", by: "name" }, done: { order: "old", by: "created" } });
  });

  it("旧格式（扁平的 {order,by}）能迁移：两组都按它排，再改一组只写这一组", async () => {
    await loadRail({ order: "old", by: "name" });
    railApi.dispatch("project.list", PROJECTS);
    // 名称降序（order=old 就是 Z→A）：乙组-联调 / 甲组-接口对齐 / 甲组-回归；完成组：甲组已完工 / 丙组已完工。
    expect(visible("active")).toEqual(["a-2", "a-1", "a-3"]);
    expect(visible("done")).toEqual(["d-1", "d-2"]);

    click(titleBtn("done", "project-sort"));
    expect(checked("data-sort-by", "name")).toBe(true);
    expect(checked("data-sort-order", "old")).toBe(true);

    click(railPage.querySelector('#sortMenu .item[data-sort-order="new"]')!);
    expect(storedSort()).toEqual({ active: { order: "old", by: "name" }, done: { order: "new", by: "name" } });
    expect(visible("active")).toEqual(["a-2", "a-1", "a-3"]);   // 还是旧偏好（old 就是 Z→A）
    expect(visible("done")).toEqual(["d-2", "d-1"]);            // 这一组换成 new，名称升序 A→Z
  });
});

/* ---- 这一轮修掉的三条 --------------------------------------------------------
   每条都钉住一个**真出过问题**的行为，注释里写了"没修之前会怎样" ——
   免得以后有人看它长得像冗余用例就删掉。*/
describe("回归：本轮修掉的若干条（失焦提交 / 原型链 / 机器名 / 窗口 / 静默成功）", () => {
  type FixApi = {
    ready: boolean;
    dispatch: (type: string, payload?: unknown) => { ok: boolean; error?: string };
    stopPolling?: () => void;
    form: {
      isAutoCommit: (node: Element) => boolean;
      commit: (node: Element, options?: unknown) => Promise<unknown>;
    };
    state: {
      patch: (partial: unknown) => unknown;
      set: (path: string, value: unknown) => unknown;
      get: (path: string, fallback?: unknown) => unknown;
    };
    api: { get: (path: string, query?: unknown, options?: unknown) => Promise<unknown> };
    render: { wizardSubAgents: (list: unknown[]) => unknown };
    app: {
      saveAgentInfo: () => Promise<unknown>;
      renameProject: (id: string) => unknown;
      submitRename: () => Promise<unknown>;
    };
    actions: { addSubAgent: (payload: unknown) => Promise<unknown> };
    ui: { window: { isOpen: (id: string) => boolean; open: (id: string) => unknown } };
    config: { get: () => Record<string, unknown> };
  };

  let fixDom: JSDOM;
  let fixPage: Document;
  let fixApi: FixApi;

  /* 记下页面发过的每一次请求：要断言的是"一条写请求都没有"，
     不记账就只能断言"没崩"。默认那份 fetch 只 reject、不留痕迹。*/
  const sent: Array<{ url: string; method: string }> = [];
  const writes = () => sent.filter((call) => call.method !== "GET");
  const quiet = () => { const p = Promise.reject(new Error("smoke: no backend")); p.catch(() => undefined); return p; };

  /* reply 给了一条"假应答"，用来造 4xx/5xx；不给就让请求失败（网络错误）。*/
  type Reply = { ok: boolean; status: number; text: () => Promise<string> };

  async function loadFix(setup?: {
    query?: string;
    config?: unknown;
    reply?: (url: string, method: string) => Reply;
  }) {
    const opts = setup || {};
    fixDom = new JSDOM(readWeb("index.html"), {
      url: "http://127.0.0.1:55862/" + (opts.query === undefined ? "?poll_ms=0" : opts.query),
      runScripts: "dangerously", pretendToBeVisual: true,
    });
    const win = fixDom.window as unknown as Window & typeof globalThis;
    sent.length = 0;
    (win as unknown as { fetch: unknown }).fetch = (input: unknown, init?: { method?: string }) => {
      const url = typeof input === "string" ? input : String((input as { url?: string })?.url ?? input);
      const method = String(init?.method ?? (input as { method?: string })?.method ?? "GET").toUpperCase();
      sent.push({ url, method });
      if (opts.reply) return Promise.resolve(opts.reply(url, method));
      return quiet();
    };
    if (opts.config === undefined) win.eval(readWeb("console.config.js"));
    else win.eval("window.TSUNAGOU_CONSOLE_CONFIG = " + JSON.stringify(opts.config) + ";");
    win.eval(readWeb("assets/js/behavior.js"));
    /* behavior.js 被 eval 时 readyState 可能还是 'loading'，init 挂在 DOMContentLoaded 上，
       所以要等一个宏任务页面才真的起来（少了这一步，失焦提交一个都还没绑上）。*/
    await new Promise((resolve) => setTimeout(resolve, 0));
    fixPage = win.document;
    fixApi = (win as unknown as { Tsunagou: FixApi }).Tsunagou;
  }

  afterEach(() => {
    fixApi?.stopPolling?.();
    fixDom?.window.close();
  });

  it("BUG-22：#netInvite 的只读邀请票不参与失焦提交（票据不会被当档案字段发出去）", async () => {
    await loadFix();
    const ticket = fixPage.querySelector<HTMLInputElement>("#netInvite .textbox2 input")!;
    // 前提：它就是那个只读展示框。
    expect(ticket.readOnly).toBe(true);

    /* 判据层：不管它落在哪个容器里（它的按钮在兄弟节点 .options 里，所以"所在块里有按钮"
       这条判据够不到它），都不许被判成"可自动提交"。
       没修之前这里返回 true —— #netInvite 不在排除名单里，而只读不挡失焦。*/
    expect(fixApi.form.isAutoCommit(ticket)).toBe(false);

    // 行为层：把票填上、聚焦再失焦，一个写请求都不许有。
    ticket.value = "invite-ticket-secret-abc";
    ticket.dispatchEvent(new fixDom.window.Event("focus"));
    ticket.dispatchEvent(new fixDom.window.Event("blur"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    /* 没修之前这条路会 POST settingSave → PUT /console/profile，
       请求体里带着票的全文 —— 所以这条断言是这条 bug 的正面钉子。*/
    expect(writes()).toEqual([]);
    // 页面确实起过请求（否则上面那条可能只是"压根没发过任何请求"）。
    expect(sent.length).toBeGreaterThan(0);
    expect(sent.every((call) => call.method === "GET")).toBe(true);
  });

  it("BUG-1：state.patch / state.set 都写不进原型链", async () => {
    await loadFix();
    const winObject = (fixDom.window as unknown as { Object: { prototype: object } }).Object;
    const proto = winObject.prototype;

    /* JSON.parse 造出来的 __proto__ 是**自有可枚举**属性（Object.keys 会把它列出来），
       这正是 deepAssign 最容易踩的那条路：不挡的话等价于改 Object.prototype。
       注意要查 jsdom 那个 realm 的原型（页面代码跑在里面），不是测试自己这个 realm 的。*/
    fixApi.state.patch(JSON.parse('{"__proto__":{"polluted":"yes"}}'));
    expect(Object.prototype.hasOwnProperty.call(proto, "polluted")).toBe(false);

    // 路径写法是同一个洞：setPath 会顺着 '__proto__' 走到 Object.prototype 上。
    fixApi.state.set("__proto__.polluted2", "yes");
    expect(Object.prototype.hasOwnProperty.call(proto, "polluted2")).toBe(false);
    fixApi.state.set("constructor.prototype.polluted3", "yes");
    expect(Object.prototype.hasOwnProperty.call(proto, "polluted3")).toBe(false);

    /* 正常字段照旧：写得进、也照样深合并 —— 守卫不许把正常路径也挡了。*/
    fixApi.state.patch({ demo: { a: 1 } });
    fixApi.state.patch({ demo: { b: 2 } });
    fixApi.state.set("demo.c", 3);
    expect(fixApi.state.get("demo")).toEqual({ a: 1, b: 2, c: 3 });
  });

  it("BUG-5：远端自报的机器名会被转义（塞不进 HTML）", async () => {
    await loadFix();
    /* 机器名是远端 `agent import --machine` 自报的，中间层原样透出 —— 属外部输入。
       2026-10-04 起它画在**详细信息窗口**的「在哪台机器」那一行（卡面只写在线/离线）。*/
    const machine = 'x<img src="x" onerror="window.__pwned=1">';
    const row = {
      id: "a-9", isMain: false, role: "子 Agent", name: "远端甲",
      network: true, online: true, machine: machine, session: "ready",
      icon: "", statusText: "已领取", statusOk: true,
      desc: "", currentTask: "", basic: [], ops: [], actions: [],
    };
    fixApi.dispatch("agent.list", [row]);

    /* 卡面上只有机器状态 —— 机器名不再拼进卡片，那里自然也不会多出元素。*/
    const badge = fixPage.querySelector("#pane-agents .header .right")!;
    expect(badge.textContent).toBe("在线");
    expect(badge.querySelector("img")).toBeNull();

    /* 机器名在窗口里，同样必须转义：没修之前这台机器上会真的多出一个
       <img src="x" onerror=…>。*/
    fixApi.dispatch("agent.info", row);
    const shown = fixPage.querySelector("#agentInfoMachine")!;
    expect(shown.querySelector("img")).toBeNull();
    expect((fixDom.window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    // 转义不是"吞掉"：字面量照旧显示给人看。
    expect(shown.textContent).toContain('x<img src="x"');
  });

  /* ---- 下面这几条钉的是同一轮修掉的另外一批 -------------------------------- */

  const tip = () => fixPage.getElementById("AnnounceMent2")!;
  const tipText = () => tip().querySelector(".aText")!.textContent ?? "";
  const agentOf = (over: Record<string, unknown>) => Object.assign({
    id: "a-1", isMain: false, role: "子 Agent", name: "甲",
    network: false, online: false, machine: "",
    icon: "", statusText: "已领取", statusOk: true,
    desc: "", currentTask: "", basic: [], ops: [], actions: [],
  }, over);
  const replyWith = (status: number, body: string) =>
    ({ ok: false, status: status, text: () => Promise.resolve(body) });

  it("BUG-23 + BUG-2：拒绝码真的被翻成中文，而且落在「警告」档", async () => {
    /* 词表的形状是 {version, domains:{…}}。以前查的是 glossary.denial_reason（永远空），
       而且失败提示走 notify.info —— 那一档不翻译。两条都得对，这句才说得上人话。*/
    await loadFix({ reply: () => replyWith(409, '{"detail":{"code":"ready_session_required"}}') });
    fixApi.state.set("glossary", {
      version: 1, domains: { denial_reason: { ready_session_required: "会话未就绪" } },
    });

    await fixApi.api.get("/whatever").catch(() => undefined);

    expect(tipText()).toBe("会话未就绪");
    expect(tip().classList.contains("secAnnounce2Warning")).toBe(true);
    expect(tip().classList.contains("secAnnounce2Error")).toBe(false);
  });

  it("BUG-2：连不上（没有 HTTP 状态）落在「错误」档，而不是「提示」档", async () => {
    await loadFix();   // 默认那份 fetch 直接 reject = 网络错误
    await fixApi.api.get("/whatever").catch(() => undefined);
    expect(tip().classList.contains("secAnnounce2Error")).toBe(true);
  });

  it("BUG-3：提交失败不记「已提交值」，同一个值再失焦还会重发", async () => {
    await loadFix({ reply: () => replyWith(500, '{"detail":"boom"}') });
    const box = fixPage.createElement("input");
    fixPage.body.appendChild(box);
    box.value = "同一个值";

    await fixApi.form.commit(box, { path: "/x", silent: true }).catch(() => undefined);
    const first = writes().length;
    expect(first).toBeGreaterThan(0);

    /* 修好之前 committedValues 在发请求**之前**就记下了这个值，
       于是这一次 value === previous 成立、直接 return —— 一次请求都不会多。*/
    await fixApi.form.commit(box, { path: "/x", silent: true }).catch(() => undefined);
    expect(writes().length).toBeGreaterThan(first);
  });

  it("BUG-25：icon 是 constructor / toString 这类键时回落到 Tsunagou 小标", async () => {
    await loadFix();
    /* 对象字面量当映射表时，这些键会命中原型链拿到函数（真值）→ 回退不到小标，
       最后把一个函数源码塞进 img.src（图裂，属性值荒谬）。*/
    for (const bad of ["constructor", "toString", "__proto__"]) {
      fixApi.dispatch("agent.list", [agentOf({ icon: bad })]);
      const img = fixPage.querySelector("#pane-agents img")!;
      expect(img.getAttribute("src")).toContain("logo-little");
    }
  });

  it("BUG-26：向导第 3 步的「×」不再发那条注定被拒的删除请求", async () => {
    await loadFix();
    fixApi.render.wizardSubAgents([{ name: "甲", vendor: "codex", icon: "", status: "manual" }]);
    const chip = fixPage.querySelector("#newXz3 .listfieldbox .itemC")!;
    chip.dispatchEvent(new fixDom.window.MouseEvent("click", { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    /* 以前这里会弹「确定要让这个 Agent 退役吗？」再发一次 agentRemove ——
       而 agent_id 是必填、这个入口又没传，必然被拒，胶囊还留在原地。*/
    expect(writes()).toEqual([]);
    expect(tipText()).toContain("还没接通");
    // 胶囊没被删掉（前端也没有假装删掉）。
    expect(fixPage.querySelectorAll("#newXz3 .listfieldbox .itemC").length).toBe(1);
  });

  it("BUG-4：点卡片本体就能开详情，而且窗口里真有内容", async () => {
    await loadFix();
    fixApi.state.set("currentProjectId", "p-1");
    fixApi.dispatch("agent.list", [agentOf({ id: "a-7", name: "远端甲" })]);
    fixApi.dispatch("agent.window", [{
      id: "p-1/a-7", agent_id: "a-7", project: "示例", task: "对齐接口",
      network: true, online: true, machine: "工位-七", copy_path: "", copy_baseline: "",
    }]);

    /* 卡片本体（不是里面那个头像胶囊）。修好之前卡片上没有 data-agent-id，
       点它什么都不发生。*/
    const card = fixPage.querySelector("#pane-agents .boxerbox > .item")!;
    expect(card.getAttribute("data-agent-id")).toBe("a-7");
    card.dispatchEvent(new fixDom.window.MouseEvent("click", { bubbles: true }));

    const info = fixPage.getElementById("mgrAgentInfo")!;
    expect(info.style.display).toBe("flex");            // 窗口真的被打开了
    expect(info.getAttribute("data-agent-id")).toBe("a-7");
    /* 而且不是空壳：协作与任务两行填上了。管理页给的是裸 agent_id，而 agentsWindow
       的 id 是「协作/Agent」—— 只按一种形状查的话这里全是空的。*/
    const shown = [...info.querySelectorAll(".dspText2")].map((node) => node.textContent);
    expect(shown[0]).toBe("示例");
    expect(shown[1]).toBe("对齐接口");
  });

  it("BUG-9：poll_ms 是 null 或空串时不要当成 0（0 = 关掉自动重拉）", async () => {
    /* null / '' / false 经 Number() 都是 0，而 0 是"不自动重拉"的合法值 ——
       于是"没写这个字段"被静默当成"明确要求不轮询"。*/
    /* 这条要一个**干净的地址**：默认那份 loadFix 的地址带 ?poll_ms=0（开发开关），
       那会把配置顶掉，测的就不是配置这条路了。*/
    await loadFix({ query: "", config: { baseUrl: "/api/v1", poll_ms: null } });
    expect(Number(fixApi.config.get().pollMs)).not.toBe(0);

    // 地址栏上的 ?poll_ms=（空值）同理，不能顶掉配置里的 5000。
    await loadFix({ query: "?poll_ms=", config: { baseUrl: "/api/v1", poll_ms: 5000 } });
    expect(Number(fixApi.config.get().pollMs)).toBe(5000);

    // 但明确的 0 仍然是"不自动重拉"：这条语义不能被我改坏。
    await loadFix({ query: "?poll_ms=0", config: { baseUrl: "/api/v1", poll_ms: 5000 } });
    expect(Number(fixApi.config.get().pollMs)).toBe(0);
  });

  /* ---- 窗口政策：黑遮罩不做反应 ------------------------------------------ */

  it("窗口政策：点黑遮罩什么都不做（普通窗口与加载遮罩都一样）", async () => {
    await loadFix();
    const backdrop = (id: string) => {
      const node = fixPage.getElementById(id)!;
      /* 黑遮罩就是 .secWindow 自己那一层：点在它身上（不是窗口盒子里）。*/
      node.dispatchEvent(new fixDom.window.MouseEvent("click", { bubbles: true }));
      return node.style.display;
    };
    fixApi.ui.window.open("renamePmt");
    expect(backdrop("renamePmt")).toBe("flex");
    /* 加载遮罩尤其重要：它只由窗口里的按钮（或流程自己）收场，
       点黑边不再等于"我不等了"。*/
    fixApi.ui.window.open("loadW");
    expect(backdrop("loadW")).toBe("flex");
  });

  /* ---- 阶段 2 第 8 条：几处静默成功 -------------------------------------- */

  it("阶段2-8：详情窗昵称没改就安静关窗，不发请求也不弹提示", async () => {
    await loadFix();
    const info = fixPage.getElementById("mgrAgentInfo")!;
    info.setAttribute("data-agent-id", "a-7");
    info.setAttribute("data-nickname", "熊猫");
    info.querySelector("input")!.value = "熊猫";
    fixApi.ui.window.open("mgrAgentInfo");

    await fixApi.app.saveAgentInfo();
    /* 点确定却没动过任何字 = 取消：窗口关掉、没有请求、也不该弹一句话打扰。
       2026-10-04 用户实测要求，覆盖此前"如实说一句、不静默关窗"的旧口径。*/
    expect(fixApi.ui.window.isOpen("mgrAgentInfo")).toBe(false);
    expect(tipText()).not.toContain("没有改动");
    expect(writes()).toEqual([]);
  });

  it("从列表点进一个名单里查不到的 id：窗口仍认下改的是谁，改名才存得下去", async () => {
    await loadFix();
    fixApi.state.set("agentsWindow", []);

    // 名单有两种形状：「协作/Agent」与裸 agent_id，查不到时要取斜杠后面那一段做身份 ——
    // 否则窗口连"改谁"都不知道，一个字没改也会弹"这条记录里没有 Agent 号"。
    fixApi.app.openAgentInfo("p-9/a-9");

    const info = fixPage.getElementById("mgrAgentInfo")!;
    expect(info.getAttribute("data-agent-id")).toBe("a-9");
  });

  it("阶段2-8：协作名字没变就不发重命名请求，也不报「已重命名」", async () => {
    await loadFix();
    fixApi.state.set("projects", [{ id: "p-1", name: "示例协作" }]);
    fixApi.app.renameProject("p-1");
    fixPage.querySelector<HTMLInputElement>("#renamePmtInput")!.value = "示例协作";

    await fixApi.app.submitRename();
    expect(tipText()).toContain("名字没有改动");
    expect(writes()).toEqual([]);
  });

  it("阶段2-8：主题存不上要说出来（否则重开又变回去）", async () => {
    await loadFix({ reply: () => replyWith(500, '{"detail":"boom"}') });
    const box = fixPage.getElementById("uSetCol1")!;
    box.dispatchEvent(new fixDom.window.CustomEvent("choosebox:change", {
      bubbles: true, detail: { value: "浅色", panel: box, box: box },
    }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(tipText()).toContain("主题没能保存");
    expect(writes().map((call) => call.method)).toEqual(["PUT"]);
  });

  it("阶段2-8：位置＝网络而编号空着时，不发那条注定失败的准备请求", async () => {
    await loadFix();
    fixApi.state.set("hosts", [{ adapter: "codex", label: "Codex", mode: "console" }]);
    /* 这家宿主需要"远端自己报的编号"（NETWORK_NUMBER_VENDORS 里有 Codex）。*/
    await fixApi.actions.addSubAgent({ name: "远端甲", vendor: "Codex", place: "network", number: "" });
    expect(tipText()).toContain("会话编号");
    expect(writes()).toEqual([]);
  });

  /* ---- 阶段 2 第 7 条：没有遮罩的那次提交要自己防连点 -------------------- */

  it("阶段2-7：昵称保存没有加载遮罩，连点两次也只发一次请求", async () => {
    await loadFix({ reply: () => ({ ok: true, status: 200, text: () => Promise.resolve('{"status":"saved"}') }) });
    const info = fixPage.getElementById("mgrAgentInfo")!;
    info.setAttribute("data-agent-id", "a-7");
    info.setAttribute("data-nickname", "旧名字");
    info.querySelector("input")!.value = "新名字";

    const first = fixApi.app.saveAgentInfo();
    const second = fixApi.app.saveAgentInfo();
    await Promise.all([first, second]);
    expect(writes().length).toBe(1);
  });
});

/* ============================================================================
 * 「冲突与协商」/「意图与权限审计」的显示回归（2026-10-04）
 * ----------------------------------------------------------------------------
 * 下面几条是同一类毛病：**适配层读了出口里根本没有的键**，于是数据明明有、
 * 屏上却是空的或者错的：
 *   · 分歧卡片读 `actor_agent_id` / `subject_ref` / `updated_at`（出口里都没有），
 *     于是 Agent 列恒空、时间恒空、标题只剩英文规则代号；
 *   · 契约的「已确认 Agent」去 /cognition 找 acceptances（那个出口从不导出它），
 *     participants 是对象数组却被当字符串印成 `[object `；
 *   · 审计页第 1 个子标签挂着一个无条件返回空列表的出口，点进去什么都没有。
 * 断言一律落在渲染出来的 DOM 上，不断言适配层的中间值 —— 后者改歪了照样绿。
 * ==========================================================================*/
describe("冲突 / 契约 / 审计：适配层只读出口真有的键", () => {
  type CollabWin = {
    fetch: unknown;
    Tsunagou: {
      refresh: (keys?: string[]) => Promise<unknown>;
      state: {
        set: (path: string, value: unknown) => unknown;
        get: (path: string, fallback?: unknown) => unknown;
      };
      dispatch: (type: string, payload?: unknown) => { ok: boolean; error?: string };
    };
  };

  const collabWin = (): CollabWin => dom.window as unknown as CollabWin;

  /* 应答表：匹配是"路径里包含即算"，更具体的路径要排在前面。 */
  function serve(replies: [string, unknown][]): void {
    collabWin().fetch = (url: string) => {
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
  }

  /* 卡片里「标签 → 紧跟它的那一格」：卡片的各字段是兄弟节点（见 dissentCardHtml
     与契约卡片那段 parts）。标签找不到就直接失败 —— 这正是"这一行没画出来"。*/
  function fieldOf(card: Element, label: string): Element {
    const head = [...card.querySelectorAll(".title")].find((node) => node.textContent === label);
    expect(head, `卡片里没有「${label}」这一行`).toBeTruthy();
    return head!.nextElementSibling as Element;
  }

  function chipNames(node: Element): string[] {
    return [...node.querySelectorAll(".listfieldbox > .item > .right")]
      .map((item) => item.textContent ?? "");
  }

  /* 中间层词表（/console/glossary）里与本次有关的那几域。词本身住在
     src/tsunagou/console/glossary.py，页面只负责查表；这里按真实答复的形状给。*/
  const GLOSSARY = {
    version: 5,
    domains: {
      discrepancy_rule: {
        "claim.literal_mismatch": "说法不一致",
        "claim.contract_digest_mismatch": "契约版本不符",
        "claim.resource_use_mismatch": "资源用法不符",
        "manual.discrepancy": "人工记录",
      },
      discrepancy_severity: { soft: "轻微", hard: "严重", critical: "致命" },
      discrepancy_status: { open: "未处理", clarifying: "澄清中", negotiating: "协商中" },
      ref_kind: { task: "任务" },
    },
  };

  const AGENTS = {
    items: [
      { agent_id: "a-1", role: "worker", status: "active" },
      { agent_id: "a-2", role: "worker", status: "active" },
      { agent_id: "a-3", role: "worker", status: "active" },
    ],
  };

  /* 昵称住在中间层的用户档案里（不在协作事实里），所以显式铺一份，
     免得与前面那些测试留在 state 里的档案串味。*/
  function profile(): void {
    collabWin().Tsunagou.state.set("profile", {
      nickname: "",
      theme: "",
      agents: {
        "a-1": { nickname: "熊猫" },
        "a-2": { nickname: "海豚" },
        "a-3": { nickname: "树懒" },
      },
    });
  }

  it("分歧卡片：标题是人话、Agent 由 claim_ids→reports 派生、严重度与状态画得出来、「…的理解」有内容", async () => {
    serve([
      ["/console/glossary", GLOSSARY],
      ["/console/views/collaboration", {
        sources: {
          agents: AGENTS,
          cognition: {
            reports: [
              {
                report_id: "r-1", task_id: "t-1", attempt_id: "at-1", actor_agent_id: "a-1",
                digest: "sha256:r1", input_revisions: {},
                claims: [{
                  subject_key: "接口契约", claim_type: "literal", equality_key: "接口契约",
                  value: "A 说：字段必填",
                }],
              },
              {
                report_id: "r-2", task_id: "t-1", attempt_id: "at-2", actor_agent_id: "a-2",
                digest: "sha256:r2", input_revisions: {},
                claims: [{
                  subject_key: "接口契约", claim_type: "literal", equality_key: "接口契约",
                  value: "B 说：字段可空",
                }],
              },
            ],
            /* 出口给的就这 7 个键：没有 actor_agent_id / subject_ref / 任何时间。
               参与 Agent 只能由 claim_ids 里的报告号 join 回 reports 的 actor_agent_id。
               注意 claim_ids 装的是**报告号**，而且自动判定出的分歧只记下**触发它的
               那一份**报告（modules/cognition.py 的 `_record_discrepancy(…, report)`）
               —— 这里照真实的形状给一条。*/
            discrepancies: [{
              discrepancy_id: "d-1", rule_id: "claim.literal_mismatch", subject_key: "接口契约",
              severity: "hard", status: "open", claim_ids: ["r-2"], input_digest: "sha256:d1",
            }],
          },
          contracts: { items: [] },
          messages: { items: [] },
          conflicts: { items: [] },
        },
        missing: {},
      }],
    ]);
    const win = collabWin();
    win.Tsunagou.state.set("currentProjectId", "p-1");
    profile();
    await win.Tsunagou.refresh(["glossary"]);
    await win.Tsunagou.refresh(["conflicts"]);

    const card = page.querySelector<HTMLElement>(
      '#block-conflict .tabContent .boxerbox > .item[data-row-id="d-1"]',
    );
    expect(card).not.toBeNull();

    // ① 卡头是人话（词表 discrepancy_rule），不是英文规则代号。
    expect(card!.querySelector(".header")!.textContent).toBe("说法不一致");
    // ② 规则代号仍然留着 —— 人要靠它跟账本、协议对上（短号那套同一个道理）。
    expect(fieldOf(card!, "规则").textContent).toContain("claim.literal_mismatch");
    // ③ 参与 Agent 由 claim_ids → reports.actor_agent_id 派生（以前读的键不存在，恒空）。
    expect(chipNames(card!)).toEqual(["海豚"]);
    // ④ severity / status 出口早就给了，以前一处没画。
    expect(fieldOf(card!, "严重度").textContent).toContain("严重");
    expect(fieldOf(card!, "处理状态").textContent).toContain("未处理");
    // ⑤ 影响范围是那件被说岔的事本身。
    expect(fieldOf(card!, "影响范围").textContent).toContain("接口契约");
    // ⑥ 「…的理解」写的是那份报告在被说岔的主题上说的话（以前恒空）。
    expect(card!.textContent).toContain("海豚的理解");
    expect(card!.textContent).toContain("B 说：字段可空");
    /* ⑦ 另一半**不补**：熊猫那份报告确实在同一个主题上说了别的话，但这条分歧里没有
       它的报告号（自动判定只记触发的那一份），页面不能凭"同一主题的另一份报告"去凑
       一个参与者出来 —— 那是编。要显示双方，得先让后端把对方也存下来。*/
    expect(card!.textContent).not.toContain("熊猫");
    // ⑧ 分歧没有任何时间戳可读（出口与领域模型里都没有），就不画时间那一行：
    //    宁可少一行，也不拿报告时间冒充"分歧发生的时间"。
    expect(card!.querySelectorAll(".textTime")).toHaveLength(0);

    // ⑨ 点卡片开侧栏：细节与卡片同一套字段（以前侧栏里是英文代号 + 一行空时间）。
    card!.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    const aside = page.getElementById("aside-conflict")!;
    expect(aside.style.display).toBe("flex");
    const detail = aside.querySelector(".content")!;
    expect(detail.textContent).toContain("claim.literal_mismatch");
    expect(detail.textContent).toContain("严重");
    expect(detail.textContent).toContain("未处理");
    expect(detail.textContent).toContain("海豚的理解");
    expect(detail.textContent).not.toContain("时间");
  });

  it("分歧引用多份报告时（discrepancy.create 的 report_refs）：参与 Agent 逐个出来且不重复", async () => {
    serve([
      ["/console/glossary", GLOSSARY],
      ["/console/views/collaboration", {
        sources: {
          agents: AGENTS,
          cognition: {
            reports: [
              { report_id: "r-1", actor_agent_id: "a-1", claims: [] },
              { report_id: "r-2", actor_agent_id: "a-2", claims: [] },
              { report_id: "r-3", actor_agent_id: "a-2", claims: [] },
            ],
            discrepancies: [{
              discrepancy_id: "d-4", rule_id: "manual.discrepancy", subject_key: "task/t-9",
              severity: "soft", status: "open", claim_ids: ["r-1", "r-2", "r-3"],
              input_digest: "sha256:d4",
            }],
          },
          contracts: { items: [] },
          messages: { items: [] },
          conflicts: { items: [] },
        },
        missing: {},
      }],
    ]);
    const win = collabWin();
    win.Tsunagou.state.set("currentProjectId", "p-1");
    profile();
    await win.Tsunagou.refresh(["glossary"]);
    await win.Tsunagou.refresh(["conflicts"]);

    const card = page.querySelector<HTMLElement>(
      '#block-conflict .tabContent .boxerbox > .item[data-row-id="d-4"]',
    );
    expect(card).not.toBeNull();
    // 同一个 Agent 报了两份就是一个人；抬头是词表里 manual.discrepancy 的说法。
    expect(chipNames(card!)).toEqual(["熊猫", "海豚"]);
    expect(card!.querySelector(".header")!.textContent).toBe("人工记录");
  });

  it("分歧的「影响范围」：引用才缩写，`workspace.driver` 这种主题名原样印（不截成 8 个字符）", async () => {
    serve([
      ["/console/glossary", GLOSSARY],
      ["/console/views/collaboration", {
        sources: {
          agents: AGENTS,
          cognition: {
            reports: [],
            discrepancies: [
              {
                discrepancy_id: "d-2", rule_id: "claim.literal_mismatch",
                subject_key: "workspace.driver", severity: "soft", status: "clarifying",
                claim_ids: [], input_digest: "sha256:d2",
              },
              {
                discrepancy_id: "d-3", rule_id: "manual.discrepancy",
                subject_key: "task/0108a623-4f59-4d8e-be4e-67ea1667a106", severity: "hard",
                status: "negotiating", claim_ids: [], input_digest: "sha256:d3",
              },
            ],
          },
          contracts: { items: [] },
          messages: { items: [] },
          conflicts: { items: [] },
        },
        missing: {},
      }],
    ]);
    const win = collabWin();
    win.Tsunagou.state.set("currentProjectId", "p-1");
    profile();
    await win.Tsunagou.refresh(["glossary"]);
    await win.Tsunagou.refresh(["conflicts"]);

    const scopeOf = (id: string): string => fieldOf(
      page.querySelector(`#block-conflict .tabContent .boxerbox > .item[data-row-id="${id}"]`)!,
      "影响范围",
    ).textContent ?? "";
    expect(scopeOf("d-2")).toBe("workspace.driver");
    expect(scopeOf("d-3")).toBe("任务 0108a623");
  });

  it("契约卡片：已确认/未确认读 /contracts 自己的 acceptances，participants 按对象取 agent_id", async () => {
    serve([
      ["/console/glossary", GLOSSARY],
      ["/console/views/collaboration", {
        sources: {
          agents: AGENTS,
          /* /cognition 从来不导出 acceptances —— 签名记录就在下面 /contracts 的每项里。*/
          cognition: { reports: [], discrepancies: [], contracts: [] },
          messages: { items: [] },
          conflicts: { items: [] },
          contracts: {
            items: [{
              proposal_id: "c-1", digest: "sha256:c1", status: "proposed",
              payload: { task_id: "t-1" }, supersedes_id: null, resolution_reason: null,
              required_slots: ["api", "ui"],
              participants: [
                { slot: "api", agent_id: "a-1", required: true },
                { slot: "ui", agent_id: "a-2", required: true },
                { slot: "review", agent_id: "a-3", required: false },
              ],
              acceptances: [{
                participant_slot: "api", proposal_digest: "sha256:c1", real_actor_id: "a-1",
                represented_participant: null, via_proxy: false,
              }],
            }],
          },
        },
        missing: {},
      }],
    ]);
    const win = collabWin();
    win.Tsunagou.state.set("currentProjectId", "p-1");
    profile();
    await win.Tsunagou.refresh(["glossary"]);
    await win.Tsunagou.refresh(["conflicts"]);

    const card = page.querySelector<HTMLElement>(
      '#block-conflict .tabContent .boxerbox > .item[data-row-id="c-1"]',
    );
    expect(card).not.toBeNull();
    // 签了的那一个在「已确认」，没签的两个在「未确认」；两边是同一份 participant 名单。
    expect(chipNames(fieldOf(card!, "已确认 Agent"))).toEqual(["熊猫"]);
    expect(chipNames(fieldOf(card!, "未确认 Agent"))).toEqual(["海豚", "树懒"]);
    // 对象被当成字符串的痕迹不许出现（`[object Object]` 截 8 个字符就是 `[object `）。
    expect(card!.textContent).not.toContain("[object");
  });

  it("审计页：只剩一栏所以没有子标签，标题是「租约审计」，点某一行开的是那一行的侧栏", async () => {
    /* 后端仍然把 /intents 列为这一屏的一个来源（中间层 CONSOLE_VIEWS 与它自己的
       测试都钉着那份名单）—— 页面不再读它，也不为它画一格。
       resources 出口给的是 `reservation_id`（显式预约模型），行身份就用它；
       `lease_set_id` / `revision` 是租约集合时代的旧拼法，出口里已经没有。
       2026-10-04：这一屏只剩一栏，那条只剩一个选项的子标签栏被去掉，整页直接生成
       （与 Agent 管理 / 工作区同一个写法）。*/
    serve([
      ["/console/views/audit", {
        sources: {
          agents: { items: [{ agent_id: "a-1", role: "main", status: "active" }] },
          resources: {
            items: [
              {
                reservation_id: "R-1", owner_agent_id: "a-1", status: "active",
                resources: ["file:src/x.py"],
              },
              {
                reservation_id: "R-2", owner_agent_id: "a-1", status: "released",
                resources: ["file:src/y.py"],
              },
            ],
          },
          intents: { items: [{ intent_id: "i-1", owner_agent_id: "a-1" }] },
        },
        missing: {},
      }],
    ]);
    const win = collabWin();
    win.Tsunagou.state.set("currentProjectId", "p-1");
    profile();
    await win.Tsunagou.refresh(["audits"]);

    const pane = page.getElementById("pane-audit")!;
    // 没有子标签栏、也没有藏着的面板：内容直接铺在这一页上。
    expect(pane.querySelectorAll(".tabPlace, .tabItem, .tabContent")).toHaveLength(0);
    expect(pane.textContent).toContain("租约审计");
    expect(pane.textContent).toContain("已经获得的租约");
    const rows = [...pane.querySelectorAll(".tablebox .tr")];
    expect(rows).toHaveLength(2);
    // 每一行都认得出自己是谁（以前读 lease_set_id，出口没有这个键 → 行号是空的，
    // 点哪一行都只会打开第一条租约）。
    expect(rows.map((node) => node.getAttribute("data-row-id"))).toEqual(["R-1", "R-2"]);
    // 出口不给 revision，所以「声明版本」那一列不许再摆着（原来恒空）。
    expect([...pane.querySelectorAll(".tablebox .th .colu")].map((cell) => cell.textContent))
      .toEqual(["Agent", "批准范围", "租约"]);
    // 出口给了 intents 数据，页面也不攒它、不画它 —— 那是被显式 reservation 取代的旧模型。
    expect(win.Tsunagou.state.get("audits")).not.toHaveProperty("intents");
    expect(pane.textContent).not.toContain("i-1");

    rows[1]!.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    const aside = page.getElementById("aside-audit")!;
    expect(aside.style.display).toBe("flex");
    // 点第二行给的是第二行的租约，不是第一条。
    expect(aside.textContent).toContain("file:src/y.py");
    expect(aside.textContent).not.toContain("file:src/x.py");

    // 静态骨架上既不再留着那半个标签，也不再叫旧名字。
    const html = readWeb("index.html");
    expect(html).not.toContain("Agent 意图");
    expect(html).not.toContain("Agent 权限");
    expect(html).not.toContain("意图与权限审计");
    expect(html).toContain("租约审计");
  });

  /* 2026-10-04 用户实测：滚动条还是会被打回顶部。根因是"谁在滚"认错了 ——
     子标签内容区 `.tabContent` 声明了 overflow:auto 却**没有 id**，原来按 `[id]` 收位置的
     写法漏掉它；而页面所有重绘都从 fill() 出去，被填的正是这个节点自己。
     jsdom 没有布局，所以这里把"浏览器换掉内容就把 scrollTop 归零"**显式做掉** ——
     不做，这条测试只会恒过，与真浏览器里的表现无关。*/
  it("重绘不把人弹回顶部：没有 id 的滚动节点也记得住位置", async () => {
    serve([
      ["/console/views/collaboration", { sources: {
        agents: { items: [{ agent_id: "a-1", status: "active", role: "worker" }] },
        messages: { items: [{
          message_id: "m-1", sender_agent_id: "a-1", recipient_agent_id: "a-1",
          summary: "一条消息", status: "none", obligations: [],
        }] },
      } }],
    ]);
    const win = collabWin();
    win.Tsunagou.state.set("currentProjectId", "p-1");
    profile();
    await win.Tsunagou.refresh(["conflicts"]);

    const pane = page.querySelector("#block-conflict .tabContent")!;   // 就是没有 id 的那个
    pane.scrollTop = 180;
    const proto = Object.getOwnPropertyDescriptor(dom.window.Element.prototype, "innerHTML")!;
    Object.defineProperty(pane, "innerHTML", {
      configurable: true,
      get() { return proto.get!.call(pane); },
      // 模拟真浏览器：innerHTML 一换，这个节点的滚动位置就归零。
      set(value: string) { proto.set!.call(pane, value); (pane as HTMLElement).scrollTop = 0; },
    });

    await win.Tsunagou.refresh(["conflicts"]);   // 再画一次 = 真浏览器里每几秒发生一次

    expect(pane.scrollTop).toBe(180);
  });
});
