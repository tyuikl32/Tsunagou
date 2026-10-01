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

  /* 接入一个 Agent 时，等待遮罩必须先说清"在哪个目录开窗口"。
     宿主的窗口开在哪个目录，决定了那个会话里的 Agent 能不能读到这个项目的规矩文件
     （`.tsunagou/agent-context.md`、`AGENTS.md` 受管区块）—— 读不到它不会报错，只会
     没有任何"我在哪个项目"的线索，然后照自己的"安装并初始化"说明去别处新建一个项目
     （真实发生过）。目录只有一个来源：中间层的项目列表（daemon 的出口不含文件路径）。*/
  it("等待接入的遮罩里写着在哪个目录开窗口", async () => {
    const win = dom.window as unknown as {
      fetch: unknown;
      Tsunagou: {
        state: { set: (path: string, value: unknown) => void };
        ui: { wizard: { go: (n: number) => number; next: () => Promise<unknown> } };
        notify: { loadingEnd: () => boolean };
      };
    };
    const projectPath = "E:\\Tsunagou\\projects\\示例协作";
    /* 中间层那份项目列表是目录的唯一来源（daemon 的概况出口不含文件路径）。
       这里喂的是**适配后**的形状，和 `project.list` 路由收到的一样。*/
    api.dispatch("project.list", [
      { id: "p-1", name: "示例协作", path: projectPath, available: true },
    ]);
    win.Tsunagou.state.set("hosts", [{ adapter: "codex", label: "Codex", supported: true }]);
    /* 第 1 步建完会刷新项目列表并把"当前项目"切过去（`openProject`），所以第 2 步
       手里两样都有：一份带 path 的列表 + 一个 currentProjectId。*/
    win.Tsunagou.state.set("currentProjectId", "p-1");
    win.Tsunagou.state.set("wizard.project", { id: "p-1", name: "示例协作" });

    /* 第 2 步会真的去中间层"准备接入"：这里让它走到"正在等待连接"就够。*/
    const prepared = {
      status: "prepared", enrollment_id: "e-1", profile: "p",
      host_registration: { status: "registered" },
    };
    win.fetch = () => Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve(prepared),
      text: () => Promise.resolve(JSON.stringify(prepared)),
    });

    win.Tsunagou.ui.wizard.go(2);
    (page.querySelector("#newXz2 input") as HTMLInputElement).value = "熊猫";
    const pending = win.Tsunagou.ui.wizard.next();

    /* 那句话是"准备"回来之后才写的，等它出现。*/
    let text = "";
    for (let tick = 0; tick < 40 && text.indexOf(projectPath) < 0; tick += 1) {
      await new Promise((resolve) => dom.window.setTimeout(resolve, 0));
      text = page.querySelector("#loadW .textW")?.textContent ?? "";
    }
    expect(text).toContain(projectPath);
    expect(text).toContain("Codex");

    /* 收尾：关掉遮罩让等待循环自己停，别留一个 2 秒的定时器在跑。*/
    win.Tsunagou.notify.loadingEnd();
    void pending.catch(() => undefined);
  });

  /* "到了"和"就位"是两件事。名单里多出一个会话只说明它兑换了票；主 Agent 的任命是
     daemon 在"会话就绪"那一步顺手做的，而首次接入天然还不就绪（连续性证据要前一次和
     这一次两份摘要）。所以遮罩必须能把"已经连上，但还缺哪几项"这句话换上 —— 否则人看到
     的只是一个转不停、最后报"票过期"的遮罩，却不知道票早就被兑换了。*/
  it("轮询到「已连上但还没就位」时，遮罩改说还缺什么", async () => {
    const win = dom.window as unknown as {
      fetch: (url: string) => Promise<unknown>;
      Tsunagou: {
        state: { set: (path: string, value: unknown) => void };
        ui: {
          wizard: { go: (n: number) => number; next: () => Promise<unknown> };
          window: { isOpen: (id: string) => boolean };
        };
        notify: { loadingEnd: () => boolean };
      };
    };
    /* jsdom 不排版，`isShown()`（checkVisibility / getClientRects）永远是 false，
       等待循环会据此以为"遮罩被人关掉了"而立即收摊（真实浏览器里不会）。
       这一条测的是轮询到的文案，所以把"遮罩还开着"这件事直接告诉它。*/
    win.Tsunagou.ui.window.isOpen = () => true;
    const projectPath = "E:\\Tsunagou\\projects\\示例协作";
    api.dispatch("project.list", [
      { id: "p-1", name: "示例协作", path: projectPath, available: true },
    ]);
    win.Tsunagou.state.set("hosts", [{ adapter: "codex", label: "Codex", supported: true }]);
    win.Tsunagou.state.set("currentProjectId", "p-1");
    win.Tsunagou.state.set("wizard.project", { id: "p-1", name: "示例协作" });

    const prepared = {
      status: "prepared", enrollment_id: "e-1", profile: "p",
      host_registration: { status: "registered" },
    };
    const calls: string[] = [];
    /* 中间层对"还没就位"的回答（console/enrollment.py 的 `pending`）。*/
    const joining = {
      status: "waiting", enrollment_id: "e-1", agent_id: null,
      pending: {
        agent_id: "a-9", role: "worker", session_status: "degraded",
        missing_admission: ["identity.continuity_evidence"],
      },
      note: "已经连上，但还没就位。",
    };
    win.fetch = (url: string) => {
      calls.push(String(url));
      const body = String(url).indexOf("e-1") >= 0 ? joining : prepared;
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
      });
    };

    win.Tsunagou.ui.wizard.go(2);
    (page.querySelector("#newXz2 input") as HTMLInputElement).value = "熊猫";
    const pending = win.Tsunagou.ui.wizard.next();

    /* 第一次轮询在 2 秒之后，等到那句话被换上为止。*/
    let text = "";
    for (let tick = 0; tick < 80 && text.indexOf("还没就位") < 0; tick += 1) {
      await new Promise((resolve) => dom.window.setTimeout(resolve, 50));
      text = page.querySelector("#loadW .textW")?.textContent ?? "";
    }
    expect(calls.join(" ")).toContain("e-1");
    expect(text).toContain("还没就位");
    expect(text).toContain("identity.continuity_evidence");
    expect(text).toContain("Codex");
    expect(text).toContain(projectPath);

    win.Tsunagou.notify.loadingEnd();
    void pending.catch(() => undefined);
  });
});
