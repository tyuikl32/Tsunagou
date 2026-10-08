/*
 * 假中间层（只给前端联调用）
 *
 * 作用：把 web/ 这份页面原样托管起来，同时用假数据回答它能请求到的每一个接口，
 *       让页面上所有界面改动（含空态、错误态、加载态、各种确认流程）都能被走一遍，
 *       而**不碰真后端、不写任何数据**——全部是内存里的常量，重启即复原。
 *
 * 跑：node tools/dev/fake_console.js [端口]        默认 5599
 * 看：http://127.0.0.1:5599/                        页面
 *     http://127.0.0.1:5599/__fake                 场景开关（点一下即切）
 *
 * 场景（也能直接在页面地址后面加 ?scenario=xxx，例如 /?scenario=empty）：
 *   normal    默认：三个项目（含已完成、含远端 Agent、带创建时间与记录）、三个 Agent（含一个已退役）
 *   empty     什么都没有：项目列表空、Agent 列表空（看空状态）
 *   error     所有接口回 500（看错误态与"部分拉取失败"）
 *   slow      所有接口慢 3 秒（看加载态、连点、有没有进行中状态）
 *   refuse    写操作回 409 并带拒绝码（ready_session_required / main_agent_cannot_retire /
 *             agent_has_open_work / main_agent_must_be_local）——用来做"错误码说人话"
 *   flaky     每次请求随机丢掉一部分（看部分失败的提示）
 *
 * 另外两个后门：
 *   GET /__fake/scenario/<名字>      切场景（返回一行 JSON）
 *   GET /__fake/fail/<路径关键字>    让某个接口单独回 500（再调一次同样的地址取消）
 */

const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = Number(process.argv[2] || 5599);
const WEB = path.join(__dirname, "..", "..", "web");
const STARTED = new Date().toISOString();

let scenario = "normal";
/* 网络 Agent（跨机器）那条流程：邀请 -> 等待 -> 到齐。
   页面读 /console/enrollments/current 与 ...:enrollments:observe；发邀请走写入口。
   这里用一份内存状态把它接成真能走完的一条路：邀请后 8 秒"到齐"，
   也可以打 /__fake/arrive 让它立刻到。到齐时那个席位会带机器名进名单。*/
let pendingEnrollment = null;   /* {ticket, machine, vendor, arrives_at} */
let forcedFail = "";           /* 只让含这个关键字的接口失败 */
const hits = [];               /* 最近的请求，给 /__fake 看 */

/* ---------------- 假数据 ---------------- */

const PROJECTS = [
  {
    project_id: "p-alpha",
    name: "甲项目：登录改造",
    objective: "把登录从 cookie 换成令牌，并补齐退出路径",
    available: true, path: "E:\\work\\alpha", lifecycle: "active",
    created_at: "2026-09-21T02:10:00.000Z",
    history: { captured_at: new Date(Date.now() - 6 * 60 * 1000).toISOString(), sources: 4 },
    daemon: { running: true, url: "http://127.0.0.1:2810" },
    main_agent_id: "a-101",
    agents: [
      { id: "a-101", agent_id: "a-101", nickname: "甲主", vendor: "deepseek", role: "main", status: "active" },
      { id: "a-102", agent_id: "a-102", nickname: "子一", vendor: "codex", role: "worker", status: "active" },
    ],
  },
  {
    project_id: "p-beta",
    name: "乙项目：导出报表",
    objective: "把每日统计导成 CSV，支持按周汇总",
    available: true, path: "E:\\work\\beta", lifecycle: "active",
    created_at: "2026-10-01T08:30:00.000Z",
    history: { captured_at: new Date(Date.now() - 90 * 60 * 1000).toISOString(), sources: 2 },
    daemon: { running: false, url: "" },
    main_agent_id: "a-201",
    agents: [
      { id: "a-201", agent_id: "a-201", nickname: "乙主", vendor: "deepseek", role: "main", status: "active" },
      { id: "a-202", agent_id: "a-202", nickname: "远端三", vendor: "opencode", role: "worker",
        status: "active", machine: "vm-win10", copy_path: "C:\\work-copy" },
    ],
  },
  {
    project_id: "p-gamma",
    name: "丙项目：文档整理（已完工）",
    objective: "把散落的说明收进一份手册",
    available: true, path: "E:\\work\\gamma", lifecycle: "completed",
    created_at: "2026-09-15T01:00:00.000Z",
    history: { captured_at: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(), sources: 1 },
    daemon: { running: false, url: "" },
    main_agent_id: "a-301",
    agents: [{ id: "a-301", agent_id: "a-301", nickname: "丙主", vendor: "deepseek", role: "main", status: "active" }],
  },
];

