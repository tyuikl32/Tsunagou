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
});
