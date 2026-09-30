/* 前端结构冒烟 —— web/tests/behavior.smoke.test.ts
 * ----------------------------------------------------------------------------
 * 为什么有这一份：这一轮踩到的两个 bug 都不是"逻辑算错了"，而是**结构**错了 ——
 *
 *   1) 总路径的行从 `.taskFlow > .inner > .item` 少了一层 `.inner`，于是点击行用的
 *      选择器（两级 `>`）再也匹配不上 —— 行点不开；
 *   2) 「任务验收情况」的结果格把标签和几行说明当**兄弟节点**摆进那个宽 200px 的
 *      flex 行容器，于是一格被挤成竖排、文字全糊：多行内容必须套 `.colu-t`。
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
import { afterAll, beforeAll, describe, expect, it } from "vitest";

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
});