const AGENTS_WINDOW = [
  { id: "a-101", agent_id: "a-101", nickname: "甲主", vendor: "deepseek", role: "main", status: "active",
    project: "甲项目：登录改造", task: "拆任务、盯进度", session: "ready" },
  { id: "a-202", agent_id: "a-202", nickname: "远端三", vendor: "opencode", role: "worker", status: "active",
    project: "乙项目：导出报表", task: "写导出脚本", session: "ready", machine: "vm-win10", copy_path: "C:\\work-copy" },
  { id: "a-102", agent_id: "a-102", nickname: "子一", vendor: "codex", role: "worker", status: "retired",
    project: "甲项目：登录改造", task: "（已退役，记录保留）", session: "ended" },
];

const TASKS = [
  { id: "t-1", title: "拆出登录状态机", detail: "现状：cookie 里塞了三个字段", status: "in_progress",
    agent: { id: "a-101", name: "甲主" }, time: "10 分钟前",
    conditions: [{ ok: true, text: "范围已确认" }, { ok: false, text: "等设计稿" }] },
  { id: "t-2", title: "补退出路径", detail: "退出后令牌要立刻失效", status: "pending",
    agent: { id: "a-202", name: "远端三" }, time: "1 小时前", conditions: [{ ok: false, text: "依赖 t-1" }] },
  { id: "t-3", title: "写导出脚本", detail: "CSV 的列顺序照旧", status: "review", detail2: "",
    agent: { id: "a-201", name: "乙主" }, time: "昨天", conditions: [] },
];

const GLOSSARY = {
  task_status: {
    pending: "待领取", in_progress: "已领取", review: "待验收", rework: "待返工",
    blocked: "受阻", done: "已完成", cancelled: "待取消", lost: "已失联",
  },
  denial_reason: {
    ready_session_required: "会话没就绪",
    main_agent_cannot_retire: "主不能删",
    agent_has_open_work: "还有活",
    main_agent_must_be_local: "本机才能当主",
    agent_retired: "已退役",
  },
  command_kind: { "agent.retire.user": "删除", "agent.appoint.main.user": "设为主" },
};

/* 词表优先用仓库里的真实导出（tools/dev/fake_glossary.json，来自 console/glossary.py 的 27 张表）：
   手写那份少一张表，界面上就会像上次那样把英文原值露出来（例如设置里的 dark）。*/
try {
  Object.assign(GLOSSARY, JSON.parse(fs.readFileSync(path.join(__dirname, "fake_glossary.json"), "utf8")));
} catch (error) { console.log("[词表] 没读到 fake_glossary.json，用内置那份"); }

/* theme 要的是**中文标签**：页面的 setTheme 认 深色/浅色/light，标签本身写死在 index.html 里，
   给它 dark 就会被当成不认识的标签原样显示在格子里。*/
const PROFILE = { nickname: "本机用户", theme: "深色", agents: { "a-101": { nickname: "甲主" }, "a-102": { nickname: "子一" } } };
const HOSTS = { items: [
  { id: "deepseek", name: "DeepSeek Harness", installed: true, ready: true },
  { id: "codex", name: "Codex", installed: true, ready: true },
  { id: "opencode", name: "OpenCode", installed: true, ready: true },
  { id: "claudecode", name: "Claude Code", installed: false, ready: false, note: "（待实现）" },
] };
const SETTINGS = { poll_ms: 0, projects_root: "E:\\work", scan_roots: ["E:\\work"], theme: "dark" };
const ENROLLMENTS_CURRENT = { items: [] };

/* ---------------- 场景对数据的影响 ---------------- */

function projectsNow() {
  if (scenario === "empty") return [];
  return PROJECTS;
}
function agentsWindowNow() {
  if (scenario === "empty") return [];
  return AGENTS_WINDOW;
}
function projectsRoot() {
  return { items: projectsNow().map(function (p) {
    const row = JSON.parse(JSON.stringify(p));
    if (scenario === "empty") return row;
    return row;
  }) };
}

/* ---------------- HTTP ---------------- */

function send(res, code, body, type) {
  const text = typeof body === "string" ? body : JSON.stringify(body, null, 2);
  res.writeHead(code, {
    "Content-Type": (type || "application/json") + "; charset=utf-8",
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(text);
}

function readBody(req) {
  return new Promise(function (resolve) {
    let raw = "";
    req.on("data", function (chunk) { raw += chunk; });
    req.on("end", function () {
      try { resolve(raw ? JSON.parse(raw) : {}); } catch (error) { resolve({ _raw: raw }); }
    });
  });
}

const MIME = {
  ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
  ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".ico": "image/x-icon",
};

function serveStatic(res, urlPath) {
  const rel = urlPath === "/" ? "index.html" : decodeURIComponent(urlPath).replace(/^\/+/, "");
  const full = path.join(WEB, rel);
  if (!full.startsWith(WEB)) { send(res, 403, { error: "forbidden" }); return; }
  fs.readFile(full, function (error, data) {
    if (error) { send(res, 404, { error: "not found", path: urlPath }); return; }
    const type = MIME[path.extname(full).toLowerCase()] || "application/octet-stream";
    /* 原样把字节发出去：**不要**转成字符串再发 —— 那会把 UTF-8 再编码一遍（中文变乱码、
       图片与字体直接坏掉），页面加载出来就是一屏"å..."。文本类顺手补上 charset。*/
    const textual = /^text\//.test(type) || /javascript|json/.test(type);
    res.writeHead(200, {
      "Content-Type": textual ? type + "; charset=utf-8" : type,
      "Cache-Control": "no-store",
    });
    res.end(data);
  });
}

function sendBinary(res, fullPath) {
  fs.readFile(fullPath, function (error, data) {
    if (error) { send(res, 404, { error: "not found" }); return; }
    const type = MIME[path.extname(fullPath).toLowerCase()] || "application/octet-stream";
    res.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store" });
    res.end(data);
  });
}

function controlPage() {
  const names = ["normal", "empty", "error", "slow", "refuse", "flaky"];
  const links = names.map(function (n) {
    return '<a class="btn' + (n === scenario ? ' on' : '') + '" href="/__fake/scenario/' + n + '">' + n + "</a>";
  }).join("");
  const log = hits.slice(-25).reverse().map(function (h) {
    return "<li><code>" + h.method + " " + h.url + "</code> → " + h.code + (h.note ? "  <em>" + h.note + "</em>" : "") + "</li>";
  }).join("");
  return "<!doctype html><meta charset='utf-8'><title>假中间层</title>" +
    "<style>body{background:#15171a;color:#e6e6e6;font:14px/1.7 system-ui;padding:24px;max-width:900px}" +
    "code{color:#9ad}em{color:#e8a}.btn{display:inline-block;margin:4px 8px 4px 0;padding:6px 12px;border-radius:8px;" +
    "background:#26292e;color:#ddd;text-decoration:none}.btn.on{background:#2f6df6;color:#fff}ul{padding-left:18px}</style>" +
    "<h1>假中间层</h1><p>启动于 " + STARTED + "　当前场景：<b>" + scenario + "</b>" +
    (forcedFail ? "　单点失败：<b>" + forcedFail + "</b>" : "") + "</p>" +
    "<p>点一下即切场景（也可在页面地址后加 <code>?scenario=xxx</code>）：</p><p>" + links + "</p>" +
    "<p>数据全部在内存里，重启即复原；不会碰真后端、不写任何文件。</p>" +
    "<h2>最近的请求</h2><ul>" + (log || "<li>（还没有）</li>") + "</ul>";
}

function apiResponse(url, body, method) {
  const p = url.pathname.replace(/^\/api\/v1/, "");
  const write = method !== "GET" && method !== "HEAD";

  /* 拒绝场景：写操作一律 409，带拒绝码（用来做"错误码说人话"） */
  if (write && scenario === "refuse") {
    const codes = ["ready_session_required", "main_agent_cannot_retire", "agent_has_open_work", "main_agent_must_be_local"];
    const code = codes[Math.floor(Math.random() * codes.length)];
    return { code: 409, body: { code: code, detail: { scenario: "refuse" } }, note: "拒绝码 " + code };
  }
  if (write) {
    if (p.indexOf(":rename") >= 0) {
      const id = p.split("/").pop().split(":")[0];
      const row = PROJECTS.filter(function (x) { return x.project_id === id; })[0];
      if (row) row.name = String((body || {}).name || row.name);
      return { code: 200, body: { status: "renamed", project_id: id, name: (body || {}).name }, note: "改名（内存里）" };
    }
    if (p.indexOf("/commands/") >= 0) {
      return { code: 200, body: { status: "accepted", command_id: "cmd-fake-" + Date.now(), result: {} }, note: "命令已受理" };
    }
    if (p.indexOf("/console/profile") >= 0) {
      /* 档案改动落回内存：不然页面刷新一次（或轮询一次）就变回旧值，调界面时很碍事 */
      const patch = (body && body.patch) || body || {};
      Object.keys(patch).forEach(function (k) { if (k !== "agents") PROFILE[k] = patch[k]; });
      if (patch.agents) Object.assign(PROFILE.agents, patch.agents);
      return { code: 200, body: { status: "saved" }, note: "档案已保存（内存里）" };
    }
    if (p === "/projects") {
      const name = String((body || {}).name || "新项目");
      const id = "p-new-" + (PROJECTS.length + 1);
      PROJECTS.unshift({
        project_id: id, name: name, objective: String((body || {}).objective || ""), available: true,
        path: String((body || {}).path || "E:\\work\\" + id), lifecycle: "active",
        created_at: new Date().toISOString(), history: { captured_at: new Date().toISOString(), sources: 0 },
        daemon: { running: false, url: "" }, main_agent_id: "", agents: [],
      });
      /* 应答照**真中间层的形状**给，并且把同一份对象放在几个常见位置（扁平的、project、
         result、manifest）：页面那层 api 会先拆一次包，拆到哪一层都得能拿到
         project_id / name / objective。只给 {status, project_id} 时，向导第 1 步拿不到
         name/objective 就静默停住，进不了第 2 步（就是上次点了「创建」没反应的原因）。*/
      const row = PROJECTS[0];
      return {
        code: 200,
        body: Object.assign({}, row, { project: row, result: row, manifest: row, status: "created" }),
        note: "新建（内存里）",
      };
    }
    return { code: 200, body: { status: "ok" }, note: "写操作（假）" };
  }

  if (p === "/projects") return { code: 200, body: { items: projectsNow() }, note: "项目列表" };
  if (p === "/console/agents") return { code: 200, body: { items: agentsWindowNow() }, note: "Agent 汇总" };
  if (p === "/console/glossary") return { code: 200, body: GLOSSARY, note: "词表" };
  if (p === "/console/profile") return { code: 200, body: PROFILE, note: "用户档案" };
  if (p === "/console/hosts") return { code: 200, body: HOSTS, note: "宿主" };
  if (p === "/console/settings") return { code: 200, body: SETTINGS, note: "设置" };
  if (p.indexOf("/enrollments/current") >= 0 || p.indexOf("/enrollments:observe") >= 0) {
    let state = "none";
    if (pendingEnrollment) {
      if (Date.now() >= pendingEnrollment.arrives_at) {
        const arrivals = AGENTS_WINDOW.filter(function (x) { return x.agent_id === "a-net-1"; });
        if (!arrivals.length) {
          AGENTS_WINDOW.push({
            id: "a-net-1", agent_id: "a-net-1", nickname: "远端来客", vendor: pendingEnrollment.vendor,
            role: "worker", status: "active", project: PROJECTS[0].name,
            task: "（刚接入，还没有任务）", session: "ready",
            machine: pendingEnrollment.machine, copy_path: "C:\\work-copy",
          });
        }
        const host = PROJECTS[0];
        if (host) {
          host.agents = host.agents || [];
          if (!host.agents.filter(function (x) { return x.agent_id === "a-net-1"; }).length) {
            host.agents.push({
              id: "a-net-1", agent_id: "a-net-1", nickname: "远端来客",
              vendor: pendingEnrollment.vendor, role: "worker", status: "active",
              machine: pendingEnrollment.machine, copy_path: "C:\\work-copy",
            });
          }
        }
        console.log("[网络 Agent] 到齐：已作为 " + pendingEnrollment.machine + " 上的席位进名单");
        pendingEnrollment = null;
        state = "arrived";
      } else {
        state = "pending";
      }
    }
    return { code: 200, note: "当前接入：" + state, body: {
      state: state, pending: pendingEnrollment,
      items: AGENTS_WINDOW.filter(function (x) { return x.machine; }),
    } };
  }
  if (p.indexOf("/enrollments:observe") >= 0) return { code: 200, body: { state: "arrived", items: agentsWindowNow() }, note: "观察接入" };
  if (p.indexOf("/console/views/") >= 0) {
    const project = PROJECTS.filter(function (x) { return x.project_id === (url.searchParams.get("project_id") || ""); })[0] || PROJECTS[0];
    return {
      code: 200,
      body: {
        sources: {
          project: project || null,
          agents: (project && project.agents) || [],
          tasks: TASKS,
          audit: [],
          conflicts: [],
          acceptance: { status: "pending", items: [] },
        },
        project: project || null,
        agents: (project && project.agents) || [],
        tasks: TASKS,
      },
      note: "聚合视图",
    };
  }
  if (/\/projects\/[^/]+\/agents/.test(p)) return { code: 200, body: { items: (PROJECTS[0] || {}).agents || [] }, note: "项目 Agent" };
  if (/\/projects\/[^/]+\/tasks/.test(p)) return { code: 200, body: { items: TASKS }, note: "项目任务" };
  if (/\/projects\/[^/]+\/workspaces/.test(p)) return { code: 200, body: { items: [] }, note: "工作区" };
  /* 这两条要排在 checkpoints 那条前面：路径是 checkpoint-failures，别被 checkpoints 的规则先接走 */
  if (/\/projects\/[^/]+\/checkpoint-failures/.test(p)) return { code: 200, body: { items: [] }, note: "存档失败" };
  if (/\/projects\/[^/]+\/history/.test(p)) return { code: 200, body: { items: [] }, note: "阅读记录" };
  if (/\/projects\/[^/]+\/checkpoints/.test(p)) return { code: 200, body: { items: [] }, note: "存档点" };
  if (/\/projects\/[^/]+\/timeline/.test(p)) return { code: 200, body: { items: [] }, note: "时间线" };
  return { code: 200, body: {}, note: "未预置（补 fixture 即可）" };
}

const server = http.createServer(function (req, res) {
  const url = new URL(req.url, "http://127.0.0.1");
  const p = url.pathname;

  /* 场景切换后门 */
  if (p.indexOf("/__fake/scenario/") === 0) {
    const name = p.split("/").pop();
    scenario = ["normal", "empty", "error", "slow", "refuse", "flaky"].indexOf(name) >= 0 ? name : "normal";
    forcedFail = "";
    console.log("[场景] -> " + scenario);
    send(res, 200, { scenario: scenario });
    return;
  }
  if (p.indexOf("/__fake/fail/") === 0) {
    const key = p.split("/").pop();
    forcedFail = forcedFail === key ? "" : key;
    console.log("[单点失败] -> " + (forcedFail || "（取消）"));
    send(res, 200, { fail: forcedFail });
    return;
  }
  if (p === "/__fake/arrive") {
    if (pendingEnrollment) { pendingEnrollment.arrives_at = 0; console.log("[网络 Agent] 改成立刻到齐"); }
    send(res, 200, { arrive: Boolean(pendingEnrollment) });
    return;
  }
  if (p === "/__fake") { send(res, 200, controlPage(), "text/html"); return; }

  /* 页面地址上带 ?scenario=xxx 也能切 */
  if (url.searchParams.get("scenario")) scenario = url.searchParams.get("scenario");

  if (p.indexOf("/api/v1") !== 0) { serveStatic(res, p); return; }

  readBody(req).then(function (body) {
    const delay = scenario === "slow" ? 3000 : (scenario === "flaky" && Math.random() < 0.4 ? 700 : 0);
    setTimeout(function () {
      if (scenario === "error" || (forcedFail && p.indexOf(forcedFail) >= 0)) {
        hits.push({ method: req.method, url: req.url, code: 500, note: "（假错误）" });
        console.log("500 " + req.method + " " + req.url);
        send(res, 500, { code: "fake_failure", detail: { path: p, scenario: scenario } });
        return;
      }
      const out = apiResponse(url, body, req.method);
      hits.push({ method: req.method, url: req.url, code: out.code, note: out.note });
      console.log(out.code + " " + req.method + " " + req.url + (out.note ? "   " + out.note : ""));
      send(res, out.code, out.body);
    }, delay);
  });
});

server.listen(PORT, "127.0.0.1", function () {
  console.log("假中间层已起：http://127.0.0.1:" + PORT + "/");
  console.log("场景开关：http://127.0.0.1:" + PORT + "/__fake");
  console.log("页面目录：" + WEB);
});
