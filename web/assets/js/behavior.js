/* ============================================================================
 * Tsunagou 前端控制层 —— assets/js/behavior.js
 * ----------------------------------------------------------------------------
 * 本文件是页面与后端之间唯一的桥：
 *   · 后端 / 宿主脚本 / 控制台 → 调 Tsunagou.dispatch(msg) 或 Tsunagou.render.*()
 *   · 用户操作                → Tsunagou.app / Tsunagou.actions → Tsunagou.api（HTTP）
 *
 * 三条铁律（改代码前先读这三条）：
 *   1. 显隐只写 display：隐藏写 'none'，显示写 CSS 里那个真实的 display 值
 *      （CSS 里 .tabMain / .asideMain / .contentNDP 的默认值就是 none，
 *        所以这些元素"显示"时必须显式写 'flex'，清成 '' 只会继续保持隐藏）。
 *      需要淡入的窗口/面板才额外写 opacity，绝不写宽高、背景、flex-* 等布局行内样式。
 *   2. 对外的名字一律挂在 window.Tsunagou 上（宿主脚本直接调得到）。
 *   3. index.html 只通过 id 与 onclick 和本文件发生关系，JS 不动 CSS、不改结构。
 *
 * 区段索引（直接搜 "§n" 即可跳转）：
 *   §0 基础工具     §1 配置·事件·状态   §2 UI 原语      §3 反馈组件
 *   §4 通信层       §5 渲染层           §6 动作与分发   §7 初始空状态   §8 启动
 * ========================================================================== */

(function () {
    'use strict';

    /* ========================================================================
     * §0 基础工具
     * ====================================================================== */

    /* ---- 查询 ------------------------------------------------------------ */

    function byId(id) { return document.getElementById(id); }

    function qs(selector, root) { return (root || document).querySelector(selector); }

    function qsa(selector, root) {
        return Array.prototype.slice.call((root || document).querySelectorAll(selector));
    }

    function closest(node, selector) {
        if (!node || node.nodeType !== 1 || !node.closest) return null;
        return node.closest(selector);
    }

    /* 元素或 id 都接受，统一解析成元素 */
    function resolveEl(target) {
        if (!target) return null;
        return typeof target === 'string' ? byId(target) : target;
    }

    /* ---- 显隐（全文件唯一写 display 的地方） ------------------------------ */

    /* 显示：把行内 display 清成空串，交回 CSS。
       只适用于"CSS 里本来就是显示状态"的元素（如 .secAside、.inner 里的 .content）。*/
    function showEl(target) {
        const node = resolveEl(target);
        if (node) node.style.display = '';
        return node;
    }

    /* 隐藏：写 display:none */
    function hideEl(target) {
        const node = resolveEl(target);
        if (node) node.style.display = 'none';
        return node;
    }

    /* 显式指定 display 值（CSS 默认是 none 的元素必须走这里） */
    function displayEl(target, value) {
        const node = resolveEl(target);
        if (node) node.style.display = value;
        return node;
    }

    /* 是否真正可见：checkVisibility 能识破"祖先被隐藏、自己 computed display 仍是 flex"的陷阱 */
    function isShown(target) {
        const node = resolveEl(target);
        if (!node) return false;
        if (node.checkVisibility) return node.checkVisibility();
        return node.getClientRects().length > 0;
    }

    /* 淡入：先落 display 并强制重排（让元素真的以 opacity:0 渲染一帧），再写 opacity:1。
       两步法不可合并 —— 同一次任务里同时改 display 和 opacity，浏览器不会触发过渡。*/
    function revealEl(target, display) {
        const node = resolveEl(target);
        if (!node) return null;
        node.style.display = display || 'flex';
        void node.offsetWidth;
        node.style.opacity = '1';
        return node;
    }

    /* 淡出并隐藏：不做离开动画（有意为之），opacity 顺手归零以便下次淡入 */
    function concealEl(target) {
        const node = resolveEl(target);
        if (!node) return null;
        node.style.display = 'none';
        node.style.opacity = '0';
        return node;
    }

    /* ---- 文本与转义 ------------------------------------------------------ */

    function toText(value) {
        if (value === null || value === undefined) return '';
        return String(value);
    }

    /* 拼 HTML 模板时，任何来自后端的数据都必须经过它 */
    function esc(value) {
        return toText(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /* 先转义再把换行变成 <br>，用于"多行文本块"字段 */
    function nl2br(value) {
        return esc(value).replace(/\r?\n/g, '<br>');
    }

    /* ---- 小工具 ---------------------------------------------------------- */

    function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

    function clampNum(value, min, max) { return Math.min(Math.max(value, min), max); }

    function deepClone(value) {
        return value === undefined ? value : JSON.parse(JSON.stringify(value));
    }

    function isPlainObject(value) {
        return !!value && typeof value === 'object' && !Array.isArray(value);
    }

    function toArray(value) {
        if (Array.isArray(value)) return value;
        return (value === null || value === undefined) ? [] : [value];
    }

    /* 深合并：把 patch 里的字段并进 target（数组整体替换，不逐项合并） */
    function deepAssign(target, patch) {
        Object.keys(patch || {}).forEach(function (key) {
            const value = patch[key];
            if (isPlainObject(value) && isPlainObject(target[key])) {
                deepAssign(target[key], value);
            } else {
                target[key] = deepClone(value);
            }
        });
        return target;
    }

    /* 按 'a.b.c' 路径读，中间缺字段就返回 fallback */
    function getPath(obj, path, fallback) {
        if (!path) return obj === undefined ? fallback : obj;
        const parts = String(path).split('.');
        let cursor = obj;
        for (let i = 0; i < parts.length; i++) {
            if (cursor === null || cursor === undefined) return fallback;
            cursor = cursor[parts[i]];
        }
        return cursor === undefined ? fallback : cursor;
    }

    /* 按 'a.b.c' 路径写，中间缺对象就补一个空对象 */
    function setPath(obj, path, value) {
        const parts = String(path).split('.');
        let cursor = obj;
        for (let i = 0; i < parts.length - 1; i++) {
            const key = parts[i];
            if (!isPlainObject(cursor[key])) cursor[key] = {};
            cursor = cursor[key];
        }
        cursor[parts[parts.length - 1]] = value;
        return value;
    }

    /* ---- DOM 构造 -------------------------------------------------------- */

    function makeEl(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = toText(text);
        return node;
    }

    /* 把 HTML 字符串变成节点列表（渲染器往里塞模板时用） */
    function parseHTML(html) {
        const tpl = document.createElement('template');
        tpl.innerHTML = html;
        return tpl.content;
    }

    /* 渲染器的出口：整体替换容器内容 */
    function fill(container, html) {
        const node = resolveEl(container);
        if (!node) return null;
        node.innerHTML = html;
        return node;
    }

    /* ---- 事件委托 -------------------------------------------------------- */

    /* 统一挂 click 委托：selectors 是 '选择器' 或 {selector, handler} 数组，
       handler(node, event) 拿到的 node 已经是 selector 命中的那个元素。 */
    function delegateClick(selectors, handler) {
        document.addEventListener('click', function (event) {
            for (let i = 0; i < selectors.length; i++) {
                const node = closest(event.target, selectors[i]);
                if (node) { handler(node, event); return; }
            }
        });
    }

    /* ========================================================================
     * §1 配置 · 事件 · 状态
     * ====================================================================== */

    /* ---- 配置 ------------------------------------------------------------ */

    const DEFAULT_PATHS = {
        /* 读取类：GET {baseUrl}{path}
           带 {project} 的表示"属于某个协作项目"，请求时用当前项目 id 替换；
           没选项目时这些请求会被直接跳过（见 Tsunagou.refresh）。
           路径为空字符串 = 后端尚未提供这个接口：refresh 会跳过它，界面保留空状态，
           不会拼出坏地址去打扰后端。见 method.md 的"后端缺口"清单。*/
        /* —— 已与 Tsunagou 后端对齐（路径即后端真实路由） —— */
        /* 左栏列表由中间层提供：一个 daemon 只服务一个项目，回答不了
           "本机有哪些项目"；接口形状见中间层 console/projects.py 的 /projects。
           agents=1 让中间层顺便回答"每个项目由谁负责"—— 它自己维护这份名单，
           只在首次读到与 daemon 存储变动时去问项目（见 console/agents.py）。*/
        projects: '/projects?agents=1',
        agents: '/projects/{project}/agents',
        tasks: '/console/views/tasks?project_id={project}',
        workspaces: '/projects/{project}/workspaces',
        checkpoints: '/projects/{project}/checkpoints',
        /* 存档失败（daemon 新出口：按 kind=checkpoint.create 筛 operations 里 failed/retry_wait 的记账）。
           存档点页要两份：存档点本身 + “没存成”的那几条。*/
        checkpointFailures: '/projects/{project}/checkpoint-failures',
        timeline: '/projects/{project}/history',
        settings: '/console/profile',
        /* 后端参数值的中文对照表由中间层维护（console/glossary.py）；
           页面只做机械替换，不自己攒词。*/
        glossary: '/console/glossary',
        /* 中间层能注册进哪些宿主（一个厂商一行，命令在 console/host_registration.py）。
           页面不自己攒一份厂商表 —— “哪个厂商支持、跑什么命令”只有一份事实。*/
        hosts: '/console/hosts',
        /* 一次“添加 Agent”的准备进度：prepared 之后票就等宿主来兑。*/
        enrollment: '/console/enrollments/{enrollment}',
        enrollmentCurrent: '/console/enrollments/current',
        enrollmentCancel: '/console/enrollments/{enrollment}:cancel',
        /* 宿主在自己聊天里接入时（`in_host`）没有票可查，只能问"名单里出现它了吗"。
           判断在中间层：它拿接入材料（bridges / onboarding 里的 host-identity.json）
           当证据，页面只负责每 2 秒问一次。见 connectInHostAgent。
           这条路由挂在中间层的 /console 下（注册见 console/app.py）：漏掉那一段就是 404，
           而轮询把一次失败当成"还没到"接着问，等待框会永远不翻绿。*/
        enrollmentObserve: '/console/projects/{project}/enrollments:observe',
        /* —— 一屏要读好几个出口的，走中间层的聚合视图 ——
           /console/views/* 只负责把几个出口的原样回答装进 sources，不解释；
           解释全在 §7 适配层（BACKEND_SHAPE）。view 取值：overview /
           collaboration / audit / acceptance（见 console/app.py 的 CONSOLE_VIEWS）。*/
        project: '/console/views/overview?project_id={project}',
        audits: '/console/views/audit?project_id={project}',
        conflicts: '/console/views/collaboration?project_id={project}',
        acceptance: '/console/views/acceptance?project_id={project}',
        /* Agent 列表窗口是**跨项目**的汇总：一个 Agent 属于哪个项目，只有中间层答得上来
           （daemon 只管自己那一个项目）。中间层顺带回答"它现在在做什么"，
           那部分要问 daemon，所以只在窗口被打开时取一次，不跟着左栏轮询走。*/
        agentsWindow: '/console/agents',
        /* 写入类不在这里。真后端的写入口只有一个：
           POST {baseUrl}/commands/{command_kind}，见 WRITE_COMMANDS 与 api.command()。
           少数几个由中间层掌管的写入口（用户档案 / 登记已有项目）直接写路径。*/
    };

    /* 写入动作 → 两种去向：
       · 带 kind：真 daemon 的命令通道 POST {baseUrl}/commands/{kind}（envelope，payload 走服务端白名单）；
       · 带 path：**中间层掌管的写入口**（用户档案 / 登记项目），直接按路径发一个普通 JSON 补丁。
       值为 null = 后端没有这个能力：api.command 会明确拒绝并说明原因，不会拼出坏地址。

       ⚠️ daemon 命令那几条（agentSetMain / checkpointRetry / acceptanceConfirm）的 payload
       由下面的 `payload` 现拼（服务端只认自己的白名单字段）。

       这里**故意没有**"创建 Agent / 创建子 Agent"这类键：后端没有"创建 Agent"这个概念。
       接入一个 Agent = 用户给某个宿主对话签一张一次性票据（agent.ticket.create.user），由那个对话的
       bridge 自己兑换。网页通过中间层准备：Codex 保存待真实聊天认领的申请，随后 agent join
       复用 connect；其他宿主仍由中间层签票、写私有文件并登记 MCP。
       见 actions.addSubAgent。*/
    const WRITE_COMMANDS = {
        /* —— 中间层掌管的写入口（不是 daemon 命令）—— */
        settingSave: {
            path: '/console/profile', method: 'PUT',
            payload: function (b) {
                const body = b || {};
                /* saveSetting / saveAgentProfile 给的是 {patch:{…}} */
                if (isPlainObject(body.patch)) return body.patch;
                /* form.commit 的写法：一次一个字段 {key, value}（中间层只认 nickname/theme/agents，
                   多余的键会被它忽略，不会写坏档案）*/
                const patch = {};
                if (toText(body.key)) patch[toText(body.key)] = body.value;
                return patch;
            }
        },
        projectCreate: {
            path: '/projects', method: 'POST',
            payload: function (b) {
                const body = b || {};
                /* 只给中间层它真有的三项：name / objective / path。
                   向导收集的 mainAgent / subAgents 这里给不了 —— Agent 要由本机 CLI 签票接入，
                   中间层不创建 Agent（也不会假装建了）。*/
                return {
                    name: toText(body.name).trim(),
                    objective: toText(body.objective),
                    path: toText(body.path)
                };
            }
        },
        /* 准备一个 Agent 接入（Codex 保存待认领申请；其他宿主签票并登记）。
           票据密钥只落在服务端写的私有文件里，答应里回的是路径与状态。
           nickname 是人写的名字（存在用户档案里），profile 由中间层生成 —— 名字改了不会挪目录。
           start_daemon：签票要 daemon 活着，而这是用户明确的一次动作，允许它顺手把项目起起来。*/
        agentPrepare: {
            path: '/console/projects/{project}/agents:prepare', method: 'POST',
            payload: function (b) {
                const body = b || {};
                return {
                    vendor: toText(body.vendor),
                    nickname: toText(body.nickname || body.name).trim(),
                    role: toText(body.role) || 'worker',
                    start_daemon: body.start_daemon !== false,
                    /* 跨机器那条路：place=network 请中间层签一张邀请；编号是"会话名由宿主
                       自己生成"的那两个宿主报上来的号（OpenCode 不用）。*/
                    place: toText(body.place) === 'network' ? 'network' : 'local',
                    conversation_id: toText(body.conversation_id).trim()
                };
            }
        },
        /* —— 已装配的后端命令 —— */
        agentSetMain: {
            /* handler 只读 `agent_id`（`handlers.py` 的 `appoint_main`）：白名单里那两个
               `expected_authority_epoch` / `ceiling_template` **运行时没人读**，所以这里不需要代次。
               两个窗口同时改主不会互相拦：后到的赢，结果仍然是"有且只有一个主 Agent"，
               不需要代次来保证正确性（协议字段留着，但我们不假装它在保护什么）。
               能失败的情形只有两种：要设的那个人不存在；他是个远端 Agent（主 Agent 必须本机）。*/
            kind: 'authority.appoint',
            payload: function (b) { return { agent_id: b.id, reason: 'set main from console' }; }
        },
        checkpointRetry: {
            /* 存档点「重试」：重跑那次失败的**记账**，不是 reconcile ——
               `durability.reconcile` 是 M 权限（控制台持的是 U 令牌，发过去会被拒）。
               `checkpoint.create.user` 收 `retry_operation_id`（`handlers.py` 的
               `checkpoint_create_user` 就是为这个写的），不需要任何版本号。*/
            kind: 'checkpoint.create.user',
            payload: function (b) {
                return {
                    retry_operation_id: toText((b || {}).operation_id),
                    reason: 'retry checkpoint from console'
                };
            }
        },
        checkpointCreate: {
            /* 存档点页「立即存档」：**同一条命令**，但不带 `retry_operation_id` ——
               `checkpoint_create_user` 据此走"新建一个存档点"那条分支（带了 id 才是重试）。
               两种语义共用一个 kind 是后端的用法，调用点必须把区别写清楚。*/
            kind: 'checkpoint.create.user',
            payload: function (b) {
                return { reason: toText((b || {}).reason) || 'console:manual_checkpoint' };
            }
        },
        acceptanceConfirm: {
            /* 验收页「确认完成」：四件套必须原样带回（少一个后端就以缺字段拒绝）。
               `expected_project_revision` 要的是**当前** policy_revision ——
               提案时那个可能已经被策略变更或上一次完成推前了，所以调用点传当前值。*/
            kind: 'project.completion.confirm',
            payload: function (b) {
                const body = b || {};
                return {
                    proposal_id: toText(body.proposal_id),
                    proposal_digest: toText(body.proposal_digest),
                    expected_project_revision: body.expected_project_revision,
                    expected_revisions: isPlainObject(body.expected_revisions) ? body.expected_revisions : {}
                };
            }
        },
        /* 决定：把**选项原文**回给 daemon（choice 就是提案方给的词，界面不自己造一个"同意/不同意"）。
           可答值由 `lifecycle.resolve_decision` 判：`choices` 里的真实值，加上 approved/rejected
           这两个兜底（完成提案不带 choices）。四件套少一个都会被以缺字段拒绝。*/
        decisionResolve: {
            kind: 'user_decision.resolve',
            payload: function (b) {
                const body = b || {};
                return {
                    decision_id: toText(body.decision_id),
                    choice: toText(body.choice),
                    expected_revisions: isPlainObject(body.expected_revisions) ? body.expected_revisions : {},
                    proposal_digest: toText(body.proposal_digest),
                    reason: toText(body.reason)
                };
            }
        },
        /* —— 后端尚未装配 / 没有这个概念 —— */
        acceptanceArchive: null,  /* project.archive 已声明但未装配；页面上已经没有归档入口了 */
        agentRemove: {
            /* handler 只读 `agent_id`/`reason`（`handlers.py` 的 `retire_agent`）。
               只有用户能删：控制台持 U 令牌，daemon 侧 `context.kind != "U"` 一律拒。*/
            kind: 'agent.retire.user',
            payload: function (b) { return { agent_id: b.id, reason: toText(b.reason) || 'removed from console' }; }
        },
        pathRecord: null          /* 后端无此概念 */
    };

    const config = {
        baseUrl: '/api/v1',
        timeout: 10000,
        token: '',
        headers: {},
        /* 自动重拉的间隔（毫秒，来自 console.config.js 的 poll_ms）。
           0 或负数 = 不自动重拉。*/
        pollMs: 5000,
        /* 命令 envelope 用（见后端 interfaces/runtime.py 与 api.command）。
           schema_bundle_digest 用 'sha256:x' 表示"不校验具体协议包版本"，
           daemon 明确接受这个通配值。Agent 类命令还需要 session 头；U（用户控制面）不需要。*/
        protocolVersion: '1.0',
        schemaBundleDigest: 'sha256:x',
        sessionId: '',
        connectionEpoch: '',
        /* 每类数据的请求路径，后端不一样时用 Tsunagou.config.setPaths({...}) 覆盖 */
        paths: Object.assign({}, DEFAULT_PATHS)
    };

    function configSnapshot() {
        return {
            baseUrl: config.baseUrl,
            timeout: config.timeout,
            token: config.token,
            headers: Object.assign({}, config.headers),
            pollMs: config.pollMs,
            paths: Object.assign({}, config.paths)
        };
    }

    /* 中间层（`tsunagou web start`）在同源下生成 /console.config.js：
       window.TSUNAGOU_CONSOLE_CONFIG = {baseUrl, poll_ms}
       双击 index.html 打开时用仓库里那份。这里只读它、不改布局。*/
    function applyConsoleConfig() {
        const provided = window.TSUNAGOU_CONSOLE_CONFIG;
        if (!isPlainObject(provided)) return null;
        if (provided.baseUrl) config.baseUrl = toText(provided.baseUrl).replace(/\/+$/, '');
        const interval = Number(provided.poll_ms);
        if (isFinite(interval)) config.pollMs = interval;
        emit('config:change', configSnapshot());
        return provided;
    }

    /* ---- 地址栏上的开发开关（只影响这一次打开，不改任何文件） --------------
       ?poll_ms=0   不自动重拉（改 CSS / 调界面时用；与 console.config.js 里写 0 / 负数一个意思）
       ?shape=dag   一进来就停在总路径的「DAG路径图」，省得每次刷新都点一下那个选择框

       只挡**定时**重拉：开项目、点标签、写操作后的即时重拉该刷还是刷 —— 那些都是你自己的操作。
       正常地址带上它们才生效，去掉就恢复原状。*/
    function applyUrlOverrides() {
        const params = new URLSearchParams(toText(window.location.search));
        const notes = [];
        if (params.has('poll_ms')) {
            const interval = Number(params.get('poll_ms'));
            if (isFinite(interval)) {
                config.pollMs = interval;
                notes.push('poll_ms=' + interval + (interval > 0 ? '' : '（不自动重拉）'));
            }
        }
        if (toText(params.get('shape')).toLowerCase() === 'dag') {
            pathChoice.shape = 'DAG路径图';
            notes.push('shape=dag');
        }
        if (notes.length) console.info('[开发开关] ' + notes.join(' · '));
        emit('config:change', configSnapshot());
        return params;
    }

    function joinUrl(path) {
        if (/^https?:\/\//i.test(path)) return path;
        const base = config.baseUrl || '';
        if (!base) return path;
        return base.replace(/\/+$/, '') + (path.charAt(0) === '/' ? path : '/' + path);
    }

    /* ---- 事件总线 -------------------------------------------------------- */

    const listenerMap = Object.create(null);

    function on(name, handler) {
        if (typeof handler !== 'function') return function () {};
        const list = listenerMap[name] || (listenerMap[name] = []);
        list.push(handler);
        return function offOne() { off(name, handler); };
    }

    function once(name, handler) {
        const unbind = on(name, function (detail) {
            unbind();
            handler(detail);
        });
        return unbind;
    }

    function off(name, handler) {
        const list = listenerMap[name];
        if (!list) return;
        if (!handler) { delete listenerMap[name]; return; }
        const index = list.indexOf(handler);
        if (index >= 0) list.splice(index, 1);
    }

    function emit(name, detail) {
        const list = listenerMap[name];
        if (!list || !list.length) return 0;
        /* 复制一份再遍历：回调里可能反向解绑 */
        list.slice().forEach(function (handler) {
            try {
                handler(detail, name);
            } catch (error) {
                console.error('[Tsunagou] 事件回调出错：' + name, error);
            }
        });
        return list.length;
    }

    /* ---- 状态 ------------------------------------------------------------ */

    /* state.data 的形状（与后端 JSON 同构，字段名见 method.md §7）：
       { currentProjectId, projects, project, agents, agentsWindow,
         tasks, taskDetail, conflicts, audits, workspaces, acceptance,
         checkpoints, timeline, settings, wizard } */

    const state = {
        data: {},

        /* 回到初始（空）状态：清空所有后端数据，只剩一个空骨架 */
        reset: function () {
            state.data = deepClone(EMPTY_STATE);
            emit('state:change', { reason: 'reset', path: '*' });
            emit('state:reset', null);
            return state.data;
        },

        /* 把缺失的字段补齐（只在没有的地方填默认值，已有数据一律保留）。
           init() 用的是它而不是 reset()：宿主脚本有可能在启动之前就
           dispatch 过数据，那种情况下不能被无条件的 reset() 冲掉。*/
        hydrate: function () {
            state.data = deepAssign(deepClone(EMPTY_STATE), state.data || {});
            return state.data;
        },

        /* 整体替换（后端一次性下发全量数据时用） */
        replace: function (data) {
            state.data = isPlainObject(data) ? deepClone(data) : {};
            emit('state:change', { reason: 'replace', path: '*' });
            return state.data;
        },

        /* 局部覆盖（深合并） */
        patch: function (partial) {
            deepAssign(state.data, partial || {});
            emit('state:change', { reason: 'patch', path: '*' });
            return state.data;
        },

        /* 读一个字段：state.get('agents', []) */
        get: function (path, fallback) {
            return getPath(state.data, path, fallback);
        },

        /* 写一个字段：state.set('project.name', '新名字') */
        set: function (path, value) {
            setPath(state.data, path, value);
            emit('state:change', { reason: 'set', path: path, value: value });
            return value;
        },

        /* 监听状态变化（渲染器靠它做自动重绘） */
        watch: function (handler) { return on('state:change', handler); }
    };

    /* ---- 命名空间 -------------------------------------------------------- */

    /* 注意 config 与 state 是"内部那个对象本体"，不是空壳：
       它们的属性都是就地 assign 上去的，所以这里必须直接引用同一个对象，
       否则 Tsunagou.config.setBaseUrl 这类方法会挂在内部对象上、外部拿不到。*/
    const Tsunagou = window.Tsunagou = {
        version: '0.2.0',
        util: {},
        config: config,
        events: {},
        state: state,
        ui: {},
        notify: {},
        dialog: {},
        api: {},
        form: {},
        render: {},
        actions: {},
        app: {}
    };

    /* 各子模块的短别名（下面的区段统一用这些名字，别再声明同名变量） */
    const util = Tsunagou.util;
    const events = Tsunagou.events;
    const ui = Tsunagou.ui;
    const notify = Tsunagou.notify;
    const dialog = Tsunagou.dialog;
    const api = Tsunagou.api;
    const form = Tsunagou.form;
    const render = Tsunagou.render;
    const actions = Tsunagou.actions;
    const app = Tsunagou.app;

    Object.assign(util, {
        byId: byId,
        qs: qs,
        qsa: qsa,
        closest: closest,
        resolveEl: resolveEl,
        show: showEl,
        hide: hideEl,
        display: displayEl,
        isShown: isShown,
        reveal: revealEl,
        conceal: concealEl,
        text: toText,
        esc: esc,
        nl2br: nl2br,
        time: formatTime,
        gloss: glossText,
        wait: wait,
        clamp: clampNum,
        clone: deepClone,
        toArray: toArray,
        isPlainObject: isPlainObject,
        deepAssign: deepAssign,
        getPath: getPath,
        setPath: setPath,
        make: makeEl,
        parseHTML: parseHTML,
        fill: fill,
        delegateClick: delegateClick
    });

    Object.assign(events, {
        on: on,
        once: once,
        off: off,
        emit: emit
    });

    Object.assign(config, {
        get: configSnapshot,
        snapshot: configSnapshot,
        joinUrl: joinUrl,
        setBaseUrl: function (url) {
            config.baseUrl = toText(url).replace(/\/+$/, '');
            return config.baseUrl;
        },
        setToken: function (token) {
            config.token = toText(token);
            return config.token;
        },
        setTimeout: function (ms) {
            const value = Number(ms);
            if (isFinite(value) && value > 0) config.timeout = value;
            return config.timeout;
        },
        setHeaders: function (headers) {
            config.headers = Object.assign({}, headers || {});
            return config.headers;
        },
        setPaths: function (paths) {
            Object.assign(config.paths, paths || {});
            return config.paths;
        },
        setPath: function (key, path) {
            config.paths[key] = path;
            return config.paths;
        },
        path: function (key) {
            return config.paths[key] || DEFAULT_PATHS[key] || '';
        }
    });

    /* ========================================================================
     * §2 UI 原语
     * ------------------------------------------------------------------------
     * 这一层只干一件事：把页面上"能点的东西"变成函数。
     * 每个函数都对应 HTML 里的一段固定结构，不承载任何业务含义 ——
     * 业务含义在 §6 的 actions / app 里。
     * ====================================================================== */

    /* ---- 项目标签页索引表 ------------------------------------------------ */

    /* 顺序必须与 index.html 里 .tabArea 的 .tabS 顺序、.inner 的 .tabMain 顺序一致。
       slug 用来拼 id：标签按钮 #tab-<slug>、主视图 #pane-<slug>、侧栏 #aside-<slug>。
       「项目验收」与「存档点」已合并成一屏（slug 仍是 acceptance）：确认完成本来就会落成一个
       存档点，拆两栏反而让人在两张卡之间找关系 —— 见图下那条注释。*/
    const PROJECT_TABS = [
        { slug: 'overview', title: '主视图' },
        { slug: 'agents', title: 'Agent 管理' },
        { slug: 'tasks', title: '任务区' },
        { slug: 'conflict', title: '冲突与协商' },
        { slug: 'audit', title: '意图与权限审计' },
        { slug: 'workspace', title: '工作区' },
        { slug: 'acceptance', title: '验收与存档点' },
        { slug: 'path', title: '总路径' }
    ];

    const TAB_ACTIVE_CLASS = 'tabSactive';
    /* 主视图 / 侧栏"显示"时要写的 display 值，必须与 CSS 里 .tabMainNormal /
       .asideMainNormal 的 display 一致（都是 flex），否则初次切换后布局会跟初始态对不上。*/
    const PANE_DISPLAY = 'flex';

    function tabButton(slug) { return byId('tab-' + slug); }
    function tabPane(slug) { return byId('pane-' + slug); }
    function tabAside(slug) { return byId('aside-' + slug); }

    function indexOfSlug(slug) {
        for (let i = 0; i < PROJECT_TABS.length; i++) {
            if (PROJECT_TABS[i].slug === slug) return i;
        }
        return -1;
    }

    /* 接受 slug / 中文标题 / 序号，统一成 slug */
    function normalizeSlug(value) {
        if (typeof value === 'number') {
            const byIndex = PROJECT_TABS[value];
            return byIndex ? byIndex.slug : '';
        }
        const text = toText(value);
        if (!text) return '';
        const hit = PROJECT_TABS.filter(function (item) {
            return item.slug === text || item.title === text;
        })[0];
        return hit ? hit.slug : '';
    }

    /* ---- 工作区：初始页 / 项目页 ------------------------------------------ */

    /* 两块 <section> 只有 class 没有 id：.secHome（初始）与 .secProjPanel（项目）。
       JS 只管显隐：隐藏方写行内 display:none，显示方清掉行内 display 交回 CSS。*/
    const WORKSPACE_NAMES = { home: 'secHome', project: 'secProjPanel' };

    ui.workspace = {
        show: function (name) {
            const key = (name === 'project' || name === 'secProjPanel') ? 'project' : 'home';
            Object.keys(WORKSPACE_NAMES).forEach(function (item) {
                const node = qs('.' + WORKSPACE_NAMES[item]);
                if (!node) return;
                if (item === key) showEl(node); else hideEl(node);
            });
            emit('ui:workspace', { name: key });
            return key;
        },
        home: function () { return ui.workspace.show('home'); },
        project: function () { return ui.workspace.show('project'); },
        current: function () {
            const node = qs('.' + WORKSPACE_NAMES.project);
            return isShown(node) ? 'project' : 'home';
        }
    };

    /* ---- 左侧大侧栏：展开 / 折叠 ------------------------------------------ */

    const SIDEBAR_WIDE_ID = 'secAside-Wide';
    const SIDEBAR_NARROW_ID = 'secAside-Narrow';

    ui.sidebar = {
        fold: function () {
            hideEl(SIDEBAR_WIDE_ID);
            displayEl(SIDEBAR_NARROW_ID, 'flex');
            emit('ui:sidebar', { folded: true });
        },
        unfold: function () {
            displayEl(SIDEBAR_WIDE_ID, 'flex');
            hideEl(SIDEBAR_NARROW_ID);
            emit('ui:sidebar', { folded: false });
        },
        isFolded: function () { return isShown(SIDEBAR_NARROW_ID); },
        toggle: function () {
            if (ui.sidebar.isFolded()) ui.sidebar.unfold(); else ui.sidebar.fold();
        }
    };

    /* ---- 模态窗口 -------------------------------------------------------- */

    /* #secWindow 的 CSS 是 display:none + opacity:0 + transition。
       开窗 = 落 display:'flex' → 强制重排 → opacity:'1'（两步走，不能合并）。*/
    const WINDOW_DISPLAY = 'flex';
    const openedWindows = [];

    ui.window = {
        /* 打开窗口；reset 为 true 时先清空窗口内的输入（表单类窗口用） */
        open: function (id, options) {
            const node = resolveEl(id);
            if (!node) return null;
            if (options && options.reset) ui.window.clearInputs(node);
            revealEl(node, WINDOW_DISPLAY);
            if (openedWindows.indexOf(node) < 0) openedWindows.push(node);
            emit('ui:window', { id: node.id, open: true });
            return node;
        },
        close: function (id) {
            const node = resolveEl(id);
            if (!node) return null;
            concealEl(node);
            const index = openedWindows.indexOf(node);
            if (index >= 0) openedWindows.splice(index, 1);
            emit('ui:window', { id: node.id, open: false });
            return node;
        },
        /* 关闭当前所有打开的窗口（从上往下） */
        closeAll: function () {
            openedWindows.slice().reverse().forEach(function (node) { ui.window.close(node); });
        },
        /* 关掉最上面那一层 */
        closeTop: function () {
            const node = openedWindows[openedWindows.length - 1];
            return node ? ui.window.close(node) : null;
        },
        isOpen: function (id) { return isShown(resolveEl(id)); },
        list: function () {
            return openedWindows.slice().map(function (node) { return node.id; });
        },
        /* 清空窗口里所有 input 的值（行内 value 不动，只清当前状态） */
        clearInputs: function (root) {
            qsa('input', resolveEl(root)).forEach(function (input) { input.value = ''; });
        },
        /* 把一组值写进窗口里的 input（后端回填表单时用） */
        fillInputs: function (root, values) {
            const list = qsa('input', resolveEl(root));
            toArray(values).forEach(function (value, index) {
                if (list[index]) list[index].value = toText(value);
            });
            return list;
        }
    };

    /* 点窗口背景（.secWindow 自己那层黑遮罩）：**不算提交、也不算取消**。
       以前这里一律 close，而"关闭"对有些窗口就等于走它自己的那条路（向导、确认框……），
       于是点一下黑边就把事情办了 —— 太容易误触。
       唯一例外是加载遮罩 #loadW：把它关掉本来就是"我不等了"。*/
    ui.window.bindBackdrop = function () {
        delegateClick(['.secWindow'], function (node, event) {
            if (event.target !== node) return;      /* 点在窗口盒子里不算 */
            if (node.id !== 'loadW') return;        /* 其余窗口：点了不动 */
            ui.window.close(node);
        });
    };

    /* ---- 项目标签页 ------------------------------------------------------ */

    let currentTabSlug = '';

    ui.tabs = {
        /* 切到某个标签页：按钮高亮 + 只显示该主视图；**侧栏一律收起**，
           侧栏必须由"点击对应内容"来唤出（见 §6 的内容点击映射）。*/
        project: function (target) {
            const slug = normalizeSlug(target);
            if (!slug) return '';
            PROJECT_TABS.forEach(function (item) {
                const button = tabButton(item.slug);
                if (button) button.classList.toggle(TAB_ACTIVE_CLASS, item.slug === slug);
                const pane = tabPane(item.slug);
                if (!pane) return;
                if (item.slug === slug) revealEl(pane, PANE_DISPLAY); else concealEl(pane);
            });
            ui.aside.hideAll();
            currentTabSlug = slug;
            emit('ui:tab', { slug: slug, index: indexOfSlug(slug) });
            return slug;
        },
        current: function () { return currentTabSlug; },
        list: function () { return PROJECT_TABS.slice(); },
        display: function () { return PANE_DISPLAY; }
    };

    /* 点击标签按钮即切换（按 DOM 顺序取序号，不依赖 id 是否存在） */
    ui.tabs.bindClicks = function () {
        document.addEventListener('click', function (event) {
            const bar = qs('.secProjPanel .tabArea');
            const button = closest(event.target, '.secProjPanel .tabArea > .tabS');
            if (!button || !bar) return;
            const list = qsa(':scope > .tabS', bar);
            ui.tabs.project(list.indexOf(button));
        });
    };

    /* ---- 区块内标签组（.tabblock） ---------------------------------------- */

    /* 结构：.tabblock > .tabPlace > .tabItem  与  .tabblock > .tabContent 按顺序配对。
       .tabContent 的 CSS 是 display:flex，所以显示就清成 ''、隐藏写 'none'。*/

    function blockTabs(block) {
        const place = Array.prototype.filter.call(block.children, function (node) {
            return node.classList.contains('tabPlace');
        })[0];
        if (!place) return [];
        return Array.prototype.filter.call(place.children, function (node) {
            return node.classList.contains('tabItem');
        });
    }

    function blockPanels(block) {
        return Array.prototype.filter.call(block.children, function (node) {
            return node.classList.contains('tabContent');
        });
    }

    ui.blockTabs = {
        /* 选中某个标签组里的第 index 个标签 */
        select: function (blockRef, index) {
            const block = resolveEl(blockRef) || byId('block-' + blockRef);
            if (!block) return -1;
            const tabs = blockTabs(block);
            const panels = blockPanels(block);
            if (index < 0 || index >= tabs.length || index >= panels.length) return -1;
            tabs.forEach(function (tab, i) { tab.classList.toggle('tabItemActive', i === index); });
            panels.forEach(function (panel, i) {
                if (i === index) showEl(panel); else hideEl(panel);
            });
            emit('ui:blocktab', { block: block.id, index: index });
            return index;
        },
        /* 按标签上的文字选（后端说"切到契约"时好用） */
        selectByText: function (blockRef, text) {
            const block = resolveEl(blockRef) || byId('block-' + blockRef);
            if (!block) return -1;
            const tabs = blockTabs(block);
            for (let i = 0; i < tabs.length; i++) {
                if (tabs[i].textContent.trim() === toText(text)) return ui.blockTabs.select(block, i);
            }
            return -1;
        },
        current: function (blockRef) {
            const block = resolveEl(blockRef) || byId('block-' + blockRef);
            if (!block) return -1;
            return blockTabs(block).findIndex(function (tab) {
                return tab.classList.contains('tabItemActive');
            });
        },
        /* 冲突与协商：0 分歧 / 1 冲突 / 2 Agent 间协商 / 3 契约 */
        conflict: function (index) { return ui.blockTabs.select('block-conflict', index); },
        /* 意图与权限审计：0 Agent 意图 / 1 Agent 权限 */
        audit: function (index) { return ui.blockTabs.select('block-audit', index); }
    };

    ui.blockTabs.bindClicks = function () {
        document.addEventListener('click', function (event) {
            const tab = closest(event.target, '.tabblock > .tabPlace > .tabItem');
            if (!tab) return;
            const block = closest(tab, '.tabblock');
            if (!block) return;
            ui.blockTabs.select(block, blockTabs(block).indexOf(tab));
        });
    };

    /* 初始化：每个 .tabblock 各自停在自己标了 .tabItemActive 的那一项上。
       不跑这一步的话，面板的 CSS 默认 display 是 flex，四个子标签会同时显示。*/
    ui.blockTabs.init = function () {
        qsa('.tabblock').forEach(function (block) {
            const tabs = blockTabs(block);
            let index = 0;
            for (let i = 0; i < tabs.length; i++) {
                if (tabs[i].classList.contains('tabItemActive')) { index = i; break; }
            }
            ui.blockTabs.select(block, index);
        });
    };

    /* ---- 设置窗口的左侧标签 ---------------------------------------------- */

    /* 键 ←→ 面板 id：personal→#uSet1、about→#uSet4
       （原"调度数据管理"页 #uSet2 / #uSetCol2 已随 HTML 删除，这里的键与分支一并清掉）*/
    const SETTING_TABS = {
        personal: 'uSet1',
        about: 'uSet4'
    };
    const SETTING_ORDER = ['personal', 'about'];
    const SETTING_DISPLAY = 'flex';

    function settingPanelId(keyOrId) {
        if (SETTING_TABS[keyOrId]) return SETTING_TABS[keyOrId];
        const text = toText(keyOrId);
        /* 只认当前登记在册的面板 id：从 DOM 里删掉的面板（如原 #uSet3）不再是有效目标 */
        const known = SETTING_ORDER.some(function (key) { return SETTING_TABS[key] === text; });
        return known ? text : '';
    }

    ui.settingTabs = {
        select: function (keyOrId) {
            const panelId = settingPanelId(keyOrId);
            if (!panelId) return '';
            SETTING_ORDER.forEach(function (key) {
                const id = SETTING_TABS[key];
                const button = byId(id + 'b');
                if (button) {
                    button.classList.toggle('Active', id === panelId);
                    button.classList.toggle('NoActive', id !== panelId);
                }
                const panel = byId(id);
                if (!panel) return;
                if (id === panelId) revealEl(panel, SETTING_DISPLAY); else concealEl(panel);
            });
            emit('ui:settingtab', { key: keyOrId, panel: panelId });
            return panelId;
        },
        personal: function () { return ui.settingTabs.select('personal'); },
        about: function () { return ui.settingTabs.select('about'); },
        current: function () {
            for (let i = 0; i < SETTING_ORDER.length; i++) {
                const panel = byId(SETTING_TABS[SETTING_ORDER[i]]);
                if (isShown(panel)) return SETTING_ORDER[i];
            }
            return '';
        }
    };

    /* ---- 新建协作向导（#addProj 的四步） ----------------------------------

       四步各自做一件真事，不再把"完成"当成唯一的提交点：
         1) 创建一个新的协作 —— 这一下就真的建（目录 + git init + 登记 + 起 daemon），
            建完之后输入框只读、按钮变成"下一步"（项目已经落地，再改名字只是自欺欺人）。
            这里只问名字：目标是用户和主 Agent 谈完、用户确认过之后才存在的东西，
            建项目时问一句只会得到一个没人看的占位；
         2) 连接到主 Agent  —— 真的准备接入申请并等原会话就绪；
         3) 连接到子 Agent  —— 同上，可以接多个，也可以一个都不接；
         4) 接入结果        —— 只是把已经发生的事列出来给人看，不再发任何请求。
       第 2/3 步要人打开或重载宿主的窗口（宿主只在自己启动时读配置），
       遮罩上给了「取消等待」：确认后请求中间层取消，已认领时按服务端拒绝继续等。*/

    /* 结构约定：#newXz1..4 是每步的正文，#xz1..4 是每步的按钮组。*/
    const WIZARD_STEPS = 4;
    let wizardStep = 1;

    /* 每一步的输入框（按 DOM 顺序）*/
    function wizardInputs(step) { return qsa('#newXz' + step + ' input'); }

    /* 每一步的必填校验：返回错误文案，null 表示通过 */
    const WIZARD_REQUIRED = {
        1: ['协作的名字'],
        2: ['主 Agent 名称']
    };

    /* 第 2 步的"厂商"现在是从选择框里挑的（HTML 里已默认选中一项），
       所以不再要求那个"API 地址"输入框。*/
    function wizardVendorBox(step) { return qs('#newXz' + step + ' .choosebox'); }
    function wizardVendor(step) { return ui.choosebox.value(wizardVendorBox(step)); }

    function wizardValidate(step) {
        const labels = WIZARD_REQUIRED[step];
        if (!labels) return null;
        const inputs = wizardInputs(step);
        for (let i = 0; i < labels.length; i++) {
            const input = inputs[i];
            if (!input || !toText(input.value).trim()) return '请填写' + labels[i];
        }
        return null;
    }

    /* 第 1 步的输入框在项目建好之后只读：那一行已经变成"这个协作的名字"了 */
    function freezeWizardStepOne(frozen) {
        wizardInputs(1).forEach(function (input) { input.readOnly = !!frozen; });
    }

    /* 第 1 步的「创建」：真建项目。建过一次就不再建第二个（按钮从此只是"下一步"）*/
    function wizardCreateProject() {
        const done = state.get('wizard.project', null);
        if (done && toText(done.id)) { ui.wizard.go(2); return Promise.resolve(true); }
        const draft = ui.wizard.collect();
        /* 这一步确实往磁盘上写（中间层建项目目录 + 登记索引），但**不弹二次确认**
           （2026-09-29 你定的）：向导本身就是多步表单，"下一步"已经是一次明确动作，
           再叠一个确认框只会多一次点击。见 §4.6 的确认分工表。*/
        return Promise.resolve(actions.createProject({ name: draft.name }))
            .then(function (project) {
                const id = toText(project && project.project_id);
                if (!project || !id) return false;
                /* 描述从后端那份项目里回读，不用草稿里的值：没有目标时它就是后端写的占位，
                   第 4 步看到的就是磁盘上真正那句话。*/
                state.set('wizard.project', {
                    id: id,
                    name: toText(project.name) || draft.name,
                    objective: toText(project.objective)
                });
                freezeWizardStepOne(true);
                /* 建完就切进这个协作：第 2/3 步的接入请求是项目作用域的，必须要"当前项目" */
                app.openProject(id);
                ui.wizard.go(2);
                return true;
            });
    }

    /* 第 2 步的「下一步」：真的去接一个主 Agent。
       重试时沿用上一次的 profile：宿主那边的登记名由 profile 定，沿用才不会越堆越多。*/
    function wizardConnectMain() {
        const inputs = wizardInputs(2);
        const nickname = toText(inputs[0] && inputs[0].value).trim();
        const vendor = wizardVendor(2);
        const icon = agentIconFor(vendor);
        const host = hostFor(vendor);
        if (!host) {
            notify.error('中间层不认识这个厂商，无法准备接入：' + vendor);
            return Promise.resolve(false);
        }
        /* 中间层办不完这个厂商时直说 —— 不假装已经排好队 */
        const blocked = hostEnrollBlocker(host);
        if (blocked) {
            if (blocked.mode === 'in_host') notify.info(blocked.note);
            else notify.error(blocked.note);
            return Promise.resolve(false);
        }
        const previous = state.get('wizard.main', null);
        return connectAgent({
            host: host, nickname: nickname, role: 'main',
            profile: (previous && previous.profile) || null,
            waiting: openWindowHint(host, '以主 Agent 身份')
        }).then(function (outcome) {
            const reached = toText(outcome && outcome.status);
            if (reached !== 'arrived' && reached !== 'manual') {
                const trouble = connectTrouble(reached, host);
                if (trouble) notify.info(trouble);
                return false;
            }
            state.set('wizard.main', {
                name: typeof outcome.nickname === 'string' ? outcome.nickname : nickname, vendor: vendor, icon: icon,
                agent_id: toText((outcome.agent || {}).agent_id),
                profile: toText(outcome.profile),
                status: reached
            });
            if (reached === 'manual') notify.info(manualNote(outcome.registration, host));
            else notify.success({ title: '主 Agent 已接入', sub: typeof outcome.nickname === 'string' ? outcome.nickname : nickname });
            ui.wizard.go(3);
            return true;
        });
    }

    ui.wizard = {
        steps: WIZARD_STEPS,
        go: function (step) {
            const value = clampNum(Number(step) || 1, 1, WIZARD_STEPS);
            wizardStep = value;
            for (let i = 1; i <= WIZARD_STEPS; i++) {
                const pane = byId('newXz' + i);
                if (pane) { if (i === value) revealEl(pane, 'flex'); else concealEl(pane); }
                const options = byId('xz' + i);
                if (options) { if (i === value) displayEl(options, 'flex'); else hideEl(options); }
            }
            /* 最后一步是"接入结果"：每次进来都按当前状态重画，避免看到上一次的残留 */
            if (value === WIZARD_STEPS) render.wizardReview(ui.wizard.collect());
            emit('ui:wizard', { step: value });
            return value;
        },
        current: function () { return wizardStep; },
        next: function () {
            const error = wizardValidate(wizardStep);
            if (error) { notify.error(error); return wizardStep; }
            /* 第 1 步要先把项目建出来，第 2 步要把主 Agent 接上：这两步都可能失败，
               失败就停在原地（项目已经建好了，不会白费）。*/
            if (wizardStep === 1) return wizardCreateProject();
            if (wizardStep === 2) return wizardConnectMain();
            return ui.wizard.go(wizardStep + 1);
        },
        prev: function () { return ui.wizard.go(wizardStep - 1); },
        reset: function () { return ui.wizard.go(1); },
        /* 打开向导窗口（每次都从第一步开始，并清掉上次的输入与结果） */
        open: function () {
            state.set('wizard.project', null);
            state.set('wizard.main', null);
            state.set('wizard.draftSubAgents', []);
            state.set('wizard.detectedMainAgent', null);
            ui.window.open('addProj');
            ui.window.clearInputs('addProj');
            freezeWizardStepOne(false);
            resetCsBox(wizardVendorBox(2));
            ui.wizard.reset();
            render.wizardSubAgents([]);
            /* "检测到的 Agent"跟着选择框当前值走（不再有后端探测）*/
            actions.detectMainAgent();
            render.wizardReview(ui.wizard.collect());
            emit('ui:wizard', { step: 1, opened: true });
            return true;
        },
        /* 收集向导里所有输入（第 1 步的名字 + 第 2 步的名称/厂商）。
           没有 objective：向导不问目标，目标是用户与主 Agent 确认之后才存在的事实。*/
        collect: function () {
            const first = wizardInputs(1);
            const mainInputs = wizardInputs(2);
            const vendor = wizardVendor(2);
            const detected = state.get('wizard.detectedMainAgent', null);
            return {
                name: toText(first[0] && first[0].value).trim(),
                mainAgent: {
                    name: toText(mainInputs[0] && mainInputs[0].value).trim(),
                    /* 厂商来自选择框（原来是"API 地址"输入框）*/
                    vendor: vendor,
                    icon: (detected && detected.icon) || agentIconFor(vendor)
                },
                /* 第 3 步已经接上的子 Agent 记在 state.data.wizard.draftSubAgents */
                subAgents: toArray(state.get('wizard.draftSubAgents', [])).slice()
            };
        },
        /* 完成：什么都不用再发（项目和 Agent 在各自的步骤里已经落地了），
           收起窗口、把向导复位，再把当前协作的数据重拉一遍。*/
        finish: function () {
            ui.window.close('addProj');
            return wait(200).then(function () {
                ui.wizard.reset();
                state.set('wizard.project', null);
                state.set('wizard.main', null);
                state.set('wizard.draftSubAgents', []);
                freezeWizardStepOne(false);
                render.wizardSubAgents([]);
                state.set('wizard.detectedMainAgent', null);
                return Tsunagou.refresh(['projects', 'agents', 'agentsWindow', 'settings']);
            }).then(function () { return true; });
        }
    };

    /* ---- 项目侧栏面板（默认隐藏，点内容才出现） --------------------------- */

    const ASIDE_SLUGS = ['tasks', 'conflict', 'audit', 'workspace', 'path'];

    /* 侧栏里的分段：直接子元素中带 .content 的那些（第二个通常还带 .contentNDP） */
    function asideSections(aside) {
        return Array.prototype.filter.call(aside.children, function (node) {
            return node.classList.contains('content');
        });
    }

    /* 换掉侧栏标题栏上的文字（后端可以让侧栏标题跟着内容变） */
    function setAsideTitle(node, text) {
        const label = qs('.title .left p', node);
        if (label && text) label.textContent = toText(text);
    }

    /* 要显示的那一段如果是空的（没被任何渲染器填过），补个空状态，
       免得调 ui.aside.show(slug) 时露出一个“只有标题栏”的空壳。*/
    function fillAsideEmpty(node) {
        asideSections(node).forEach(function (block) {
            if (!isShown(block)) return;
            if (!block.querySelector('*')) fill(block, EMPTY_BOX);
        });
    }

    ui.aside = {
        /* 显示某个侧栏；section 是分段序号（0 起），不传则保持当前分段 */
        show: function (slug, section) {
            const node = tabAside(slug);
            if (!node) return null;
            if (section !== undefined && section !== null) ui.aside.load(slug, section);
            revealEl(node, PANE_DISPLAY);
            /* 必须在显示之后：isShown 会看祖先的 display，隐藏时判断不出该不该补。*/
            fillAsideEmpty(node);
            emit('ui:aside', { slug: slug, visible: true, section: section });
            return node;
        },
        hide: function (slug) {
            const node = tabAside(slug);
            if (!node) return null;
            concealEl(node);
            emit('ui:aside', { slug: slug, visible: false });
            return node;
        },
        hideAll: function () {
            ASIDE_SLUGS.forEach(function (slug) { concealEl(tabAside(slug)); });
            emit('ui:aside', { slug: '*', visible: false });
        },
        /* 清空所有侧栏的内容（启动时调一次）
           目的：index.html 里那些占位文案不该有机会在"还没人填过"的时候露出来。*/
        clearAll: function () {
            ASIDE_SLUGS.forEach(function (slug) {
                const node = tabAside(slug);
                if (!node) return;
                asideSections(node).forEach(function (section) { fill(section, ''); });
            });
            return true;
        },
        /* 切到侧栏里的第几段（冲突的"分歧详情/契约详情"、审计的"意图/租约"靠它互斥）。
           .contentNDP 在 CSS 里就是 display:none，所以显示必须显式写 flex。*/
        load: function (slug, section, title) {
            const node = tabAside(slug);
            if (!node) return null;
            const sections = asideSections(node);
            const index = clampNum(Number(section) || 0, 0, Math.max(sections.length - 1, 0));
            sections.forEach(function (block, i) {
                displayEl(block, i === index ? 'flex' : 'none');
            });
            if (title) setAsideTitle(node, title);
            return sections[index] || null;
        },
        /* 整体重写某个侧栏的内容（渲染器调用） */
        fill: function (slug, html, options) {
            const node = tabAside(slug);
            if (!node) return null;
            const sections = asideSections(node);
            const target = sections[(options && options.section) || 0];
            if (!target) return null;
            fill(target, html);
            if (options && options.title) setAsideTitle(node, options.title);
            return target;
        },
        isOpen: function (slug) { return isShown(tabAside(slug)); }
    };

    /* 点侧栏标题栏右上角的 × 收起它自己 */
    ui.aside.bindClose = function () {
        delegateClick(['.secProjPanel .inner > .asideMain > .title > .right'], function (button) {
            concealEl(closest(button, '.asideMain'));
        });
    };

    /* ---- 侧栏宽度拖拽 ---------------------------------------------------- */

    /* 只改宽度和光标，不碰其它样式；拖拽范围由下面的常量决定。*/
    const ASIDE_EDGE_IN = 6;
    const ASIDE_EDGE_OUT = 8;
    const ASIDE_MIN_W = 300;
    const ASIDE_MAX_W = 600;
    const ASIDE_MAIN_MIN = 240;

    let asideDrag = null;
    let asideCursor = null;

    /* 当前可见的侧栏：不能靠 id（换页后就不对了），只能按"可见"找 */
    function activeAside() {
        const list = qsa('.secProjPanel .inner > .asideMain');
        for (let i = 0; i < list.length; i++) {
            if (isShown(list[i])) return list[i];
        }
        return null;
    }

    function asideMinWidth(node) {
        const value = parseFloat(getComputedStyle(node).minWidth);
        return Math.max(isNaN(value) ? 0 : value, ASIDE_MIN_W);
    }

    function asideMaxWidth(node) {
        const parent = node.parentElement;
        const available = parent ? parent.clientWidth : Infinity;
        return Math.max(asideMinWidth(node), Math.min(ASIDE_MAX_W, available - ASIDE_MAIN_MIN));
    }

    function onAsideEdge(node, event) {
        if (!isShown(node)) return false;
        const rect = node.getBoundingClientRect();
        return event.clientY >= rect.top && event.clientY <= rect.bottom &&
            event.clientX >= rect.left - ASIDE_EDGE_OUT && event.clientX <= rect.left + ASIDE_EDGE_IN;
    }

    function updateAsideCursor(event) {
        const node = activeAside();
        const on = onAsideEdge(node, event);
        if (asideCursor && asideCursor.el === node && asideCursor.on === on) return;
        if (asideCursor && asideCursor.el && asideCursor.el !== node) asideCursor.el.style.cursor = '';
        asideCursor = { el: node, on: on };
        if (node) node.style.cursor = on ? 'col-resize' : '';
    }

    function endAsideDrag() {
        if (!asideDrag) return;
        asideDrag = null;
        document.body.style.cursor = '';
    }

    ui.asideDrag = {
        bind: function () {
            document.addEventListener('pointerdown', function (event) {
                if (event.button !== 0) return;
                const node = activeAside();
                if (!onAsideEdge(node, event)) return;
                event.preventDefault();
                asideDrag = {
                    el: node,
                    startX: event.clientX,
                    startWidth: node.offsetWidth,
                    min: asideMinWidth(node),
                    max: asideMaxWidth(node)
                };
                document.body.style.cursor = 'col-resize';
            });
            document.addEventListener('pointermove', function (event) {
                if (!asideDrag) { updateAsideCursor(event); return; }
                const width = asideDrag.startWidth + (asideDrag.startX - event.clientX);
                asideDrag.el.style.width = clampNum(width, asideDrag.min, asideDrag.max) + 'px';
            });
            document.addEventListener('pointerup', endAsideDrag);
            document.addEventListener('pointercancel', endAsideDrag);
        }
    };

    /* ---- 下拉选择框（.choosebox + .chooseboxOpen） ----------------------- */

    /* 配对规则：面板是 .choosebox 的下一个 .chooseboxOpen 兄弟；
       也可以给 .choosebox 写 data-target="面板id" 显式指定（面板放别处时用）。
       选中后：回填 .choosebox > .left 的文字 → 收起面板 →
       在 .choosebox 上派发冒泡事件 choosebox:change（detail = {value, option, box, panel}）。*/

    const CSBOX_ANIM_TIMEOUT = 240; /* 略大于 CSS 里 height 过渡的 0.2s，作兜底 */

    function findCsPanel(box) {
        if (!box) return null;
        /* 有人直接递面板过来（`ui.choosebox.setValue('某个面板的 id', …)` 就是这种）：
           那就别再去找"它的面板"了 —— 同一个容器里有第二个选择框时，找下去的答案会是
           第一个面板，于是值写到了别的框上。*/
        if (box.classList && box.classList.contains('chooseboxOpen')) return box;
        const targetId = box.dataset.target;
        if (targetId) {
            const panel = byId(targetId);
            if (panel) return panel;
        }
        for (let node = box.nextElementSibling; node; node = node.nextElementSibling) {
            if (node.classList && node.classList.contains('chooseboxOpen')) return node;
            if (node.classList && node.classList.contains('choosebox')) break;
        }
        return box.parentElement ? qs('.chooseboxOpen', box.parentElement) : null;
    }

    function findCsBox(panel) {
        if (!panel) return null;
        if (panel.id) {
            const box = qs('.choosebox[data-target="' + panel.id + '"]');
            if (box) return box;
        }
        for (let node = panel.previousElementSibling; node; node = node.previousElementSibling) {
            if (node.classList && node.classList.contains('choosebox')) return node;
        }
        return panel.parentElement ? qs('.choosebox', panel.parentElement) : null;
    }

    /* ---- 面板定位 --------------------------------------------------------
       面板（.chooseboxOpen）在 CSS 里是 position:absolute，需要一个"定位祖先"才落得准
       （设置窗口里那个是 .uiBlock .items .item > .right）。
       两种地方整条链上都没有定位祖先，浏览器会把面板的静态位置算到 flex 容器的起点，
       于是展开后跑到**第一个**选择框下面（错位）：
         · 向导第 2 步 / 添加子 Agent 窗口：面板直接放在 .uiBlock 中（还在 .secWindow 里）；
         · 主屏 tabMain 的标题栏（总路径那一屏）：连 .secWindow 都没有。
       这里在展开时把面板设成与选择框等宽、并钉到它正下方；主屏那种连 .secWindow
       都没有的地方（fixed 不会被 overscroll 容器裁掉）改用 fixed + 视口坐标。
       已经有定位祖先时不动它（位置与宽度都交给 CSS）。*/

    const CSBOX_ANCHOR_GAP = 4;
    const CSBOX_VIEWPORT_MARGIN = 8;

    function csHasPositionedWrapper(panel, stopAt) {
        for (let node = panel.parentElement; node && node !== stopAt; node = node.parentElement) {
            if (getComputedStyle(node).position !== 'static') return true;
        }
        return false;
    }

    /* 打开时的锚点：把面板设成与选择框**等宽**，水平方向让右边缘贴着选择框右边缘
       （即掉在右侧箭头下方），竖直方向贴在框正下方。
       注意：必须在面板 display 打开之后调 —— 要先量得到它自己的宽度。
       已经有定位祖先时不动（例如设置窗口，尺寸与位置都交给 CSS）。*/
    function anchorCsPanel(panel) {
        const box = findCsBox(panel);
        if (!box) return;
        const viewport = closest(panel, '.secWindow');
        if (viewport && csHasPositionedWrapper(panel, viewport)) return;
        /* 主屏（tabMain 的标题栏）里连 .secWindow 都没有：整条链上一个定位祖先也没有，
           绝对定位的"静态位置"会被算到 .right 的起点 —— 展开后两个框的面板都跑到
           **第一个**框下面（错位）。这种地方改用 fixed + 视口坐标最稳：
           链上没有 transform / filter，fixed 就等于视口；容器滚动时跟着重定位
           由 scroll 捕获监听兜住（scheduleCsReanchor）。*/
        placeCsPanelAtBox(panel, box, !viewport);
    }

    /* 与选择框等宽、右缘对齐、钉在正下方；useFixed 时用视口坐标（见上）*/
    function placeCsPanelAtBox(panel, box, useFixed) {
        const rect = box.getBoundingClientRect();
        if (useFixed) panel.style.position = 'fixed';
        /* 与选择框等宽（CSS 是全局 box-sizing: border-box，所以就是外层宽度）*/
        panel.style.width = Math.round(rect.width) + 'px';
        /* 设完宽度再量实际宽度：CSS 的 min-width 可能让它比选择框还宽 */
        const width = panel.offsetWidth || Math.round(rect.width);
        /* 贴右边缘；再兜一道：窗口被拖得很窄时别让面板跑出视口 */
        const limit = Math.max(CSBOX_VIEWPORT_MARGIN, window.innerWidth - width - CSBOX_VIEWPORT_MARGIN);
        const left = Math.min(Math.max(rect.right - width, CSBOX_VIEWPORT_MARGIN), limit);
        panel.style.left = Math.round(left) + 'px';
        panel.style.top = Math.round(rect.bottom + CSBOX_ANCHOR_GAP) + 'px';
    }

    /* 面板收起后清掉锚点与宽度，别在 DOM 上留过期的行内值 */
    function releaseCsPanel(panel) {
        panel.style.left = '';
        panel.style.top = '';
        panel.style.width = '';
        panel.style.position = '';
    }

    /* 面板还开着的时候，如果窗口尺寸变了、或面板所在的容器滚动了，选择框就移位了 ——
       面板必须跟着重新定位，否则会停在旧位置（错位）。*/
    function reanchorOpenCsPanels() {
        qsa('.chooseboxOpen[data-cs-state="open"]').forEach(function (panel) { anchorCsPanel(panel); });
    }

    let csReanchorScheduled = false;

    /* resize / scroll 会连续触发，用一帧合并一次，别每来一次就量一遍布局 */
    function scheduleCsReanchor() {
        if (csReanchorScheduled) return;
        csReanchorScheduled = true;
        requestAnimationFrame(function () {
            csReanchorScheduled = false;
            reanchorOpenCsPanels();
        });
    }

    function settleCsPanel(panel, expanded) {
        clearTimeout(panel.csAnimTimer);
        const finish = function () {
            panel.removeEventListener('transitionend', onEnd);
            clearTimeout(panel.csAnimTimer);
            if (panel.dataset.csState === 'open' && expanded) {
                panel.style.height = 'auto';
            } else if (!expanded && panel.dataset.csState !== 'open') {
                panel.style.display = 'none';
                panel.style.height = '';
                releaseCsPanel(panel);
            }
        };
        const onEnd = function (event) {
            if (event.target === panel && event.propertyName === 'height') finish();
        };
        panel.addEventListener('transitionend', onEnd);
        panel.csAnimTimer = setTimeout(finish, CSBOX_ANIM_TIMEOUT);
    }

    function openCsPanel(panel) {
        if (!panel || panel.dataset.csState === 'open') return;
        ui.choosebox.closeAll();
        panel.dataset.csState = 'open';
        panel.classList.add('open');
        panel.style.display = 'flex';
        anchorCsPanel(panel);
        panel.style.height = '0px';
        void panel.offsetHeight;
        panel.style.height = panel.scrollHeight + 'px';
        settleCsPanel(panel, true);
    }

    function closeCsPanel(panel) {
        if (!panel || panel.dataset.csState !== 'open') return;
        panel.dataset.csState = 'closed';
        panel.classList.remove('open');
        /* 面板收起后，里面的图标统一回到当前主题的版本
           （hover 时它们被 setCsIconWhite 临时换成过白色版）*/
        qsa('img', panel).forEach(function (img) {
            img.setAttribute('src', themedIconPath(img.getAttribute('src')));
        });
        panel.style.height = panel.scrollHeight + 'px';
        void panel.offsetHeight;
        panel.style.height = '0px';
        settleCsPanel(panel, false);
    }

    /* 选中某个选项。options.silent = true 时**不**派发 choosebox:change ——
       程序化回填（如 render.settings）必须走 silent，否则会被当成用户操作，
       在页面刚加载时弹出“改动已成功保存”。*/
    function selectCsOption(option, options) {
        const opts = options || {};
        const panel = closest(option, '.chooseboxOpen');
        const box = findCsBox(panel);
        const value = option.textContent.trim();
        if (box) {
            const label = qs('.left', box);
            if (label) setCsBoxLabel(label, option);
        }
        closeCsPanel(panel);
        if (box && !opts.silent) {
            box.dispatchEvent(new CustomEvent('choosebox:change', {
                bubbles: true,
                detail: { value: value, option: option, box: box, panel: panel }
            }));
        }
        emit('ui:choosebox', { value: value, box: box, panel: panel, silent: !!opts.silent });
    }

    /* 回填 .choosebox 的显示值。
       框里的 .left 可能带一个 <img>（厂商图标）—— 直接写 textContent 会把它一起删掉，
       所以有图标时只改文字节点，并把图标同步成所选那一项的图标。
       注意：被点选的那一项可能正处于 hover 状态（图标被换成了白色版），
       所以要用 themedIconPath() 按当前主题纠正一次后缀，否则框里会留下白图标。*/
    function setCsBoxLabel(label, option) {
        const value = option.textContent.trim();
        const own = qs('img', label);
        if (!own) { label.textContent = value; return; }
        const picked = qs('img', option);
        if (picked) own.src = themedIconPath(picked.getAttribute('src'));
        const texts = Array.prototype.filter.call(label.childNodes, function (node) {
            return node.nodeType === 3 && String(node.nodeValue || '').trim();
        });
        if (texts.length) texts[0].nodeValue = value;
        else label.appendChild(document.createTextNode(value));
    }

    /* 把一个选择框恢复到它的默认项（表单"清空"用；不派发事件）。
       默认项 = 面板里带 data-default 的那一项（index.html 里标在 Codex 上），
       没有标记的框退回第一项 —— 老规矩，不动 HTML 也能用。*/
    function resetCsBox(box) {
        const panel = findCsPanel(box);
        const first = panel ? (qs('p[data-default]', panel) || qs('p', panel)) : null;
        if (!first) return;
        const value = first.textContent.trim();
        if (ui.choosebox.value(box) !== value) ui.choosebox.setValue(box, value, { silent: true });
    }

    ui.choosebox = {
        /* 参数可以是 .choosebox 元素/id，也可以是 .chooseboxOpen 面板元素/id */
        open: function (ref) {
            const node = resolveEl(ref);
            if (!node) return null;
            const panel = node.classList.contains('chooseboxOpen') ? node : findCsPanel(node);
            openCsPanel(panel);
            return panel;
        },
        close: function (ref) {
            const node = resolveEl(ref);
            if (!node) return null;
            const panel = node.classList.contains('chooseboxOpen') ? node : findCsPanel(node);
            closeCsPanel(panel);
            return panel;
        },
        toggle: function (ref) {
            const node = resolveEl(ref);
            if (!node) return null;
            const panel = node.classList.contains('chooseboxOpen') ? node : findCsPanel(node);
            if (!panel) return null;
            if (panel.dataset.csState === 'open') closeCsPanel(panel); else openCsPanel(panel);
            return panel;
        },
        closeAll: function () {
            qsa('.chooseboxOpen[data-cs-state="open"]').forEach(closeCsPanel);
        },
        /* 按选项文字选中（后端说"把主题设成浅色"时用）。
           传 { silent: true } 则只改显示值、不当成用户操作。*/
        setValue: function (boxRef, value, options) {
            const box = resolveEl(boxRef);
            if (!box) return false;
            const panel = findCsPanel(box);
            if (!panel) return false;
            const list = qsa('p', panel);
            const text = toText(value);
            for (let i = 0; i < list.length; i++) {
                if (list[i].textContent.trim() === text) {
                    selectCsOption(list[i], options);
                    return true;
                }
            }
            /* 面板里没有这个选项时也允许直接写值（后端给了个自定义值） */
            const label = qs('.left', box);
            if (label) label.textContent = text;
            return false;
        },
        value: function (boxRef) {
            const box = resolveEl(boxRef);
            const label = box ? qs('.left', box) : null;
            return label ? label.textContent.trim() : '';
        },
        isOpen: function (ref) {
            const node = resolveEl(ref);
            const panel = node && (node.classList.contains('chooseboxOpen') ? node : findCsPanel(node));
            return !!panel && panel.dataset.csState === 'open';
        }
    };

    /* 把某个 <img> 换成白色版 / 换回深色版（只处理 -l / -d 结尾的主题配图）。
       浅色模式下选择框里的图标是深色版（-d），hover 到品牌色底上时必须变白，
       否则看不清 —— 白色版就是同一套资源里的 -l 文件。*/
    function setCsIconWhite(img, white) {
        const src = img.getAttribute('src');
        if (!src || !/-[ld]\.png$/i.test(src)) return;
        const wanted = src.replace(/-[ld]\.png$/i, white ? '-l.png' : '-d.png');
        if (src !== wanted) img.setAttribute('src', wanted);
    }

    /* hover 时要"变白"的对象：面板里的选项，或选择框本身（它的图标在 .left 里）*/
    function csHoverTarget(event) {
        const node = closest(event.target, '.chooseboxOpen p') || closest(event.target, '.choosebox');
        if (!node) return null;
        const img = node.classList.contains('choosebox') ? qs('.left img', node) : qs('img', node);
        return img ? { node: node, img: img } : null;
    }

    ui.choosebox.bindClicks = function () {
        document.addEventListener('click', function (event) {
            const option = closest(event.target, '.chooseboxOpen p');
            /* 带 data-disabled 的选项（如"Claude Code（待实现）"）画出来但不给选：
               点了什么都不发生，面板留着让人挑别的。程序化回填不走这里，照旧可用。*/
            if (option && !option.hasAttribute('data-disabled')) { selectCsOption(option); return; }
            if (option) return;
            const box = closest(event.target, '.choosebox');
            const inPanel = closest(event.target, '.chooseboxOpen');
            if (box && !inPanel) { ui.choosebox.toggle(box); return; }
            if (inPanel) return; /* 点在面板空白处不收起 */
            ui.choosebox.closeAll();
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') ui.choosebox.closeAll();
        });
        /* 面板展开期间：窗口尺寸变化、或滚动容器滚动，都要跟着重新定位
           （scroll 不冒泡，所以必须用捕获阶段监听）*/
        window.addEventListener('resize', scheduleCsReanchor);
        document.addEventListener('scroll', scheduleCsReanchor, true);

        /* hover 变白：面板里的选项、以及选择框本身在 hover 时底色会变成品牌色
           （CSS 的 .chooseboxOpen p:hover / .choosebox:hover），浅色模式下必须把
           深色图标换成白色版；深色模式里图标本来就是白的，直接跳过。*/
        document.addEventListener('mouseover', function (event) {
            if (currentThemeName !== 'light') return;
            const hit = csHoverTarget(event);
            if (hit) setCsIconWhite(hit.img, true);
        });
        document.addEventListener('mouseout', function (event) {
            if (currentThemeName !== 'light') return;
            const hit = csHoverTarget(event);
            /* 在同一个元素内部移动（图标 ↔ 文字）不算离开 */
            if (!hit || (event.relatedTarget && hit.node.contains(event.relatedTarget))) return;
            setCsIconWhite(hit.img, false);
        });
    };

    /* ========================================================================
     * §3 反馈组件
     * ------------------------------------------------------------------------
     * index.html 里那四个"只能给 DEBUG 按钮用"的弹窗，在这一层变成通用组件：
     *   #AnnounceMent  → notify.success()   右下角带进度条的成功提示
     *   #AnnounceMent2 → notify.info()      顶部居中的一句话提示（error 也用它）
     *   #loadW         → notify.loading()   转圈遮罩
     *   #rightGetWin   → dialog.decision()  底部"需要用户确认/决定"卡片，带按钮，Promise 化
     *   #delPmt        → dialog.confirm()   通用二次确认框，Promise<boolean>
     * 组件本身不新增 CSS，全部靠已有类名与图标类（fa-solid / fa-regular）切换外观。
     * 注：成功的品牌色与错误的品牌色在 CSS 里是同一个（--brand-col），
     *     所以 error 靠图标与文案区分，颜色由 CSS 决定，JS 不插手。
     * ====================================================================== */

    function pad2(value) { return value < 10 ? '0' + value : '' + value; }

    function todayText() {
        const date = new Date();
        return date.getFullYear() + '/' + pad2(date.getMonth() + 1) + '/' + pad2(date.getDate());
    }

    /* ---- 成功提示（右下角，带 2s 进度条） -------------------------------- */

    const SUCCESS_ID = 'AnnounceMent';
    const SUCCESS_BAR_ID = 'secApgr';
    const SUCCESS_DEFAULT_DURATION = 2600; /* 进度条本身固定 2s（CSS），这个值只管什么时候滑走 */
    let successTimer = null;

    notify.success = function (options) {
        const node = byId(SUCCESS_ID);
        if (!node) return false;
        const opts = (typeof options === 'string') ? { title: options } : (options || {});
        const icon = qs('.top .aIcon i', node);
        const titleNode = qs('.aText .fword', node);
        const subNode = qs('.aText .sword', node);
        const bar = byId(SUCCESS_BAR_ID);

        if (icon) icon.className = opts.icon || 'fa-solid fa-check';
        if (titleNode) titleNode.textContent = opts.title || '操作成功';
        if (subNode) subNode.textContent = opts.sub || ('Tsunagou ' + todayText());

        /* 进度条重播：先摘掉类并强制重排，再加回去，动画才会从头跑 */
        if (bar) {
            bar.classList.remove('Active');
            void bar.offsetWidth;
            bar.classList.add('Active');
        }
        node.style.right = '30px';

        clearTimeout(successTimer);
        const duration = opts.duration === undefined ? SUCCESS_DEFAULT_DURATION : Number(opts.duration);
        if (duration > 0) successTimer = setTimeout(function () { notify.success.hide(); }, duration);
        emit('notify', { kind: 'success', options: opts });
        return true;
    };

    notify.success.hide = function () {
        const node = byId(SUCCESS_ID);
        if (node) node.style.right = '-300px';
        const bar = byId(SUCCESS_BAR_ID);
        if (bar) bar.classList.remove('Active');
        clearTimeout(successTimer);
    };

    /* ---- 一句话提示（顶部居中） ------------------------------------------ */

    const INFO_ID = 'AnnounceMent2';
    const INFO_DEFAULT_DURATION = 2500;
    let infoTimer = null;

    function showTip(text, options) {
        const node = byId(INFO_ID);
        if (!node) return false;
        const opts = options || {};
        const icon = qs('.aIcon i', node);
        const label = qs('.aText', node);
        if (icon) icon.className = opts.icon || 'fa-solid fa-circle-info';
        if (label) label.textContent = toText(text);
        node.style.top = '30px';

        clearTimeout(infoTimer);
        const duration = opts.duration === undefined ? INFO_DEFAULT_DURATION : Number(opts.duration);
        if (duration > 0) infoTimer = setTimeout(function () { notify.tipHide(); }, duration);
        emit('notify', { kind: opts.kind || 'info', text: toText(text) });
        return true;
    }

    notify.info = function (text, options) {
        return showTip(text, Object.assign({ kind: 'info', icon: 'fa-solid fa-circle-info' }, options || {}));
    };

    /* 失败提示：同一个组件，换图标和停留时长（颜色由 CSS 决定，JS 不写颜色） */
    notify.error = function (text, options) {
        return showTip(text, Object.assign({
            kind: 'error',
            icon: 'fa-solid fa-circle-exclamation',
            duration: 4000
        }, options || {}));
    };

    notify.warn = function (text, options) {
        return showTip(text, Object.assign({
            kind: 'warn',
            icon: 'fa-solid fa-triangle-exclamation',
            duration: 3500
        }, options || {}));
    };

    notify.tipHide = function () {
        const node = byId(INFO_ID);
        if (node) node.style.top = '-100px';
        clearTimeout(infoTimer);
    };

    /* ---- 加载遮罩（#loadW） ---------------------------------------------- */

    const LOADING_ID = 'loadW';

    /* 「取消等待」入口的显隐（元素在 index.html 的 #loadW 里，默认不显示）*/
    function setCancelEntry(visible) {
        const entry = byId('loadWCancel');
        if (entry) entry.style.display = visible ? '' : 'none';
    }

    /* 「取消等待」入口只在“可以取消的等待”里露出来（接入 Agent 要等宿主那边动手，
       这一段人可以放弃）。点一下先问一次，确认后由当前等待者自己收尾：
       作废票据 + 注销宿主登记。遮罩由收尾的一方关。*/
    let cancelWait = null;        /* 当前等待的“取消”动作（null = 这段等待不能取消）*/
    let cancelWaitCopy = null;    /* 这段等待自己的确认框文案（没有就用下面那套等票的说法）*/
    let cancelAsking = false;     /* 「取消等待」的确认框正开着（防止重点）*/

    notify.loading = function (text, options) {
        const node = byId(LOADING_ID);
        if (!node) return false;
        const label = qs('.textW', node);
        const opts = options || {};
        const shown = toText(text) || '正在处理';
        if (label) label.textContent = shown;
        cancelWait = (typeof opts.cancel === 'function') ? opts.cancel : null;
        cancelWaitCopy = (cancelWait && isPlainObject(opts.cancelDialog)) ? opts.cancelDialog : null;
        cancelAsking = false;
        /* 先摆好入口再开窗：遮罩出现时就是它最后的样子，不会闪一下。*/
        setCancelEntry(!!cancelWait);
        ui.window.open(node);
        return true;
    };

    notify.loadingEnd = function () {
        cancelWait = null;
        cancelWaitCopy = null;
        cancelAsking = false;
        setCancelEntry(false);
        ui.window.close(LOADING_ID);
        return true;
    };

    /* 确认框开着的时候，“遮罩关了”不算人放弃了等待 */
    notify.cancelPending = function () { return cancelAsking; };

    notify.cancelWaiting = function () {
        const task = cancelWait;
        if (!task || cancelAsking) return Promise.resolve(false);
        cancelAsking = true;
        /* 这段等待自己有没有说法（等票那段是"作废票据"，等宿主自己接入那段只是"不看了"）。
           没有就照旧用等票那套。*/
        const copy = cancelWaitCopy || {};
        /* 确认框本来就是最上面一层（见 init() 把 #delPmt 移到 body 末尾），
           所以不用把遮罩收起来，遮罩就在背后接着转。*/
        return dialog.confirm({
            title: toText(copy.title) || '取消等待接入？',
            text: toText(copy.text) || '要停止等待这个 Agent 连接吗？',
            description: toText(copy.description) || ('系统会核对这次接入是否仍可取消；已经开始接入时会说明原因，' +
                '不会移除已接入的 Agent。'),
            okText: toText(copy.okText) || '取消接入'
        }).then(function (ok) {
            cancelAsking = false;
            /* 确认框开着的时候这次等待可能已经结束了（例如那边正好连上了）*/
            const stillWaiting = (cancelWait === task);
            if (ok && stillWaiting) {
                cancelWait = null;
                setCancelEntry(false);
                task();
            }
            return ok;
        });
    };

    /* 包一个异步任务：自动开遮罩、结束才收起（失败也收）
       用法：await Tsunagou.notify.track('正在重试存档', api.post('checkpointRetry', { id: id })) */
    notify.track = function (text, task) {
        notify.loading(text);
        let chain;
        try {
            chain = (typeof task === 'function') ? task() : task;
        } catch (error) {
            notify.loadingEnd();
            return Promise.reject(error);
        }
        return Promise.resolve(chain).then(function (value) {
            notify.loadingEnd();
            return value;
        }, function (error) {
            notify.loadingEnd();
            throw error;
        });
    };

    /* ---- 二次确认框（#delPmt，Promise<boolean>） ------------------------- */

    const CONFIRM_ID = 'delPmt';
    let confirmPending = null;

    dialog.confirm = function (options) {
        const node = byId(CONFIRM_ID);
        if (!node) return Promise.resolve(false);
        const opts = options || {};
        const titleNode = qs('.titleBar .title', node);
        const textNode = qs('.content .bigTxt', node);
        const descNode = qs('.content .description', node);
        const buttons = qsa('.options .buttonbox2', node);

        if (titleNode) titleNode.textContent = opts.title || '确认操作';
        if (textNode) textNode.textContent = opts.text || '确定要继续吗？';
        if (descNode) {
            if (opts.description) {
                descNode.textContent = opts.description;
                showEl(descNode);
            } else {
                hideEl(descNode);
            }
        }
        if (buttons[0]) buttons[0].textContent = opts.cancelText || '取消';
        if (buttons[1]) {
            buttons[1].textContent = opts.okText || '确定';
            buttons[1].classList.toggle('buttonbox2important', !!opts.danger);
        }

        /* 上一次还没收尾的确认框，直接当作取消 */
        if (confirmPending) confirmPending.finish(false);

        return new Promise(function (resolve) {
            const pending = { node: node, resolve: resolve, settled: false };

            pending.finish = function (result) {
                if (pending.settled) return;
                pending.settled = true;
                node.removeEventListener('click', onClick, true);
                if (confirmPending === pending) confirmPending = null;
                ui.window.close(node);
                resolve(result);
            };

            /* 用捕获阶段拦下点击：按钮自带的 onclick（关窗）照样会执行，不影响收尾 */
            function onClick(event) {
                const button = closest(event.target, '.buttonbox2');
                const closeBtn = closest(event.target, '.titleBar .button');
                const onBackdrop = (event.target === node);
                if (!button && !closeBtn && !onBackdrop) return;
                pending.finish(button ? buttons.indexOf(button) === 1 : false);
            }

            confirmPending = pending;
            node.addEventListener('click', onClick, true);
            ui.window.open(node);
        });
    };

    /* 任何方式关掉确认框（例如被 closeAll）都要收尾，避免 Promise 永远挂着 */
    events.on('ui:window', function (detail) {
        if (!detail || detail.open) return;
        if (confirmPending && confirmPending.node.id === detail.id) confirmPending.finish(false);
    });

    /* ---- 需要用户决定的卡片（#rightGetWin，Promise<值>） ------------------ */

    const DECISION_ID = 'rightGetWin';
    let decisionPending = null;

    function decisionEl() { return byId(DECISION_ID); }

    dialog.decision = function (options) {
        const node = decisionEl();
        if (!node) return Promise.resolve(null);
        const opts = options || {};
        const actions3 = toArray(opts.actions);
        const titleNode = qs('.title', node);
        const contentNode = qs('.content', node);
        const optionBox = qs('.option', node);

        if (titleNode) titleNode.textContent = opts.title || '需要用户确认/决定的信息';
        if (contentNode) contentNode.textContent = toText(opts.content);
        if (optionBox) {
            fill(optionBox, actions3.map(function (item, index) {
                const kind = item.kind === 'important' ? ' buttonbox2important' : '';
                return '<div class="buttonbox2' + kind + '" data-decision-index="' + index + '">' +
                    esc(item.label || ('选项 ' + (index + 1))) + '</div>';
            }).join(''));
        }

        if (decisionPending) decisionPending.finish(null);
        node.style.transform = 'translateX(50%) translateY(0%)';

        return new Promise(function (resolve) {
            /* actions 存在 pending 上：点击监听只绑一次，如果读外层的 actions3，
               第二次调用 decision 时就会拿上一次的按钮表去映射，值会错。*/
            const pending = { node: node, settled: false, actions: actions3 };
            pending.finish = function (value) {
                if (pending.settled) return;
                pending.settled = true;
                if (decisionPending === pending) decisionPending = null;
                resolve(value);
            };
            decisionPending = pending;

            /* 点按钮 → 收起卡片 → 把按钮携带的值给调用方 */
            if (optionBox && !optionBox.dataset.tgBound) {
                optionBox.dataset.tgBound = '1';
                optionBox.addEventListener('click', function (event) {
                    const button = closest(event.target, '[data-decision-index]');
                    if (!button || !decisionPending) return;
                    const index = Number(button.dataset.decisionIndex);
                    const action = (decisionPending.actions || [])[index] || {};
                    const value = (action.value === undefined) ? (action.label || index) : action.value;
                    dialog.hideDecision();
                    decisionPending.finish(value);
                });
            }

            if (opts.duration > 0) {
                setTimeout(function () {
                    if (!pending.settled && decisionPending === pending) {
                        dialog.hideDecision();
                        pending.finish(null);
                    }
                }, Number(opts.duration));
            }
        });
    };

    dialog.hideDecision = function () {
        const node = decisionEl();
        if (node) node.style.transform = 'translateX(50%) translateY(150%)';
        return true;
    };

    /* notify.decision 是 dialog.decision 的别名（按语义放在通知里更顺手） */
    notify.decision = dialog.decision;

    /* ========================================================================
     * §4 通信层
     * ------------------------------------------------------------------------
     * 一个请求封装 + 一套表单规则。
     * 请求：Tsunagou.api.get('tasks')            ← 用配置里的键
     *       Tsunagou.api.get('/custom/path')     ← 直接用路径
     *       Tsunagou.api.post('checkpointRetry', { id: 'op-1' })
     * 表单：没有提交按钮的 input → 失焦即提交，并提示"改动已成功保存"。
     * ====================================================================== */

    /* ---- 错误对象 -------------------------------------------------------- */

    class ApiError extends Error {
        constructor(message, info) {
            super(message || '请求失败');
            const data = info || {};
            this.name = 'ApiError';
            this.status = data.status || 0;
            this.code = data.code;
            this.raw = data.raw;
            this.url = data.url || '';
            this.method = data.method || 'GET';
        }
    }

    /* ---- 响应解包 -------------------------------------------------------- */

    /* 支持三种后端风格：
       1) {code:0, message:'', data:{...}}   → 取 data（code 非 0 视为失败）
       2) {code:0, result:{...}}             → 取 result
       3) 裸 JSON / 数组 / 纯文本            → 原样返回 */
    const OK_CODES = [0, '0', 200, '200', 'ok', 'OK', 'success', true];

    function isOkCode(code) {
        for (let i = 0; i < OK_CODES.length; i++) {
            if (OK_CODES[i] === code) return true;
        }
        return false;
    }

    function unwrapPayload(payload) {
        if (!isPlainObject(payload) || !('code' in payload)) return payload;
        const code = payload.code;
        const message = payload.message || payload.msg || payload.error || '';
        if (!isOkCode(code)) {
            throw new ApiError(message || ('后端返回错误码 ' + code), { code: code, raw: payload });
        }
        if ('data' in payload) return payload.data;
        if ('result' in payload) return payload.result;
        return payload;
    }

    /* ---- 地址与查询串 ---------------------------------------------------- */

    function buildQuery(query) {
        if (!query) return '';
        const parts = [];
        Object.keys(query).forEach(function (key) {
            const value = query[key];
            if (value === undefined || value === null || value === '') return;
            if (Array.isArray(value)) {
                value.forEach(function (item) { parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(item)); });
            } else {
                parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(value));
            }
        });
        return parts.length ? ('?' + parts.join('&')) : '';
    }

    /* 允许传配置键（'tasks'）或真实路径（'/x/y'）；
       模板里的 {project} 用当前项目 id 替换。*/
    const PROJECT_PLACEHOLDER = '{project}';

    /* 中间层认这个请求头（见 console/app.py 的 PROJECT_HEADER）。daemon 会忽略它。*/
    const PROJECT_HEADER = 'Tsunagou-Project';

    function pathTemplate(pathOrKey) {
        if (!pathOrKey) return '';
        return config.paths[pathOrKey] || toText(pathOrKey);
    }

    function pathNeedsProject(pathOrKey) {
        return pathTemplate(pathOrKey).indexOf(PROJECT_PLACEHOLDER) >= 0;
    }

    function resolvePath(pathOrKey) {
        const template = pathTemplate(pathOrKey);
        if (template.indexOf(PROJECT_PLACEHOLDER) < 0) return template;
        const projectId = toText(state.get('currentProjectId'));
        return template.split(PROJECT_PLACEHOLDER).join(encodeURIComponent(projectId));
    }

    /* ---- 请求 ------------------------------------------------------------ */

    api.ApiError = ApiError;

    api.request = function (options) {
        const opts = options || {};
        const method = toText(opts.method || 'GET').toUpperCase();
        const pathKey = opts.path || opts.url;

        /* 项目作用域的接口：没选项目就不发请求，报一个说得清的错，
           免得拼出 /projects//tasks 这种地址去打扰后端。*/
        if (pathNeedsProject(pathKey) && !toText(state.get('currentProjectId'))) {
            const noProject = new ApiError('还没有选择协作项目，无法请求 ' + toText(pathKey), {
                method: method,
                url: toText(pathKey)
            });
            if (!opts.silent) notify.error(noProject.message);
            emit('api:error', { method: method, url: toText(pathKey), error: noProject });
            return Promise.reject(noProject);
        }

        const path = resolvePath(pathKey);
        const url = config.joinUrl(path) + buildQuery(opts.query);
        const timeout = Number(opts.timeout) || config.timeout;

        const controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        let timer = null;
        if (controller) timer = setTimeout(function () { controller.abort(); }, timeout);

        const headers = Object.assign({}, config.headers, opts.headers || {});
        if (config.token && !headers.Authorization) headers.Authorization = 'Bearer ' + config.token;
        /* 中间层靠这个头知道这次请求属于哪个项目：项目作用域的路径里已经有 id，
           但 /commands/*、/decisions、/checkpoints 这类路由没有，daemon 自己会忽略它。*/
        const current = toText(state.get('currentProjectId'));
        if (current && !headers[PROJECT_HEADER]) headers[PROJECT_HEADER] = current;
        /* Agent 类命令（B/M/X/R）要额外带会话头；U（用户控制面）命令不需要。
           daemon 会用 session_id + connection_epoch 核对身份与代次，见 api/auth.py。*/
        if (config.sessionId && !headers['Tsunagou-Session-Id']) {
            headers['Tsunagou-Session-Id'] = config.sessionId;
        }
        if (config.connectionEpoch !== '' && config.connectionEpoch !== null &&
            config.connectionEpoch !== undefined && !headers['Tsunagou-Connection-Epoch']) {
            headers['Tsunagou-Connection-Epoch'] = String(config.connectionEpoch);
        }

        const init = { method: method, headers: headers, credentials: opts.credentials || 'same-origin' };
        if (controller) init.signal = controller.signal;
        if (opts.body !== undefined && method !== 'GET' && method !== 'HEAD') {
            if (!headers['Content-Type']) headers['Content-Type'] = 'application/json;charset=utf-8';
            init.body = (typeof opts.body === 'string') ? opts.body : JSON.stringify(opts.body);
        }

        const request = fetch(url, init).then(function (response) {
            return response.text().then(function (text) {
                let payload = null;
                if (text) {
                    try { payload = JSON.parse(text); } catch (error) { payload = text; }
                }
                if (!response.ok) {
                    /* 真后端的错误体是 RFC 9457 风格：{"detail":{"code":"unknown_payload_field"}}，
                       也可能直接是 {"detail":"..."} 字符串。两种都要读得出来，
                       否则界面上只剩一句"请求失败（HTTP 400）"，看不到原因码。*/
                    let message = '';
                    if (isPlainObject(payload)) {
                        message = payload.message || payload.msg || payload.error || '';
                        if (!message && isPlainObject(payload.detail)) {
                            message = payload.detail.code || payload.detail.message || '';
                        }
                        if (!message && typeof payload.detail === 'string') message = payload.detail;
                    } else if (typeof payload === 'string') {
                        message = payload;
                    }
                    throw new ApiError(message || ('请求失败（HTTP ' + response.status + '）'),
                        { status: response.status, raw: payload, url: url, method: method });
                }
                return unwrapPayload(payload);
            });
        });

        return request.then(function (data) {
            if (timer) clearTimeout(timer);
            emit('api:success', { method: method, url: url, data: data });
            return data;
        }, function (error) {
            if (timer) clearTimeout(timer);
            const normalized = (error instanceof ApiError) ? error : new ApiError(
                (error && error.name === 'AbortError') ? ('请求超时（' + timeout + 'ms）') : ('网络错误：' + ((error && error.message) || '未知')),
                { url: url, method: method, raw: error }
            );
            if (!opts.silent) notify.error(normalized.message);
            emit('api:error', { method: method, url: url, error: normalized });
            throw normalized;
        });
    };

    api.get = function (pathOrKey, query, options) {
        return api.request(Object.assign({ method: 'GET', path: pathOrKey, query: query }, options || {}));
    };

    /* 命令 envelope 的幂等键。一次用户点击 = 一个 command_id；
       daemon 以 (project, principal, kind, command_id) 去重，重放只返回原结果。*/
    function newCommandId() {
        if (typeof crypto !== 'undefined' && crypto && typeof crypto.randomUUID === 'function') {
            return crypto.randomUUID().toLowerCase();
        }
        return 'cmd-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    }

    /* 真后端唯一的写入口：POST {baseUrl}/commands/{command_kind}
       body 是协议 envelope，payload 走服务端白名单（interfaces/runtime.py）。
       键不在 WRITE_COMMANDS 里时当作字面路径，保持旧用法。*/
    api.command = function (key, body, options) {
        if (!Object.prototype.hasOwnProperty.call(WRITE_COMMANDS, key)) {
            return api.post(key, body, options);
        }
        const spec = WRITE_COMMANDS[key];
        if (!spec) {
            const error = new ApiError(
                '这个操作还没接通：' + key +
                '（命令没装配、后端没有这个概念，或映射还没补上 —— 见 behavior.js 的 WRITE_COMMANDS；' +
                '缺口清单见 Tsunagou-前端接入-尚未实现清单.md）',
                { url: config.joinUrl('/commands/' + key), method: 'POST' }
            );
            if (!(options && options.silent)) notify.error(error.message);
            return Promise.reject(error);
        }
        const payload = spec.payload ? spec.payload(body || {}) : (body || {});
        /* 少数写入口由中间层掌管（用户档案、登记已有项目）：它们不是 daemon 命令，
           直接按路径发；只有带 kind 的才走命令通道 envelope。*/
        if (spec.path) {
            return api.request(Object.assign({
                method: spec.method || 'POST', path: spec.path, body: payload
            }, options || {}));
        }
        return api.request(Object.assign({
            method: 'POST',
            path: '/commands/' + spec.kind,
            body: {
                command_id: newCommandId(),
                protocol_version: config.protocolVersion,
                schema_bundle_digest: config.schemaBundleDigest,
                payload: payload
            }
        }, options || {}));
    };

    api.post = function (pathOrKey, body, options) {
        /* 写动作统一走命令通道：调用点不用改，键名照旧。*/
        if (Object.prototype.hasOwnProperty.call(WRITE_COMMANDS, pathOrKey)) {
            return api.command(pathOrKey, body, options);
        }
        return api.request(Object.assign({ method: 'POST', path: pathOrKey, body: body }, options || {}));
    };

    /* 直接给后端用：拿到某个键最终会请求的真实地址（便于后端对齐路由）。
       写动作给对应的 /commands/{kind}；后端未提供时返回空串。*/
    api.path = function (key) {
        if (Object.prototype.hasOwnProperty.call(WRITE_COMMANDS, key)) {
            const spec = WRITE_COMMANDS[key];
            if (!spec) return '';
            return spec.path ? config.joinUrl(spec.path) : config.joinUrl('/commands/' + spec.kind);
        }
        return config.joinUrl(resolvePath(key));
    };

    /* ---- 表单 ------------------------------------------------------------ */

    /* 自动提交（失焦即提交）的判定规则：
       1) 命中 .textbox / .textbox2 里的 input；
       2) 不在"按钮提交"的窗口里（向导、添加子 Agent —— 它们有明确的提交按钮；
          Agent 详情窗口的两个输入是只读展示，更没有东西可提交）；
       3) 自己所在的 .item / .uiBlock 里没有按钮。 */
    const AUTOCOMMIT_SELECTOR = '.textbox input, .textbox2 input';
    const AUTOCOMMIT_EXCLUDE = ['#addProj', '#addSubAgent', '#mgrAgentInfo'];

    function inputScope(input) {
        return closest(input, '.item') || closest(input, '.uiBlock') || closest(input, '.secWindow');
    }

    function isAutoCommitInput(input) {
        if (!input || input.dataset.tgCommit === 'manual') return false;
        for (let i = 0; i < AUTOCOMMIT_EXCLUDE.length; i++) {
            if (closest(input, AUTOCOMMIT_EXCLUDE[i])) return false;
        }
        const scope = inputScope(input);
        if (scope && qs('.buttonbox2, .buttonbox', scope)) return false;
        return true;
    }

    /* 给一个 input 起个稳定的名字，作为提交时的字段键 */
    function keyOfInput(input) {
        const win = closest(input, '.secWindow');
        const label = closest(input, '.item') ? qs('.fword', closest(input, '.item')) : null;
        const placeholder = input.getAttribute('placeholder') || '';
        const index = qsa('input', input.parentElement || document).indexOf(input);
        return [
            win ? win.id : 'page',
            toText(label && label.textContent).trim() || placeholder || ('field' + index)
        ].join('.');
    }

    const committedValues = Object.create(null);

    form.keyOf = keyOfInput;
    form.isAutoCommit = isAutoCommitInput;
    form.fields = function (root) { return qsa(AUTOCOMMIT_SELECTOR, resolveEl(root) || document); };

    /* 收集一组输入的值：默认按 DOM 顺序返回数组，传 { byKey: true } 返回对象 */
    form.collect = function (root, options) {
        const opts = options || {};
        const fields = qsa('input', resolveEl(root) || document);
        if (opts.byKey) {
            const result = {};
            fields.forEach(function (input) {
                if (input.type === 'checkbox' || input.type === 'radio') return;
                result[keyOfInput(input)] = toText(input.value).trim();
            });
            return result;
        }
        return fields.filter(function (input) {
            return input.type !== 'checkbox' && input.type !== 'radio';
        }).map(function (input) { return toText(input.value).trim(); });
    };

    /* 按顺序（或按 {键: 值}）回填一组输入 */
    form.fill = function (root, values) {
        const fields = qsa('input', resolveEl(root) || document);
        if (Array.isArray(values)) {
            fields.forEach(function (input, index) {
                if (values[index] !== undefined) input.value = toText(values[index]);
            });
            return fields;
        }
        const source = values || {};
        fields.forEach(function (input) {
            const key = keyOfInput(input);
            if (source[key] !== undefined) input.value = toText(source[key]);
        });
        return fields;
    };

    /* 提交一个输入框：值没变就什么都不做（不重复发请求、也不重复提示） */
    form.commit = function (input, options) {
        const node = resolveEl(input);
        if (!node) return Promise.resolve(null);
        const opts = options || {};
        const value = opts.raw ? toText(node.value) : toText(node.value).trim();
        const key = opts.key || keyOfInput(node);
        const previous = committedValues[key];
        if (value === previous) return Promise.resolve(value);

        const detail = {
            input: node,
            key: key,
            value: value,
            previous: previous,
            window: (closest(node, '.secWindow') || {}).id || '',
            label: opts.label || ''
        };
        committedValues[key] = value;
        emit('form:commit', detail);

        /* 后端可以用 events.on('form:commit') 接管；默认按配置里的地址提交 */
        if (opts.local) {
            if (opts.toast !== false) notify.success({ title: opts.title || '改动已成功保存' });
            return Promise.resolve(value);
        }
        return api.post(opts.path || 'settingSave', { key: key, value: value }, { silent: opts.silent })
            .then(function (result) {
                if (opts.toast !== false) notify.success({ title: opts.title || '改动已成功保存' });
                return result;
            });
    };

    /* 扫描并绑定：给页面上所有"没有提交按钮"的 input 装上失焦提交 */
    form.watch = function (root) {
        const fields = qsa('input', resolveEl(root) || document);
        fields.forEach(function (input) {
            if (input.dataset.tgAutoBound === '1') return;
            if (!isAutoCommitInput(input)) return;
            input.dataset.tgAutoBound = '1';
            input.addEventListener('blur', function () { form.commit(input); });
            input.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') { event.preventDefault(); input.blur(); }
            });
        });
        return fields.length;
    };

    /* 主按钮（"确定"）提交某个容器里的所有输入：用于窗口表单 */
    form.submitByButton = function (root, options) {
        const node = resolveEl(root);
        if (!node) return Promise.resolve(null);
        const opts = options || {};
        const values = form.collect(node, { byKey: true });
        const detail = { window: node.id, values: values, valuesList: form.collect(node) };
        emit('form:submit', detail);
        const path = opts.path || 'settingSave';
        return api.post(path, Object.assign({ window: node.id }, values), { silent: opts.silent });
    };

    /* 清掉"已提交值"的记录（关窗后重置时用） */
    form.resetCommitted = function (key) {
        if (key === undefined) { Object.keys(committedValues).forEach(function (k) { delete committedValues[k]; }); return; }
        delete committedValues[key];
    };

    /* ========================================================================
     * §5 渲染层
     * ------------------------------------------------------------------------
     * 每个 render.xxx(data) 都是"数据进、DOM 出"：内部拼 HTML 字符串，
     * 最后用 util.fill 整体替换某个容器。模板严格照抄 index.html 原有片段，
     * 只用已经存在的类名，因此不需要碰 CSS。
     *
     * 所有动态文本一律经过 esc / nl2br 转义；
     * 需要内嵌 HTML（如胶囊、标签）时由本层的 html 小件生成，不接受外部字符串。
     *
     * 渲染出来的元素会带上 data-* 标记（tg-kind / tg-id），
     * 事件委托靠它们反查数据 —— 这是唯一使用自定义属性的地方，且只加在 JS 生成的节点上。
     * ====================================================================== */

    /* ---- 图标 ------------------------------------------------------------ */

    /* 图标一律用 -l 版（applyThemeImages 会按主题换成 -d 版） */
    const AGENT_ICONS = {
        deepseek: './assets/img/agent/deepseek-l.png',
        codex: './assets/img/agent/codex-l.png',
        claudecode: './assets/img/agent/claudecode-l.png',
        claude: './assets/img/agent/claudecode-l.png',
        opencode: './assets/img/agent/opencode-l.png'
    };

    /* 厂商未知（或压根没有 Agent）时摆的图标：Tsunagou 自己的小标（本来就是 1:1，
       跟头像位一样高）。不拿某个厂商图标冒充 —— 那会让人以为项目里真有个那家的
       Agent。它有 -l/-d 两版，主题切换会跟着换。*/
    const TSUNAGOU_CARD_ICON = './assets/img/logo-little-l.png';

    /* 主题配图的文件名约定：-l 是白色版（深色模式用）、-d 是深色版（浅色模式用）。
       代码里引用的都是 -l 路径，这里按当前主题纠正后缀 —— 否则浅色模式下"新渲染出来"的
       图标会是白色、在浅色底上看不见（只有切主题时 applyThemeImages 才会统一纠正）。*/
    function themedIconPath(path) {
        const text = toText(path);
        if (!/-[ld]\.png$/i.test(text)) return text;
        return text.replace(/-[ld]\.png$/i, currentThemeName === 'light' ? '-d.png' : '-l.png');
    }

    function iconOf(agent) {
        const source = isPlainObject(agent) ? agent.icon : agent;
        const text = toText(source);
        if (/\.(png|jpe?g|svg|webp)$/i.test(text)) return themedIconPath(text);
        return themedIconPath(AGENT_ICONS[text.toLowerCase()] || TSUNAGOU_CARD_ICON);
    }

    /* 选择框里的厂商文字（"DeepSeek Harness" / "Claude Code（待实现）" / "OpenCode" …）→ 图标。
       认不出来（空串、id 缩写、没见过的厂商）就摆 Tsunagou 小标 —— 这是全页唯一一处
       "未知怎么画"的规则，调用点不要再各写一遍（写歪一处就会显示成某家的图标）。
       待实现的那家在选项里带着"（待实现）"后缀，这里按前缀认厂商，照样画它自己的图标。*/
    function agentIconFor(vendor) {
        const text = toText(vendor).toLowerCase();
        if (text.indexOf('claude') >= 0) return AGENT_ICONS.claudecode;
        if (text.indexOf('deepseek') >= 0) return AGENT_ICONS.deepseek;
        if (text.indexOf('opencode') >= 0) return AGENT_ICONS.opencode;
        if (text.indexOf('codex') >= 0) return AGENT_ICONS.codex;
        return TSUNAGOU_CARD_ICON;
    }

    /* ---- 小件 ------------------------------------------------------------ */

    /* 空状态占位：容器里没内容时放它一个。“这里暂时还没有内容”这行字由 CSS 的
       .emptybox::before 生成，JS 只出这个空 div（宽度由 CSS 的 width:100% 撑满）。*/
    const EMPTY_BOX = '<div class="emptybox"></div>';
    /* 同上，给 .boxerbox 用（卡片组里它得冒充一张卡片的宽高占位）*/
    const EMPTY_CARD = { cls: 'emptybox', parts: [] };

    /* 空状态居中：容器里只剩"这里暂时还没有内容"时，那行字贴左看着很孤单。
       做法：容器临时变成"一行、水平居中"，并让那个空盒子**独占一整行**
       （flex-basis 100%）。只加必要的几条，有内容了全部清掉、交回 CSS。
       为什么还要管空盒子本身：它 CSS 里是 width:100%，但在换行的 flex 行里
       一旦被压成内容宽度，容器再居中也没有用 —— 两边一起写才稳。 */
    function centerEmptyState(container, empty) {
        if (!container) return null;
        const box = qs('.emptybox', container);
        container.style.display = empty ? 'flex' : '';
        container.style.justifyContent = empty ? 'center' : '';
        if (box) box.style.flex = empty ? '1 1 100%' : '';
        return container;
    }

    /* Agent 胶囊：<div class="item [cls]"><img class="left"><div class="right">名字</div></div>
       options.identity = true 时才考虑 .id-user / .id-mAgent 这两个配色类
       —— 因为原设计里它们只用在“总路径”那一张表上，别处都是普通胶囊。
       （user:true 用用户图标；mainAgent:true 表示这是主 Agent）*/
    function chipHtml(agent, cls, options) {
        const info = isPlainObject(agent) ? agent : { name: agent };
        const opts = options || {};
        const left = info.user
            ? '<i class="left fa-solid fa-user"></i>'
            : '<img class="left" src="' + esc(iconOf(info)) + '" />';
        const classes = [cls || 'itemS'];
        if (opts.identity) {
            if (info.user) classes.push('id-user');
            else if (info.mainAgent) classes.push('id-mAgent');
        }
        return '<div class="item ' + esc(classes.join(' ')) + '"' +
            (info.id ? ' data-agent-id="' + esc(info.id) + '"' : '') + '>' +
            left + '<div class="right">' + esc(info.name) + '</div></div>';
    }

    function listFieldHtml(agents, cls, options) {
        return '<div class="listfieldbox">' +
            toArray(agents).map(function (agent) { return chipHtml(agent, cls, options); }).join('') +
            '</div>';
    }

    /* 标签：container 默认 .tgBox（自带 flex 行）；传 container:false 则不包容器
       （原设计里“Agent 卡片当前状态”就是 .textZ > .tagZ，中间没有 .tgBox）*/
    function tagHtml(tag) {
        const info = isPlainObject(tag) ? tag : { text: tag };
        const cls = ['tagZ'];
        if (info.ok) cls.push('tagZOK');
        if (info.small) cls.push('tagZS');
        return '<div class="' + cls.join(' ') + '">' + esc(info.text) + '</div>';
    }

    function tagsHtml(tags, options) {
        const opts = options || {};
        const list = toArray(tags).map(function (tag) {
            const info = isPlainObject(tag) ? Object.assign({ small: opts.small }, tag) : tag;
            if (opts.container === 'tagZbox') {
                /* tagZbox 里放的是 span，外层包一个 div.tagZbox */
                const item = tagHtml(info).replace(/^<div class="/, '<span class="')
                    .replace(/<\/div>$/, '</span>');
                return item;
            }
            return tagHtml(info);
        }).join('');
        const container = opts.container === undefined ? 'tgBox' : opts.container;
        return container ? '<div class="' + container + '">' + list + '</div>' : list;
    }

    /* 任务状态：13 种状态的名字由 CSS 的 ::after 生成，JS 只给类名 */
    function stHtml(code) {
        const index = clampNum(Number(code) || 1, 1, 13);
        return '<span class="st st-' + index + '"></span>';
    }

    /* 表格（.tablebox：表头 .th + 行 .tr + 单元格 .colu） */
    function columnsHtml(columns) {
        return toArray(columns).map(function (column) {
            const info = isPlainObject(column) ? column : { text: column };
            return '<div class="colu' + (info.cls ? ' ' + info.cls : '') + '">' + esc(info.text) + '</div>';
        }).join('');
    }

    function cellHtml(cell) {
        if (cell === null || cell === undefined) return '<div class="colu"></div>';
        if (typeof cell === 'string') return '<div class="colu">' + esc(cell) + '</div>';
        const cls = cell.cls ? ' ' + cell.cls : '';
        const body = (cell.html !== undefined) ? cell.html : esc(cell.text);
        return '<div class="colu' + cls + '">' + body + '</div>';
    }

    function tableBoxHtml(cfg) {
        const options = cfg || {};
        const rows = toArray(options.rows);
        const head = options.columns ? '<div class="th">' + columnsHtml(options.columns) + '</div>' : '';
        const body = rows.length ? rows.map(function (row) {
            const attrs = row && row.attrs ? row.attrs : '';
            const cells = (row && row.cells) ? row.cells : row;
            return '<div class="tr"' + attrs + '>' + toArray(cells).map(cellHtml).join('') + '</div>';
        }).join('') : EMPTY_BOX;
        return '<div class="tablebox' + (options.cls ? ' ' + options.cls : '') + '">' + head + body + '</div>';
    }

    /* 键值表（.table：.item > .itemTh + .itemTd） */
    function keyValueTableHtml(items) {
        const list = toArray(items);
        return '<div class="table">' + (list.length ? list.map(function (item) {
            const body = (item.html !== undefined) ? item.html : esc(item.value);
            return '<div class="item"><div class="itemTh">' + esc(item.label) + '</div>' +
                '<div class="itemTd' + (item.active ? ' itemTdActive' : '') + '">' + body + '</div></div>';
        }).join('') : EMPTY_BOX) + '</div>';
    }

    /* 卡片组（.boxerbox，里面是 .item / .itemL / .itemAdd）
       卡片的 attrs 用来挂 data-* 身份标记（JS 生成的节点才允许加）*/
    function boxerHtml(cards, cls) {
        const list = toArray(cards);
        return '<div class="boxerbox' + (cls ? ' ' + cls : '') + '">' +
            (list.length ? list.map(function (card) {
                return '<div class="' + esc(card.cls || 'item') + '"' + (card.attrs || '') + '>' +
                    toArray(card.parts).join('') + '</div>';
            }).join('') : EMPTY_BOX) + '</div>';
    }

    /* 卡片里的小件 */
    function headerHtml(text, cls) {
        return '<p class="header' + (cls ? ' ' + cls : '') + '">' + esc(text) + '</p>';
    }

    function titleHtml(text, tag) {
        return '<' + (tag || 'p') + ' class="title">' + esc(text) + '</' + (tag || 'p') + '>';
    }

    /* 页面标题（tabMain 的直接子级）。CSS 是 .tabMain > .title > .left：
       标题文字要套一层 .left（品牌色标签），右侧 .right 留给工具区（选择框之类）。
       卡片 / 窗口 / 侧栏里的 titleHtml 不是这个结构，别动它们。*/
    function pageTitleHtml(text) {
        return '<div class="title"><p class="left">' + esc(text) + '</p></div>';
    }

    function textZHtml(text) { return '<p class="textZ">' + esc(text) + '</p>'; }

    function textZboxHtml(text) { return '<div class="textZbox">' + nl2br(text) + '</div>'; }

    function timeHtml(text) { return '<p class="textTime">' + esc(text) + '</p>'; }

    function bgTitleHtml(text) { return '<p class="bgTitle">' + esc(text) + '</p>'; }

    function textNHtml(text) { return '<div class="textN">' + nl2br(text) + '</div>'; }

    /* 按钮组：{text, kind:'active'|'important'|'' , action} */
    function buttonsHtml(buttons) {
        return toArray(buttons).map(function (button) {
            const info = isPlainObject(button) ? button : { text: button };
            const cls = ['buttonbox2'];
            if (info.kind === 'active') cls.push('buttonbox2active');
            if (info.kind === 'important') cls.push('buttonbox2important');
            return '<div class="' + cls.join(' ') + '"' +
                (info.action ? ' data-tg-action="' + esc(info.action) + '"' : '') + '>' +
                esc(info.text) + '</div>';
        }).join('');
    }

    function optionHtml(buttons) {
        return '<div class="option">' + buttonsHtml(buttons) + '</div>';
    }

    /* 侧栏里的"字段块"：{title, text} 或 {title, html} 或 {bgTitle}
       注：text 会转义；html 不会（只用来嵌本库生成的小件，别塞用户输入）。*/
    function asideFieldsHtml(fields) {
        return toArray(fields).map(function (field) {
            if (field.bgTitle) return bgTitleHtml(field.bgTitle);
            const head = field.title ? titleHtml(field.title) : '';
            if (field.html !== undefined) return head + field.html;
            if (field.text !== undefined) return head + textNHtml(field.text);
            return head;
        }).join('');
    }

    /* ---- 通用小件对外暴露 ------------------------------------------------ */

    Object.assign(render, {
        icon: iconOf,
        chip: chipHtml,
        listField: listFieldHtml,
        tag: tagHtml,
        tags: tagsHtml,
        status: stHtml,
        table: tableBoxHtml,
        keyValueTable: keyValueTableHtml,
        boxer: boxerHtml,
        buttons: buttonsHtml,
        asideFields: asideFieldsHtml
    });

    /* ---- 左栏：协作项目列表 ---------------------------------------------- */

    const PROJECT_STATUS = {
        working: { cls: 'wking', text: '工作中' },
        preparing: { cls: 'starting', text: '准备中' },
        finished: { cls: 'finished', text: '已完成' }
    };

    /* 左栏列表是否已经收到过后端的数据。
       用途：区分“还没拉到”和“后端确实说一个协作都没有”——
       前者不要出空状态，否则页面刚打开的一瞬间会闪一下“这里暂时还没有内容”。*/
    let projectListLoaded = false;

    /* 卡片上的 Agent 胶囊按 id **现算**名字与图标：
       项目列表与用户档案（昵称/厂商）是启动时并发拉的，谁先回来不定 ——
       烘焙进数据的话，先到的名单会一路显示成 id 缩写。*/
    function cardAgent(agent) {
        const ref = toText(agent && (agent.id || agent.agent_id));
        if (!ref) return agent;
        const probe = { agent_id: ref };
        return { id: ref, name: agentDisplayName(probe), icon: agentIconFor(agentVendor(probe)) };
    }

    /* 卡片上没有主 Agent 时摆的就是 TSUNAGOU_CARD_ICON（见上面"图标"那一节）*/

    /* 卡片的样子。selected 由 render.list 统一判定后传进来 ——
       这里不自己算：否则条目一旦自称 selected、或 id 为空又刚好赶上"没选项目"，
       整列标题就全变成蓝色了（一列里最多只能有一张选中）。*/
    /* 子 Agent 头像一行最多摆 3 个，多出来的收进 `+N` 那个小圆圈里，N 是**没摆出来的**数量。
       别把总数写进去：只有 2 个子 Agent 时会画成"2 个头像 +2"，看起来像有 4 个。*/
    const OTHERS_SHOWN = 3;

    function projectCardHtml(project, selected) {
        const status = PROJECT_STATUS[project.status] || PROJECT_STATUS.working;
        const agents = toArray(project.agents).map(cardAgent);
        const mainAgent = cardAgent(project.mainAgent) || { name: '', icon: TSUNAGOU_CARD_ICON };
        /* 名单可能比中间层报的总数短（它才是权威），所以两者取大的那个当总数。*/
        const declared = Number(project.extra);
        const total = Number.isFinite(declared) ? Math.max(declared, agents.length) : agents.length;
        const shown = Math.min(OTHERS_SHOWN, agents.length);
        const hidden = Math.max(0, total - shown);
        const others = agents.slice(0, shown).map(function (agent) {
            return '<img src="' + esc(iconOf(agent)) + '" />';
        }).join('') + (hidden > 0 ? '<span class="plus">' + esc(hidden) + '</span>' : '');
        return '<div class="projItem' + (selected ? ' projItemSelected' : '') + '" data-project-id="' + esc(project.id) + '">' +
            '<div class="inner">' +
            /* 删除入口：与 .title / .content 平级的 .edit。
               它默认在右上角外面，鼠标落到这张卡片上（.inner:hover）才滑进来 ——
               位置和动画都在 CSS 里，这里只负责把标记摆对。*/
            '<div class="edit"></div>' +
            '<p class="title">' + esc(project.name) + '</p>' +
            '<div class="content">' +
            '<div class="left">' +
            '<div class="mainAgent"><img src="' + esc(iconOf(mainAgent)) + '" />' +
            '<p>' + esc((mainAgent || {}).name) + '</p></div>' +
            '<div class="anotherAgent">' + others + '</div>' +
            '</div>' +
            '<div class="right">' +
            '<p class="' + status.cls + '">' + esc(project.statusText || status.text) + '</p>' +
            '<p class="time">' + esc(project.time) + '</p>' +
            '</div>' +
            '</div>' +
            '</div>' +
            /* 最后这一层是 .projItem 自己的收尾，不能省：少了它，浏览器会把后面每张
               卡片都嵌进前一张里。那样 `.projItemSelected .inner .title` 这条**后代**
               选择器会把选中卡片内部所有卡片的标题一起点亮 —— 表现就是"点一张，下面
               一片跟着高亮"。卡片必须是兄弟节点（同名的几个项目一样适用）。*/
            '</div>';
    }

    /* ---- 左栏排序：偏好记在浏览器本地 -------------------------------------
       “我这台机器想怎么看这个列表”是本机偏好，不占项目里的任何事实，所以存 localStorage。
       三种排序方式里：**名称**是后端给的事实；**查看时间**是"我上次打开它是几点"——
       这是本机记录（后端没有这个概念），没打开过的退回卡片上那个"上次记录"时刻；
       **创建时间**后端目前也没有给这个字段，同样先用记录时刻顶上：等中间层在列表行里
       补一个创建时间，把 projStamp 里那一行换掉即可（不用动别处）。 */
    const PROJ_SORT_KEY = 'tsunagou.console.projSort';
    const PROJ_VIEWED_KEY = 'tsunagou.console.projViewedAt';
    const PROJ_SORT_DEFAULT = { order: 'new', by: 'viewed' };

    function readStoredJson(key, fallback) {
        try {
            const raw = JSON.parse(window.localStorage.getItem(key) || 'null');
            return isPlainObject(raw) ? raw : fallback;
        } catch (error) {
            return fallback;   /* 本地存储读不出来（隐私模式等）就用默认值 */
        }
    }

    let projSort = (function () {
        const stored = readStoredJson(PROJ_SORT_KEY, {});
        const order = stored.order === 'old' ? 'old' : (stored.order === 'new' ? 'new' : PROJ_SORT_DEFAULT.order);
        const by = ['viewed', 'created', 'name'].indexOf(stored.by) >= 0 ? stored.by : PROJ_SORT_DEFAULT.by;
        return { order: order, by: by };
    })();
    let projViewedAt = readStoredJson(PROJ_VIEWED_KEY, {});

    function saveProjSort() {
        try { window.localStorage.setItem(PROJ_SORT_KEY, JSON.stringify(projSort)); } catch (error) { /* 存不下就只在这次会话里生效 */ }
    }

    /* 打开一个项目时记一笔：排序用的"查看时间"就是这么来的（只在本机、只在这台浏览器）。*/
    function rememberProjViewed(projectId) {
        const id = toText(projectId);
        if (!id) return;
        projViewedAt[id] = Date.now();
        try { window.localStorage.setItem(PROJ_VIEWED_KEY, JSON.stringify(projViewedAt)); } catch (error) { /* 同上 */ }
    }

    function stampOf(text) {
        const ms = Date.parse(toText(text));
        return Number.isFinite(ms) ? ms : 0;
    }

    function projStamp(row) {
        const data = row || {};
        const id = toText(data.project_id) || toText(data.id);
        /* 按创建时间：用后端给的 created_at（项目索引里"第一次登记"的时刻）。
           后端没给就退回记录时刻 —— 那时它和"按查看时间"的回退值同源，两种排序结果一样。*/
        if (projSort.by === 'created') {
            return stampOf(data.created_at) || stampOf((data.history || {}).captured_at);
        }
        const local = Number(projViewedAt[id]);
        if (Number.isFinite(local) && local > 0) return local;
        return stampOf((data.history || {}).captured_at);
    }

    function sortProjects(rows) {
        const list = toArray(rows).slice();
        const newestFirst = projSort.order !== 'old';
        list.sort(function (a, b) {
            if (projSort.by === 'name') {
                const diff = toText(a.name).localeCompare(toText(b.name), 'zh-Hans-CN');
                return newestFirst ? -diff : diff;
            }
            const diff = projStamp(a) - projStamp(b);
            return newestFirst ? -diff : diff;
        });
        return list;
    }

    /* ---- 左栏的两个弹出菜单（项目操作 / 排序）-----------------------------
       菜单本身写在 index.html 里（`<section class="selection">`）：CSS 是
       display:none + position:fixed。JS 只做两件事 —— 写 display 开/收，以及把它贴到
       触发它的那个按钮旁边。贴位置要写 left/top：fixed 的弹层脱离文档流，没有别的写法
       能表达"贴在谁旁边"（这是全文件唯一一处这样写行内样式的地方）。
       点别处、按 Esc 都收起来；菜单开着的期间点它自己的项不算"点别处"。*/
    const SELECTION_IDS = ['projMenu', 'sortMenu'];
    let openSelectionId = '';
    let openSelectionAnchor = null;   /* 是哪个键把它打开的：再点同一个键就是收起 */
    let selectionProjectId = '';
    /* 重命名窗口正在改哪个项目（窗口开着的时候记着，确定时用它）。*/
    let renameTargetId = '';

    function closeSelections() {
        SELECTION_IDS.forEach(function (id) { hideEl(byId(id)); });
        openSelectionId = '';
        openSelectionAnchor = null;
    }

    /* 把菜单贴到触发它的那个东西旁边。两种菜单贴法不同：
       · 卡片菜单（#projMenu）：贴在右上角那支笔的**右边**，顶部与**卡片**齐平；
       · 排序菜单（#sortMenu）：贴在被点的设置键下方，右对齐到那个键。
       量尺寸必须在 syncSortMenu() **之后**：第一次打开时对勾是 JS 现加的，
       先量再摆会量到"还没有对勾"的宽高，位置就偏了。 */
    function positionSelection(menu, anchor) {
        const rect = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : null;
        if (!rect) return;
        const width = menu.offsetWidth || 150;
        const height = menu.offsetHeight || 90;
        let left;
        let top;
        if (menu.id === 'projMenu') {
            const card = closest(anchor, '.projItem');
            /* 与"看得见的卡片"上沿齐平：量 .inner —— 它带着外边距，那才是那张卡片真正的框；
               量 .projItem 外层会连着外边距一起算进去，菜单就比卡片高出一截。 */
            const face = card ? qs('.inner', card) : null;
            const faceRect = face && face.getBoundingClientRect ? face.getBoundingClientRect() : null;
            const cardRect = card && card.getBoundingClientRect ? card.getBoundingClientRect() : null;
            left = rect.right + 6;
            top = (faceRect || cardRect || rect).top;
        } else {
            left = rect.right - width;
            top = rect.bottom + 6;
        }
        menu.style.left = Math.max(8, Math.min(left, window.innerWidth - width - 8)) + 'px';
        menu.style.top = Math.max(8, Math.min(top, window.innerHeight - height - 8)) + 'px';
    }

    function openSelection(id, anchor, projectId) {
        const menu = byId(id);
        if (!menu) return null;
        closeSelections();
        if (toText(projectId)) selectionProjectId = toText(projectId);
        displayEl(menu, 'flex');
        openSelectionId = id;
        openSelectionAnchor = anchor || null;
        syncSortMenu();                       /* 先摆对勾（会改变宽高）… */
        positionSelection(menu, anchor);      /* …再量、再贴 */
        return menu;
    }

    /* 同一个触发键再点一次 = 收起（不是"收起又立刻打开"）；点另一个键则挪到那边。*/
    function toggleSelection(id, anchor, projectId) {
        if (openSelectionId === id && openSelectionAnchor === anchor) {
            closeSelections();
            return null;
        }
        return openSelection(id, anchor, projectId);
    }

    /* 排序菜单里那个对勾：挪到当前选择上（HTML 里初始标在哪不重要，以这里为准）。*/
    function syncSortMenu() {
        const menu = byId('sortMenu');
        if (!menu) return;
        qsa('.item[data-sort-order], .item[data-sort-by]', menu).forEach(function (item) {
            let right = qs('.right', item);
            if (!right) {
                right = document.createElement('div');
                right.className = 'right';
                item.appendChild(right);
            }
            const active = toText(item.getAttribute('data-sort-order')) === projSort.order
                || toText(item.getAttribute('data-sort-by')) === projSort.by;
            fill(right, active ? '<i class="fa-solid fa-check"></i>' : '');
        });
    }

    /* ---- 项目搜索（左栏那个搜索条）----------------------------------------
       HTML 挂在**第一个**分组标题下面（见 render.list 里的 titleWithSearch）。CSS 里
       `display:none` 那行是注释掉的，所以它默认可见 —— 初始由这里写 display:none，
       打开时清成空串、交回 CSS。
       打字只做"过滤已经画出来的卡片"，不重画整列：重画会把输入框连同光标一起换掉。
       过滤期间分组标题收起来；一张都不匹配时复用同一个空状态占位符。*/
    const PROJECT_SEARCH_BAR = '<div class="searchBar">' +
        '<div class="inner">' +
        '<div class="icon iconA"></div><input class="left" placeholder="搜索你的项目">' +
        '<div class="icon iconB"></div>' +
        '</div></div>';
    let projQuery = '';
    let projSearchOpen = false;

    function applyProjectFilter() {
        const container = byId('projList') || qs('.secAside .subMgr');
        if (!container) return null;
        const bar = qs('.searchBar', container);
        if (bar) {
            displayEl(bar, projSearchOpen ? '' : 'none');
            const input = qs('.left', bar);
            /* 只在"和状态不一致"时回填（重画之后要补回来）；打字过程中两者一致，不动光标 */
            if (input && toText(input.value) !== toText(projQuery)) input.value = toText(projQuery);
        }
        const query = toText(projQuery).trim().toLowerCase();
        /* 搜索条一打开，分组标题就收起来（不只是"输了字之后"）：位置让给搜索条。*/
        qsa('.wkTitle', container).forEach(function (node) {
            displayEl(node, (projSearchOpen || query) ? 'none' : '');
        });
        let matches = 0;
        qsa('.projItem', container).forEach(function (card) {
            const name = toText(qs('.title', card) && qs('.title', card).textContent).toLowerCase();
            const hit = !query || name.indexOf(query) >= 0;
            if (hit) matches += 1;
            displayEl(card, hit ? '' : 'none');
        });
        /* 一张都不匹配时用同一个空状态占位符；列表自己已经带着一个（真的没有项目）就不再加 */
        const own = qs('.emptybox[data-search-blank]', container);
        const listed = qs('.emptybox:not([data-search-blank])', container);
        if (query && matches === 0 && !listed) {
            if (!own) container.insertAdjacentHTML('beforeend', '<div class="emptybox" data-search-blank="1"></div>');
        } else if (own) {
            own.remove();
        }
        return container;
    }

    render.list = function (projects) {
        const list = sortProjects(toArray(projects));
        const active = list.filter(function (item) { return item.group !== 'done'; });
        const done = list.filter(function (item) { return item.group === 'done'; });
        /* 哪一张是"选中"的：整列一次算清，**最多一张**。
           优先"当前项目"（currentProjectId），没有再看第一条自称 selected 的
           （id 为空的条目一律不算 —— 空 id 对上空的"当前项目"会把整列都点亮）。*/
        const currentId = toText(state.get('currentProjectId'));
        let selectedAt = -1;
        if (currentId) {
            list.forEach(function (item, index) {
                if (selectedAt < 0 && toText(item.id) === currentId) selectedAt = index;
            });
        }
        if (selectedAt < 0) {
            list.forEach(function (item, index) {
                if (selectedAt < 0 && item.selected === true && toText(item.id) !== '') selectedAt = index;
            });
        }
        const card = function (item) {
            return projectCardHtml(item, list.indexOf(item) === selectedAt);
        };
        const groupTitle = function (text) {
            return '<div class="wkTitle"><div class="wkTleft">' + esc(text) + '</div>' +
                '<div class="wkTright">' +
                '<div class="wkTbtn" data-tg-role="project-search"><i class="fa-solid fa-search"></i></div>' +
                '<div class="wkTbtn" data-tg-role="project-sort"><i class="fa-solid fa-cog"></i></div>' +
                '</div></div>';
        };
        /* 空的分组不显示标题，免得出现只有标题没有卡片的空段；
           一个协作都没有时给一个空状态（但数据还没来过就先空着，见 projectListLoaded）。*/
        /* 搜索条挂在**第一个**分组标题下面（"进行中的协作"通常就是第一个）。
           两个分组都为空时不画标题，也就没有搜索条 —— 没有项目可搜。*/
        let searchPlaced = false;
        const titleWithSearch = function (text) {
            const block = groupTitle(text);
            if (searchPlaced) return block;
            searchPlaced = true;
            return block + PROJECT_SEARCH_BAR;
        };
        const html = list.length ?
            (active.length ? titleWithSearch('进行中的协作') + active.map(card).join('') : '') +
            (done.length ? titleWithSearch('已完成的协作') + done.map(card).join('') : '')
            : (projectListLoaded ? EMPTY_BOX : '');
        const container = byId('projList') || qs('.secAside .subMgr');
        fill(container, html);
        /* 重画之后把"正在搜索"的状态贴回去：搜索条显隐、标题显隐、卡片过滤、输入框里的字 */
        applyProjectFilter();
        return container;
    };

    /* ---- 主视图 ---------------------------------------------------------- */

    /* 顶部导航条：.navArea 在 .inner 外面，不属于任何标签页，单独渲染。
       输出的标记与原 index.html 里的静态写法完全一致（名字 + 状态胶囊），
       只是换成由数据驱动，不多不少。*/
    /* 顶部标题那条渐隐（CSS 里 `.navArea .left > p` 的 mask-image）只在文字**确实够长**时
       才该出现：短标题被渐隐，看着像是后面还有字被截掉了。所以这里量一下文字本身的宽度，
       不到 160px 就用行内 `mask-image: none` 把 CSS 那条盖掉；够长就把行内值清掉、交回 CSS。
       量的是文字宽度（Range 框住文本节点），不是容器的宽度 —— 容器宽度不等于"字有多长"。
       什么时候重量：标题重画（render.navbar）、窗口尺寸变化、字体加载完。*/
    const TITLE_MASK_MIN_PX = 160;

    function titleTextWidth(node) {
        if (!node) return 0;
        try {
            const range = document.createRange();
            range.selectNodeContents(node);
            const rect = range.getBoundingClientRect();
            if (rect && rect.width) return rect.width;
        } catch (error) { /* 量不了文字就退回下面两种 */ }
        const box = node.getBoundingClientRect ? node.getBoundingClientRect() : null;
        return Math.max(node.scrollWidth || 0, (box && box.width) || 0);
    }

    function syncTitleMask(node) {
        const target = node || qs('.secProjPanel .navArea .left > p');
        if (!target) return null;
        const value = titleTextWidth(target) >= TITLE_MASK_MIN_PX ? '' : 'none';
        target.style.maskImage = value;
        target.style.webkitMaskImage = value;   /* 老 Chrome 认前缀版；浏览器不认也无害 */
        return target;
    }

    window.addEventListener('resize', function () { syncTitleMask(); });
    if (document.fonts && document.fonts.ready) {
        /* 字体晚一步到齐时文字宽度会变（图标字体尤其）：到齐后重量一次 */
        document.fonts.ready.then(function () { syncTitleMask(); }, function () { /* 忽略 */ });
    }

    render.navbar = function (project) {
        const data = project || {};
        const box = qs('.secProjPanel .navArea .left');
        if (!box) return null;
        fill(box, '<p>' + esc(data.name) + '</p>' +
            '<div class="status' + (data.statusClass ? ' ' + esc(data.statusClass) : '') + '">' +
            esc(data.statusText || '') + '</div>');
        /* 刚写进去的名字：够长才留渐隐（见上面 syncTitleMask） */
        syncTitleMask(qs('p', box));
        return box;
    };

    const TASK_STATE_CLASS = { done: 'taskF', doing: 'taskD', todo: 'task' };

    render.overview = function (project) {
        const data = project || {};
        render.navbar(data);
        const basics = toArray(data.basics).map(function (item) {
            return { label: item.label, value: item.value, active: !!item.active };
        });
        const progress = data.progress || {};
        const plan = toArray(progress.plan).map(function (item) {
            return '<div class="task ' + (TASK_STATE_CLASS[item.state] || 'task') + '">' + esc(item.text) + '</div>';
        }).join('');
        const section = function (title, html) {
            return '<p class="title2">' + esc(title) + '</p>' + html;
        };
        /* 整页一个字都没有时只留一个空状态：否则五个小节会各占一个 240px 的占位块（
           小节的空状态交给 keyValueTableHtml 处理，那是“某个小节单独为空”的情形）。*/
        const hasAny = !!(toText(data.name) || toText(data.description) || basics.length || plan.length ||
            toArray(data.versions).length || toArray(data.stats).length || toArray(data.storage).length ||
            toArray(data.pending).length);
        if (!hasAny) {
            const blank = pageTitleHtml('主视图') + '<p class="title2">项目名称/描述</p>' + EMPTY_BOX;
            fill(byId('pane-overview'), blank);
            return blank;
        }
        const pending = toArray(data.pending);
        /* 这一节只有一种卡片：直接一个 .boxerbox（不带 boxerboxC，也不套 .dataArea）
           —— 按使用者的写法，别自作主张加外层容器。*/
        const pendingSection = pending.length
            ? section('待用户决定', boxerHtml(pending.map(function (item) {
                return {
                    cls: 'item',
                    attrs: ' data-row-id="' + esc(item.id) + '"',
                    parts: [
                        headerHtml(item.title, 'header-ok'),
                        item.detail ? textZHtml(item.detail) : '',
                        item.choices ? titleHtml('可选答复') + textZHtml(item.choices) : '',
                        /* 收尾提案只能在那张卡上答（它没有可选答复，走的是 `project.completion.confirm`
                           那条专属命令）——这里只负责指路，不放一个点了没用的「决定」。*/
                        optionHtml(item.completion
                            ? [{ text: '查看详情', kind: 'active', action: 'ui.tab:acceptance' }]
                            : [
                                { text: '决定', kind: 'active', action: 'decision.resolve:' + esc(item.id) },
                                { text: '稍后', action: 'decision.later:' + esc(item.id) }
                            ])
                    ]
                };
            })))
            : '';
        const html =
            pageTitleHtml('主视图') +
            '<p class="title2">项目名称/描述</p>' +
            '<div class="bgTxt">' + esc(data.name) + '</div>' +
            '<p class="textArea">' + esc(data.description) + '</p>' +
            pendingSection +
            section('基本信息', '<div class="dataArea">' + keyValueTableHtml(basics) + '</div>') +
            section('项目进度', '<div class="dataArea"><div class="statbox">' +
                '<div class="left"><p class="title">总进度</p>' + esc(progress.total) + '</div>' +
                '<div class="right"><p class="title">计划进度</p><div class="inner">' + plan + '</div></div>' +
                '</div></div>') +
            section('项目版本', '<div class="dataArea">' + keyValueTableHtml(data.versions) + '</div>') +
            section('项目统计信息', '<div class="dataArea">' + keyValueTableHtml(data.stats) + '</div>') +
            section('项目数据存储', '<div class="dataArea">' + keyValueTableHtml(data.storage) + '</div>');
        fill(byId('pane-overview'), html);
        return html;
    };

    /* ---- 表格通用小件 ------------------------------------------------------ */

    /* "Agent 胶囊 + 时间"这一格 */
    function agentTimeCell(agent, time) {
        return {
            cls: 'colu-m',
            html: '<div class="colu-t"><div class="citem1">' + listFieldHtml([agent]) + '</div>' +
                (time ? '<div class="citem2">' + esc(time) + '</div>' : '') + '</div>'
        };
    }

    /* ---- Agent 管理 ------------------------------------------------------ */

    /* Agent 的“在哪台机器”标记（跨机器协作）：右上角一句「网络在线 / 网络离线」加一个网络图标。
       规则：
       · **本机接入的 Agent 什么都不画** —— 连那个 `<i>` 图标也不出现，所以本机接入的
         Agent 看起来和加这个功能之前一模一样；
       · **只有子 Agent 可能跨机器** —— 主 Agent 必须和 daemon 在同一台机器上，
         映射那边就不给它这个标记（见 `agents:` 那一块）。
       谁是不是网络接入由**中间层**说，两条通道都行：
       · 随接口带 `network` / `online` 字段（适配层原样传下来）；
       · 运行时推一条：`app.setAgentNetwork(id, online)` 或 dispatch `agent.network`
         （推来的优先于数据里的，见 agentNetworkOf）。
       标记的形状由人定下来（`<p class="right">文字 + <i>`），这里只是把它写进渲染，
       样式全部在 CSS。*/
    function agentNetworkHtml(agent) {
        const info = agentNetworkOf(agent);
        if (!info.network) return '';
        /* 远端自己报的名字里没有，就还是原来那句「网络在线 / 网络离线」——
           本机接入的 Agent 依旧什么都不画。*/
        const where = info.machine ? ' · ' + info.machine : '';
        return '<p class="right">' + (info.online ? '网络在线' : '网络离线') + where +
            '<i class="fa-solid fa-circle-nodes"></i></p>';
    }

    /* 一个 Agent 的网络状态：{network, online, machine}。
       优先级：中间层推来的 > 数据里带的 > 两边都没有（= 本机接入，不画徽标）。
       「自报的机器名」是远端的证据：本机接入那条路从来不写它（见 `agent import`）。*/
    function agentNetworkOf(agent) {
        const record = isPlainObject(agent) ? agent : {};
        /* 主 Agent 必须和 daemon 同机 —— 它永远不是网络接入（中间层推了也不画）*/
        if (record.isMain === true) return { network: false, online: false, machine: '' };
        const machine = toText(record.machine);
        const id = toText(record.agent_id || record.id);
        const pushed = state.get('agentNetwork', {}) || {};
        const known = id ? pushed[id] : undefined;
        /* 推来的布尔值就是“在不在线”；有键 = 这个 Agent 是网络接入的 */
        if (known === true || known === false) return { network: true, online: known, machine: machine };
        if (isPlainObject(known)) {
            return {
                network: known.network === true, machine: machine,
                online: known.network === true && known.online === true
            };
        }
        const network = record.network === true || Boolean(machine);
        return { network: network, online: network && record.online === true, machine: machine };
    }

    /* 徽标重绘：中间层刚推来网络状态时调它（卡片与 Agent 列表两处都画这个标记）。*/
    function renderNetworkBadges() {
        render.agents(state.get('agents', []));
        render.agentWindow(state.get('agentsWindow', []));
    }

    function agentCardHtml(agent) {
        const abilities = function (title, list) {
            if (!toArray(list).length) return '';
            return titleHtml(title) + tagsHtml(list, { });
        };
        return {
            cls: 'item',
            parts: [
                '<div class="header">' + esc(agent.role) + agentNetworkHtml(agent) + '</div>',
                listFieldHtml([{ name: agent.name, icon: agent.icon, id: agent.id }]),
                titleHtml('当前状态'),
                '<div class="textZ">' + tagsHtml([{ text: agent.statusText, ok: agent.statusOk }], { container: false }) + '</div>',
                titleHtml('说明'), textZHtml(agent.desc),
                titleHtml('当前任务'), textZHtml(agent.currentTask),
                abilities('基础能力', agent.basic),
                abilities('运营能力', agent.ops),
                optionHtml(toArray(agent.actions).map(function (action) {
                    return { text: action.text, kind: action.kind, action: action.action };
                }))
            ]
        };
    }

    render.agents = function (agents) {
        const list = toArray(agents);
        /* 末尾那个大加号是"添加子 Agent"的入口；一个 Agent 都没有时先放个空状态（加号留着）。
           项目确认完成之后不再画它：往一个已经收尾的协作里再接入 Agent 没有意义。*/
        const cards = list.length ? list.map(agentCardHtml) : [EMPTY_CARD];
        if (!projectFinished()) cards.push({ cls: 'itemAdd', parts: [] });
        const html = pageTitleHtml('Agent 管理') +
            '<p class="title2">管理现有的 Agent</p>' +
            boxerHtml(cards);
        fill(byId('pane-agents'), html);
        return html;
    };

    /* ---- 任务区 ---------------------------------------------------------- */

    render.tasks = function (tasks) {
        const html = pageTitleHtml('任务区') +
            '<p class="title2">当前子 Agent 的任务清单</p>' +
            tableBoxHtml({
                columns: [{ text: '任务', cls: 'colu-l' }, { text: '状态' },
                    { text: '负责 Agent', cls: 'colu-m' }, { text: '开工条件', cls: 'colu-m' },
                    { text: '改动范围', cls: 'colu-m' }],
                rows: toArray(tasks).map(function (task) {
                    return {
                        attrs: ' data-row-id="' + esc(task.id) + '"',
                        cells: [
                            {
                                cls: 'colu-l',
                                html: '<div class="colu-t"><div class="citem1 lev-active">' + esc(task.title) + '</div>' +
                                    '<div class="citem2">' + esc(task.detail) + '</div></div>'
                            },
                            { html: stHtml(task.status) },
                            agentTimeCell(task.agent, task.time),
                            {
                                /* 开工条件：有就点✓（tagZOK），没有就是灰的短横 —— 两种形状都在 CSS 里。*/
                                cls: 'colu-m colu-cdt',
                                html: toArray(task.conditions).map(function (item) {
                                    return '<span class="tagZ' + (item.ok ? ' tagZOK' : '') + '">' + esc(item.text) + '</span>';
                                }).join('')
                            },
                            { cls: 'colu-m', text: task.scope }
                        ]
                    };
                })
            });
        fill(byId('pane-tasks'), html);
        return html;
    };

    /* ---- 冲突与协商（4 个子标签） ---------------------------------------- */

    function dissentCardHtml(dissent) {
        const understandings = toArray(dissent.understandings).map(function (item) {
            return titleHtml(item.agent + '的理解') + '<p class="textZbox">' + esc(item.text) + '</p>';
        }).join('');
        return {
            cls: 'item',
            attrs: ' data-row-id="' + esc(dissent.id) + '"',
            parts: [
                headerHtml(dissent.title),
                listFieldHtml(dissent.agents, 'itemS'),
                timeHtml(dissent.time),
                titleHtml('影响范围'), textZHtml(dissent.scope),
                understandings,
                optionHtml(toArray(dissent.actions).map(function (action) {
                    return { text: action.text, kind: action.kind, action: action.action };
                }))
            ]
        };
    }

    render.conflicts = function (conflicts) {
        const data = conflicts || {};
        const block = byId('block-conflict');
        if (!block) return null;
        const panels = blockPanels(block);
        if (panels[0]) {
            fill(panels[0], boxerHtml(toArray(data.dissents).map(dissentCardHtml), 'boxerboxC'));
        }
        /* 子标签：0 分歧 · 1 冲突（租约冲突账本）· 2 Agent 间协商（消息与义务只读观测）· 3 契约。
           账本一行 = 一次被拒的租约申请；「处理方案」是后端按**当前**租约与 Attempt
           状态机械推断的，不是谁报上来的（见 container.py 的 conflicts 出口）。*/
        if (panels[1]) {
            fill(panels[1], tableBoxHtml({
                cls: 'tableboxC',
                columns: [{ text: '冲突', cls: 'colu-l' }, { text: '影响范围', cls: 'colu-m' },
                    { text: '相关 Agent', cls: 'colu-m' }, { text: '处理方案', cls: 'colu-l' }],
                rows: toArray(data.conflicts).map(function (item) {
                    return {
                        attrs: ' data-row-id="' + esc(item.id) + '"',
                        cells: [
                            {
                                cls: 'colu-l',
                                html: '<div class="colu-t"><div class="citem1 lev-active">' + esc(item.title) + '</div>' +
                                    '<div class="citem2">' + esc(item.detail) + '</div></div>'
                            },
                            { cls: 'colu-m', text: item.scope },
                            {
                                cls: 'colu-m',
                                html: '<div class="colu-t">' + toArray(item.agents).map(function (agent) {
                                    return '<div class="citem1">' + listFieldHtml([agent]) + '</div>';
                                }).join('') + (item.time ? '<div class="citem2">' + esc(item.time) + '</div>' : '') + '</div>'
                            },
                            { cls: 'colu-l', text: item.solution || '——' }
                        ]
                    };
                })
            }) + (toText(data.note) ? textZHtml(data.note) : ''));
        }
        if (panels[2]) {
            fill(panels[2], tableBoxHtml({
                cls: 'tableboxC',
                columns: [{ text: '收发 Agent', cls: 'colu-m' }, { text: '内容', cls: 'colu-l' },
                    { text: '状态' }, { text: '消息处理情况', cls: 'colu-m' }],
                rows: toArray(data.messages).map(function (item) {
                    return {
                        attrs: ' data-row-id="' + esc(item.id) + '"',
                        cells: [
                            {
                                cls: 'colu-m',
                                html: '<div class="colu-t">' +
                                    '<div class="citem3"><p class="lev-inactive">发件</p> ' + esc(item.from) + '</div>' +
                                    '<div class="citem3"><p class="lev-inactive">收件</p> ' + esc(item.to) + '</div>' +
                                    '</div>'
                            },
                            { cls: 'colu-l', html: '<div class="colu-t">' + esc(item.content) + '</div>' },
                            { html: '<span class="tagZ' + (item.answeredOk ? ' tagZOK' : '') + '">' + esc(item.answered) + '</span>' },
                            {
                                cls: 'colu-m',
                                html: tagsHtml(item.progress, { container: 'tagZbox' })
                            }
                        ]
                    };
                })
            }));
        }
        if (panels[3]) {
            fill(panels[3], boxerHtml(toArray(data.contracts).map(function (contract) {
                return {
                    cls: 'item',
                    attrs: ' data-row-id="' + esc(contract.id) + '"',
                    parts: [
                        headerHtml(contract.title),
                        timeHtml(contract.time),
                        titleHtml('提出 Agent'), listFieldHtml(contract.proposers, 'itemS'),
                        titleHtml('影响范围'), textZHtml(contract.scope),
                        titleHtml('已确认 Agent'), listFieldHtml(contract.confirmed, 'itemS'),
                        titleHtml('未确认 Agent'), listFieldHtml(contract.unconfirmed, 'itemS'),
                        optionHtml([{ text: '查看详情', kind: 'active', action: contract.action || 'contract.detail' }])
                    ]
                };
            }), 'boxerboxC'));
        }
        return true;
    };

    /* ---- 意图与权限审计（2 个子标签） ------------------------------------ */

    render.audit = function (audit) {
        const data = audit || {};
        const block = byId('block-audit');
        if (!block) return null;
        const panels = blockPanels(block);
        const leaseCell = function (lease) {
            return { cls: 'colu-m', html: '<div class="tagZ' + (lease.ok ? ' tagZOK' : '') + '">' + esc(lease.text) + '</div>' };
        };
        if (panels[0]) {
            fill(panels[0], tableBoxHtml({
                cls: 'tableboxC',
                columns: [{ text: 'Agent', cls: 'colu-m' }, { text: '目标', cls: 'colu-m' }, { text: '方式' },
                    { text: '原因', cls: 'colu-l' }, { text: '声明版本' }, { text: '租约', cls: 'colu-m' }],
                rows: toArray(data.intents).map(function (item) {
                    return {
                        attrs: ' data-row-id="' + esc(item.id) + '"',
                        cells: [
                            { cls: 'colu-m', html: listFieldHtml([item.agent]) },
                            { cls: 'colu-m', text: item.target },
                            { text: item.mode },
                            { cls: 'colu-l', text: item.reason },
                            { text: item.version },
                            leaseCell(item.lease)
                        ]
                    };
                })
            }));
        }
        if (panels[1]) {
            const leaseTable = function (title, rows) {
                return '<p class="title3">' + esc(title) + '</p>' + tableBoxHtml({
                    cls: 'tableboxC',
                    columns: [{ text: 'Agent', cls: 'colu-m' }, { text: '批准范围', cls: 'colu-l' },
                        { text: '声明版本' }, { text: '租约', cls: 'colu-m' }],
                    rows: toArray(rows).map(function (item) {
                        return {
                            attrs: ' data-row-id="' + esc(item.id) + '"',
                            cells: [
                                { cls: 'colu-m', html: listFieldHtml([item.agent]) },
                                { cls: 'colu-l', text: item.scope },
                                { text: item.version },
                                leaseCell(item.lease)
                            ]
                        };
                    })
                });
            };
            /* 只列真实拿到的租约：daemon 没把”等着拿“的队列做成出口，
               所以不摆一个永远为空的表（决定 11 砍掉了这一栏）。
               租约冲突不在本页：它在「冲突与协商 → 冲突」里（render.conflicts）。*/
            fill(panels[1], leaseTable('已经获得的租约', data.leases));
        }
        return true;
    };

    /* ---- 工作区 ---------------------------------------------------------- */

    render.workspaces = function (workspaces) {
        const cards = toArray(workspaces).map(function (item) {
            return {
                cls: 'item',
                attrs: ' data-workspace-id="' + esc(item.id) + '"',
                parts: [
                    '<div class="header">' + esc(item.name) + '</div>',
                    titleHtml('修改者'), listFieldHtml([item.agent]),
                    titleHtml('隔离方式'), textZHtml(item.isolation),
                    titleHtml('改动的文件'), textZboxHtml(toArray(item.files).join('\n')),
                    titleHtml('当前状态'), tagsHtml(item.states),
                    titleHtml('补丁'), textZHtml(item.patch)
                ]
            };
        });
        const html = pageTitleHtml('工作区') +
            '<p class="title2">Agent 所做的改动</p>' +
            boxerHtml(cards);
        fill(byId('pane-workspace'), html);
        return html;
    };

    /* ---- 验收与存档点（slug 仍是 acceptance）------------------------------ */

    /* 这一屏原来是两块：「项目验收」和「存档点」。合并的理由是一条因果链 ——
       主 Agent 提收尾（段 1）、任务级的交与验（段 2）、收尾一确认就落成一个存档点（段 3）；
       拆成两栏反而要人在两张卡之间自己找关系。所以它同时要三份数据：
       `acceptance` / `checkpoints` / `checkpointFailures`（后两份从 state 里取，
       谁先到谁先重绘一次，见 dispatch 表）。*/

    /* 存档卡：摘要 + 时间 + 取档原因 + 校验态，外加「校验」。
       `校验` 是 daemon 的真校验（会比对 manifest 与 git 锚点，失败是 409）。*/
    function checkpointCardHtml(item) {
        return {
            cls: 'item',
            parts: [
                headerHtml(item.title),
                item.time ? timeHtml(item.time) : '',
                item.reason ? titleHtml('取档原因') + textZHtml(item.reason) : '',
                optionHtml([{ text: '校验', action: 'checkpoint.verify:' + esc(item.id) }])
            ]
        };
    }

    /* 失败卡：说的是**记账**（那次存档没成），不是存档点。
       错误码是后端的原话，取档原因是当初谁要的 —— 两者都要，否则"没成"没法定位。*/
    function checkpointFailureCardHtml(item) {
        return {
            cls: 'item',
            parts: [
                headerHtml('存档失败'),
                item.time ? timeHtml(item.time) : '',
                titleHtml('失败原因') + textZHtml(item.error + (item.reason ? '（' + item.reason + '）' : '')),
                item.attempts ? textZHtml('已试 ' + item.attempts + ' 次') : '',
                optionHtml([{ text: '重试', kind: 'active', action: 'checkpoint.retry:' + esc(item.id) }])
            ]
        };
    }

    /* 「任务验收情况」的结果格：**只有真验过才给绿色**。
       原来这里恒为绿色 + "已提交 <摘要>"，等于替后端宣布了一个它没说的结论；
       没验过就写"还没验收"，提交本身只作为次要一行放在下面。
       多行内容必须套 `.colu-t`：那一格是 flex 行容器（宽 200px），把几个块直接当兄弟节点摆进去
       会被挤成竖排 —— `.colu-t` 的 flex-direction:column 才是"这一格里叠几行"的写法
       （`.citem1` 主行、`.citem2` 次要行，与 agentTimeCell 同一套）。*/
    function verdictHtml(item) {
        const reviewed = !!item.reviewed;
        const tag = reviewed ? (glossText('review_decision', item.decision) || item.decision) : '还没验收';
        const cls = reviewed && item.decision === 'accepted' ? 'tagZ tagZOK' : 'tagZ';
        const notes = [
            item.result,
            reviewed && item.round ? '第 ' + item.round + ' 轮' + (item.reviewer ? ' · 验收人 ' + item.reviewer : '') : '',
            reviewed && item.reason ? '理由：' + item.reason : ''
        ].filter(Boolean);
        return '<div class="colu-t">' +
            '<div class="citem1"><div class="' + cls + '">' + esc(tag) + '</div></div>' +
            notes.map(function (note) { return '<div class="citem2">' + esc(note) + '</div>'; }).join('') +
            '</div>';
    }

    render.acceptance = function (acceptance) {
        const data = acceptance || {};
        const proposal = data.proposal || {};
        const store = state.get('checkpoints', {}) || {};
        const failures = toArray((state.get('checkpointFailures', {}) || {}).items);
        const html =
            pageTitleHtml('验收与存档点') +
            /* 这一屏是从记录里拿的（daemon 不在了）就先说清楚：验收结果最容易让人
               以为"刚看过"，而记录可能已经是几天前的。*/
            (data.recordDetail ? boxerHtml([{
                cls: 'item', parts: [headerHtml('上次记录'), textZHtml(data.recordDetail)]
            }]) : '') +
            '<p class="title2">项目完成提案</p>' +
            /* 提案与它的答复是一件事的两半：正文是"还差什么"，按钮是「确认完成」。
               没有待决定的提案时整段空 —— 没有对象可确认（后端也要 proposal_id）。*/
            boxerHtml((proposal.title || proposal.text) ? [{
                cls: 'itemL',
                parts: [
                    headerHtml(proposal.title, 'header-ok'),
                    timeHtml(proposal.time),
                    textZboxHtml(proposal.text),
                    optionHtml(toArray(proposal.actions).map(function (action) {
                        return { text: action.text, kind: action.kind, action: action.action };
                    }))
                ]
            }] : []) +
            '<p class="title2">任务验收情况</p>' +
            tableBoxHtml({
                columns: [{ text: 'Agent', cls: 'colu-m' }, { text: '任务', cls: 'colu-l' }, { text: '验收结果', cls: 'colu-m' }],
                rows: toArray(data.taskResults).map(function (item) {
                    return [
                        { cls: 'colu-m', html: listFieldHtml([item.agent]) },
                        { cls: 'colu-l', text: item.task },
                        { cls: 'colu-m', html: verdictHtml(item) }
                    ];
                })
            }) +
            '<p class="title2">最新存档点</p>' +
            boxerHtml(toArray(store.latest).map(checkpointCardHtml).concat(
                /* 主动存档也是一张卡：不摆标题与说明的话，那张卡里只剩一个悬空按钮。
                   项目确认完成之后**不再画这张卡** —— 完工本来就会落一个存档点，
                   再"立即存档"属于只该在做项目时用的动作。*/
                projectFinished() ? [] : [{
                    cls: 'item',
                    parts: [
                        headerHtml('立即存档'),
                        textZHtml('立即将当前状态存档，而不必等待自动存档。'),
                        optionHtml([{ text: '立即存档', kind: 'active', action: 'checkpoint.create' }])
                    ]
                }])) +
            '<p class="title2">历史存档点</p>' +
            boxerHtml(toArray(store.history).map(checkpointCardHtml)) +
            '<p class="title2">存档失败</p>' +
            boxerHtml(failures.map(checkpointFailureCardHtml));
        fill(byId('pane-acceptance'), html);
        return html;
    };

    /* ---- 总路径 ---------------------------------------------------------- */

    /* ────────────────────────────────────────────────────────────────────
       总路径那一屏：标题栏右侧那两个选择框（查看看法 / 图表形态）。
       这一屏整体由 JS 画，选择框跟着一起画，所以结构也在这里发出来 —— 用的是
       index.html 里既有的 .choosebox + .chooseboxOpen 写法（面板按"紧接着的下一个
       兄弟"配对），id 另起一套，别去撞设置窗口里的 uSetCol1。

       选过的值存在 pathChoice 里：每次重画都按它渲染标签，展开状态由
       replayPathChoice() 复原，所以轮询刷屏不会把正在挑的那一项弹掉。
       注意：这两个框目前**只记住选择**，「切换看法 / 换图形态」的实际效果还没接
       —— 等设计定了再接（到时候读 pathChoice 就行）。
       ────────────────────────────────────────────────────────────────── */
    const PATH_CHOICES = [
        /* 「看法」的选项是**现算**的（总视角 + 这个项目的每个 Agent），所以这里不写死；
           见 pathViewOptions()。*/
        { key: 'view', box: 'pathViewBox', panel: 'pathViewPanel' },
        { key: 'shape', box: 'pathShapeBox', panel: 'pathShapePanel',
          options: ['线性时间图', 'DAG路径图'] }
    ];

    /* 看法那一栏存的是 **agent id**（'all' = 总视角）；图形态那一栏存的是选项文字。*/
    const pathChoice = { view: 'all', shape: '线性时间图' };

    /* 视角选项：总视角 + 当前项目里的每个 Agent（主 Agent 用角色名，其余用昵称）。
       没读到时只剩「总视角」—— 不编一堆假 Agent 出来。*/
    function pathViewOptions() {
        const options = [{ key: 'all', text: '总视角' }];
        toArray(state.get('agents', [])).forEach(function (agent) {
            const id = toText(agent && agent.id);
            if (!id) return;
            options.push({
                key: id,
                text: agent.isMain ? '主 Agent 视角' : ((toText(agent.name) || shortId(id)) + ' 视角')
            });
        });
        return options;
    }

    /* 当前选中的那一项。选的那个 Agent 不在了（换了项目 / 名单变了）就静默退回总视角。*/
    function pathViewOption() {
        const list = pathViewOptions();
        const found = list.filter(function (item) { return item.key === pathChoice.view; })[0];
        if (found) return found;
        pathChoice.view = 'all';
        return list[0];
    }

    function pathViewLabel() { return pathViewOption().text; }

    /* 过滤用的 agent id：'' = 总视角（不过滤）*/
    function pathViewAgent() {
        const option = pathViewOption();
        return option.key === 'all' ? '' : option.key;
    }

    /* 「图形态」决定这一屏看哪一种图：线性时间图（.taskFlow，画在 pane 里）还是
       DAG（.dagArea，结构写在 index.html、样式在 dag.css）。两个都只写 display：
       时间图清成 '' 交回 CSS，DAG 显式写它在 dag.css 里的真实显示值 block。*/
    function applyPathMode() {
        const pane = byId('pane-path');
        if (!pane) return null;
        const dagOn = pathChoice.shape === 'DAG路径图';
        const flow = qs('.taskFlow', pane);
        if (flow) flow.style.display = dagOn ? 'none' : '';
        const area = qs('.dagArea', pane);
        if (area) area.style.display = dagOn ? 'block' : 'none';
        if (dagOn) {
            if (!dagGraph) dagSetData({});
            /* 数据没变、画面也画过了 → 不重画（否则每 5 秒把节点全拆了重建，会闪）*/
            if (dagDirty || !dagPainted) dagRender();
        }
        return dagOn;
    }

    function pathTitleHtml() {
        const boxes = PATH_CHOICES.map(function (item) {
            const info = (item.key === 'view')
                ? { label: pathViewLabel(), options: pathViewOptions().map(function (option) { return option.text; }) }
                : { label: pathChoice[item.key], options: item.options };
            return '<div class="choosebox chooseboxD" id="' + item.box + '">' +
                '<div class="left">' + esc(info.label) + '</div>' +
                '<div class="right"></div></div>' +
                '<div class="chooseboxOpen" id="' + item.panel + '">' +
                info.options.map(function (option) {
                    return '<p>' + esc(option) + '</p>';
                }).join('') + '</div>';
        }).join('');
        return '<div class="title"><p class="left">总路径</p>' +
            '<div class="right">' + boxes + '</div></div>';
    }

    /* 重画刚发生时把"哪个框正开着"接回来；没开就什么都不做 */
    function replayPathChoice(openKeys) {
        toArray(openKeys).forEach(function (key) {
            const item = PATH_CHOICES.filter(function (choice) { return choice.key === key; })[0];
            const box = item ? byId(item.box) : null;
            if (box && findCsPanel(box) && !ui.choosebox.isOpen(box)) ui.choosebox.open(box);
        });
    }

    /* 记住用户选的值（框每次重画都是新元素，所以监听挂在 document 上、按 id 认）*/
    function bindPathChoice() {
        document.addEventListener('choosebox:change', function (event) {
            const detail = event.detail || {};
            if (!detail.box || !closest(detail.box, '#pane-path')) return;
            const picked = PATH_CHOICES.filter(function (item) { return detail.box.id === item.box; })[0];
            if (!picked) return;
            if (picked.key === 'view') {
                /* 选择框写的是文字，这里换回 agent id */
                const option = pathViewOptions().filter(function (item) { return item.text === detail.value; })[0];
                pathChoice.view = option ? option.key : 'all';
                /* 看法变了，DAG 的"留哪些节点"也跟着变 —— 数据没动，但要重画一次 */
                dagDirty = true;
                /* 整屏重画一次（标题、时间图一起过），图形态也跟着回来 */
                render.timeline(state.get('timeline', []));
                return;
            }
            pathChoice.shape = detail.value;
            /* 换的是「图形态」就当场换图 */
            applyPathMode();
        });
    }

    render.timeline = function (timeline) {
        /* 重画前先记下哪个选择框正开着，重画后接回来（两处都是新元素）*/
        const openKeys = PATH_CHOICES.filter(function (item) {
            const box = byId(item.box);
            return box && ui.choosebox.isOpen(box);
        }).map(function (item) { return item.key; });
        /* 「看法」选到某个 Agent 时只留他这一路：行按操作人过滤，整段没他就不画那一段
           （阶段是项目自己的，名字与起止不跟着某个 Agent 变）。*/
        const only = pathViewAgent();
        const groups = toArray(timeline).map(function (group) {
            return {
                era: group.era,
                items: toArray(group.items).filter(function (item) {
                    return !only || toText((item.actor || {}).ref) === only;
                })
            };
        }).filter(function (group) {
            return group.items.length;
        });
        const rows = groups.map(function (group) {
            return '<div class="eraTitle">' + esc(group.era) + '</div>' +
                toArray(group.items).map(function (item) {
                    return '<div class="item" data-row-id="' + esc(item.id) + '">' +
                        '<div class="Cit1">' + esc(item.time) + '</div>' +
                        '<div class="Cit2">' + listFieldHtml([actorFor(item.actor)], 'itemS', { identity: true }) + '</div>' +
                        '<div class="Cit2">' + esc(item.task) + '</div>' +
                        '<div class="Cit3">' + esc(item.action) + '</div>' +
                        '</div>';
                }).join('');
        }).join('');
        const html = pathTitleHtml() +
            '<p class="title2">可视化 Agent 的协作过程</p>' +
            /* .taskFlow 是外框，里面的行与表头都放进多出来那层 .inner（`.inner` 是类名，
               结构：.taskFlow > .inner > .header / .eraTitle / .item —— 样式全归 style.css）。*/
            '<div class="taskFlow">' +
            '<div class="inner">' +
            '<div class="header"><div class="Cit1">时间</div><div class="Cit2">操作人</div>' +
            '<div class="Cit2">任务</div><div class="Cit3">操作</div></div>' +
            (rows || EMPTY_BOX) +
            '</div>' +
            '</div>';
        /* .dagArea 是 index.html 里的固定结构（里面的节点与边都是 JS 攒的），
           重画只换它前面那部分：先把它摘下来、画完再挂回末尾，
           它的内容与行内尺寸都不会被冲掉。*/
        const pane = byId('pane-path');
        const area = pane ? qs('.dagArea', pane) : null;
        if (area) area.remove();
        fill(pane, html);
        if (pane && area) pane.appendChild(area);
        replayPathChoice(openKeys);
        applyPathMode();
        return html;
    };

    /* ========================================================================
       总路径 · DAG（任务依赖图）—— 原独立页面 DAG/ 搬进来的一节
       ------------------------------------------------------------------------
       结构（.dagArea > .canvas > svg#edges）在 index.html 的 #pane-path 里，
       样式另起一份 assets/css/dag.css（不与 style.css 合并），行为就是这一段：
       只画 /tasks 出口里 tasks[].blocks 这一层依赖 —— parent_task_id 是委派导航，
       task.edge.add 才是依赖，所以图上只连 blocks。

       数据：中间层 view=tasks 的 sources（tasks / attempts / agents 三份原样数据），
             由 BACKEND_SHAPE.tasks 顺手交给 dagSetData() —— blocks / current_attempt_id /
             block_reason 这些字段在"界面形状"里用不到，被适配层丢掉了。
       显隐：只有标题栏「图形态」选到 DAG路径图 时才显示（applyPathMode）。
       点节点：选中/取消高亮，并按任务号走现有详情通道（openDetail('path', …)）开右侧栏 ——
              DAG 原来那个侧栏不要了，用主页面现有的。

       两条与主页面一致的规矩：显隐只写 display；对外只挂 Tsunagou（这里挂 Tsunagou.dag）。
       尺寸例外：画布只写一个 `min-height`（图有多高就多高），**宽度不定**（跟着 .dagArea 走）；
       节点位置是行内的 `left` / `top`。这些是图的内容本身，不是拿行内样式去补效果。

       区段：§D1 数据→图  §D2 摆位  §D3 渲染  §D4 对外接口
       （前缀 D 是 DAG 的意思，与文件顶上那套 §0…§8 分开，免得搜 §1 撞上"配置·事件·状态"）
       ====================================================================== */
    const DAG_SATISFIED = 'completed';        /* 只有 completed 才算"前置已满足" */
    const DAG_DEAD = ['failed', 'cancelled']; /* 这两个不会自动满足 */
    const DAG_SVG_NS = 'http://www.w3.org/2000/svg';

    /* folded：被折叠起来的任务号（点标题左边那个圆点切换）—— 折叠时节点只剩标题条，
       摆位也跟着变矮（整张图跟着收，这就是那个"缩放"）。
       点一下是**连锁**的：它下游连着的（递归到底）一起折/展 —— 一条链一起收。*/
    const dagOptions = { dir: 'TB', focus: false, showIso: true, sel: null, folded: {} };
    let dagGraph = null;
    let dagBox = null;
    let dagWarned = '';
    let dagSignature = '';    /* 原样数据的指纹：一样就不重画（轮询每几秒来一发）*/
    let dagDirty = true;      /* 需要重画（数据变了，或者还没画过）*/
    let dagPainted = false;

    function dagAreaNode() { return qs('#pane-path .dagArea'); }

    /* 尺寸/间距/配色都从 dag.css 读（写在 .dagArea 上，找不到就退回 :root）——
       改 CSS 不用改 JS。*/
    function dagCss(name) {
        const host = dagAreaNode() || document.documentElement;
        return toText(getComputedStyle(host).getPropertyValue(name));
    }

    function dagNum(name) {
        const value = parseFloat(dagCss(name));
        return isFinite(value) ? value : 0;
    }

    function dagTime(seconds) {
        const stamp = Number(seconds);
        if (!isFinite(stamp) || stamp <= 0) return '';
        const date = new Date(stamp * 1000);
        const pad = function (n) { return (n < 10 ? '0' : '') + n; };
        return (date.getMonth() + 1) + '月' + date.getDate() + '日' + pad(date.getHours()) + ':' + pad(date.getMinutes());
    }

    /* ---- §D1 数据 → 图：列节点、连边、分层、找环 ------------------------- */

    function dagBuildGraph(tasks, attempts, agents) {
        const owners = agentsById(agents);
        const nodes = toArray(tasks).map(function (task) {
            const attempt = toArray(attempts).filter(function (item) {
                return toText(item.attempt_id) === toText(task.current_attempt_id);
            })[0];
            const owner = attempt ? owners[toText(attempt.owner_agent_id)] : null;
            return {
                id: toText(task.task_id),
                title: toText(task.title),
                status: toText(task.status),
                blockReason: toText(task.block_reason),
                parent: toText(task.parent_task_id),
                /* 名字照 Agent 管理那一套解析（用户档案里的昵称），不显示裸 agent_id；
                   ownerId 留着给"看法"过滤用（按 Agent 看只留他负责的任务）*/
                ownerId: attempt ? toText(attempt.owner_agent_id) : '',
                owner: attempt ? (owner ? agentDisplayName(owner) : shortId(attempt.owner_agent_id)) : '',
                startedAt: attempt ? attempt.started_at : null,
                up: [], down: []          /* up＝谁挡着我（前置），down＝我挡着谁（下游）*/
            };
        });
        const byId = {};
        nodes.forEach(function (node) { byId[node.id] = node; });

        let orphanEdges = 0;      /* 指向"不在本页任务名单里"的 id（跨代/别的项目）——如实计数，不硬画 */
        toArray(tasks).forEach(function (task) {
            toArray(task.blocks).forEach(function (targetId) {
                const from = byId[toText(task.task_id)], to = byId[toText(targetId)];
                if (!from || !to || from === to) { orphanEdges += 1; return; }
                if (from.down.indexOf(to) < 0) from.down.push(to);
                if (to.up.indexOf(from) < 0) to.up.push(from);
            });
        });

        /* 分层：最长路径（rank(n) = 0 或 1 + max(rank(前置))）。顺带用三色标记找环 ——
           后端 _validate_dag 不许 blocks 成环，这里是兜底：万一成环，把环上的节点并到
           最后一层，页面照样出得来，不会卡死。*/
        const rank = {};
        const mark = {};                  /* 0 未访问 / 1 在栈上 / 2 完成 */
        const inCycle = {};
        function visit(id) {
            if (mark[id] === 1) { inCycle[id] = true; return 0; }
            if (mark[id] === 2) return rank[id] || 0;
            mark[id] = 1;
            let value = 0;
            byId[id].up.forEach(function (parent) { value = Math.max(value, visit(parent.id) + 1); });
            mark[id] = 2;
            rank[id] = value;
            return value;
        }
        nodes.forEach(function (node) { visit(node.id); });
        if (Object.keys(inCycle).length) {
            const max = Math.max.apply(null, nodes.map(function (node) { return rank[node.id] || 0; }));
            Object.keys(inCycle).forEach(function (id) { rank[id] = max + 1; });
        }

        return { nodes: nodes, byId: byId, rank: rank, cycle: Object.keys(inCycle), orphanEdges: orphanEdges };
    }

    /* ---- §D2 摆位：分层 → 同层次序 → 坐标（尺寸全从 CSS 变量读）---------- */

    function dagLayout(graph) {
        const dir = dagOptions.dir;       /* 'TB'（上→下，默认）或 'LR'（左→右）*/
        const W = dagNum('--node-w'), H = dagNum('--node-h');
        const GX = dagNum('--gap-x'), GY = dagNum('--gap-y'), PAD = dagNum('--pad');

        /* 折叠的节点矮一截，所以高度得逐个算（同一层里可能有的折了、有的没折）。
           量一次就够 —— 同一次摆位里折叠的节点一样高。*/
        let foldedH = 0;
        const heightOf = function (node) {
            if (!dagOptions.folded[node.id]) return H;
            if (!foldedH) foldedH = dagFoldHeight(H);
            return foldedH;
        };

        const visible = graph.nodes.filter(function (node) {
            if (!dagViewAllows(node)) return false;
            return dagOptions.showIso || node.up.length || node.down.length;
        });
        const shown = {};
        visible.forEach(function (node) { shown[node.id] = true; });

        /* 同一层里的先后：**按 /tasks 给的顺序**（也就是创建顺序）—— 稳定、可预期，
           不做重心平衡那一套。想更"顺眼"可以之后换成按前置的平均位置排。*/
        const layers = {};
        visible.forEach(function (node) {
            const at = graph.rank[node.id] || 0;
            (layers[at] = layers[at] || []).push(node);
        });
        const ranks = Object.keys(layers).map(Number).sort(function (a, b) { return a - b; });

        /* 主方向（TB 是纵、LR 是横）一层占多厚；交叉方向一层铺多长 */
        const rankMain = function (row) {
            if (dir === 'LR') return W;
            return row.reduce(function (max, node) { return Math.max(max, heightOf(node)); }, 0);
        };
        const rowCross = function (row) {
            if (dir === 'TB') return row.length * W + (row.length - 1) * GX;
            let span = 0;
            row.forEach(function (node, index) {
                span += (index ? GY : 0) + heightOf(node);
            });
            return span;
        };

        const starts = {};                /* 每层在主方向的起点 */
        let main = 0;                     /* 主方向的长度（到最后一层的末尾）*/
        let cross = 0;                    /* 交叉方向的最大长度 */
        ranks.forEach(function (rank, index) {
            starts[rank] = main;
            main += rankMain(layers[rank]) + (index === ranks.length - 1 ? 0 : GY);
            cross = Math.max(cross, rowCross(layers[rank]));
        });

        const boxes = {};
        ranks.forEach(function (rank) {
            const row = layers[rank];
            let at = PAD + (cross - rowCross(row)) / 2;      /* 每层居中 */
            row.forEach(function (node) {
                const h = heightOf(node);
                boxes[node.id] = dir === 'TB'
                    ? { x: at, y: PAD + starts[rank], w: W, h: h }
                    : { x: PAD + starts[rank], y: at, w: W, h: h };
                at += (dir === 'TB' ? W + GX : h + GY);
            });
        });
        const depth = PAD + main;
        return {
            boxes: boxes, shown: shown,
            width: dir === 'TB' ? cross + PAD * 2 : depth + PAD,
            height: dir === 'TB' ? depth + PAD : cross + PAD * 2
        };
    }

    /* 折叠后的高度：只剩标题条那一行。两个来源，优先 CSS ——
       · dag.css 里写了 `--node-h-fold` → 用它（你说了算）；
       · 没写就量：临时挂一个"只有标题条、高度交给内容"的同款节点，量完就摘。*/
    function dagFoldHeight(fallback) {
        const declared = dagNum('--node-h-fold');
        if (declared > 0) return declared;
        const canvas = byId('canvas');
        if (!canvas) return fallback;
        const probe = document.createElement('div');
        probe.className = 'node';
        probe.style.height = 'auto';
        probe.style.visibility = 'hidden';
        probe.innerHTML = '<div class="t">　</div>';
        canvas.appendChild(probe);
        const measured = probe.getBoundingClientRect().height;
        probe.remove();
        return measured > 0 ? Math.round(measured) : fallback;
    }

    /* "看法"选到某个 Agent 时，只留他负责的任务（节点）。总视角不过滤。
       过滤放在摆位这一层，于是边、居中、空状态都自动跟着变。*/
    function dagViewAllows(node) {
        const only = pathViewAgent();
        return !only || node.ownerId === only;
    }

    /* 一个节点的"下游链"：它挡着的那些，递归到底（连锁折叠就折这一串）。
       顺着 down（我挡着谁）走、不看 up —— 只往下游连；成环的兜底：seen 挡回边。*/
    function dagFoldChain(id) {
        const seen = {};
        const chain = [];
        (function walk(one) {
            if (!one || seen[one]) return;
            seen[one] = true;
            chain.push(one);
            const node = dagGraph ? dagGraph.byId[one] : null;
            if (node) node.down.forEach(function (next) { walk(next.id); });
        })(toText(id));
        return chain;
    }

    /* 折叠/展开一个节点（标题左边那个圆点是开关）。返回折叠后的状态。
       默认**连锁**：它下游连着的（递归到底）一起跟着折/展 —— 点中间那个，下面那截也收。
       只想动这一个就传 cascade = false（Tsunagou.dag.toggleFold(任务号, false)）。*/
    function dagToggleFold(taskId, cascade) {
        const id = toText(taskId);
        if (!id) return null;
        const fold = !dagOptions.folded[id];      /* 这一次是折还是展 */
        const chain = (cascade === false) ? [id] : dagFoldChain(id);
        chain.forEach(function (one) {
            if (fold) dagOptions.folded[one] = true;
            else delete dagOptions.folded[one];
        });
        dagRender();
        return !!dagOptions.folded[id];
    }

    /* 判断这次点的是不是"标题左边那个圆点"。
       圆点是 CSS 的 ::before（\f111）—— **不占 DOM**，所以只能按位置认：横向落在
       [标题行左内边距，左内边距 + 圆点宽] 之内就算点到它。圆点宽按它的 font-size 估
       （Font Awesome 的字形大约 1em），右边多给 6px 容错。
       圆点长在**每个**节点的标题行上（dag.css 的 .node .t::before）—— 选没选中都能折。*/
    function dagHitFoldDot(event) {
        const title = closest(event.target, '.t');
        if (!title) return false;
        const dot = getComputedStyle(title, '::before');
        if (!dot || !dot.content || dot.content === 'none' || dot.content === 'normal') return false;
        const style = getComputedStyle(title);
        const size = parseFloat(dot.fontSize) || parseFloat(style.fontSize) || 14;
        const padding = parseFloat(style.paddingLeft) || 0;
        const offset = event.clientX - title.getBoundingClientRect().left;
        return offset >= 0 && offset <= padding + size + 6;
    }

    /* 边的两端：从上边中点出发到下边中点（LR 时换成左右边中点），画一条三次贝塞尔的弧 */
    function dagEdgePath(a, b, dir) {
        let x1, y1, x2, y2;
        if (dir === 'TB') {
            x1 = a.x + a.w / 2; y1 = a.y + a.h;
            x2 = b.x + b.w / 2; y2 = b.y;
            const dy = Math.max(24, (y2 - y1) / 2);
            return 'M' + x1 + ',' + y1 + ' C' + x1 + ',' + (y1 + dy) + ' ' + x2 + ',' + (y2 - dy) + ' ' + x2 + ',' + y2;
        }
        x1 = a.x + a.w; y1 = a.y + a.h / 2;
        x2 = b.x; y2 = b.y + b.h / 2;
        const dx = Math.max(24, (x2 - x1) / 2);
        return 'M' + x1 + ',' + y1 + ' C' + (x1 + dx) + ',' + y1 + ' ' + (x2 - dx) + ',' + y2 + ' ' + x2 + ',' + y2;
    }

    /* ---- §D3 渲染：节点是绝对定位的 div，边是底层 SVG -------------------- */

    /* 箭头：四种颜色各一个 marker（SVG 的 marker 不吃 currentColor，所以显式备好）。
       颜色与四条边同源 —— 直接读 style.css 那套变量（dag.css 不再自带配色），
       改配色只改 style.css 的 :root。*/
    function dagMarkers() {
        const defs = document.createElementNS(DAG_SVG_NS, 'defs');
        const arrow = function (id, color) {
            return '<marker id="' + id + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">' +
                '<path d="M0,0 L10,5 L0,10 z" fill="' + color + '"/></marker>';
        };
        defs.innerHTML = arrow('dagArrow', dagCss('--col-5') || '#595959') +
            arrow('dagArrowOk', dagCss('--col-7') || '#C9C9C9') +
            arrow('dagArrowDead', dagCss('--active-col') || '#ff793d') +
            arrow('dagArrowHot', dagCss('--brand-col-2') || '#118ddf');
        return defs;
    }

    function dagRender() {
        const canvas = byId('canvas');
        const svg = byId('edges');
        if (!dagAreaNode() || !canvas || !svg || !dagGraph) return null;

        const hasNode = dagGraph.nodes.length > 0;
        dagBox = dagLayout(dagGraph);
        /* 画布**不定宽**：它是块级元素，宽度就跟着 .dagArea（也就是跟着窗口）走；
           图比画布宽时靠 .canvas 自己的滚动条 —— 节点的绝对定位会把滚动区撑出来。
           高度只给一个下限（图有多高就多高），尽量不出现内部纵向滚动条。

           SVG **不设 viewBox**：边的坐标就是像素，和节点的 left/top 是同一套坐标系
           （两者都以 .canvas 的 padding box 为原点）。所以画布多宽、有没有滚动条、
           窗口怎么缩放，边和节点都严丝合缝 —— 以前 `svg { width:100% }` + viewBox
           会把边按画布尺寸缩放，滚动条一出现（少 7px）就偏几像素。*/
        canvas.style.width = '';
        canvas.style.minWidth = '';
        canvas.style.minHeight = hasNode ? dagBox.height + 'px' : '';
        svg.removeAttribute('viewBox');
        canvas.className = 'canvas' + (dagOptions.focus && dagOptions.sel ? ' focus' : '');

        /* 画不出来的东西如实说，不静默：成环（后端不许发生）、跨名单的边。
           另一句“有任务但彼此没有依赖”要等 shownCount / anyEdge 算完才能决定，
           所以统一在节点画完之后发一次（见下面 dagNotice）。
           同一句话不重复刷屏 —— 内容变了才提醒。*/
        const notes = [];
        if (dagGraph.cycle.length) notes.push('依赖成环（后端不许 blocks 成环，这是兜底显示）：' + dagGraph.cycle.join('、'));
        if (dagGraph.orphanEdges) notes.push('有 ' + dagGraph.orphanEdges + ' 条依赖指向不在本页任务名单里的 id，未画');

        /* --- 节点 --- */
        qsa('.node, .empty', canvas).forEach(function (el) { el.remove(); });
        dagGraph.nodes.forEach(function (node) {
            if (!dagBox.shown[node.id]) return;
            const at = dagBox.boxes[node.id];
            const folded = !!dagOptions.folded[node.id];
            const el = document.createElement('div');
            /* fold 类留给 CSS 用（想让圆点换个样子、或者自己定折叠高度就用它）；
               折叠时高度得写死一个 —— CSS 里 .node 是固定高，不覆盖就白折了。*/
            el.className = 'node' + (folded ? ' fold' : '');
            el.style.left = at.x + 'px';
            el.style.top = at.y + 'px';
            if (folded) el.style.height = at.h + 'px';
            el.setAttribute('data-task-id', node.id);
            el.innerHTML =
                '<div class="t" title="' + esc(node.title) + '">' + esc(node.title) + '</div>' +
                (folded ? '' :
                    '<div class="m">' + esc(node.owner || '还没有负责人') +
                    (node.startedAt ? ' · ' + esc(dagTime(node.startedAt)) : '') + '</div>' +
                    '<div class="s"><span class="st st-' + (TASK_STATUS_NUMBER[node.status] || 1) + '"></span>' +
                    (node.blockReason ? '<span class="m">' + esc(node.blockReason.split(':')[0]) + '</span>' : '') +
                    '</div>');
            canvas.appendChild(el);
        });
        /* 空状态要说清楚是哪一种：没任务 / 这个视角没他的任务。
           **不能**在“有节点但没依赖”时再摆这块 —— .empty 是画布里一个流转内的块，
           而节点是绝对定位的，两者同时存在就会叠在一起（曾经“都是独立任务”那句话
           正好压在第一个节点上）。那句话改由下面的 dagNotice 说。*/
        const shownCount = Object.keys(dagBox.shown).length;
        const anyEdge = dagGraph.nodes.some(function (from) {
            if (!dagBox.shown[from.id]) return false;
            return from.down.some(function (to) { return dagBox.shown[to.id]; });
        });
        if (!hasNode || !shownCount) {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.textContent = !hasNode ? '这个项目还没有任务。'
                : ('这个视角没有任务：' + pathViewLabel() + ' 没有负责的任务。');
            canvas.appendChild(empty);
        }
        /* 图已经画出来了，其余的就用通知说，不往画布上再摆字。
           成环/跨名单是故障（warn），“任务之间本来就没有依赖”只是陈述（info）。*/
        if (hasNode && shownCount && !anyEdge) notes.push('这个项目的任务之间还没有依赖（都是独立任务）。');
        const signature = notes.join(' | ');
        if (signature && signature !== dagWarned) {
            dagWarned = signature;
            if (dagGraph.cycle.length || dagGraph.orphanEdges) notify.warn('DAG 图：' + notes.join('；'));
            else notify.info('DAG 图：' + notes.join('；'));
        }
        if (!signature) dagWarned = '';

        /* --- 边 --- */
        while (svg.firstChild) svg.removeChild(svg.firstChild);
        svg.appendChild(dagMarkers());
        const sel = dagOptions.sel;
        const related = function (id) {
            const node = sel ? dagGraph.byId[sel] : null;
            if (!node) return false;
            return node.down.some(function (item) { return item.id === id; }) ||
                node.up.some(function (item) { return item.id === id; });
        };
        dagGraph.nodes.forEach(function (from) {
            if (!dagBox.shown[from.id]) return;
            from.down.forEach(function (to) {
                if (!dagBox.shown[to.id]) return;
                /* "满不满足"看的是**前置**（from）的状态：completed 才算满足；
                   failed/cancelled 不会自动满足；其余算还没满足。*/
                const edgeState = from.status === DAG_SATISFIED ? 'ok'
                    : (DAG_DEAD.indexOf(from.status) >= 0 ? 'dead' : 'pending');
                const hot = !!sel && (from.id === sel || to.id === sel);
                const path = document.createElementNS(DAG_SVG_NS, 'path');
                path.setAttribute('d', dagEdgePath(dagBox.boxes[from.id], dagBox.boxes[to.id], dagOptions.dir));
                path.setAttribute('class', 'edge ' + edgeState + (hot ? ' hot' : (sel && !hot ? ' dim' : '')));
                path.setAttribute('marker-end', 'url(#' + (hot ? 'dagArrowHot' : edgeState === 'ok' ? 'dagArrowOk'
                    : edgeState === 'dead' ? 'dagArrowDead' : 'dagArrow') + ')');
                path.appendChild(document.createElementNS(DAG_SVG_NS, 'title')).textContent =
                    from.title + ' → ' + to.title + '（' + (edgeState === 'ok' ? '前置已满足'
                        : edgeState === 'dead' ? '前置失败/取消，不会自动满足' : '前置还没满足') + '）';
                svg.appendChild(path);
            });
        });

        /* 节点上的高亮类（选中、相关、变暗）*/
        qsa('.node', canvas).forEach(function (el) {
            const id = el.getAttribute('data-task-id');
            if (!sel) { el.classList.remove('sel', 'rel', 'dim'); return; }
            el.classList.toggle('sel', id === sel);
            el.classList.toggle('rel', id !== sel && related(id));
            el.classList.toggle('dim', id !== sel && !related(id));
        });
        dagDirty = false;
        dagPainted = true;
        return dagBox;
    }

    /* ---- §D4 对外接口（挂 Tsunagou.dag；页面上没有别的全局）-------------- */

    /* 换数据：中间层 view=tasks 的 sources 原样递进来即可（其它视图的 raw 也认，
       出口不在里面就是空图）。选中的任务还在名单里就留着 —— 轮询每几秒来一次，
       别把用户点开的高亮刷掉。*/
    function dagSetData(sources) {
        const source = isPlainObject(sources) ? sources : {};
        const next = {
            tasks: sourceItems(source, 'tasks'),
            attempts: sourceItems(source, 'attempts'),
            agents: sourceItems(source, 'agents')
        };
        /* 轮询每几秒来一发，数据没变就别重画：重画会把节点全拆了重建 —— 会闪，
           也会打断 hover 与过渡。指纹一样就只把引用换掉，不动画面。*/
        const signature = JSON.stringify(next);
        if (signature === dagSignature) return dagGraph;
        dagSignature = signature;
        dagGraph = dagBuildGraph(next.tasks, next.attempts, next.agents);
        dagDirty = true;
        if (dagOptions.sel && !dagGraph.byId[dagOptions.sel]) dagOptions.sel = null;
        /* 折叠状态也跟着名单清一遍：不在这个项目里的任务号留着只会越积越多 */
        Object.keys(dagOptions.folded).forEach(function (id) {
            if (!dagGraph.byId[id]) delete dagOptions.folded[id];
        });
        return dagGraph;
    }

    /* 选中/取消一个任务（图上的高亮）*/
    function dagSelect(taskId) {
        const id = toText(taskId);
        dagOptions.sel = (dagOptions.sel === id) ? null : id;
        dagRender();
        return dagOptions.sel;
    }

    Tsunagou.dag = {
        version: '0.1.0',
        options: dagOptions,
        setData: dagSetData,
        render: dagRender,
        buildGraph: dagBuildGraph,      /* 只想要"数据 → 图"的话，单独调它也行 */
        layout: dagLayout,
        select: dagSelect,
        toggleFold: dagToggleFold,      /* 折叠/展开（标题左边那个圆点就是它）；默认连锁下游，传 false 只动这一个 */
        folded: function () { return Object.keys(dagOptions.folded); }
    };

    /* ---- 侧栏面板 -------------------------------------------------------- */

    render.aside = function (slug, section, fields, options) {
        const node = tabAside(slug);
        if (!node) return null;
        const sections = asideSections(node);
        const index = clampNum(Number(section) || 0, 0, Math.max(sections.length - 1, 0));
        const target = sections[index];
        if (!target) return null;
        fill(target, toArray(fields).length ? asideFieldsHtml(fields) : EMPTY_BOX);
        const title = (options && options.title) || (fields && fields.title);
        if (title) setAsideTitle(node, title);
        return target;
    };

    /* Agent 列表窗口 / Agent 详情窗口 */
    /* 列表/详情里那个"（短号）"：静态样例写的是「DeepSeek Harness（054）」，即昵称加一个
       能区分同名 Agent 的号。号取 agent_id 的**尾部** —— 前面是接入时间戳，同一毫秒里
       接入的两个 Agent 前缀一模一样，尾部才是随机的那个（a-054 这种写法就还原成 054）。*/
    function agentTagOf(agentId) {
        const text = toText(agentId);
        if (!text) return '';
        const tail = text.slice(text.lastIndexOf('-') + 1);
        return tail.length > 4 ? tail.slice(-4) : tail;
    }

    function agentTitleOf(agent) {
        const probe = { agent_id: toText(agent && agent.agent_id) };
        const name = agentDisplayName(probe);
        const tag = agentTagOf(probe.agent_id);
        return (tag && name !== tag) ? (name + '（' + tag + '）') : name;
    }

    /* 窗口标题里那个图标（静态 HTML 里已有的 <i>）要留着，只换它后面那截文字 ——
       直接写 textContent 会把图标一起擦掉。*/
    function setWindowTitleText(node, text) {
        if (!node) return;
        for (let i = node.childNodes.length - 1; i >= 0; i--) {
            if (node.childNodes[i].nodeType === 3) node.removeChild(node.childNodes[i]);
        }
        node.appendChild(document.createTextNode(toText(text)));
    }

    render.agentWindow = function (agents) {
        const container = qs('#mgrAgent .inner');
        if (!container) return null;
        const list = toArray(agents);
        /* 名字与图标按 id 现算（与左栏卡片同一个道理）：名单和用户档案是并发拉回来的，
           谁先到不定，烘焙进数据的话会先显示成 id 缩写。*/
        fill(container, '<div class="table">' + (list.length ? list.map(function (agent) {
            const probe = { agent_id: toText(agent.agent_id) };
            return '<div class="item" data-agent-id="' + esc(agent.id) + '">' +
                '<div class="title"><p class="left"><img src="' + esc(iconOf(agentIconFor(agentVendor(probe)))) + '" />' +
                esc(agentTitleOf(probe)) + '</p>' + agentNetworkHtml(agent) + '</div>' +
                '<div class="content">' +
                '<div class="txtBlock"><div class="left">协作</div><div class="right">' + esc(agent.project) + '</div></div>' +
                '<div class="txtBlock"><div class="left">任务</div><div class="right">' + esc(agent.task) + '</div></div>' +
                '</div></div>';
        }).join('') : EMPTY_BOX) + '</div>');
        /* 一个 Agent 都没有时，把那行"这里暂时还没有内容"水平居中（有内容就交回 CSS）*/
        centerEmptyState(qs('.table', container), !list.length);
        return container;
    };

    /* Agent 详情窗口：项目/任务是后端持有的协作事实（只读）；
       **昵称可以改**（它是本机用户档案里的东西，不是协作事实）。
       厂商不单列一栏 —— 窗口标题与胶囊上的 logo 已经说明它来自哪个宿主，
       而且那个值是按 id 从用户档案现算的，不需要写出来让人改。
       昵称是窗口里的第一个文本框；窗口上另存了 agent_id 与"打开时的昵称"，
       确定时用它决定要不要真发一次保存。*/
    render.agentInfoWindow = function (agent) {
        const node = byId('mgrAgentInfo');
        if (!node) return null;
        const data = agent || {};
        const agentId = toText(data.agent_id || data.id);
        const nickname = toText(data.nickname) || agentDisplayName({ agent_id: agentId });
        const titleNode = qs('.titleBar .title', node);
        if (titleNode) setWindowTitleText(titleNode, agentTitleOf(data) || 'Agent 详细信息');
        /* 记下是谁：没有 agent_id 就没地方存昵称（保存时会如实拒绘）*/
        node.setAttribute('data-agent-id', agentId);
        node.setAttribute('data-nickname', nickname);
        /* 这个窗口的版式是「标签 + 值」自上而下排（.title2 / .textbox2 / .dspText2），
           没有 .item、也没有 .fword，所以按位置回填而不是按标签文字：
           唯一那个输入框是昵称，四个 .dspText2 依次是项目、任务、在哪台机器、这台机器的限制。*/
        form.fill(node, [nickname]);
        const shown = qsa('.dspText2', node);
        if (shown[0]) shown[0].textContent = toText(data.project);
        if (shown[1]) shown[1].textContent = toText(data.task);
        /* 跨机器才有「在哪台机器 / 这台机器的限制」这两行：
           有自报的机器名就是远端（本机接入从来不写它）。本机接入的 Agent 连标题都不出现，
           与加这个功能之前一模一样。 */
        const info = agentNetworkOf(data);
        const record = isPlainObject(data) ? data : {};
        const machine = toText(record.machine || info.machine);
        const copyPath = toText(record.copy_path);
        const remote = Boolean(machine) || info.network === true;
        [
            { title: byId('agentInfoMachineTitle'), value: byId('agentInfoMachine'), text: machine },
            { title: byId('agentInfoCopyTitle'), value: byId('agentInfoCopy'),
              text: copyPath ? (copyPath + (toText(record.copy_baseline) ? '（' + toText(record.copy_baseline) + '）' : '')) : '' },
            { title: byId('agentInfoLimitsTitle'), value: byId('agentInfoLimits'),
              text: remote ? remoteLimitsText(copyPath) : '' }
        ].forEach(function (row) {
            const visible = Boolean(remote && toText(row.text));
            [row.title, row.value].forEach(function (target) {
                if (target) target.style.display = visible ? '' : 'none';
            });
            if (visible && row.value) row.value.textContent = toText(row.text);
        });
        return node;
    };

    /* 远端那台机器做不到/做得到什么，各一句人话。唤醒是本机机制（主机叫不醒别的机器上的窗口），
       永远做不到；文件任务要看它有没有报过自己的代码副本（D192）—— 报了就以"外部准备"的形态
       让它做，但证据是它**自报**的（主机读不到那份副本，也就不出清单）。*/
    function remoteLimitsText(copyPath) {
        if (toText(copyPath)) {
            return '叫不醒它：消息等它自己来取；文件活能做，但证据是它自报的（主机不读那份副本）';
        }
        return '叫不醒它：消息等它自己来取；没报代码副本，只做不需要文件的活（要文件活请在主机上做）';
    }

    /* 设置窗口：把值回填到控件（现在只剩"颜色主题"一项）。
       回填一律走 silent，否则会被 choosebox:change 当成用户操作。*/
    render.settings = function (settings) {
        const data = settings || {};
        if (data.theme) ui.choosebox.setValue(qs('#uSet1 .choosebox'), data.theme, { silent: true });
        return data;
    };

    /* 侧栏细节内容的专用渲染器（点击内容时调用） */
    render.taskDetail = function (task) {
        const data = task || {};
        return render.aside('tasks', 0, [
            { title: '任务', text: data.title },
            { title: '当前状态', html: '<div class="textN"><div class="' + (data.statusClass || 'status-start') + '">' + esc(data.statusText) + '</div></div>' },
            { title: '负责 Agent', text: (data.agent || {}).name },
            { title: '理解报告', text: data.report },
            /* 开工条件在表格里是✓/短横的小标签，这里用同样的两个记号写成一行文字 */
            { title: '开工条件', text: toArray(data.conditions).map(function (item) {
                return item && typeof item === 'object' ? ((item.ok ? '✓' : '—') + item.text) : toText(item);
            }).join('  ') },
            { title: '改动范围', text: data.scope },
            /* 详情比表格细一级：这里给到毫秒 */
            { title: '时间', text: data.timePrecise || data.time }
        ], { title: '任务细节' });
    };

    render.dissentDetail = function (dissent) {
        const data = dissent || {};
        const parts = [
            { bgTitle: data.title },
            { title: '参与 Agent', html: listFieldHtml(data.agents, 'itemS') },
            /* 详情比表格细一级：这里给到毫秒 */
            { title: '时间', text: data.timePrecise || data.time },
            { title: '影响范围', text: data.scope }
        ];
        toArray(data.understandings).forEach(function (item) {
            parts.push({ title: item.agent + '的理解', text: item.text });
        });
        return render.aside('conflict', 0, parts, { title: '详细信息' });
    };

    render.contractDetail = function (contract) {
        const data = contract || {};
        const parts = [
            { bgTitle: data.title },
            { title: '提出 Agent', html: listFieldHtml(data.proposers, 'itemS') },
            /* 详情比表格细一级：这里给到毫秒 */
            { title: '提出时间', text: data.timePrecise || data.time },
            { title: '影响范围', text: data.scope },
            { title: '契约内容', text: data.text },
            { title: '已确认 Agent', html: listFieldHtml(data.confirmed, 'itemS') },
            { title: '未确认 Agent', html: listFieldHtml(data.unconfirmed, 'itemS') }
        ];
        return render.aside('conflict', 1, parts, { title: '详细信息' });
    };

    /* 冲突（"冲突"子标签里的一行）——侧栏第 3 段 */
    render.conflictDetail = function (conflict) {
        const data = conflict || {};
        return render.aside('conflict', 2, [
            { bgTitle: data.title },
            { title: '描述', text: data.detail },
            { title: '影响范围', text: data.scope },
            { title: '相关 Agent', html: listFieldHtml(data.agents, 'itemS') },
            { title: '时间', text: data.time },
            { title: '处理方案', text: data.solution || '——' }
        ], { title: '详细信息' });
    };

    /* Agent 间协商（"Agent 间协商"子标签里的一行）——侧栏第 4 段 */
    render.messageDetail = function (message) {
        const data = message || {};
        const pair = [toText(data.from), toText(data.to)].filter(function (name) {
            return !!name;
        }).join(' → ');
        return render.aside('conflict', 3, [
            { bgTitle: pair },
            { title: '发件 Agent', text: data.from },
            { title: '收件 Agent', text: data.to },
            { title: '内容', text: data.content },
            { title: '状态', html: '<div class="tagZ' + (data.answeredOk ? ' tagZOK' : '') + '">' +
                esc(data.answered) + '</div>' },
            { title: '消息处理情况', html: '<div class="textN">' + tagsHtml(data.progress) + '</div>' }
        ], { title: '详细信息' });
    };

    render.intentDetail = function (intent) {
        const data = intent || {};
        const agentName = (data.agent || {}).name || data.agentName || 'Agent';
        return render.aside('audit', 0, [
            { bgTitle: agentName + ' 的意图声明' },
            { title: 'Agent', html: listFieldHtml([data.agent], 'itemS') },
            { title: '目标', text: data.target },
            { title: '方式', text: data.mode },
            { title: '原因', text: data.reason },
            { title: '声明版本', text: data.version },
            { title: '租约', html: '<div class="tagZ' + (data.lease && data.lease.ok ? ' tagZOK' : '') + '">' + esc(data.lease && data.lease.text) + '</div>' }
        ], { title: '详细信息' });
    };

    render.leaseDetail = function (lease) {
        const data = lease || {};
        const agentName = (data.agent || {}).name || data.agentName || 'Agent';
        return render.aside('audit', 1, [
            { bgTitle: agentName + ' 的权限租约' },
            { title: 'Agent', html: listFieldHtml([data.agent], 'itemS') },
            { title: '批准范围', text: data.scope },
            { title: '声明版本', text: data.version },
            { title: '租约', html: '<div class="tagZ' + (data.lease && data.lease.ok ? ' tagZOK' : '') + '">' + esc(data.lease && data.lease.text) + '</div>' }
        ], { title: '详细信息' });
    };

    render.workspaceDetail = function (workspace) {
        const data = workspace || {};
        return render.aside('workspace', 0, [
            { bgTitle: data.name },
            { title: '修改者', html: listFieldHtml([data.agent], 'item') },
            { title: '隔离方式', text: data.isolation },
            { title: '改动的文件', text: toArray(data.files).join('\n') },
            { title: '当前状态', html: '<div class="textN">' + tagsHtml(data.states) + '</div>' },
            { title: '补丁', text: data.patch }
        ], { title: '详细信息' });
    };

    render.pathDetail = function (record) {
        const data = record || {};
        return render.aside('path', 0, [
            /* 详情比表格细一级：这里给到毫秒 */
            { title: '时间', text: data.timePrecise || data.time },
            { title: '操作人', text: actorFor(data.actor).name },
            { title: '任务', text: data.task },
            { title: '操作', text: data.action }
        ], { title: '路径详情' });
    };

    /* DAG 节点的详情：走主页面侧栏那一套字段（{title,text}），标题跟着换成「任务详情」
       —— 点线性时间图的行会把它换回「路径详情」。状态词查中间层词表（glossText），
       表里没有就原样显示，不编一个中文出来。*/
    render.dagTaskDetail = function (task) {
        const node = task || {};
        const titles = function (list) {
            const names = toArray(list).map(function (item) { return item.title; });
            return names.length ? names.join('、') : '';
        };
        const parts = [
            { title: '任务', text: node.title },
            { title: '状态', text: glossText('task_status', node.status) },
            { title: '负责 Agent', text: node.owner }
        ];
        if (node.startedAt) parts.push({ title: '开工时间', text: dagTime(node.startedAt) });
        if (node.blockReason) parts.push({ title: '卡住原因', text: node.blockReason });
        parts.push({ title: '前置（谁挡着它）', text: titles(node.up) || '没有前置：可以直接认领。' });
        parts.push({ title: '下游（它挡着谁）', text: titles(node.down) || '不挡任何任务。' });
        if (node.parent) parts.push({ title: '父任务', text: node.parent });
        parts.push({ title: '任务号', text: node.id });
        return render.aside('path', 0, parts, { title: '任务详情' });
    };

    /* ---- 一次性重绘 ------------------------------------------------------ */

    /* 把 state 里的所有数据铺到页面上（refresh / 初始化 / dispatch 之后调用） */
    render.all = function () {
        render.list(state.get('projects', []));
        render.overview(state.get('project', {}));
        render.agents(state.get('agents', []));
        render.tasks(state.get('tasks', []));
        render.conflicts(state.get('conflicts', {}));
        render.audit(state.get('audits', {}));
        render.workspaces(state.get('workspaces', []));
        render.acceptance(state.get('acceptance', {}));
        render.timeline(state.get('timeline', []));
        render.agentWindow(state.get('agentsWindow', []));
        render.settings(state.get('settings', {}));
        form.watch(document); /* 渲染出来的新 input 也自动装上失焦提交 */
        emit('render:all', null);
        return true;
    };

    /* ========================================================================
     * §6 动作与分发
     * ------------------------------------------------------------------------
     * 三件事：
     *   1) app.*     —— 给 index.html 的 onclick 用的页面级命令（短、稳定）
     *   2) actions.* —— 真正的业务动作：必要时先确认，再发请求，再提示 + 局部重绘
     *   3) dispatch  —— 反向通道：后端 / 宿主脚本用 {type, payload} 驱动前端
     * 另外这里还把"点击内容 → 唤出侧栏"的映射接上（侧栏默认全隐藏）。
     * ====================================================================== */

    /* ---- 动作路由 -------------------------------------------------------- */

    /* 渲染器写出的按钮带 data-tg-action="名字:参数"，在这里查表执行；
       没注册的名字不会被吞掉，而是以 action:request 事件抛给后端/宿主。*/
    const ACTION_HANDLERS = Object.create(null);

    function parseActionSpec(spec) {
        const text = toText(spec);
        const at = text.indexOf(':');
        return (at < 0) ? { name: text, id: '' } : { name: text.slice(0, at), id: text.slice(at + 1) };
    }

    function runAction(spec) {
        const parsed = parseActionSpec(spec);
        if (!parsed.name) return null;
        const handler = ACTION_HANDLERS[parsed.name];
        if (handler) return handler(parsed.id, parsed.name);
        /* 找不到专用处理器时，允许直接写 dispatch 的类型名（如 ui.workspace.home），
           冒号后面那截作为 payload。这样渲染器里可以放心地把接口名当动作名用。*/
        if (DISPATCH_ROUTES[parsed.name]) return Tsunagou.dispatch(parsed.name, parsed.id || undefined);
        emit('action:request', parsed);
        return null;
    }

    function registerAction(name, handler) { ACTION_HANDLERS[name] = handler; }

    /* ---- 数据查找小工具 -------------------------------------------------- */

    function findById(list, id) {
        const target = toText(id);
        let hit = null;
        toArray(list).forEach(function (item) {
            if (!hit && item && toText(item.id) === target) hit = item;
        });
        return hit;
    }

    /* ---- 新建协作向导第 3 步：已接上的子 Agent 列表 ---------------------- */

    /* （放在 §6 是因为它跟着 actions.addSubAgent 一起变）
       列表里是**已经接上**的子 Agent（不是草稿）：manual 表示票备好了但要人手工配置宿主。*/
    function agentReachSuffix(agent) {
        return toText(agent && agent.status) === 'manual' ? '（待手工接入）' : '';
    }

    render.wizardSubAgents = function (list) {
        const box = qs('#newXz3 .listfieldbox');
        if (!box) return null;
        fill(box, toArray(list).map(function (agent) {
            return chipHtml({
                name: toText(agent.name) + agentReachSuffix(agent),
                icon: agent.icon, id: agent.vendor
            }, 'itemC');
        }).join('') + '<div class="itemAdd"><i class="fa fa-circle-plus"></i></div>');
        return box;
    };

    /* 「你所选的 Agent」这一块（标签 + 预览框）什么时侯露面：
       上面那两样（厂商选择框、名称输入框）都给出了东西才显示；
       刚打开向导、或把名字清空时，它就是一块空板子，不占位置。
       显隐只动 display（亮回来 = 清成空串、交回 CSS），位置与尺寸归 CSS。*/
    function wizardAgentPreview(visible) {
        const box = qs('#newXz2 .agentbox');
        if (!box) return;
        /* 标签就是预览框紧邻的前一个 .descbox（HTML 里的静态写法）*/
        const label = box.previousElementSibling;
        const nodes = (label && label.classList.contains('descbox')) ? [label, box] : [box];
        nodes.forEach(function (node) {
            if (visible) showEl(node);
            else hideEl(node);
        });
    }

    /* 向导第 2 步的"检测到的 Agent"：传 null 就清空 */
    render.wizardAgentBox = function (agent) {
        const box = qs('#newXz2 .agentbox');
        if (!box) return null;
        if (!agent || !toText(agent.name)) { fill(box, ''); return box; }
        fill(box, '<img class="left" src="' + esc(iconOf(agent)) + '" />' +
            '<div class="right">' + esc(agent.name) + '</div>');
        return box;
    };

    /* 向导第 4 步的"接入结果"：已经发生的事，不是待确认的草稿 ——
       项目名/描述来自第 1 步真建出来的那个项目，Agent 名单来自第 2/3 步真接上的那些。*/
    render.wizardReview = function (draft) {
        const data = draft || {};
        const box = qs('#newXz4 .freebox');
        if (!box) return null;
        const project = state.get('wizard.project', null) || {};
        const main = state.get('wizard.main', null);
        const subs = toArray(state.get('wizard.draftSubAgents', []));
        fill(box,
            '<div class="descbox">项目名称</div>' +
            '<div class="title">' + esc(toText(project.name) || data.name || '（还没创建）') + '</div>' +
            '<div class="descbox">项目描述</div>' +
            '<div class="descbox">' + esc(toText(project.objective) || '（没有填写）') + '</div>' +
            '<div class="descbox">主 Agent</div>' +
            (main && toText(main.name)
                ? listFieldHtml([{
                    name: toText(main.name) + agentReachSuffix(main),
                    icon: main.icon
                }], 'itemJ')
                : '<div class="descbox">（未接入）</div>') +
            '<div class="descbox">子 Agent</div>' +
            (subs.length
                ? listFieldHtml(subs.map(function (agent) {
                    return {
                        name: toText(agent.name) + agentReachSuffix(agent),
                        icon: agent.icon
                    };
                }), 'itemJ')
                : '<div class="descbox">（未接入）</div>'));
        return box;
    };

    /* ---- 业务动作 -------------------------------------------------------- */

    /* 「添加子 Agent」窗口（#addSubAgent）有两个入口，提交成功后要回到不同的地方：
      wizard —— 向导第 3 步的小加号，结果进向导的草稿列表；
      agents —— Agent 管理页的大加号，结果进 Agent 列表。
   打开窗口时把来源记下来（由 app.addSubAgent 写），提交时读它。*/
    let addSubAgentSource = 'agents';

    /* 统一"先确认、再提交"的写法 */
    function confirmThen(confirmOptions, task) {
        return dialog.confirm(confirmOptions).then(function (ok) {
            if (!ok) return false;
            return Promise.resolve(task());
        });
    }

    /* 界面上保留但后端还没装配的动作（撤回类）：统一就一句话。
       不猬原因、不说假成功，也不静默地什么都不干。*/
    const NOT_IMPLEMENTED_TEXT = '撤回功能当前尚未实现';

    function notImplemented() {
        notify.info(NOT_IMPLEMENTED_TEXT);
        return Promise.resolve(false);
    }

    const actionsApi = {
        /* 新建协作：向导第 1 步的「创建」按钮调用（app.registerProject 也走它）。
           成功后返回后端那份项目（{project_id, name, ...}），失败返回 false ——
           向导要靠这个 id 才能把"当前协作"切过去、继续接入 Agent。
           中间层接了这一下之后：建目录、git init、登记进索引，并顺手把这个项目的 daemon 起起来。*/
        createProject: function (draft) {
            const data = draft || {};
            if (!toText(data.name).trim()) {
                notify.error('请填写协作的名字');
                return Promise.resolve(false);
            }
            return notify.track('正在创建协作', api.post('projectCreate', data)).then(function (result) {
                const project = (result && result.project) || null;
                /* 项目入口文件（AGENTS.md / .tsunagou/agent-context.md / 项目 skill）没写成就说一声：
                   少了它们，接进来的 Agent 读不到"我在哪个项目、这次是为谁准备的"，只会照它自己的
                   "安装并初始化"说明去别处新建一个项目。项目本身建好了，所以这只是提醒。*/
                const entry = (project && project.bootstrap) || {};
                if (toText(entry.status) && toText(entry.status) !== 'bootstrapped') {
                    notify.info('项目的 Agent 入口文件没写成功（' + (toText(entry.error) || '未知原因') +
                        '）：接进来的 Agent 可能读不到这个项目的规矩。');
                }
                notify.success({ title: '协作已创建', sub: data.name });
                /* 列表以后端为准：重新拉一次，别自己造一张卡片 */
                return Tsunagou.refresh(['projects']).then(function () { return project; });
            }, function () { return false; });   /* 失败提示由 api.request 弹，这里只表态"没建成" */
        },

        /* 一次性删掉整个协作（中间层 `POST /console/projects/{id}:forget`）。
           做的是"整个删掉"，不是分步后撤：先问一次、把删掉什么说清楚。
           中间层自己决定能不能动文件（只删它自己 projects_root 底下的），
           报告里会写明哪一步做了什么、哪一步没做。*/
        deleteProject: function (projectId) {
            const id = toText(projectId);
            if (!id) return Promise.resolve(false);
            const project = findById(state.get('projects', []), id) || {};
            const name = toText(project.name) || shortId(id);
            return dialog.confirm({
                title: '删除这个协作？',
                text: '“' + name + '”会被整个删掉，不能撤销。',
                description: '它的 daemon 会停掉，宿主里为它注册的 bridge 会注销，' +
                    '项目目录与里面的协作数据一并删除。',
                okText: '删除', danger: true
            }).then(function (ok) {
                if (!ok) return false;
                /* 路径里带的是**这张卡片**的 id，不是"当前项目"——
                   所以不用 WRITE_COMMANDS 的 {project} 模板，直接拼字面路径。*/
                const path = '/console/projects/' + encodeURIComponent(id) + ':forget';
                return notify.track('正在删除协作', api.post(path, { delete_files: true }))
                    .then(function (report) {
                        const files = (report || {}).files || {};
                        notify.success({ title: '协作已删除', sub: name });
                        if (files.deleted === false) {
                            notify.info('目录没有删除：' + (toText(files.reason) || '中间层没动文件'));
                        }
                        if (toText(state.get('currentProjectId')) === id) {
                            state.set('currentProjectId', '');
                            forgetLastProject();
                            ui.workspace.home();
                        }
                        return Tsunagou.refresh(['projects']).then(function () { return true; });
                    }, function () { return false; });
            });
        },

        /* 重命名一个协作（中间层 `POST /console/projects/{id}:rename`）。
           名字是给人看的标签，不是项目的身份：id/路径都不动，所以不碰任何数据。
           走窗口里那个输入框（#renamePmt），确定后交给 submitRename。*/
        renameProject: function (projectId) {
            const id = toText(projectId);
            if (!id) return Promise.resolve(false);
            const project = findById(state.get('projects', []), id) || {};
            /* 名字优先取名单里的；名单里没有（数据还没到、或字段对不上）就从**卡片上**读 ——
               那张卡片上正写着它，人就是看着它点的。这样输入框不会空着让人重打一遍。*/
            const card = qsa('#projList .projItem').filter(function (node) {
                return toText(node.getAttribute('data-project-id')) === id;
            })[0] || null;
            const title = card ? qs('.title', card) : null;
            renameTargetId = id;
            const input = byId('renamePmtInput');
            if (input) input.value = toText(project.name) || toText(title && title.textContent);
            ui.window.open('renamePmt');
            if (input && input.focus) input.focus();
            return Promise.resolve(true);
        },

        /* 重命名窗口的"确定"。空名字不动（名字是必填的），失败原样说出来。*/
        submitRename: function () {
            const id = toText(renameTargetId);
            const input = byId('renamePmtInput');
            const name = toText(input && input.value).trim();
            if (!id) return Promise.resolve(false);
            if (!name) { notify.error('名字不能是空的'); return Promise.resolve(false); }
            const path = '/console/projects/' + encodeURIComponent(id) + ':rename';
            return notify.track('正在重命名协作', api.post(path, { name: name }))
                .then(function () {
                    ui.window.close('renamePmt');
                    notify.success({ title: '已重命名', sub: name });
                    return Tsunagou.refresh(['projects', 'project']).then(function () { return true; });
                }, function () { return false; });
        },

        /* 添加子 Agent（窗口 #addSubAgent 的"确定"）。
           后端**没有**"创建 Agent"这个能力：Agent 是在宿主那边连上来的。
           所以这里的动作是"让中间层准备接入"：Codex 由真实聊天认领申请，其他宿主签票并登记。
           只有本次接入的身份就绪、通过中间层完成核验才算成功。
             agents —— Agent 管理页的入口：成功后刷新名单；
             wizard —— 向导第 3 步的入口：成功后进向导的结果列表。*/
        addSubAgent: function (payload) {
            const data = payload || {};
            const name = toText(data.name).trim();
            /* 厂商从选择框来（原来是"API 地址"输入框）*/
            const vendor = toText(data.vendor).trim();
            if (!name || !vendor) {
                notify.error('请填写子 Agent 名称并选择厂商');
                return Promise.resolve(false);
            }
            const source = (data.source === 'wizard' || data.source === 'agents') ? data.source : addSubAgentSource;
            const host = hostFor(vendor);
            if (!host) {
                notify.error('中间层不认识这个厂商，无法准备接入：' + vendor);
                return Promise.resolve(false);
            }
            /* 中间层办不完这个厂商时直说 —— 不假装"已排好队"。*/
            const blocked = hostEnrollBlocker(host);
            if (blocked) {
                if (blocked.mode === 'in_host') notify.info(blocked.note);
                else notify.error(blocked.note);
                return Promise.resolve(false);
            }
            const finishWindow = function () {
                ui.window.close('addSubAgent');
                ui.window.clearInputs('addSubAgent');
                resetCsBox(subAgentVendorBox());
                resetCsBox(subAgentPlaceBox());
                syncSubAgentPlace();
            };
            /* 「位置＝网络」走跨机器那条路：主机签一张邀请，人把它交给那台机器。
               其余（本机）照旧：中间层准备、等那条会话来兑换。两条路返回同一个形状，
               下面的收尾因此共用一份。*/
            const connecting = (data.place === 'network')
                ? connectNetworkAgent({ host: host, nickname: name, role: 'worker', number: toText(data.number).trim() })
                : connectAgent({
                    host: host, nickname: name, role: 'worker',
                    waiting: openWindowHint(host, '作为子 Agent '),
                    profile: data.profile || null
                });
            return connecting.then(function (outcome) {
                const reached = toText(outcome && outcome.status);
                if (reached !== 'arrived' && reached !== 'manual') {
                    const trouble = connectTrouble(reached, host);
                    if (trouble) notify.info(trouble);
                    return false;
                }
                const manual = (reached === 'manual');
                const agent = {
                    name: typeof outcome.nickname === 'string' ? outcome.nickname : name, vendor: vendor, icon: data.icon || agentIconFor(vendor),
                    agent_id: toText((outcome.agent || {}).agent_id),
                    profile: toText(outcome.profile),
                    status: reached
                };
                if (source === 'wizard') {
                    /* 项目已经在第 1 步建好了，列表只是向导里的"接入结果" */
                    const list = toArray(state.get('wizard.draftSubAgents', [])).slice();
                    list.push(agent);
                    state.set('wizard.draftSubAgents', list);
                    render.wizardSubAgents(list);
                }
                finishWindow();
                if (manual) {
                    notify.info(manualNote(outcome.registration, host));
                } else {
                    notify.success({ title: '接入成功', sub: agent.name + ' 已加入这个协作' });
                }
                if (source === 'wizard') return true;
                /* 名单、卡片上的胶囊、昵称显示都要跟着变 */
                Tsunagou.refresh(['agents', 'projects', 'agentsWindow', 'settings']);
                return true;
            });
        },

        /* 向导第 2 步那个"你所选的 Agent"预览框。
           里面要显示的是这个 Agent 的**名字**（用户填的"工位号"），图标才是厂商 ——
           不要把厂商名当名字显示。名字还没填就留空。
           选择框一变、或名称输入框一改，都调这里刷新。
           顺便把这一整块（标签 + 预览框）的显隐一起定了：两样都没给就不显示。*/
        detectMainAgent: function () {
            const vendor = wizardVendor(2);
            const input = wizardInputs(2)[0];
            const name = toText(input && input.value).trim();
            wizardAgentPreview(!!name && !!vendor);
            if (!name) {
                state.set('wizard.detectedMainAgent', null);
                render.wizardAgentBox(null);
                return Promise.resolve(false);
            }
            const detected = { name: name, vendor: vendor, icon: agentIconFor(vendor) };
            state.set('wizard.detectedMainAgent', detected);
            render.wizardAgentBox(detected);
            return Promise.resolve(detected);
        },

        /* 保存一条设置（现在只有颜色主题）：存放地点是中间层的用户档案。
           主题不是协作事实，daemon 不管它，所以这里发的是一个补丁而不是命令。*/
        saveSetting: function (key, value) {
            const patch = {};
            patch[toText(key) || 'theme'] = value;
            return api.post('settingSave', { patch: patch }, { silent: true })
                .then(function (stored) {
                    /* 两份都要更新：设置面板读 settings，名字/主题的显示读 profile */
                    state.set('profile', stored);
                    state.set('settings', stored);
                    return true;
                }, function () { return false; });
        },

        /* 保存某个 Agent 的昵称 / 厂商（中间层用户档案，不是协作事实）。
           厂商不给就别动它 —— 界面上的"修改"只允许改昵称。*/
        saveAgentProfile: function (agentId, values) {
            const entry = {};
            if (values && values.nickname !== undefined) entry.nickname = values.nickname;
            if (values && values.vendor !== undefined) entry.vendor = values.vendor;
            const agents = {};
            agents[toText(agentId)] = entry;
            return api.post('settingSave', { patch: { agents: agents } }).then(function (stored) {
                state.set('profile', stored);
                state.set('settings', stored);
                notify.success({ title: '已保存 Agent 昵称' });
                /* 用到名字的地方都刷一遍：Agent 管理卡片、任务/审计/冲突里的胶囊、
                   Agent 列表与左栏卡片（后两个也是按 id 现算名字的）。*/
                Tsunagou.refresh(['agents', 'tasks', 'audits', 'conflicts', 'project', 'agentsWindow', 'projects']);
                return true;
            }, function () { return false; });
        },

        /* 删除 / 退役一个 Agent：他从此不能再动，但他做过的事一个字都不改。
           两道拒绝由后端说了算：当前主 Agent 不能删；手上还压着活的不能删（把清单一起
           给出来，页面照着列）。远端 Agent 只在这台机器上被停掉，确认框里会提醒去那台
           机器上清登记。*/
        removeAgent: function (id) {
            const agent = toArray(state.get('agents', [])).filter(function (item) {
                return toText(item.id) === toText(id);
            })[0] || {};
            const machine = toText(agent.machine);
            return confirmThen({
                title: '删除 Agent',
                text: '确定要让这个 Agent 退役吗？他立刻不能再派活、接活。',
                description: '他做过的任务和发过的消息仍然记他的名字，不会被改写。'
                    + (machine ? '那台机器（' + machine + '）上还留着一条登记，请去那台机器上清掉。' : ''),
                okText: '删除',
                danger: true
            }, function () {
                return api.post('agentRemove', { id: id, reason: 'removed from console' })
                    .then(function () {
                        notify.success({ title: '已删除 Agent' });
                        Tsunagou.refresh(['agents', 'project', 'tasks']);
                        return true;
                    }, function (error) {
                        /* 后端把"他还占着哪些任务"一起给了：照它列出来，别自己编一句话。*/
                        const detail = (error && error.raw && error.raw.detail) || {};
                        const held = toArray(detail.tasks).map(function (task) {
                            return toText(task.title) || toText(task.task_id);
                        });
                        if (held.length) {
                            notify.error('他手上还有活，先处理：' + held.slice(0, 3).join('、')
                                + (held.length > 3 ? ' 等 ' + held.length + ' 个任务' : ''));
                        }
                        return false;
                    });
            });
        },

        /* 设为主 Agent */
        setMainAgent: function (id) {
            return confirmThen({
                title: '设为主 Agent',
                text: '确定要让这个 Agent 接管主 Agent 的位置吗？原来的主 Agent 会变回普通成员。',
                okText: '设为主 Agent'
            }, function () {
                /* 不带代次：后端根本不读它（见上面 agentSetMain 的注释）。*/
                return api.post('agentSetMain', { id: id })
                    .then(function () {
                        notify.success({ title: '已设为主 Agent' });
                        Tsunagou.refresh(['agents', 'project']);
                        return true;
                    }, function () { return false; });
            });
        },

        /* 备注：Agent 详情窗口**没有**保存动作 —— 那两个框是只读的展示，
           "确定"在 index.html 里就是内联关窗。昵称/厂商的写入口是 saveAgentProfile。*/

        acceptanceConfirm: function () {
            const acceptance = state.get('acceptance', {}) || {};
            const proposal = acceptance.proposal || {};
            if (!proposal.id) {
                notify.error('还没有读到项目完成提案，无法确认——请先让主 Agent 提交完成提案');
                return Promise.resolve(false);
            }
            /* 后端拿它与**当前** policy_revision 比：提案时那个可能已经过期。*/
            const current = Number((state.get('project', {}) || {}).policyRevision);
            return confirmThen({
                title: '确认完成项目',
                text: '确定要确认项目完成吗？',
                description: '项目会立即被标注为“已完成”，并新建一个存档点。',
                okText: '确认完成'
            }, function () {
                return api.post('acceptanceConfirm', {
                    proposal_id: proposal.proposal_id || proposal.id,
                    proposal_digest: proposal.digest,
                    expected_project_revision: isFinite(current) ? current : proposal.revision,
                    /* 后端只对 `expected_revisions.decision` 有读的地方（决策自身版本）；
                       项目版本走上面那一项。*/
                    expected_revisions: { decision: proposal.revision }
                }).then(function () {
                    notify.success({ title: '项目已完成', sub: '已新建存档点' });
                    /* 本地乐观更新：顶部状态 + 基本信息里的"项目状态" */
                    state.set('project.statusText', '已完成');
                    const basics = toArray(state.get('project.basics', []));
                    const lifecycleRow = basics.filter(function (row) {
                        return row.label === '生命周期';
                    })[0];
                    if (lifecycleRow) lifecycleRow.value = glossText('lifecycle', 'completed');
                    state.set('project.basics', basics);
                    render.overview(state.get('project', {}));
                    Tsunagou.refresh(['projects', 'acceptance']);
                    return true;
                }, function () { return false; });
            });
        },

        /* 归档：已砍掉（决定 11），daemon 也没装配 project.archive；页面上连按钮都已撤掉。*/

        checkpointRetry: function (id) {
            return confirmThen({
                title: '重试存档',
                text: '确定要重新尝试这次存档吗？',
                okText: '重试'
            }, function () {
                /* 重试的是那次失败的 Operation（卡片上的 data-row-id）。*/
                return api.post('checkpointRetry', { operation_id: id }).then(function () {
                    notify.success({ title: '已重新发起存档' });
                    Tsunagou.refresh(['checkpoints', 'checkpointFailures']);
                    return true;
                }, function () { return false; });
            });
        },

        /* 「立即存档」：不带 retry_operation_id 的同一条命令 —— 后端据此新建一个存档点。
           存档是个真动作（会落一份可校验的快照），所以先弹确认，和其他写动作一个口径。*/
        checkpointCreate: function () {
            return confirmThen({
                title: '立即存档',
                text: '要把当前状态存成一个存档点吗？',
                description: '不用等自动存档，存好之后这一屏的“最新存档点”会多一条。',
                okText: '存档'
            }, function () {
                return notify.track('正在存档', api.post('checkpointCreate', {})).then(function (result) {
                    const status = toText((result || {}).checkpoint_status);
                    notify.success({
                        title: '已发起存档',
                        sub: glossText('checkpoint_status', status) || status
                    });
                    Tsunagou.refresh(['checkpoints', 'checkpointFailures']);
                    return result;
                }, function () { return false; });
            });
        },

        /* 「校验」一个存档点：daemon 会真去比对 manifest 与 git 锚点（失败是 409）。
           路径里是**这一张卡**的 digest，不是当前项目 —— 项目头由 api.request 自己带上。*/
        checkpointVerify: function (id) {
            const digest = toText(id);
            if (!digest) return Promise.resolve(false);
            const path = '/checkpoints/' + encodeURIComponent(digest) + '/verify';
            return notify.track('正在校验存档点 ' + shortDigest(digest), api.request({ method: 'GET', path: path }))
                .then(function (result) {
                    const anchors = toArray((result || {}).git_anchors).length;
                    notify.success({
                        title: '校验通过',
                        sub: '封存到事件 ' + toText((result || {}).through_event_seq) +
                            (anchors ? ' · git 锚点 ' + anchors + ' 个' : ' · 本机没有对应的 git 锚点')
                    });
                    Tsunagou.refresh(['checkpoints']);
                    return result;
                }, function () { return false; });
        },

        /* 待用户决定：弹的是页面本来就有的"需要用户确认/决定的信息"卡片，
           选中哪一项就把哪一项原文当 choice 回给 daemon；选不对后端会以结构化 4xx
           说明原因，界面把那句话展示出来。*/
        decisionResolve: function (id) {
            const pending = toArray((state.get('project', {}) || {}).pending).filter(function (item) {
                return toText(item.id) === toText(id);
            })[0] || {};
            const choices = toArray(pending.choiceList);
            if (!choices.length) {
                notify.error('这条决定没有可选答复，无法决定：' + (pending.title || id));
                return Promise.resolve(false);
            }
            return dialog.decision({
                title: pending.title || '需要用户决定',
                content: (pending.detail ? pending.detail + '\n' : '') +
                    '可选答复：' + choices.join(' / '),
                actions: choices.map(function (choice) {
                    return { label: choice, value: choice };
                })
            }).then(function (choice) {
                if (!choice) return false;
                return api.post('decisionResolve', {
                    decision_id: pending.id,
                    choice: choice,
                    expected_revisions: { decision: pending.revision },
                    proposal_digest: pending.digest,
                    reason: 'resolved from console'
                }).then(function () {
                    notify.success({ title: '已提交决定', sub: choice });
                    Tsunagou.refresh(['project', 'acceptance', 'audits']);
                    return true;
                }, function () { return false; });
            });
        },

        /* "稍后"：不改后端任何状态，只是把这一条从当前视图里收起来（本地）。*/
        decisionLater: function (id) {
            const project = state.get('project', {}) || {};
            project.pending = toArray(project.pending).filter(function (item) {
                return toText(item.id) !== toText(id);
            });
            state.set('project', project);
            render.overview(project);
            notify.info('已先收起这条：' + (id || ''));
            return Promise.resolve(true);
        }
    };

    Object.assign(actions, actionsApi);

    /* 动作名 → 处理函数（渲染器里的 data-tg-action 就认这些名字） */
    registerAction('acceptance.confirm', function () { return actions.acceptanceConfirm(); });
    registerAction('checkpoint.retry', function (id) { return actions.checkpointRetry(id); });
    registerAction('checkpoint.create', function () { return actions.checkpointCreate(); });
    registerAction('checkpoint.verify', function (id) { return actions.checkpointVerify(id); });
    registerAction('agent.remove', function (id) { return actions.removeAgent(id); });
    registerAction('agent.setMain', function (id) { return actions.setMainAgent(id); });
    /* Agent 管理卡片上的「修改」：开详情窗口改昵称（厂商只读）*/
    registerAction('agent.edit', function (id) { return app.editAgent(id); });
    registerAction('decision.resolve', function (id) { return actions.decisionResolve(id); });
    registerAction('decision.later', function (id) { return actions.decisionLater(id); });
    registerAction('contract.detail', function (id) {
        /* 契约在冲突页的第 4 个子标签里，对应侧栏第 2 段 */
        openDetail('conflict', id, 3);
        return true;
    });
    registerAction('dissent.negotiate', function () {
        /* 「Agent 间协商」（消息与义务）现在是第 3 个子标签。*/
        ui.blockTabs.conflict(2);
        ui.aside.hide('conflict');
        return true;
    });
    registerAction('dissent.contract', function (id) {
        const dissent = findById(state.get('conflicts.dissents', []), id);
        const contract = toArray(state.get('conflicts.contracts', []))[0];
        ui.blockTabs.conflict(3);
        if (contract) {
            render.contractDetail(contract);
            ui.aside.show('conflict', 1);
        } else if (dissent) {
            render.dissentDetail(dissent);
            ui.aside.show('conflict', 0);
        }
        return true;
    });

    /* ---- 打开某条数据的详情（点内容唤侧栏） ----

       侧栏默认全部隐藏（切标签页也会全收起），只有"点到对应内容"才出现。
       每个页面的"拿 id 找数据 → 画进侧栏 → 用第几段"写在下表里，
       由 bindContentClicks 统一驱动。

       每个函数返回侧栏的分段号；找不到数据就返回 null（调用方什么都不做）。*/
    const DETAIL_VIEWS = {
        tasks: function (id) {
            const row = findById(state.get('tasks', []), id) || {};
            /* 侧栏内容先就着表格行本身画（大多数字段行里就有）；
               如果后端另外发过这条任务的详情（dispatch 'task.detail'），
               且 id 对得上，再用它盖一层。保存的详情不属于这条任务时一律忽略。*/
            const detail = Object.assign({}, row);
            const stored = state.get('taskDetail', null);
            if (stored && toText(stored.id) === toText(row.id)) Object.assign(detail, stored);
            render.taskDetail(detail);
            return 0;
        },
        workspace: function (id) {
            const item = findById(state.get('workspaces', []), id);
            if (!item) return null;
            render.workspaceDetail(item);
            return 0;
        },
        path: function (id) {
            let found = null;
            toArray(state.get('timeline', [])).forEach(function (group) {
                toArray(group.items).forEach(function (line) {
                    if (!found && toText(line.id) === toText(id)) found = line;
                });
            });
            if (found) { render.pathDetail(found); return 0; }
            /* 总路径上有两张图：点线性时间图的行给的是**行动号**，点 DAG 的节点给的是
               **任务号**。同一个侧栏、同一段，任务号就换成任务详情（找不到就是真没了）。*/
            const task = dagGraph ? dagGraph.byId[toText(id)] : null;
            if (!task) return null;
            render.dagTaskDetail(task);
            return 0;
        },
        /* 冲突与协商的 4 个子标签各有自己的侧栏分段（对应 #aside-conflict 里的四段）：
           0 分歧 → 第 1 段；1 冲突 → 第 3 段；2 Agent 间协商 → 第 4 段；3 契约 → 第 2 段 */
        conflict: function (id, block) {
            const index = Number(block) || 0;
            if (index === 1) {
                const conflict = findById(state.get('conflicts.conflicts', []), id);
                if (!conflict) return null;
                render.conflictDetail(conflict);
                return 2;
            }
            if (index === 2) {
                const message = findById(state.get('conflicts.messages', []), id);
                if (!message) return null;
                render.messageDetail(message);
                return 3;
            }
            if (index === 3) {
                const contract = findById(state.get('conflicts.contracts', []), id);
                if (!contract) return null;
                render.contractDetail(contract);
                return 1;
            }
            const dissent = findById(state.get('conflicts.dissents', []), id);
            if (!dissent) return null;
            render.dissentDetail(dissent);
            return 0;
        },
        /* 意图与权限审计：区块第 2 段（权限租约）对应侧栏第 2 段，其余都在第 1 段 */
        audit: function (id, block) {
            if (Number(block) === 1) {
                const lease = findById(state.get('audits.leases', []), id) ||
                    findById(state.get('audits.waiting', []), id);
                if (!lease) return null;
                render.leaseDetail(lease);
                return 1;
            }
            const intent = findById(state.get('audits.intents', []), id);
            if (!intent) return null;
            render.intentDetail(intent);
            return 0;
        }
    };

    /* 打开某页某条数据的详情并唤出侧栏。block 只对冲突/审计有意义（决定侧栏用哪一段）。
       返回是否打开了。*/
    function openDetail(slug, id, block) {
        const view = DETAIL_VIEWS[slug];
        if (!view) return false;
        const section = view(id, block);
        if (section === null || section === undefined) return false;
        ui.aside.show(slug, section);
        return true;
    }

    /* 点在哪一段上（区块子标签的序号）—— 决定侧栏用哪一段 */
    function blockIndexOf(node, blockId) {
        const block = byId(blockId);
        const panel = closest(node, '.tabContent');
        return block ? Math.max(blockPanels(block).indexOf(panel), 0) : 0;
    }

    function bindContentClicks() {
        document.addEventListener('click', function (event) {
            /* 按钮自己走动作通道，不参与"点内容唤侧栏" */
            if (closest(event.target, '[data-tg-action]')) return;

            const target = event.target;
            const rowId = function (node) { return node.getAttribute('data-row-id'); };

            const taskRow = closest(target, '#pane-tasks .tablebox .tr');
            if (taskRow) { openDetail('tasks', rowId(taskRow)); return; }

            const auditRow = closest(target, '#pane-audit .tabContent .tablebox .tr');
            if (auditRow) {
                openDetail('audit', rowId(auditRow), blockIndexOf(auditRow, 'block-audit'));
                return;
            }

            /* 选择器里的 '>' 是必须的：卡片内部还有 .listfieldbox > .item 的胶囊，
               不加 '>' 就会命中胶囊本身（它没有身份标记），侧栏就打不开了。*/
            /* 冲突与协商里，「冲突」和「Agent 间协商」两个子标签是表格，「分歧」和「契约」是卡片 */
            const conflictRow = closest(target, '#pane-conflict .tabContent .tablebox .tr');
            if (conflictRow) {
                openDetail('conflict', rowId(conflictRow), blockIndexOf(conflictRow, 'block-conflict'));
                return;
            }

            const conflictCard = closest(target, '#pane-conflict .tabContent > .boxerbox > .item');
            if (conflictCard) {
                openDetail('conflict', rowId(conflictCard), blockIndexOf(conflictCard, 'block-conflict'));
                return;
            }

            const workspaceCard = closest(target, '#pane-workspace .boxerbox > .item');
            if (workspaceCard) { openDetail('workspace', workspaceCard.getAttribute('data-workspace-id')); return; }

            /* 两级 '>' 都要：行是 .taskFlow > .inner > .item；再往下还有
               .listfieldbox > .item 的胶囊（操作人那一列），少了 '>' 会先命中胶囊，
               而胶囊上没有 data-row-id。*/
            const pathRow = closest(target, '#pane-path .taskFlow > .inner > .item');
            if (pathRow) { openDetail('path', rowId(pathRow)); return; }

            /* DAG 图上的节点：标题左边那个圆点是折叠开关（点它只折叠，不选中、不换详情；
               连锁：它下游连着的跟着一起折/展），其余地方才是"选中 + 开右侧栏"。*/
            const dagNode = closest(target, '#pane-path .dagArea .node');
            if (dagNode) {
                const taskId = dagNode.getAttribute('data-task-id');
                if (dagHitFoldDot(event)) { dagToggleFold(taskId); return; }
                dagSelect(taskId);
                openDetail('path', taskId);
                return;
            }
        });
    }

    /* 上次打开的项目：只记 id，不存任何协作数据。
       localStorage 写不进去也不影响功能（隐私模式、file:// 等）。*/
    const LAST_PROJECT_KEY = 'tsunagou.console.lastProject';

    function rememberProjectId(projectId) {
        try { window.localStorage.setItem(LAST_PROJECT_KEY, toText(projectId)); } catch (error) { /* 忽略 */ }
        return projectId;
    }

    function lastProjectId() {
        try { return toText(window.localStorage.getItem(LAST_PROJECT_KEY)); } catch (error) { return ''; }
    }

    /* 项目没了，"上次打开的那个"也得忘掉，不然下次进来会白找一遍 */
    function forgetLastProject() {
        try { window.localStorage.removeItem(LAST_PROJECT_KEY); } catch (error) { /* 忽略 */ }
    }

    /* ---- 页面级命令（index.html 的 onclick 指向这里） -------------------- */

    Object.assign(app, {
        /* 工作区 —— openProject(id) 会顺带把"当前项目"切成 id，并拉这个项目的数据 */
        openProject: function (id) {
            const projectId = toText(id);
            if (projectId) {
                state.set('currentProjectId', projectId);
                rememberProjectId(projectId);
                /* 列表数据本来就在手上，直接重绘一次就能把选中态换过去，不用再请求 */
                render.list(state.get('projects', []));
                /* 换项目时统一回到主视图：上一个项目停在哪个标签页，不该带到新项目来。
                   顺带会把所有侧栏收起来，正好是"刚进一个新项目"该有的初始状态。*/
                ui.tabs.project('overview');
            }
            ui.workspace.project();
            if (!projectId) return true;
            emit('project:open', { id: projectId });
            return Tsunagou.refresh(PROJECT_SCOPED_KEYS);
        },
        openHome: function () { ui.workspace.home(); return true; },

        /* 左侧栏折叠 / 展开 */
        foldSidebar: function () { ui.sidebar.fold(); return true; },
        unfoldSidebar: function () { ui.sidebar.unfold(); return true; },
        toggleSidebar: function () { ui.sidebar.toggle(); return true; },

        /* 窗口 */
        openWindow: function (id) { ui.window.open(id); return true; },
        closeWindow: function (id) { ui.window.close(id); return true; },

        /* 加载遮罩上的「取消等待」入口（#loadW 里的 #loadWCancel，onclick 指向这里）。
           先弹一次确认，确认后由当前的等待者作废票据、注销宿主登记。*/
        cancelWaiting: function () { return notify.cancelWaiting(); },

        /* 设置窗口：打开并切到某一页（不传则停在个性化设置） */
        openSettings: function (key) {
            ui.window.open('setPanel');
            ui.settingTabs.select(key || 'personal');
            return true;
        },
        settingTab: function (key) { return ui.settingTabs.select(key); },

        /* Agent 列表窗口。先把手上有的名单铺上，再问一次最新 —— 跨项目汇总要逐个问
           中间层，比左栏那两次请求贵，所以不放进轮询，只在人打开窗口时发生。*/
        openAgents: function () {
            render.agentWindow(state.get('agentsWindow', []));
            ui.window.open('mgrAgent');
            return Tsunagou.refresh(['agentsWindow']).then(function () { return true; },
                function () { return false; });
        },
        /* 点 Agent 列表里的某一条 → 打开详情 */
        openAgentInfo: function (id) {
            const agent = findById(state.get('agentsWindow', []), id);
            render.agentInfoWindow(agent || {});
            ui.window.open('mgrAgentInfo');
            return true;
        },

        /* 网络接入标记（跨机器）：**中间层专用入口** —— 定一个 Agent 是从网络接进来的。
           `online` 给 true/false（在线/离线），也可以给 {network, online} 两个都说；
           `network:false` 等于 clearAgentNetwork。只改状态与徽标，不发任何请求。
           本机接入的 Agent 根本不用调它（默认就不画徽标）。*/
        setAgentNetwork: function (agentId, online) {
            const id = toText(agentId);
            if (!id) return false;
            const spec = isPlainObject(online) ? online : { network: true, online: online === true };
            if (spec.network === false) return app.clearAgentNetwork(id);
            const table = Object.assign({}, state.get('agentNetwork', {}) || {});
            /* 有键 = 网络接入，值 = 在不在线（取值规则见 agentNetworkOf）*/
            table[id] = spec.online === true;
            state.set('agentNetwork', table);
            renderNetworkBadges();
            return true;
        },
        /* 撇回本机：这个 Agent 不是网络接入的（回到“不画徽标”）*/
        clearAgentNetwork: function (agentId) {
            const id = toText(agentId);
            if (!id) return false;
            const table = Object.assign({}, state.get('agentNetwork', {}) || {});
            if (!(id in table)) return true;
            delete table[id];
            state.set('agentNetwork', table);
            renderNetworkBadges();
            return true;
        },

        /* Agent 管理卡片上的「修改」（data-tg-action="agent.edit:<id>"）：
           开的是同一个详情窗口 —— 昵称可改。*/
        editAgent: function (agentId) {
            const agent = findById(state.get('agents', []), agentId) || {};
            const project = findById(state.get('projects', []), state.get('currentProjectId')) || {};
            render.agentInfoWindow({
                agent_id: toText(agent.id || agentId),
                nickname: toText(agent.name),
                project: toText(state.get('project.name')) || toText(project.name),
                task: toText(agent.currentTask)
            });
            ui.window.open('mgrAgentInfo');
            return true;
        },

        /* 详情窗口的「确定」：把昵称存进中间层的用户档案（厂商从不上送），存完关窗。
           值没变就只关窗 —— 不发无意义的请求、也不弹“已保存”。*/
        saveAgentInfo: function () {
            const node = byId('mgrAgentInfo');
            if (!node) return Promise.resolve(false);
            const agentId = toText(node.getAttribute('data-agent-id'));
            const before = toText(node.getAttribute('data-nickname'));
            const input = qs('.textbox2 input', node);
            const nickname = toText(input && input.value).trim();
            if (!agentId) {
                ui.window.close(node);
                notify.info('这条记录里没有 Agent 号，改不了昵称');
                return Promise.resolve(false);
            }
            if (!nickname) { notify.error('昵称不能为空'); return Promise.resolve(false); }
            if (nickname === before) { ui.window.close(node); return Promise.resolve(true); }
            return actions.saveAgentProfile(agentId, { nickname: nickname }).then(function (ok) {
                /* 没存上就留在窗口里，让人改完再试（提示已由 api 弹过）*/
                if (ok) ui.window.close(node);
                return ok;
            });
        },

        /* 邀请窗口的两个出口：确认＝内容已转交，开始等；取消＝这次邀请作废（撤掉那条申请）。
           窗口上的 × 与「取消」都走 cancelNetworkInvite，行为一致。*/
        confirmNetworkInvite: function () {
            const pending = networkInvite;
            networkInvite = null;
            ui.window.close('netInvite');
            if (pending) pending.resolve(true);
            return true;
        },
        cancelNetworkInvite: function () {
            const pending = networkInvite;
            networkInvite = null;
            ui.window.close('netInvite');
            if (pending) pending.resolve(false);
            return true;
        },

        /* 新建协作向导 */
        createProject: function () { ui.wizard.open(); return true; },
        /* 卡片右上角的删除块（.edit）走这里，也可以从宿主脚本调 */
        deleteProject: function (id) { return actions.deleteProject(id); },
        /* 卡片菜单里的「重命名」与重命名窗口的「确定」（index.html 里那个按钮调的是 submitRename）*/
        renameProject: function (id) { return actions.renameProject(id); },
        submitRename: function () { return actions.submitRename(); },
        /* 「登记已有项目」：向导已按决定 11 改成这个语义。
           传本机项目目录（里面已经有 .tsunagou/project.json）就登记进项目索引，
           其余参数（name/objective）则会在中间层配置的 projects_root 下新建一个项目。
           给宿主脚本用，界面上不新加控件。*/
        registerProject: function (pathOrDraft) {
            const draft = isPlainObject(pathOrDraft) ? pathOrDraft : { path: pathOrDraft };
            return actions.createProject(draft);
        },
        wizardNext: function () { return ui.wizard.next(); },
        /* 向导的「上一步」：按钮留着，但它想做的事 = 撤回上一步的效果，而这件事
           暂不实现 —— 一句话说清楚。（低层导航 ui.wizard.prev() 仍在，给宿主脚本用）*/
        wizardPrev: function () { return notImplemented(); },
        wizardFinish: function () { return ui.wizard.finish(); },

        /* 添加子 Agent（向导第 3 步的小加号、Agent 管理页的大加号都走这里）
           options.source 标记这次是从哪开的（见 addSubAgentSource）。*/
        addSubAgent: function (options) {
            const node = byId('addSubAgent');
            if (!node) return false;
            const opts = options || {};
            if (opts.source) addSubAgentSource = (opts.source === 'wizard') ? 'wizard' : 'agents';
            ui.window.clearInputs(node);
            resetCsBox(subAgentVendorBox());
            resetCsBox(subAgentPlaceBox());
            syncSubAgentPlace();
            /* 只有真给了名字/厂商才回填，光传 source 不要清空表单 */
            if (opts.name !== undefined) {
                ui.window.fillInputs(node, [opts.name]);
            }
            if (opts.vendor !== undefined) {
                ui.choosebox.setValue(subAgentVendorBox(), opts.vendor, { silent: true });
            }
            ui.window.open(node);
            return true;
        },

        /* 四类通用组件的现场演示。原来挂在"设置 → DEBUG 选项"页的四个按钮上，
           该页已删除，这里保留为程序化调用入口（app.demo.*）。*/
        demo: {
            success: function () { notify.success({ title: '改动已成功保存' }); return true; },
            info: function () { notify.info('请至少选择一个Agent'); return true; },
            loading: function () {
                notify.loading('正在连接 Agent');
                setTimeout(function () { notify.loadingEnd(); }, 2000);
                return true;
            },
            decision: function () {
                return dialog.decision({
                    title: '需要用户确认/决定的信息',
                    content: '项目"Hello World"的子 Agent（Claude Code 051）试图将 main() 函数的 printf("%d",a) ' +
                        '关键位置改为 printf("%f",a)，主 Agent 认为这一改动可能会影响整个程序的输出结果，需要人工裁定。',
                    actions: [
                        { label: '忽略', value: 'ignore' },
                        { label: '查看详情', kind: 'important', value: 'detail' }
                    ]
                }).then(function (value) {
                    if (value === 'detail') app.demo.info('已打开详情（示例）');
                    return value;
                });
            }
        }
    });

    /* 点任意 .itemAdd（大加号 / 小加号）都是"加人"，但要分清是哪张页面上的：
       向导第 3 步的小加号在 #newXz3 里面，其余（Agent 管理页末尾那个大加号）算 Agent 列表。*/
    delegateClick(['.itemAdd'], function (node) {
        app.addSubAgent({ source: closest(node, '#newXz3') ? 'wizard' : 'agents' });
    });

    /* 左栏协作卡片：点卡片 = 选中它 + 进入项目工作区。 */
    function selectProjectCard(card) {
        qsa('#projList .projItem').forEach(function (node) {
            if (node === card) node.className = 'projItem projItemSelected';
            else node.classList.remove('projItemSelected');
        });
        const id = card.getAttribute('data-project-id');
        const list = toArray(state.get('projects', []));
        list.forEach(function (item) { item.selected = (toText(item.id) === toText(id)); });
        state.set('projects', list);
        emit('project:select', { id: id });
        return id;
    }

    function bindProjectCards() {
        delegateClick(['#projList .projItem'], function (card, event) {
            /* 点右上角那一块不属于"选这个项目" —— 它自己有一套（见下面的 .edit 绑定），
               这里直接让路，不然会先把项目打开、再弹出菜单。*/
            if (closest(event.target, '.edit')) return;
            const id = selectProjectCard(card);
            rememberProjViewed(id);
            app.openProject(id);
        });
        /* 卡片右上角那一块（.edit，CSS 里 hover 才露出来；样式已改成"修改"的笔）。
           点它不再直接删项目，而是弹出菜单：重命名 / 删除项目。再点一次收起。*/
        delegateClick(['#projList .projItem .edit'], function (node) {
            const card = closest(node, '.projItem');
            return toggleSelection('projMenu', node, card && card.getAttribute('data-project-id'));
        });
        /* 「进行中的协作」右边那个设置按钮：排这个列表的序（搜索按钮先留着不动）。
           再点一次收起 —— 开着的时候点它必须能关掉。*/
        delegateClick(['#projList .wkTbtn[data-tg-role="project-sort"]'], function (node) {
            return toggleSelection('sortMenu', node, '');
        });
        /* 项目操作菜单里的两项 */
        delegateClick(['#projMenu .item'], function (node) {
            const action = toText(node.getAttribute('data-proj-action'));
            const id = selectionProjectId;
            closeSelections();
            if (action === 'rename') return app.renameProject(id);
            if (action === 'delete') return app.deleteProject(id);
            return null;
        });
        /* 排序菜单：选规则或选方式，选完整列重排一次（并记住这个偏好）。*/
        delegateClick(['#sortMenu .item'], function (node) {
            const order = toText(node.getAttribute('data-sort-order'));
            const by = toText(node.getAttribute('data-sort-by'));
            if (order) projSort = { order: order, by: projSort.by };
            if (by) projSort = { order: projSort.order, by: by };
            saveProjSort();
            syncSortMenu();
            render.list(state.get('projects', []));
            return null;
        });
        /* 搜索：点放大镜 → 收起分组标题、放出搜索条并聚焦输入框；
           点搜索条里的 iconB → 收回去、清掉关键字（列表复原）。*/
        delegateClick(['#projList .wkTbtn[data-tg-role="project-search"]'], function () {
            closeSelections();
            projSearchOpen = true;
            applyProjectFilter();
            const input = qs('#projList .searchBar .left');
            if (input && input.focus) input.focus();
            return null;
        });
        delegateClick(['#projList .searchBar .iconB'], function () {
            projSearchOpen = false;
            projQuery = '';
            applyProjectFilter();
            return null;
        });
        /* 点菜单以外的地方 / 按 Esc 收起来。只绑一次：绑定函数可能被多次调用。*/
        if (!bindProjectCards.bound) {
            bindProjectCards.bound = true;
            /* 打字实时过滤。挂在 document 上再按选择器认：列会重画，元素会被换掉。*/
            document.addEventListener('input', function (event) {
                const input = closest(event.target, '#projList .searchBar .left');
                if (!input) return;
                projSearchOpen = true;
                projQuery = toText(input.value);
                applyProjectFilter();
            });
            document.addEventListener('click', function (event) {
                if (!openSelectionId) return;
                if (closest(event.target, '.selection')) return;
                if (closest(event.target, '.projItem .edit')) return;
                if (closest(event.target, '.wkTbtn[data-tg-role="project-sort"]')) return;
                closeSelections();
            }, true);
            document.addEventListener('keydown', function (event) {
                if (event.key === 'Escape') closeSelections();
            });
        }
    }

    /* 点 Agent 卡片的选中态（先只广播事件，具体功能后面再补） */
    delegateClick(['#pane-agents .boxerbox > .item .listfieldbox .item'], function (node) {
        emit('agent:select', { id: node.getAttribute('data-agent-id') || '' });
    });

    /* ---- 添加子 Agent 窗口里的"厂商 + 位置"那一对 ----------------------
       左边是厂商（.chooseboxE.TOG1），右边是位置（本机/网络，.chooseboxE.TOG0）。
       两个框的 class 都以 choosebox 开头，所以按修饰类点名 —— 不写"第一个 .choosebox"
       这种看顺序的写法：顺序会变，标签不会。*/

    function subAgentVendorBox() { return qs('#addSubAgent .choosebox.TOG1'); }
    function subAgentPlaceBox() { return qs('#addSubAgent .choosebox.TOG0'); }

    /* 需要"远端报号"的宿主：它们的会话名只有自己知道，主机签票前必须先拿到那个号。
       OpenCode 的会话名由主机起（ses_<名字>），所以它不用这一格 —— 主机直接发邀请即可。*/
    const NETWORK_NUMBER_VENDORS = ['Codex', 'DeepSeek Harness'];

    function networkNeedsNumber(vendor) {
        return NETWORK_NUMBER_VENDORS.indexOf(toText(vendor).trim()) >= 0;
    }

    /* 位置选"网络"**并且**厂商是"会话名自己说了算"的那两个时，才要那个号。
       显示/隐藏只动 display：显示清成空串交回 CSS，隐藏写 none —— 不往元素上写布局样式。
       比对的是选项文字：选择框的值本来就是选项文字（见 selectCsOption），没有 data-value。*/
    function syncSubAgentPlace() {
        const field = byId('addSubAgentAddr');
        if (!field) return;
        const network = toText(ui.choosebox.value(subAgentPlaceBox())).trim() === '网络';
        const vendor = ui.choosebox.value(subAgentVendorBox());
        field.style.display = (network && networkNeedsNumber(vendor)) ? '' : 'none';
    }

    /* ---- 静态窗口里的按钮 ------------------------------------------------ */

    function bindStaticWindowButtons() {
        /* 位置或厂商一变，那个"网络 Agent 编号"输入框跟着显/隐 */
        const place = subAgentPlaceBox();
        if (place) place.addEventListener('choosebox:change', function () { syncSubAgentPlace(); });
        const vendor = subAgentVendorBox();
        if (vendor) vendor.addEventListener('choosebox:change', function () { syncSubAgentPlace(); });
        delegateClick(['#addSubAgent .options .buttonbox2active'], function () {
            /* 窗口里有一个名称输入框 + 厂商/位置两个选择框（网络+那两个厂商时多一个编号输入框）*/
            const input = qs('#addSubAgent input');
            const number = qs('#addSubAgentAddr input', byId('addSubAgent'));
            actions.addSubAgent({
                name: toText(input && input.value).trim(),
                vendor: ui.choosebox.value(subAgentVendorBox()),
                place: toText(ui.choosebox.value(subAgentPlaceBox())).trim() === '网络' ? 'network' : 'local',
                number: toText(number && number.value).trim()
            });
        });
        /* 向导第 3 步子 Agent 胶囊上的「×」是 CSS 画的（.itemC::before，hover 才滑出来）：
           点它 = 删掉这个已接入的 Agent，后端还没装配 —— 如实说，不假装删掉。*/
        delegateClick(['#newXz3 .listfieldbox .itemC'], function () {
            return actions.removeAgent();
        });
        delegateClick(['#mgrAgent .inner .table .item'], function (node) {
            app.openAgentInfo(node.getAttribute('data-agent-id'));
        });
    }

    /* 向导第 2 步：厂商选择框一变、名称输入框一改，"你所选的 Agent"预览框跟着刷新 */
    function bindWizardDetect() {
        const box = wizardVendorBox(2);
        if (box) box.addEventListener('choosebox:change', function () { actions.detectMainAgent(); });
        const input = wizardInputs(2)[0];
        if (input) input.addEventListener('input', function () { actions.detectMainAgent(); });
    }

    /* ---- 设置窗口里的下拉框（现在只剩"颜色主题"）------------------------- */

    function bindSettingChooseboxes() {
        document.addEventListener('choosebox:change', function (event) {
            const panel = event.detail.panel;
            /* 只管设置窗口里的下拉框：向导 / 添加子 Agent 的"厂商"选择框
               不能被当成"改了设置"（面板 id 已各自独立，这里再按窗口收一道口）。*/
            if (!panel || !closest(panel, '#setPanel')) return;
            if (panel.id === 'uSetCol1') {
                app.setTheme(event.detail.value);
                actions.saveSetting('theme', event.detail.value);
            }
        });
    }

    /* ---- 主题 ------------------------------------------------------------ */

    /* 只做两件事：改写 :root 上的颜色变量 + 把成对的配图切成 -l / -d 版。
       深色值 = style.css 里 :root 的原始值；浅色值 = 明暗反相。*/
    const THEME_VARS = {
        dark: {
            '--col-1': '#151517', '--col-1-a': '#1515178a', '--col-1-5': '#1a1a1a',
            '--col-2': '#1D1D1F', '--col-3': '#2C2C2E', '--col-4': '#303435',
            '--col-4-5': '#3B3B3B', '--col-5': '#595959', '--col-6': '#999999',
            '--col-7': '#C9C9C9', '--col-7-5': '#E4E4E4', '--col-8': 'white'
        },
        light: {
            '--col-1': '#FFFFFF', '--col-1-a': '#FFFFFFB3', '--col-1-5': '#E8E8EC',
            '--col-2': '#F4F4F7', '--col-3': '#E9E9EE', '--col-4': '#DFDFE5',
            '--col-4-5': '#D6D6DD', '--col-5': '#B9B9C1', '--col-6': '#7C7C85',
            '--col-7': '#414149', '--col-7-5': '#1F1F26', '--col-8': '#111114'
        }
    };

    /* 当前生效的主题（'dark' / 'light'）：hover 换图标颜色时要判断 */
    let currentThemeName = 'dark';

    /* 配图：-l 是白色版（深色模式用），-d 是深色版（浅色模式用） */
    function applyThemeImages(light) {
        const suffix = light ? '-d.png' : '-l.png';
        qsa('img').forEach(function (img) {
            const src = img.getAttribute('src');
            if (!src || !/-[ld]\.png$/i.test(src)) return;
            img.setAttribute('src', src.replace(/-[ld]\.png$/i, suffix));
        });
    }

    app.setTheme = function (mode) {
        const wanted = toText(mode) || '深色'; /* 不传参时按深色，不要写进 undefined */
        const name = (wanted === '浅色' || wanted === 'light') ? 'light' : 'dark';
        const style = document.documentElement.style;
        Object.keys(THEME_VARS[name]).forEach(function (key) {
            style.setProperty(key, THEME_VARS[name][key]);
        });
        applyThemeImages(name === 'light');
        currentThemeName = name;
        state.set('settings.theme', wanted);
        /* 回填下拉框：值不同才写，而且走 silent —— 回填不是用户操作，
           不该派发 choosebox:change（否则会反过来再进一次主题切换）。*/
        const box = qs('#uSet1 .choosebox');
        if (box && ui.choosebox.value(box) !== wanted) ui.choosebox.setValue(box, wanted, { silent: true });
        emit('theme:change', { mode: wanted, resolved: name });
        return name;
    };

    /* ---- 反向通道：dispatch ---------------------------------------------- */

    /* 路由表：type → 处理函数，payload 就是后端给的数据 */
    const DISPATCH_ROUTES = {
        /* 全量 / 增量数据 */
        'state.replace': function (payload) { state.replace(payload); render.all(); },
        'state.patch': function (payload) { state.patch(payload); render.all(); },
        'state.reset': function () { state.reset(); render.all(); },
        'render.all': function () { render.all(); },

        'project.list': function (payload) { projectListLoaded = true; state.set('projects', payload); render.list(payload); },
        'project.current': function (payload) { state.set('project', payload); render.overview(payload); },
        'agent.list': function (payload) {
            state.set('agents', payload);
            render.agents(payload);
            /* 总路径的操作人名字与主 Agent 配色要用 agents，重绘一次补上 */
            render.timeline(state.get('timeline', []));
        },
        'agent.window': function (payload) { state.set('agentsWindow', payload); render.agentWindow(payload); },
        'agent.info': function (payload) { render.agentInfoWindow(payload); ui.window.open('mgrAgentInfo'); },
        /* 网络接入标记（跨机器）：中间层推一条就把徽标改掉，不用等下一次刷新。
           payload：{agent_id, online} = 网络接入（在线/离线）；
                    {agent_id, network:false} 或 `agent.network.clear` = 撇回本机（不画）。*/
        'agent.network': function (payload) {
            const data = payload || {};
            return app.setAgentNetwork(data.agent_id || data.id, data);
        },
        'agent.network.clear': function (payload) {
            const data = isPlainObject(payload) ? payload : { agent_id: payload };
            return app.clearAgentNetwork(data.agent_id || data.id);
        },
        'task.list': function (payload) { state.set('tasks', payload); render.tasks(payload); },
        'task.detail': function (payload) { state.set('taskDetail', payload); return payload; },
        'conflict.data': function (payload) { state.set('conflicts', payload); render.conflicts(payload); },
        'audit.data': function (payload) { state.set('audits', payload); render.audit(payload); },
        'workspace.list': function (payload) { state.set('workspaces', payload); render.workspaces(payload); },
        'acceptance.data': function (payload) { state.set('acceptance', payload); render.acceptance(payload); },
        'checkpoint.list': function (payload) { state.set('checkpoints', payload); render.acceptance(state.get('acceptance', {})); },
        'checkpoint.failures': function (payload) {
            /* 这一屏要三个出口凑（提案/验收情况、存档点、存档失败），谁后到谁重绘一次 ——
               重绘函数自己会从 state 里把另外两份取齐。*/
            state.set('checkpointFailures', payload);
            render.acceptance(state.get('acceptance', {}));
        },
        'timeline.list': function (payload) { state.set('timeline', payload); render.timeline(payload); },
        'settings.data': function (payload) {
            /* 这份 payload 就是中间层的用户档案（/console/profile：昵称、主题、
               Agent 昵称与厂商）。两处要用它：系统设置面板读 settings，
               而 agentProfileEntry / 总路径的名字读 profile —— 都要给到，
               否则"在档案里改昵称"不会反映到任何显示名字的地方。*/
            state.set('profile', payload);
            state.set('settings', payload);
            render.settings(payload);
            /* 改完昵称/厂商要立刻反映到总路径那一列操作人与左栏项目卡片上 */
            render.timeline(state.get('timeline', []));
            render.list(state.get('projects', []));
            /* 存在中间层档案里的主题也是主题：拉回来就应用
               （值就是选择框里的选项文字，与 index.html 里的写法一致）。*/
            if (isPlainObject(payload) && payload.theme) app.setTheme(payload.theme);
        },
        'glossary.data': function (payload) {
            /* 后端参数值的中文对照表（中间层维护，见 console/glossary.py）。
               它通常比项目数据先到，拿回来就整页重绘一次 —— 这样每个渲染器
               只管查表，不必自己盯着"词表到没到"。*/
            state.set('glossary', payload);
            render.all();
        },
        'hosts.data': function (payload) { state.set('hosts', payload); },
        'wizard.subAgents': function (payload) { state.set('wizard.draftSubAgents', payload); render.wizardSubAgents(payload); },

        /* 反馈 */
        'notify.success': function (payload) { notify.success(payload); },
        'notify.info': function (payload) {
            if (isPlainObject(payload)) notify.info(payload.text, payload); else notify.info(payload);
        },
        'notify.error': function (payload) {
            if (isPlainObject(payload)) notify.error(payload.text, payload); else notify.error(payload);
        },
        'notify.loading': function (payload) { notify.loading(isPlainObject(payload) ? payload.text : payload); },
        'notify.loading.hide': function () { notify.loadingEnd(); },
        'dialog.confirm': function (payload) { return dialog.confirm(payload); },
        'dialog.decision': function (payload) { return dialog.decision(payload); },

        /* 界面控制 */
        'ui.window.open': function (payload) { return ui.window.open(isPlainObject(payload) ? payload.id : payload); },
        'ui.window.close': function (payload) { return ui.window.close(isPlainObject(payload) ? payload.id : payload); },
        'ui.window.closeAll': function () { return ui.window.closeAll(); },
        'ui.workspace': function (payload) { return ui.workspace.show(payload); },
        'ui.sidebar': function (payload) { return (payload === 'fold' || payload === true) ? ui.sidebar.fold() : ui.sidebar.unfold(); },
        'ui.tab': function (payload) { return ui.tabs.project(isPlainObject(payload) ? payload.slug : payload); },
        'ui.project.open': function (payload) { return app.openProject(isPlainObject(payload) ? payload.id : payload); },
        'ui.workspace.home': function () { return app.openHome(); },
        'ui.blocktab': function (payload) {
            const data = isPlainObject(payload) ? payload : { block: 'conflict', index: payload };
            return ui.blockTabs.select(data.block, data.index);
        },
        'ui.settingtab': function (payload) { return ui.settingTabs.select(payload); },
        'ui.wizard.go': function (payload) { return ui.wizard.go(payload); },
        'ui.aside.show': function (payload) {
            const data = isPlainObject(payload) ? payload : { slug: payload };
            return ui.aside.show(data.slug, data.section);
        },
        'ui.aside.hide': function (payload) { return ui.aside.hide(payload); },
        'ui.aside.hideAll': function () { return ui.aside.hideAll(); },
        'ui.choosebox.set': function (payload) {
            const data = payload || {};
            const panel = byId(data.panel);
            const box = data.selector ? qs(data.selector) : (panel ? findCsBox(panel) : resolveEl(data.box));
            return ui.choosebox.setValue(box, data.value);
        },
        'theme.set': function (payload) { return app.setTheme(payload); }
    };

    /* 后端 / 宿主脚本的统一入口：
       Tsunagou.dispatch({type:'task.list', payload:[...]})
       Tsunagou.dispatch('ui.tab', 'tasks') */
    Tsunagou.dispatch = function (message, payload) {
        const msg = (typeof message === 'string') ? { type: message, payload: payload } : (message || {});
        const type = toText(msg.type);
        const route = DISPATCH_ROUTES[type];
        if (!route) {
            const error = new Error('未知的 dispatch 类型：' + type);
            emit('dispatch:error', { type: type, error: error });
            return { ok: false, type: type, error: error.message };
        }
        try {
            const result = route(msg.payload);
            if (result && typeof result.then === 'function') {
                return result.then(function (value) { return { ok: true, type: type, value: value }; },
                    function (error) { return { ok: false, type: type, error: error.message }; });
            }
            return { ok: true, type: type, value: result };
        } catch (error) {
            emit('dispatch:error', { type: type, error: error });
            return { ok: false, type: type, error: error.message };
        }
    };

    Tsunagou.types = function () { return Object.keys(DISPATCH_ROUTES); };

    /* ---- 从后端刷新 ------------------------------------------------------ */

    /* 需要"当前项目"才能请求的数据键（路径里带 {project}）。
       只有列在这里的键才会在 openProject 时一次性拉回；其余键不依赖项目。*/
    const PROJECT_SCOPED_KEYS = [
        'project', 'agents', 'tasks', 'audits', 'workspaces',
        'conflicts', 'acceptance', 'checkpoints', 'checkpointFailures', 'timeline'
    ];

    /* 前端主动拉取的唯一入口：一次 GET 配一个 dispatch 处理器（见下表）。*/
    const REFRESH_ROUTES = [
        ['projects', 'project.list'],
        ['agentsWindow', 'agent.window'],
        ['settings', 'settings.data'],
        ['glossary', 'glossary.data'],
        ['hosts', 'hosts.data'],
        ['project', 'project.current'],
        ['agents', 'agent.list'],
        ['tasks', 'task.list'],
        ['conflicts', 'conflict.data'],
        ['audits', 'audit.data'],
        ['workspaces', 'workspace.list'],
        ['acceptance', 'acceptance.data'],
        ['checkpoints', 'checkpoint.list'],
        ['checkpointFailures', 'checkpoint.failures'],
        ['timeline', 'timeline.list']
    ];

    /* ========================================================================
     * 后端形状 → 界面形状
     * ------------------------------------------------------------------------
     * 真后端返回的是领域原语（{items:[...]}、字符串状态…），渲染器要的是展示形状
     * （见 method.md §7）。转换只在这张表里做一处：后端补了字段，只改这里。
     * 后端暂时给不出的字段一律留空 —— 界面显示空状态，不编造数据。
     * ====================================================================== */

    /* 后端任务状态（字符串） → CSS 的 .st-1…13（文案在 style.css 里，别在这里改）。
       顺序**照 style.css 的 ::after 文案**排，不是照后端自己的枚举顺序：
       1 草稿 · 2 已就绪 · 3 待认领 · 4 已认领 · 5 执行中 · 6 卡住了 · 7 待验收 ·
       8 被打回 · 9 取消中 · 10 执行者丢失 · 11 已完成 · 12 失败 · 13 已取消。
       （原来这份表从 `submitted` 起就错位了：`submitted→6` 会显示成「卡住了」、
       `blocked→9` 会显示成「取消中」……照 CSS 的文案逐个数一遍才是对的。）*/
    const TASK_STATUS_NUMBER = {
        draft: 1, ready: 2, open: 3, claimed: 4, running: 5, blocked: 6, submitted: 7,
        changes_requested: 8, cancel_requested: 9, orphaned: 10, completed: 11,
        failed: 12, cancelled: 13
    };

    /* —— 后端参数值的中文 ——
       词表在**中间层**（console/glossary.py，经 GET /console/glossary 取回），
       这里只负责查表。两条纪律：
         · 只用在**要显示给人看**的地方；判断逻辑一律拿原值（如 status === 'active'）；
         · 表里没有的值原样显示 —— 宁可难看，也不编一个中文出来。*/
    function glossText(domain, value) {
        const token = toText(value);
        if (!token) return '';
        const table = state.get('glossary.domains.' + toText(domain), {}) || {};
        return toText(table[token]) || token;
    }

    /* 同一次查表，但"表里没有"返回空串 —— 调用方要靠这个区别决定要不要退回原样。
       （glossText 兜底返回原 token，适合"查不到就直接显示"，不适合"查到了才改写"。）*/
    function glossWord(domain, value) {
        const token = toText(value);
        if (!token) return '';
        const table = state.get('glossary.domains.' + toText(domain), {}) || {};
        return toText(table[token]);
    }

    /* 总路径的「操作」列：命令名 → 短中文。
       被拒的写操作在账本里叫 `command.<命令>.denied`，先剥掉这层壳再查表，
       查到就补一句「（被拒）」；查不到仍旧原样印（词表的规矩：不编）。*/
    function actionText(action) {
        const raw = toText(action);
        if (!raw) return '';
        const denied = /\.denied$/.test(raw);
        const kind = raw.replace(/^command\./, '').replace(/\.denied$/, '');
        return (glossWord('command_kind', kind) || kind) + (denied ? '（被拒）' : '');
    }

    /* 引用（`task/<id>`、`ticket/0`、`session/<id>`…）→「种类 + 短号」。
       以前是整串截 8 个字符，于是 `session/<uuid>` 显示成 "session/"、谁也不是。
       前缀认不出来才退回原来的截法。短号必须留着：人要靠它跟别的屏对上。*/
    function refText(ref) {
        const text = toText(ref);
        if (!text) return '';
        const at = text.indexOf('/');
        const noun = glossWord('ref_kind', at < 0 ? text : text.slice(0, at));
        if (!noun) return shortId(text);
        const key = at < 0 ? '' : text.slice(at + 1);
        return key ? (noun + ' ' + shortId(key)) : noun;
    }

    /* 词表里的**整张域** → 一组标签 {text, ok}。
       用在"这一栏有哪几项、每项叫什么"的地方，比如 Agent 管理的基础能力（4 项）
       与运营能力（7 项）：名字与顺序都跟着词表走，页面不自己维护一份名单。
       missing 是后端说"缺哪几项"的名字表；传 null（读不到会话/没接入）时返回空数组，
       那一栏就不画 —— 不把"不知道"画成"都没有"。*/
    function glossTags(domain, missing) {
        if (!Array.isArray(missing)) return [];
        const table = state.get('glossary.domains.' + toText(domain), {}) || {};
        const absent = missing.map(toText);
        return Object.keys(table).map(function (name) {
            return { text: toText(table[name]), ok: absent.indexOf(name) < 0 };
        });
    }

    /* 总路径/审计里的 subject_ref → 给人看的标题。
       `task/<id>` 能在当前任务名单里找到就写标题，`project/<id>` 写项目名；
       找不到（跨代、别的项目、任务已不在名单里）退回空串，调用方再用 id 缩写兑底 ——
       历史不会因为指名道姓而变准，但能对上时就别拿 id 糊人。*/
    function subjectLabel(ref) {
        const text = toText(ref);
        if (!text) return '';
        const at = text.indexOf('/');
        if (at < 0) return '';
        const kind = text.slice(0, at);
        const key = text.slice(at + 1);
        if (kind === 'task') {
            const task = findById(state.get('tasks', []), key);
            return task ? toText(task.title) : '';
        }
        if (kind === 'project') {
            const project = findById(state.get('projects', []), key);
            return project ? toText(project.name) : '';
        }
        return '';
    }

    /* 事件后面那句括注（审计出口的 reason_code）→ 中文。两种来源同一栏：
       写操作被拒的原因码（denial_reason），以及事件自己那句"为什么"
       （event_reason：用户裁决、后台作业重试用尽…）。码可能带参数
       （`resource_conflict:file:src/x.py`），所以只查冒号前那截、后面原样保留；
       两张表都没命中就把整串原样返回 —— 宁可难看，也不编一个中文出来。*/
    function reasonText(code) {
        const text = toText(code);
        if (!text) return '';
        const at = text.indexOf(':');
        const head = at < 0 ? text : text.slice(0, at);
        const tail = at < 0 ? '' : text.slice(at);
        const word = glossWord('denial_reason', head) || glossWord('event_reason', head);
        return word ? (word + tail) : text;
    }

    /* 能力名 → 中文。11 项基线分成两张表（4 项准入 / 7 项运营），名字都只写一遍，
       所以先查准入再查运营；两边都没就原样返回 —— 不编一个名字出来。*/
    function capabilityText(name) {
        const token = toText(name);
        if (!token) return '';
        const admission = state.get('glossary.domains.capability_admission', {}) || {};
        const operational = state.get('glossary.domains.capability_operational', {}) || {};
        return toText(admission[token]) || toText(operational[token]) || token;
    }

    /* 会话事件（入会话/重接/重连）后面那句括注：**那刻**会话是降级还是通过、缺哪几项。
       后端只在这类事件上带 session_status / missing_admission（别的命令不做会话判定），
       没这两个字段就返回空串 —— 老事件不补，也不猜。*/
    function sessionNote(event) {
        const status = toText(event.session_status);
        if (!status) return '';
        if (status === 'degraded') {
            const missing = toArray(event.missing_admission).map(capabilityText).filter(Boolean);
            return missing.length ? ('降级：缺 ' + missing.join('、')) : '降级';
        }
        if (status === 'ended') return '已结束';
        /* 第一次入会话叫"已就绪"；重接/重连是先降级再修回来，所以叫"已恢复"。*/
        return toText(event.action) === 'agent.enroll' ? '已就绪：能力全通过' : '已恢复：能力全通过';
    }

    function backendItems(raw) {
        if (Array.isArray(raw)) return raw;
        if (isPlainObject(raw) && Array.isArray(raw.items)) return raw.items;
        return [];
    }

    function shortId(value) {
        const s = toText(value);
        return s.length > 8 ? s.slice(0, 8) : s;
    }

    /* 摘要类 ref 都带 `sha256:` 前缀，而 shortId 只截 8 个字符 —— 直接套的话截到的是
       前缀本身（页面上会显示成 “sha256:b”）。摘要的本意是“能对上号”，所以先去掉前缀。*/
    function shortDigest(value) {
        return shortId(toText(value).replace(/^sha256:/, ''));
    }

    /* ---- 时间显示 --------------------------------------------------------

       表里只写"9月28日16:05:02"这种颗粒度：不带毫秒，本年不写年份，跨年才写；
       毫秒只在详情（侧栏）里给 —— formatTime(value, { precise: true })。
       解析不了的值原样返回：宁可难看，也不编一个时间出来。本地时区。*/

    function pad2(value) {
        return (value < 10 ? '0' : '') + value;
    }

    function formatTime(value, options) {
        const text = toText(value);
        if (!text) return '';
        const at = new Date(text);
        if (isNaN(at.getTime())) return text;
        const opts = options || {};
        const head = (at.getFullYear() === new Date().getFullYear()) ? '' : (at.getFullYear() + '年');
        let clock = pad2(at.getHours()) + ':' + pad2(at.getMinutes());
        if (opts.second !== false) clock += ':' + pad2(at.getSeconds());
        if (opts.precise) clock += '.' + ('00' + at.getMilliseconds()).slice(-3);
        return head + (at.getMonth() + 1) + '月' + at.getDate() + '日' + clock;
    }

    /* Attempt 的时间在出口里是 **epoch 秒**（`container.py` 的 `attempts` 出口原样给
       `attempt.started_at`，是个 float），而别处的时间都是 RFC3339 串。这里先把秒换成
       `formatTime` 认识的那一种；不是正数就原样交回去（宁可难看，也不编一个时间）。*/
    function epochSecondsTime(value) {
        const number = typeof value === 'number' ? value : Number(toText(value));
        if (!isFinite(number) || number <= 0) return value;
        return new Date(number * 1000).toISOString();
    }

    /* 记账类的时间戳（`operations` 表）是 **epoch 毫秒**（`now_ms()`），而 formatTime
       认的是 RFC3339 串：数字直接丢进去会当成非法日期字符串原样退回来。
       已经是字符串的（ISO）不动 —— Number('2026-…') 是 NaN，自然走过。*/
    function epochMillisTime(value) {
        const number = typeof value === 'number' ? value : Number(toText(value));
        if (!isFinite(number) || number <= 0) return value;
        return new Date(number).toISOString();
    }

    function leaseState(lease) {
        /* 括号里的"还剩/已到期"是页面自己算的展示补充；状态本身走词表。*/
        const status = toText(lease.status);
        const shown = glossText('lease_status', status) || '未知';
        if (!lease.expires_at) return { text: shown, ok: status === 'active' };
        const left = Math.round(Number(lease.expires_at) - Date.now() / 1000);
        return {
            text: left > 0 ? (shown + '（还剩 ' + Math.round(left / 60) + ' 分钟）') : (shown + '（已到期）'),
            ok: status === 'active' && left > 0
        };
    }

    /* ---- 人的名字从哪里来 ------------------------------------------------

       Agent 的昵称与厂商不是协作事实（协议里没有这个概念），它们存在中间层的
       用户档案里（GET /console/profile 的 agents 表）。所以这里一律：
       档案里的昵称 > 演示数据里的昵称 > 项目里真实存在的 agent_id 缩写。*/

    function agentProfileEntry(agent) {
        const agents = state.get('profile.agents', {}) || {};
        const entry = agents[toText(agent && agent.agent_id)];
        return isPlainObject(entry) ? entry : {};
    }

    function agentDisplayName(agent) {
        const entry = agentProfileEntry(agent);
        return toText(entry.nickname) || toText(agent && agent.nickname) || shortId(agent && agent.agent_id);
    }

    function agentVendor(agent) {
        const entry = agentProfileEntry(agent);
        return toText(entry.vendor) || toText(agent && agent.vendor);
    }

    function agentsById(list) {
        const table = {};
        toArray(list).forEach(function (agent) {
            if (agent && toText(agent.agent_id)) table[toText(agent.agent_id)] = agent;
        });
        return table;
    }

    /* 界面上选的厂商 → 中间层的宿主行（GET /console/hosts，表在 platform/host_registration.py）。
       匹配 adapter 名或显示名都行；"支不支持、跑什么命令"由中间层那张表决定，
       页面不维护第二份名单（否则加一个厂商要改两种语言）。
       选项文字可能带着"（待实现）"这类后缀（页面上要如实标出来，见 index.html 的
       data-disabled），比对前先去掉它 —— 中间层表里的显示名是干净的名字。*/
    function vendorName(value) {
        return toText(value).replace(/（待实现）\s*$/, '').trim().toLowerCase();
    }

    function hostFor(vendor) {
        const wanted = vendorName(vendor);
        if (!wanted) return null;
        return toArray(state.get('hosts', [])).filter(function (host) {
            return toText(host.adapter).toLowerCase() === wanted
                || vendorName(host.label) === wanted;
        })[0] || null;
    }

    /* 这个厂商点了"下一步"会怎样：
         · console —— 页面能办完：签票、写配置，然后等那条会话来兑换；
         · in_host —— 页面办不完，但**等得起**：开同一块等待遮罩，看名单里它什么时候
           出现（中间层拿接入材料当证据，见 connectInHostAgent）—— 所以这里不挡；
         · unsupported —— 连宿主动作都还没有，只能红字说明。
       能签票的只有 console 一种：别的模式一律不发准备请求、不假装排队。*/
    function hostEnrollBlocker(host) {
        const mode = toText((host || {}).mode) || 'unsupported';
        if (mode === 'console' || mode === 'in_host') return null;
        const label = toText((host || {}).label) || toText((host || {}).adapter) || '这个宿主';
        return {
            mode: mode,
            note: toText((host || {}).note)
                || (label + ' 的 MCP 注册还没实现，暂时不能从网页接入')
        };
    }

    /* 等宿主把 Agent 连上：每 2 秒问一次中间层"到了没有"，直到到了 / 票过期 /
       人把加载遮罩关掉。中间层每次都会重读项目名单（指纹没变就复用缓存），
       所以轮询很便宜，也不会因为网络抖一下就让人重新来一遍。*/
    const ENROLLMENT_POLL_MS = 2000;

    function waitForEnrollment(enrollmentId, label, onWaiting) {
        const template = pathTemplate('enrollment');
        const path = template.split('{enrollment}').join(encodeURIComponent(enrollmentId));
        return new Promise(function (resolve) {
            if (!enrollmentId || !template) return resolve({ status: 'unknown' });
            let stopped = false;
            let timer = null;
            const stop = function (outcome) {
                if (stopped) return;
                stopped = true;
                if (timer) clearTimeout(timer);
                resolve(outcome);
            };
            const tick = function () {
                if (stopped) return;
                /* 遮罩是"正在等"的可见信号：人把它关了，就是不等了。
                   但「取消等待」的确认框会先把遮罩收起来 —— 那一瞬间不算放弃。*/
                if (!ui.window.isOpen('loadW') && !notify.cancelPending()) return stop({ status: 'dismissed' });
                api.get(path, null, { silent: true }).then(function (answer) {
                    const status = toText(answer && answer.status);
                    if (status === 'arrived') return stop({ status: 'arrived', agent: answer });
                    if (status === 'expired') return stop({ status: 'expired', agent: answer });
                    if (status === 'cancelled') return stop({ status: 'cancelled', agent: answer });
                    /* “还没就位”也算一种进展：把中间层给的缺项和"该做什么"换到遮罩上。*/
                    if (typeof onWaiting === 'function') onWaiting(answer || {});
                    timer = setTimeout(tick, ENROLLMENT_POLL_MS);
                }, function () {
                    /* 一次问不到不算失败：接着等下一次。*/
                    timer = setTimeout(tick, ENROLLMENT_POLL_MS);
                });
            };
            timer = setTimeout(tick, ENROLLMENT_POLL_MS);
            emit('enrollment:waiting', { enrollment_id: enrollmentId, label: label });
        });
    }

    /* 宿主登记没能自动完成时，把那条要人手工跑的命令拿出来（中间层的报告里就是字符串）*/
    function firstCommand(registration) {
        const commands = toArray((registration || {}).commands);
        return commands.length ? toText(commands[0]) : '';
    }

    /* 要人手工配置宿主时的一句人话：优先用中间层给的理由（例如"没找到 codex 命令"），
       没有理由才退回那条命令本身。提示条放不下一整条带 --env 的命令，所以默认不说命令。*/
    function manualNote(registration, host) {
        const note = toText((registration || {}).note);
        if (note) return note;
        const command = firstCommand(registration);
        if (command) return '这个宿主要人手工把 bridge 写进它的 MCP 配置：' + command;
        return '还没能把这次接入写进 ' + (toText((host || {}).label) || '宿主') + ' 的配置';
    }

    /* 当前项目的目录：中间层知道（一个 daemon 只服务一个项目，概况出口不含文件路径），
       所以从项目列表里按 id 取。取不到就返回空串，由调用方换一句不含路径的说法。*/
    function currentProjectPath() {
        const id = toText(state.get('currentProjectId'));
        if (!id) return '';
        const known = findById(state.get('projects', []), id) || {};
        return toText(known.path);
    }

    /* 项目确认完成（或已归档）之后，"只能在做项目时用"的入口就该消失：再接一个 Agent、
       再存一档、再任命主 Agent —— 都没有意义了。判据只有一处：项目自己那份
       `.tsunagou/project.json` 里的 lifecycle（中间层随项目列表给过来），
       所以 daemon 停着也判得出来。删项目、校验存档点、重试存档不受影响：
       清理与"把没存成的那一档补上"恰恰是完工之后还需要做的事。*/
    function projectFinished() {
        const id = toText(state.get('currentProjectId'));
        if (!id) return false;
        const known = findById(state.get('projects', []), id) || {};
        const lifecycle = toText(known.lifecycle);
        return lifecycle === 'completed' || lifecycle === 'archived';
    }

    /* 进度和下一步由中间层判断：已认领、登记、工具加载与原会话回执是不同阶段。
       尤其不能把“再读一次上下文”描述成所有失败都能修好的保证。*/
    function joiningNote(answer, host) {
        const note = toText(answer.note);
        if (note) return note;
        const pending = isPlainObject(answer.pending) ? answer.pending : null;
        if (!pending) return '';
        const label = toText((host || {}).label) || '宿主';
        const missing = toArray(pending.missing_admission).map(toText).filter(Boolean);
        const path = currentProjectPath();
        return '“' + label + '”那边的会话已经连上了，但还没就位' +
            (missing.length ? '（还缺：' + missing.join('、') + '）' : '') +
            '。请在' + (path ? '“' + path + '”下' : '那边') +
            '让它检查接入状态，并确认原会话能读取项目上下文。正在等待连接';
    }

    /* 两个向导共用入口：Codex 项目和角色取自申请，只需在目标聊天说一句话；
       其他宿主仍需要目录与加载提示来读取对应项目的规则。*/
    function openWindowHint(host, phrase) {
        const label = toText((host || {}).label) || '宿主';
        if (toText((host || {}).adapter).toLowerCase() === 'codex') {
            return '请在要接入的 Codex 当前对话中说“请接入 Tsunagou”。正在等待连接';
        }
        const path = currentProjectPath();
        return '请在“' + (path || '这个项目所在的目录') + '”下打开/重载 ' + label +
            ' 窗口，让它' + (phrase || '') + '接入 Tsunagou。正在等待连接';
    }

    /* ---- 接入一个 Agent：准备 → 等原宿主会话就绪 ----

       Codex 准备的是唯一待认领申请（deferred），其余宿主保留签票/登记流程。
       成功由中间层核验本次身份与原会话回执，页面不通过名单新增来猜测。
       取消是否成功也以中间层回答为准，409 仍继续等，不移除共享 MCP。
       回调得到的 status：
         arrived    —— 连上了（中间层已经把昵称写进档案）
         manual     —— 宿主没法自动注册（没装 CLI / 还没实现），票与配置已备好，要人手工接
         expired    —— 票过期，这次作废
         cancelled  —— 人在确认框里选了取消接入
         dismissed  —— 遮罩被别的操作收掉了，停止等待（票还有效）
         failed     —— 请求本身失败（提示已由 api 弹过）*/
    /* 把"这张票是给哪个厂商的、这个 Agent 叫什么"记进用户档案。
       卡片上的 logo 与昵称都是按 agent_id 从档案里现算的 —— 不记下来，
       那个 Agent 就只能一直显示默认图标和代号。失败就算了：这只是显示层。*/
    function rememberAgentProfile(agentId, nickname, vendor) {
        const id = toText(agentId);
        const label = toText(vendor);
        if (!id || !label) return Promise.resolve(false);
        const agents = {};
        agents[id] = { nickname: toText(nickname), vendor: label };
        return api.post('settingSave', { patch: { agents: agents } }, { silent: true })
            .then(function (stored) {
                state.set('profile', stored);
                state.set('settings', stored);
                return true;
            }, function () { return false; });
    }

    let enrollmentFlowActive = false;

    function enrollmentSelectionNote(enrollment) {
        const id = toText((enrollment || {}).project_id);
        const project = findById(state.get('projects', []), id) || {};
        const role = toText((enrollment || {}).role) === 'main' ? '主 Agent' : '子 Agent';
        return '项目“' + (toText(project.name) || id || '原项目') + '”的' + role + '：';
    }

    /* 宿主自己接入（`in_host`）时遮罩上那句话：中间层给的那句指路（"在目标聊天里让它
       接入 Tsunagou"）+ 这次要接的身份 + 一句"我在这儿看着"。页面不自己编步骤 ——
       去哪条聊天、说什么，都是宿主表里写好的那一句。有项目目录就带上：那条聊天得开在
       这个项目里才最省事（工作目录不是项目时，由机器上那条待接入记录兜底，见
       connectInHostAgent）。身份要写出来：那条聊天把它交给 `tsunagou_connect` 的 `role`，
       而机器上那条记录会压过任何不一致的说法（冲突直接拒绝）。*/
    function inHostHint(host, role) {
        const label = toText((host || {}).label) || '这个宿主';
        const note = toText((host || {}).note)
            || ('请在 ' + label + ' 自己的项目聊天里让它接入 Tsunagou。');
        const path = currentProjectPath();
        const as = toText(role) === 'main' ? '以主 Agent 身份接入' : '以子 Agent 身份接入';
        return (path ? ('请在“' + path + '”下：') : '') + note +
            '（本次' + as + '）正在等待它出现';
    }

    /* 等一个"在自己聊天里接入"的宿主出现：没有票可问，所以每 2 秒问一次中间层
       "名单里出现它了吗"。三种收场和等票那套一样（到了 / 人不看了 / 等太久），
       只是没有"票过期"——因为这里根本没有票。*/
    const HOST_ARRIVAL_TIMEOUT_MS = 15 * 60 * 1000;

    function waitForHostArrival(host, baseline, onWaiting, enrollmentId) {
        const adapter = toText((host || {}).adapter);
        const startedAt = Date.now();
        return new Promise(function (resolve) {
            let stopped = false;
            let timer = null;
            const stop = function (outcome) {
                if (stopped) return;
                stopped = true;
                if (timer) clearTimeout(timer);
                resolve(outcome);
            };
            const tick = function () {
                if (stopped) return;
                /* 遮罩是"正在等"的可见信号：人把它关了就是不等了（确认框开着的那一下不算）。*/
                if (!ui.window.isOpen('loadW') && !notify.cancelPending()) return stop({ status: 'dismissed' });
                if (Date.now() - startedAt > HOST_ARRIVAL_TIMEOUT_MS) return stop({ status: 'timeout' });
                api.get('enrollmentObserve', {
                    adapter: adapter, baseline: baseline.join(','), enrollment_id: toText(enrollmentId)
                }, { silent: true })
                    .then(function (answer) {
                        if (toText(answer && answer.status) === 'arrived') {
                            return stop({ status: 'arrived', agent: answer.agent });
                        }
                        /* "还没到"里也可能带一句有用的（daemon 没起、名单读不到）：换到遮罩上。*/
                        if (typeof onWaiting === 'function') onWaiting(answer || {});
                        timer = setTimeout(tick, ENROLLMENT_POLL_MS);
                    }, function () {
                        /* 一次问不到不算失败：接着等下一次。*/
                        timer = setTimeout(tick, ENROLLMENT_POLL_MS);
                    });
            };
            timer = setTimeout(tick, ENROLLMENT_POLL_MS);
        });
    }

    /* 撤销一次接入申请（路径里的 {enrollment} 换成编号）。等票那条路作废票据，
       宿主自己接入那条路撤掉机器级记录，跨机器这条路撤掉刚记下的那条申请 ——
       都是同一扇门、同一个编号。*/
    function cancelEnrollment(enrollmentId) {
        const template = pathTemplate('enrollmentCancel');
        const id = toText(enrollmentId);
        const path = (template && id) ? template.split('{enrollment}').join(encodeURIComponent(id)) : '';
        if (!path) return Promise.resolve({});
        return api.post(path, {}, { silent: true });
    }

    /* 人不想等了：把这次申请撤掉，并收掉遮罩。撤不掉也照旧收场（人已经决定不等了），
       但要说清"没撤掉"，不能让人以为服务器那边也干净了。*/
    function withdrawEnrollment(enrollmentId, done) {
        const id = toText(enrollmentId);
        if (!id) {
            notify.loadingEnd();
            notify.info('已停止等待');
            if (done) done();
            return Promise.resolve({ status: 'dismissed' });
        }
        notify.loading('正在撤销这次接入申请 …');
        return cancelEnrollment(id).then(function (answer) {
            notify.loadingEnd();
            notify.info(toText((answer || {}).note) || '已停止等待：这次接入申请已撤掉，可以重新接入');
            if (done) done();
            return answer || { status: 'cancelled' };
        }, function (error) {
            notify.loadingEnd();
            notify.info('已停止等待（这次申请没能撤掉：' + ((error && error.message) || '原因未知') + '）');
            if (done) done();
            return { status: 'failed' };
        });
    }

    function connectAgent(options) {
        const opts = options || {};
        const host = opts.host || {};
        /* 宿主自己接入的那条路（in_host，例如 DeepSeek Harness）：中间层不签票、
           不写配置，页面也不发准备请求 —— 只开同一块等待遮罩，等中间层从接入材料 +
           名单里确认"它到了"。能不能算到了由中间层判，页面不拿"名单多了一个人"当成功。*/
        if (toText(host.mode) === 'in_host') return connectInHostAgent(opts);
        if (enrollmentFlowActive) {
            notify.info('已有接入正在等待，请先处理当前接入申请');
            return Promise.resolve({ status: 'failed' });
        }
        enrollmentFlowActive = true;
        let nickname = toText(opts.nickname).trim();
        let prepared = null;
        let cancelled = false;
        let finished = false;
        let cancelRequested = false;
        let cancelInFlight = false;
        let waitingText = opts.waiting || openWindowHint(host);
        const waitingPrefix = toText(opts.waitingPrefix);
        const cancel = function () {
            cancelRequested = true;
            if (!prepared) {
                notify.loading('正在等待准备完成后取消 …');
                return;
            }
            if (cancelInFlight) return;
            const template = pathTemplate('enrollmentCancel');
            const id = toText((prepared || {}).enrollment_id);
            const path = (template && id) ? template.split('{enrollment}').join(encodeURIComponent(id)) : '';
            if (!path) {
                cancelRequested = false;
                notify.loading('没有取得接入编号，无法确认取消结果。' + waitingText, { cancel: cancel });
                return;
            }
            cancelInFlight = true;
            notify.loading('正在取消这次接入 …');
            api.post(path, {}, { silent: true }).then(function (answer) {
                cancelInFlight = false;
                if (finished) return;
                if (toText((answer || {}).status) !== 'cancelled') {
                    cancelRequested = false;
                    notify.loading(toText((answer || {}).note) || waitingText, { cancel: cancel });
                    return;
                }
                cancelled = true;
                notify.loadingEnd();
                const registration = (answer || {}).host_registration || {};
                const registrationState = toText(registration.status);
                if (toText(host.adapter).toLowerCase() === 'codex') {
                    notify.info(toText(answer.note) || '已取消这次待接入申请');
                } else if (registrationState && registrationState !== 'unregistered') {
                    notify.info(toText(registration.note) || '这次准备的票据已作废，但宿主配置里可能还留着一条登记');
                } else {
                    notify.info('已取消等待：这次准备的票据已作废');
                }
            }, function (error) {
                cancelInFlight = false;
                if (finished) return;
                cancelRequested = false;
                const detail = error && error.raw && error.raw.detail;
                const note = isPlainObject(detail) ? toText(detail.message || detail.note) : '';
                notify.loading(note || ((error && error.status === 409)
                    ? '这个 Agent 已经开始接入，当前申请不能取消。正在继续等待'
                    : ((error && error.message) || '未能取消这次接入，正在继续等待')), { cancel: cancel });
            });
        };
        notify.loading('正在准备接入 …', { cancel: cancel });
        const preparation = opts.prepared ? Promise.resolve(opts.prepared) : api.post('agentPrepare', {
            vendor: toText(host.adapter || opts.vendor),
            nickname: nickname,
            role: opts.role || 'worker',
            profile: opts.profile || null,
            start_daemon: true
        }, { silent: true });
        return preparation.then(function (result) {
            prepared = result || {};
            if (typeof prepared.nickname === 'string') nickname = prepared.nickname.trim();
            const registration = prepared.host_registration || {};
            const registrationState = toText(registration.status);
            /* `in_host` 也是"等着就行"：那条聊天里说一句话就完成接入，没有要人手工补的命令
               （它的 next 已经写着该去哪说）。以前不认这个状态，于是 DSH 被说成"要人手工
               补一条命令"——一句话的接入被写成了手工活。*/
            if (registrationState && registrationState !== 'registered'
                && registrationState !== 'deferred' && registrationState !== 'in_host') {
                /* 票和 bridge 配置都备好了，只是这个宿主要人手工补一条命令 —— 不假装在等 */
                finished = true;
                enrollmentFlowActive = false;
                notify.loadingEnd();
                return {
                    status: 'manual', registration: registration, nickname: nickname,
                    profile: toText(prepared.profile), enrollment_id: toText(prepared.enrollment_id)
                };
            }
            /* 下一步由中间层说：Codex 是"去那个聊天说一句话"，OpenCode 是"用这个名字开会话"。
               页面不自己编，也不替后端承诺。*/
            waitingText = waitingPrefix + (toText(prepared.next) || toText(prepared.note) || waitingText);
            notify.loading(waitingText, { cancel: cancel });
            const waiting = waitForEnrollment(toText(prepared.enrollment_id), toText(host.label), function (answer) {
                const note = joiningNote(answer, host);
                if (note && !cancelInFlight) {
                    waitingText = waitingPrefix + note;
                    notify.loading(waitingText, { cancel: cancel });
                }
            });
            if (cancelRequested) cancel();
            return waiting.then(function (outcome) {
                /* 等到结果（到了/过期/取消/不等了）就把遮罩收起来，后面由调用方发声 */
                finished = true;
                enrollmentFlowActive = false;
                notify.loadingEnd();
                const merged = {
                    registration: registration,
                    nickname: nickname,
                    profile: toText(prepared.profile),
                    enrollment_id: toText(prepared.enrollment_id),
                    agent: outcome.agent
                };
                merged.status = cancelled ? 'cancelled' : toText(outcome.status);
                /* 这一刻是唯一"厂商 + 昵称 + agent_id"同时在手的时候。
                   中间层也在到达时写一次，但人要是没等就关掉遮罩，那边就轮不到。*/
                if (merged.status === 'arrived') {
                    rememberAgentProfile(
                        toText((outcome.agent || {}).agent_id), nickname,
                        toText(host.label) || toText(host.adapter || opts.vendor));
                }
                return merged;
            });
        }, function (error) {
            /* 申请冲突不能接着等另一项目或角色；说明原选择，当前向导保持原地。*/
            finished = true;
            enrollmentFlowActive = false;
            notify.loadingEnd();
            const detail = error && error.raw && error.raw.detail;
            if (isPlainObject(detail) && detail.code === 'enrollment_already_pending') {
                notify.info(enrollmentSelectionNote(detail.enrollment) +
                    (toText(detail.note) || '已有待接入申请，请先在原聊天继续；尚未认领时可取消后重新准备'));
            } else {
                notify.error((error && error.message) || '准备接入失败');
            }
            return { status: 'failed' };
        });
    }

    /* 宿主在自己聊天里接入（DeepSeek Harness 这一种）：控制台不签票、不写宿主配置，
       但**要记下"谁要接哪个项目、什么角色"**—— 那条聊天里说"请接入 Tsunagou"时只有自己的
       会话 id 和工作目录，而工作目录常常不是协调仓库，唯一说得清的就是这条机器级记录
       （`agent pending` 读它）。所以这里先 prepare（只写记录），再开同一块等待遮罩等名单里
       出现它。判断"到了"在中间层，页面不数人头。*/
    /* 跨机器接入（「位置＝网络」）：主机签一张一次性票，产出一段可复制的内容交给人；
       那台机器上的 `agent import` 收下它就完成接入。这里做三件事 —— 请中间层签票并给内容、
       把内容摆在窗口里让人转交、确认后等那个席位出现（判断仍在中间层，与其它等待同一套）。

       为什么"确认"是必须的一步：内容得由人送过去，页面无从知道人有没有送到。*/
    let networkInvite = null;

    function networkWaitHint(host) {
        const label = toText((host || {}).label) || '那台机器';
        return '邀请已经生成。请把它交给 ' + label + ' 那台机器上的人，让他在那边跑一次导入命令；' +
            '他接入后这里会自动出现。（本次以子 Agent 身份接入）';
    }

    function askForInvite(prepared, host) {
        const node = byId('netInvite');
        if (!node) return Promise.resolve(false);
        const input = qs('.textbox2 input', node);
        const shown = qsa('.dspText2', node);
        if (input) input.value = toText(prepared.invite);
        if (shown[1]) {
            const minutes = Math.max(1, Math.round(Number(prepared.expires_in_seconds || 0) / 60));
            shown[1].textContent = '一次性、约 ' + minutes + ' 分钟内有效（到 ' +
                formatTime(toText(prepared.expires_at)) + '）；过期就回来重新生成一张。';
        }
        return new Promise(function (resolve) {
            networkInvite = {
                resolve: resolve, enrollment_id: toText(prepared.enrollment_id),
                label: toText((host || {}).label) || '远端'
            };
            notify.loadingEnd();
            ui.window.open('netInvite');
        });
    }

    function connectNetworkAgent(opts) {
        const host = (opts || {}).host || {};
        if (enrollmentFlowActive) {
            notify.info('已有接入正在等待，请先处理当前接入申请');
            return Promise.resolve({ status: 'failed' });
        }
        enrollmentFlowActive = true;
        const nickname = toText((opts || {}).nickname).trim();
        const vendor = toText(host.adapter || (opts || {}).vendor);
        const baseline = toArray(state.get('agents', [])).map(function (agent) {
            return toText(agent.id);
        }).filter(Boolean);
        notify.loading('正在生成邀请 …');
        return api.post('agentPrepare', {
            vendor: vendor, nickname: nickname, role: 'worker', profile: null,
            start_daemon: true, place: 'network', conversation_id: toText((opts || {}).number)
        }, { silent: true }).then(function (prepared) {
            const answer = prepared || {};
            return askForInvite(answer, host).then(function (confirmed) {
                if (!confirmed) {
                    return withdrawEnrollment(toText(answer.enrollment_id)).then(function () {
                        return { status: 'cancelled', nickname: nickname };
                    });
                }
                let waiting = true;
                const cancel = function () {
                    if (!waiting) return;
                    waiting = false;
                    withdrawEnrollment(toText(answer.enrollment_id));
                };
                notify.loading(networkWaitHint(host), { cancel: cancel });
                return waitForHostArrival(host, baseline, function (note) {
                    if (note && waiting) notify.loading(note + '（本次以子 Agent 身份接入）', { cancel: cancel });
                }, toText(answer.enrollment_id)).then(function (outcome) {
                    waiting = false;
                    return outcome;
                });
            }).then(function (outcome) {
                enrollmentFlowActive = false;
                notify.loadingEnd();
                const reached = toText(outcome.status);
                if (reached === 'arrived') {
                    rememberAgentProfile(
                        toText((outcome.agent || {}).agent_id), nickname,
                        toText(host.label) || vendor);
                }
                return {
                    status: reached, agent: outcome.agent, nickname: nickname, profile: '',
                    registration: {}, enrollment_id: toText(answer.enrollment_id)
                };
            });
        }, function (error) {
            enrollmentFlowActive = false;
            notify.loadingEnd();
            const detail = error && error.raw && error.raw.detail;
            if (isPlainObject(detail)) {
                notify.info(toText(detail.note) || toText(detail.code) || '这次邀请没能生成');
            } else {
                notify.error((error && error.message) || '生成邀请失败');
            }
            return { status: 'failed' };
        });
    }

    function connectInHostAgent(opts) {
        const host = (opts || {}).host || {};
        if (enrollmentFlowActive) {
            notify.info('已有接入正在等待，请先处理当前接入申请');
            return Promise.resolve({ status: 'failed' });
        }
        enrollmentFlowActive = true;
        const nickname = toText((opts || {}).nickname).trim();
        const vendor = toText(host.adapter || (opts || {}).vendor);
        /* 角色写进记录（中间层），页面上也说出来：那条聊天把它交给 tsunagou_connect 的
           `role`；就算它不说，CLI 也会以记录里的角色签票（不一致的说法会被直接拒绝）。*/
        const role = toText((opts || {}).role) || 'worker';
        /* 开等之前名单里已经有谁 —— 中间层只回答"有没有出现这份名单之外的席位"，
           这一串就是我们告诉它"我来的时候看到了谁"。*/
        const baseline = toArray(state.get('agents', [])).map(function (agent) {
            return toText(agent.id);
        }).filter(Boolean);
        let prepared = null;
        let askedToStop = false;
        let cancelInFlight = false;
        const cancelDialog = {
            title: '停止等待它出现？',
            text: '要停止等待这个 Agent 接入吗？',
            description: '这一步会撤掉刚记下的那条接入申请（它只写着"哪个项目、什么角色"，没有票）。' +
                '宿主里那次接入如果已经在进行，会照常完成，之后它仍会出现在 Agent 名单里。',
            okText: '停止等待'
        };
        const cancel = function () {
            /* 没有票要作废，但有一条机器级记录要撤：那条聊天可能正靠它找项目。*/
            askedToStop = true;
            if (cancelInFlight) return;
            cancelInFlight = true;
            withdrawEnrollment(toText((prepared || {}).enrollment_id), function () { cancelInFlight = false; });
        };
        notify.loading('正在准备接入 …', { cancel: cancel });
        return api.post('agentPrepare', {
            vendor: vendor, nickname: nickname, role: role,
            profile: null, start_daemon: false
        }, { silent: true }).then(function (result) {
            prepared = result || {};
            if (askedToStop) {
                /* 人在准备完成前就点了停止：现在有编号了，把记录撤掉再收场。*/
                cancel();
                return { status: 'stopped' };
            }
            notify.loading(inHostHint(host, role), { cancel: cancel, cancelDialog: cancelDialog });
            const rolePhrase = '（本次' + (toText(role) === 'main' ? '以主 Agent 身份接入' : '以子 Agent 身份接入') + '）';
            return waitForHostArrival(
                host, baseline,
                function (answer) {
                    /* 中间层的说法更具体（还没到 / 到了但角色不对）：换成它那句，身份照旧带上。*/
                    const note = toText((answer || {}).note);
                    if (note && !askedToStop) notify.loading(note + rolePhrase, { cancel: cancel });
                },
                toText(prepared.enrollment_id)
            );
        }, function (error) {
            enrollmentFlowActive = false;
            notify.loadingEnd();
            const detail = error && error.raw && error.raw.detail;
            if (isPlainObject(detail) && detail.code === 'enrollment_already_pending') {
                notify.info(enrollmentSelectionNote(detail.enrollment) +
                    (toText(detail.note) || '已有待接入申请，请先处理当前申请'));
            } else {
                notify.error((error && error.message) || '准备接入失败');
            }
            return { status: 'failed' };
        }).then(function (outcome) {
            enrollmentFlowActive = false;
            notify.loadingEnd();
            const reached = askedToStop ? 'stopped' : toText(outcome.status);
            if (reached === 'arrived') {
                rememberAgentProfile(
                    toText((outcome.agent || {}).agent_id), nickname,
                    toText(host.label) || toText(host.adapter));
            }
            return {
                status: reached, agent: outcome.agent, nickname: nickname, profile: '',
                registration: {}, enrollment_id: toText((prepared || {}).enrollment_id)
            };
        });
    }

    /* 刷新后恢复唯一申请的等待/取消，不重建申请、不恢复未知的旧向导步骤，
       也不因申请属于另一个项目而切换当前项目。*/
    function resumeConsoleEnrollment() {
        if (enrollmentFlowActive) return Promise.resolve(false);
        return api.get('enrollmentCurrent', null, { silent: true }).then(function (current) {
            if (enrollmentFlowActive || !current || current.status !== 'waiting' || !current.enrollment_id) return false;
            const projectId = toText(current.project_id);
            /* 这条申请是哪个宿主的，就按哪个宿主继续等 —— 以前这里写死 Codex，于是一条 DSH
               的申请被当成 Codex 的申请去等一个它永远不会有的回执（等待框永远不翻绿）。
               中间层那边已经给"没有回执可等"的申请改用名单判定，所以照实带上宿主即可。*/
            return connectAgent({
                host: {
                    adapter: toText(current.vendor) || 'codex',
                    label: toText(current.label) || 'Codex'
                },
                role: current.role,
                nickname: current.nickname, prepared: current,
                waitingPrefix: enrollmentSelectionNote(current)
            }).then(function (outcome) {
                if (outcome.status === 'arrived') {
                    notify.success({ title: '接入成功', sub: enrollmentSelectionNote(current) + toText(outcome.nickname) });
                    const keys = ['projects', 'agentsWindow', 'settings'];
                    if (toText(state.get('currentProjectId')) === projectId) keys.push('agents', 'project');
                    return Tsunagou.refresh(keys);
                }
                const trouble = connectTrouble(outcome.status, { adapter: 'codex', label: 'Codex' });
                if (trouble) notify.info(trouble);
                return false;
            });
        }, function () { return false; });
    }

    /* 等待/失败时给人一句能读懂的话（两个入口共用，免得文案两处跑偏）*/
    function connectTrouble(status, host) {
        const label = toText((host || {}).label) || '宿主';
        /* 在宿主自己聊天里接入的那条路没有票：这里不能说"票过期/票据作废"。判据用宿主本身
           （codex 之外都是"那条聊天自己签票"），不靠调用点额外传一个 mode —— 传漏了就会
           把 DSH 说成 Codex。*/
        if (toText((host || {}).adapter).toLowerCase() !== 'codex') {
            if (status === 'timeout') {
                return '还没看到它出现在名单里：确认那条聊天里已经说了“接入 Tsunagou”，' +
                    '或者让它把那边的报错说出来';
            }
            if (status === 'cancelled' || status === 'stopped') {
                return '已停止等待：这次接入申请已撤掉，可以重新接入';
            }
            if (status === 'dismissed') {
                return '已停止等待显示；那条申请还在，它接上时仍会作为新席位出现在名单里';
            }
            return '';
        }
        if (toText((host || {}).adapter).toLowerCase() === 'codex') {
            if (status === 'expired') return '待接入申请已过期，请在前端重新准备接入';
            if (status === 'cancelled') return '已取消这次待接入申请，可以重新接入';
            if (status === 'dismissed') return '已停止等待显示，接入申请的实际状态以控制台查询结果为准';
        }
        if (status === 'expired') return '票据已过期，这一次接入作废了，可以再试一次';
        if (status === 'cancelled') return '已取消等待：这次准备的票据已作废，可以重新接入';
        if (status === 'dismissed') return '已停止等待接入；票还有效，稍后打开 ' + label + ' 连接上仍会加入';
        return '';
    }

    /* attempt_id → 谁在做（任务表和租约表都靠它把 owner 显示出来）*/
    function agentNameTable(attempts, agents) {
        const table = {};
        toArray(attempts).forEach(function (attempt) {
            const owner = agents[toText(attempt.owner_agent_id)];
            table[toText(attempt.attempt_id)] = {
                id: attempt.owner_agent_id,
                name: owner ? agentDisplayName(owner) : shortId(attempt.owner_agent_id),
                icon: owner ? agentIconFor(agentVendor(owner)) : TSUNAGOU_CARD_ICON
            };
        });
        return table;
    }

    /* 冲突账本里"后来怎么样了"（后端按当前租约与 Attempt 状态机械推断，见
       src/tsunagou/bootstrap/container.py 的 conflicts 出口）。
       词表见 console/glossary.py 的 conflict_resolution。*/

    /* 中间层聚合视图：sources 是各出口的原样回答，missing 是哪个出口没能给回答。
       单出口的键（例如 projects）直接收到那个出口本身，viewSources 会返回空对象，
       所以下面的适配器可以直接写 `sources.tasks` 而不用先判断。*/
    function viewSources(raw) {
        return (isPlainObject(raw) && isPlainObject(raw.sources)) ? raw.sources : {};
    }

    function viewMissing(raw) {
        return (isPlainObject(raw) && isPlainObject(raw.missing)) ? raw.missing : {};
    }

    function sourceItems(sources, name, field) {
        const bucket = sources[name];
        if (!isPlainObject(bucket)) return [];
        return backendItems(bucket);
    }

    /* 项目目标落在哪：`user_decision.propose` 里 kind 为 project.objective 的那条决定，
       用户确认后（status=resolved）它的 summary 就是主 Agent 与用户谈定的目标。
       已解决的决定不能被撤回，只能再提一条，所以取最后一条 = 最新的那版理解。
       没有这样的决定就返回空串，由调用方回落到项目记录里那句（后端写的是占位）。
       计划（coordination.plan）的抬头**故意不算数**：那是"这一批任务要干什么"，
       可以被下一个阶段换掉，不能冒充整个项目的目标。*/
    const OBJECTIVE_DECISION_KIND = 'project.objective';

    function confirmedObjective(decisions) {
        const rows = toArray(decisions).filter(function (item) {
            const payload = isPlainObject(item.payload) ? item.payload : {};
            return toText(item.kind) === OBJECTIVE_DECISION_KIND
                && toText(item.status) === 'resolved'
                && (toText(item.summary) || toText(payload.summary));
        });
        const latest = rows[rows.length - 1];
        if (!latest) return '';
        const payload = isPlainObject(latest.payload) ? latest.payload : {};
        return toText(latest.summary) || toText(payload.summary);
    }

    /* 一个出口没能给回答时，界面只把这一块留空 —— 但要说清楚为什么，
       不能装作"本来就没有"。返回 null 表示这个出口好好地给了回答。*/
    function missingNote(missing, name, label) {
        const note = missing[name];
        if (!note) return null;
        return label + '读取不到（' + (note.code || note.status || '未知原因') + '）';
    }

    /* ---- 上一次记录 -------------------------------------------------------
       项目结束（daemon 停了）之后，中间层会把它**搬运过的**那些出口拿出来顶上，
       并在回答里说清那是**记录**：聚合视图放在 `history`（一个出口一个时刻），
       页面自己直连的那些出口放在 payload 的 `_history` 里。

       两条纪律：只能在"读不到"的时候用它；显示时必须带记录时刻。把记录当成现在看，
       比留空难查得多 —— 所以这里只负责把时刻取出来，由各处写明「上次记录（记录到 …）」。*/
    function recordStamp(raw) {
        if (!isPlainObject(raw)) return '';
        const relayed = isPlainObject(raw._history) ? toText(raw._history.captured_at) : '';
        if (relayed) return relayed;
        const sources = isPlainObject(raw.history) ? raw.history : {};
        const stamps = Object.keys(sources).map(function (name) { return toText(sources[name]); });
        return stamps.filter(Boolean).sort().pop() || '';
    }

    function recordText(stamp) {
        const at = toText(stamp);
        if (!at) return '';
        /* 后端的时刻是带时区的 ISO 串；人读的是"几点"，所以取时分那一段。*/
        const part = at.replace('T', ' ').slice(0, 16);
        return '上次记录（记录到 ' + part + '）';
    }

    function recordNote(raw) {
        const stamp = recordStamp(raw);
        if (!stamp) return null;
        return recordText(stamp) + '：daemon 已经不在，下面是它还在时最近一次看到的内容。';
    }

    /* 同一件事的另一种说法：卡片已经有「上次记录」这个抬头时用它，免得抬头与正文重复。*/
    function recordDetail(raw) {
        const stamp = recordStamp(raw);
        if (!stamp) return '';
        return '记录到 ' + toText(stamp).replace('T', ' ').slice(0, 16)
            + '：daemon 已经不在，下面是它还在时最近一次看到的内容。';
    }

    /* ---- 总路径的阶段 ----------------------------------------------------

       协议里没有"阶段"这个字段 —— 它是**展示口径**：把行动按发生先后排好，
       命中里程碑就进入下一段。里程碑用真实 command kind 判断
       （docs/implementation/command-catalog.md；审计出口给的 action 就是 kind）：

         初始化      项目创建起，到第一条任务真正开工之前
         正式开工    第一条 task.publish / task.claim / task.start
         开始总验收  第一份 project.completion.propose.*（收尾提案）
         结束        project.completion.confirm（或 project.archive）

       两条例外：
       · project.reactivate.* 让阶段**退回**"正式开工" —— 结束后又复工的项目，
         总路径应该如实再出现一段"正式开工"，而不是把复工之后的事算进"结束"；
       · 被拒绝的行动（*.denied）不算里程碑，否则一条没通过的 publish 会假装已开工。

       命中的是"从哪一条开始算下一段"（所以初始化是起点、不必命中任何行动）。*/

    const TIMELINE_PHASES = ['初始化', '正式开工', '开始总验收', '结束'];
    const TIMELINE_STEPS = [
        { pattern: /^project\.(completion\.confirm|archive)/, phase: 3 },
        { pattern: /^project\.reactivate/, phase: 1 },
        { pattern: /^project\.completion\.propose/, phase: 2 },
        { pattern: /^task\.(publish|claim|start)/, phase: 1 }
    ];

    /* 返回这条行动把阶段推进到哪一段；-1 表示它不改变当前阶段。*/
    function timelinePhaseStep(action) {
        const text = toText(action);
        if (/\.denied$/.test(text)) return -1;
        for (let index = 0; index < TIMELINE_STEPS.length; index += 1) {
            if (TIMELINE_STEPS[index].pattern.test(text)) return TIMELINE_STEPS[index].phase;
        }
        return -1;
    }

    /* 蓝条上的字：阶段名 + 这一段的起止（段内只有一条行动时只给一个时间）。
       同一天只写一次日期 —— 蓝条太长了会折行。*/
    function timelineEra(phase, lines) {
        const label = TIMELINE_PHASES[phase] || TIMELINE_PHASES[0];
        const from = toText((lines[0] || {}).at);
        const to = toText((lines[lines.length - 1] || {}).at);
        const start = toText((lines[0] || {}).time);
        if (!start) return label;
        const end = toText((lines[lines.length - 1] || {}).time);
        if (start === end) return label + ' · ' + start;
        const sameDay = from.slice(0, 10) === to.slice(0, 10);
        return label + ' · ' + start + ' – ' + (sameDay ? end.replace(/^.*?日/, '') : end);
    }

    /* 操作人：项目里的 Agent 显示昵称（和 Agent 管理一致），用户显示"用户"；
       其余（例如 runtime）只能给 actor_ref 缩写 —— 后端手里就只有这个。

       两处都查：state 里的 agents（适配过，名字/图标/是否主 Agent 都算好了）
       与用户档案（启动时就拉好，早于任何项目被打开）。只认 agents 不行 ——
       总路径和 agents 是同一次 refresh 并发拉的，谁先回来不定，赶上 agents 后到
       第一屏就会是一串 id 缩写。*/
    function timelineActor(actorRef) {
        const ref = toText(actorRef);
        /* 先认"这不是 Agent"的那几个主体（用户 / 后台 / 协调中心…），词表说了算。*/
        const known = glossWord('actor_kind', ref);
        if (known) return { ref: ref, name: known, user: ref === 'user_control' };
        const agent = toArray(state.get('agents', [])).filter(function (item) {
            return toText(item.id) === ref;
        })[0];
        const profile = (state.get('profile.agents', {}) || {})[ref];
        if (agent || isPlainObject(profile)) {
            return {
                ref: ref, id: ref,
                name: toText(agent && agent.name) || toText(profile && profile.nickname) || shortId(ref),
                icon: toText(agent && agent.icon) || agentIconFor(profile && profile.vendor),
                mainAgent: !!(agent && agent.isMain)
            };
        }
        return { ref: ref, name: refText(ref), user: ref.indexOf('user') === 0 };
    }

    /* 行里的 actor 是**适配那一刻**算的，而 agents / 用户档案是并发拉的，谁先回来不定。
       所以渲染时按 ref 再算一遍：名字和主 Agent 的配色不会取决于谁先到。*/
    function actorFor(actor) {
        const ref = toText(actor && actor.ref);
        return ref ? timelineActor(ref) : actor;
    }

    const BACKEND_SHAPE = {
        /* 中间层 GET /projects → render.list 需要的左栏卡片字段。
           注意 id 必须映射出来，否则卡片的 data-project-id 是空的、点不开项目。*/
        projects: function (raw) {
            return backendItems(raw).map(function (p) {
                const done = (p.lifecycle === 'completed' || p.lifecycle === 'archived');
                const daemon = isPlainObject(p.daemon) ? p.daemon : null;
                const running = !!(daemon && daemon.running);
                /* 谁负责这个项目：中间层给的只有 agent_id/status/role，
                   名字与图标照旧由用户档案解析（与 Agent 管理页同一套）。
                   只算 status=active 的 —— 退役/接入中的不算"现在负责"。*/
                const mainAgentId = toText(p.main_agent_id);
                const chipOf = function (agentId) {
                    const ref = { agent_id: toText(agentId) };
                    return {
                        id: toText(agentId), name: agentDisplayName(ref),
                        icon: agentIconFor(agentVendor(ref))
                    };
                };
                const others = toArray(p.agents).filter(function (agent) {
                    return toText(agent.status) === 'active' && toText(agent.agent_id) !== mainAgentId;
                });
                return {
                    id: p.project_id,
                    name: p.available === false ? (toText(p.name) + '（目录已不在）') : p.name,
                    status: done ? 'finished' : (running ? 'working' : 'preparing'),
                    statusText: done ? (p.lifecycle === 'archived' ? '已归档' : '已完成')
                        : (running ? '进行中' : '未启动'),
                    /* 卡片右下角那行小字：daemon 起没起。daemon 不在了但有记录时，补一句
                       "上次记录"—— 这样人知道点进去还能看到东西，也知道那是旧的那一份。*/
                    time: (running ? 'daemon 运行中' : (daemon ? 'daemon 无响应' : 'daemon 未启动'))
                        + (!running && isPlainObject(p.history) && toText(p.history.captured_at)
                            ? ' · ' + recordText(p.history.captured_at) : ''),
                    /* 上面那行要"项目是否已完工"和"有没有记录"都判得了，两份原值都留着。*/
                    lifecycle: toText(p.lifecycle),
                    history: isPlainObject(p.history) ? p.history : null,
                    /* 分组与状态文字用同一个判据：确认完工（completed）的项目就该和已归档的
                       一起落到「已完成的协作」那一组 —— 否则卡片写着"已完成"却留在上面那一组，
                       而控制台里没有归档入口，它会一直混在"进行中"里。*/
                    group: done ? 'done' : undefined,
                    selected: false,
                    /* 卡片上不用，但别的面板要：项目目录、daemon 端点 */
                    path: p.path,
                    daemon: daemon,
                    /* agents === null = 中间层读不到（daemon 没起/没答）——
                       此时只给主 Agent（主 Agent 是中间层名单里的一部分，读不到就都没有），
                       不能写成 []，那会看起来像"这个项目没有 Agent"。
                       extra 是"其他 Agent"的数量（不含主 Agent），与卡片原本的算法一致。*/
                    mainAgent: mainAgentId ? chipOf(mainAgentId) : null,
                    agents: others.map(function (agent) { return chipOf(agent.agent_id); }),
                    extra: others.length
                };
            });
        },
        /* 中间层 GET /console/agents → render.agentWindow 需要的行。
           一行 = 一个 (项目, Agent)：同一个 Agent 在几个项目里干活就出现几行，
           所以 id 拼上项目号（否则详情窗口按 id 找会撞车）。
           昵称与图标不在这里查档案 —— 渲染时按 agent_id 现算（见 render.agentWindow）。
           task 空就是"现在没有在做的任务"，不编一句话填进去。*/
        agentsWindow: function (raw) {
            return backendItems(raw).map(function (item) {
                const agentId = toText(item.agent_id);
                return {
                    id: toText(item.project_id) + '/' + agentId,
                    agent_id: agentId,
                    project: toText(item.project_name) || shortId(item.project_id),
                    task: toText(item.task),
                    /* 是不是从网络接进来的（本机接入不画徽标）、此刻在不在线。
                       中间层不给这两个字段就一律当本机 —— 不编造“网络离线”。
                       远端还会自报一个机器名（`machine`）：有它就知道是哪台机器，
                       也等于"这是远端"（本机接入那条路从来不写它）。*/
                    network: item.network === true || Boolean(toText(item.machine)),
                    online: item.online === true,
                    machine: toText(item.machine),
                    copy_path: toText(item.copy_path),
                    copy_baseline: toText(item.copy_baseline)
                };
            });
        },
        /* 中间层 GET /console/hosts → 宿主表（点下一步会发生什么）。
           页面只做"名字对上"，不自己维护"能不能接入、跑什么命令"。
           mode 只有三种：console = 页面能办完；in_host = 去宿主自己的聊天里接入；
           unsupported = 还没做。只有 console 才发准备请求。*/
        hosts: function (raw) {
            return backendItems(raw).map(function (host) {
                const mode = toText(host.mode);
                return {
                    adapter: toText(host.adapter),
                    label: toText(host.label) || toText(host.adapter),
                    mode: mode || 'unsupported',
                    note: toText(host.note)
                };
            });
        },
        /* 中间层 view=tasks → render.tasks 需要的
           [{id,title,detail,status,agent,time,conditions,scope}]
           后端分在多个出口里：任务本身 + attempts（谁在做）+ agents（名字）+
           cognition / workspaces / resources（开工条件与改动范围要用的三张表）。*/
        tasks: function (raw) {
            const sources = viewSources(raw);
            const agents = agentsById(sourceItems(sources, 'agents'));
            const attempts = agentNameTable(sourceItems(sources, 'attempts'), agents);
            /* 任务自己**没有时间字段**：什么时候开的工挂在当前 Attempt 上（轮询也是）。*/
            const attemptStarted = {};
            sourceItems(sources, 'attempts').forEach(function (attempt) {
                attemptStarted[toText(attempt.attempt_id)] = attempt.started_at;
            });
            /* attempt → task：工作区与租约都挂在 attempt 上，只有 attempts 知道它属于哪个任务 */
            const attemptTask = {};
            sourceItems(sources, 'attempts').forEach(function (attempt) {
                attemptTask[toText(attempt.attempt_id)] = toText(attempt.task_id);
            });
            const taskOfAttempt = function (attemptId) { return attemptTask[toText(attemptId)] || ''; };
            const reports = toArray(isPlainObject(sources.cognition) ? sources.cognition.reports : null)
                .map(function (report) { return toText(report.task_id); });
            const contracts = backendItems(sources.contracts);
            const workspaces = sourceItems(sources, 'workspaces');
            const leases = sourceItems(sources, 'resources');
            /* 契约与任务的边后端**只认 payload.task_id**（cognition.linked_contracts
               就是这么连的：契约内容里写明覆盖哪个任务；不写就是项目级契约，
               不归任何任务）。所以这一件也照另外三件的规矩画：有就亮、没有就灰。*/
            const contractTaskOf = function (contract) {
                const payload = isPlainObject(contract && contract.payload) ? contract.payload : {};
                const direct = toText(payload.task_id);
                if (direct) return direct;
                const ref = toText(payload.subject_ref);
                return ref.indexOf('task/') === 0 ? ref.slice(5) : '';
            };
            /* 总路径的「DAG路径图」要的是**原样**的三份出口数据（tasks / attempts / agents）：
               blocks、parent_task_id、block_reason、current_attempt_id 在下面的界面形状里
               都用不到、会被丢掉，所以在这里留一份给它。*/
            dagSetData(sources);
            return sourceItems(sources, 'tasks').map(function (t) {
                const id = toText(t.task_id);
                const owner = attempts[toText(t.current_attempt_id)] || null;
                /* "负责 Agent"那一格下面的小字是**当前 attempt 什么时候开的工**：
                   后端把时间挂在 Attempt 上（`/tasks` 出口没有时间字段），所以从同一次
                   视图里拖的 `attempts` 出口取；旧演示数据里万一写在任务上，也认。*/
                const at = epochSecondsTime(attemptStarted[toText(t.current_attempt_id)])
                    || t.started_at || t.updated_at || '';
                /* 开工条件：回答"现在具备哪几件"（认知报告 / 契约 / 工作空间 / 租约）。
                   任务自己声明的"前置条件"后端没落库（协议里有、运行时白名单不含），
                   所以这四个是**当前状态**，不是"任务要求"。*/
                const conditions = [{ text: '认知报告', ok: reports.indexOf(id) >= 0 }];
                conditions.push({ text: '契约', ok: contracts.some(function (c) {
                    return contractTaskOf(c) === id;
                }) });
                conditions.push({ text: '工作空间', ok: workspaces.some(function (w) {
                    return taskOfAttempt(w.attempt_id) === id;
                }) });
                conditions.push({ text: '租约', ok: leases.some(function (l) {
                    return taskOfAttempt(l.attempt_id) === id && toText(l.status) === 'active';
                }) });
                /* 改动范围 = 这个任务的租约涉及的资源键之和（只算 active；过期的另外提一句）。
                   一条租约都没有时，退回任务自己声明的 execution_scope。*/
                const activeKeys = [];
                let stale = 0;
                leases.forEach(function (lease) {
                    if (taskOfAttempt(lease.attempt_id) !== id) return;
                    /* 真出口给的是资源键字符串（`repo:x/**`）；旧演示数据里写成 {key,mode}，两者都认。*/
                    const keys = toArray(lease.resources).map(function (r) {
                        return isPlainObject(r) ? (toText(r.key) || toText(r.resource)) : toText(r);
                    }).filter(Boolean);
                    if (!keys.length) return;
                    if (toText(lease.status) === 'active') activeKeys.push.apply(activeKeys, keys);
                    else stale += 1;
                });
                const unique = activeKeys.filter(function (key, index) {
                    return activeKeys.indexOf(key) === index;
                });
                let scope = unique.join('、');
                if (!scope) scope = toText(t.execution_scope);
                if (stale) scope += (scope ? '（另有 ' : '') + stale + ' 条租约已过期' + (scope ? '）' : '');
                return {
                    id: t.task_id,
                    title: t.title,
                    detail: t.objective,
                    status: TASK_STATUS_NUMBER[t.status] || 1,
                    agent: owner ? { name: owner.name, icon: owner.icon, id: owner.id } : null,
                    time: formatTime(at),
                    timePrecise: formatTime(at, { precise: true }),
                    conditions: conditions,
                    scope: scope
                };
            });
        },
        /* 中间层 view=overview → render.overview 需要的整页字段。
           一个出口一个来源：概况、任务、Agent、认知报告、存档点、待决定。*/
        project: function (raw) {
            const sources = viewSources(raw);
            const missing = viewMissing(raw);
            const header = isPlainObject(sources.overview) ? sources.overview : {};
            const agents = sourceItems(sources, 'agents');
            const tasks = sourceItems(sources, 'tasks');
            const reports = backendItems(isPlainObject(sources.cognition) ? sources.cognition.reports : null);
            const checkpoints = isPlainObject(sources.checkpoints) ? sources.checkpoints : {};
            const decisions = sourceItems(sources, 'decisions');
            const pending = decisions.filter(function (d) { return toText(d.status) === 'pending'; });
            const done = tasks.filter(function (t) { return t.status === 'completed'; });
            const main = agents.filter(function (a) { return a.role === 'main'; })[0];
            /* 项目目录由中间层知道（daemon 的概况出口不含文件路径），从项目列表里取。*/
            const known = toArray(state.get('projects', [])).filter(function (item) {
                return toText(item.id) === toText(header.project_id);
            })[0] || {};
            const knownPath = toText(known.path);
            const notes = [
                missingNote(missing, 'agents', 'Agent'),
                missingNote(missing, 'tasks', '任务'),
                missingNote(missing, 'cognition', '认知报告'),
                missingNote(missing, 'decisions', '待用户决定'),
                /* daemon 不在了、这一屏是从记录里拿的：写清时刻，别让人当现在看。*/
                recordNote(raw)
            ].filter(Boolean);
            return {
                id: header.project_id,
                name: header.name,
                description: confirmedObjective(decisions) || header.objective,
                /* 策略版本的原值（基本信息的「策略版本」是它的显示写法 r7）。
                   确认项目完成要拿它与后端做 CAS，所以得留着数字。*/
                policyRevision: header.policy_revision,
                statusText: header.lifecycle === 'completed' ? '已完成'
                    : (header.lifecycle === 'archived' ? '已归档' : '进行中'),
                statusClass: header.lifecycle === 'active' ? 'status-doing' : '',
                basics: [
                    { label: '项目编号', value: header.project_id },
                    { label: '生命周期', value: glossText('lifecycle', header.lifecycle) },
                    { label: '策略版本', value: toText(header.policy_revision) ? ('r' + header.policy_revision) : '' },
                    { label: '项目根', value: toArray(header.roots).length + ' 个' },
                    { label: '仓库', value: toArray(header.repositories).length + ' 个' },
                    { label: '主 Agent', value: main ? agentDisplayName(main) : '未指定', active: !!main }
                ],
                progress: {
                    /* 左边那个 60px 大字是进度百分数：已完成 / 全部（没有任务就是 0%）。*/
                    total: (tasks.length ? Math.round(done.length / tasks.length * 100) : 0) + '%',
                    /* 右边是可滚动的任务清单，就是"计划进度"：
                       ✓ 已完成（.taskF）· ● 在做（.taskD）· 没有图标 = 未完成（.task）。
                       图标与颜色由 CSS 给，这里只报状态和标题。*/
                    plan: (tasks.length ? tasks : [{ title: '还没有任务', status: 'draft' }]).map(function (t) {
                        return {
                            state: t.status === 'completed' ? 'done'
                                : (['claimed', 'running', 'submitted'].indexOf(t.status) >= 0 ? 'doing' : 'todo'),
                            text: t.title
                        };
                    })
                },
                versions: [
                    { label: '血缘（lineage）', value: shortId(header.current_lineage_id) },
                    { label: '运行代次（epoch）', value: shortId(header.runtime_epoch) }
                ],
                stats: [
                    { label: 'Agent', value: agents.length + ' 个' },
                    { label: '任务', value: tasks.length + ' 个（已完成 ' + done.length + '）' },
                    { label: '认知报告', value: reports.length + ' 份' },
                    { label: '存档点', value: toArray(checkpoints.items).length + ' 个' }
                ],
                /* 没有真实项目目录时（演示数据）就不摆两个空行，别装作有目录。*/
                storage: (knownPath ? [
                    { label: '项目目录', value: knownPath },
                    { label: '状态目录', value: knownPath + '/.tsunagou' }
                ] : []).concat(notes.length ? [{ label: '读不到的东西', value: notes.join('；') }] : []),
                /* 「待用户决定」：后端 decisions 出口里还没定的那些（render.overview 里多一节）*/
                pending: pending.map(function (d) {
                    const payload = isPlainObject(d.payload) ? d.payload : {};
                    /* 选项可能是字符串，也可能是 {value,label} 成对结构。"要给人看的"与"要回传的"
                       是同一句话，所以只算一次：成对结构取 value（没 value 就取 label）。
                       分开算就会出现一边显示 [object Object]、另一边回传得好好的。*/
                    const choiceWords = toArray(payload.choices).map(function (choice) {
                        return toText(isPlainObject(choice) ? (choice.value || choice.label) : choice);
                    }).filter(Boolean);
                    return {
                        id: d.decision_id,
                        /* 收尾提案的正文写在 `outstanding_summary`（completion_propose 只写这两个
                           字段），提案方自定义的决定才用 title/summary —— 两种都认，别退成裸 kind。*/
                        title: toText(payload.title) || toText(payload.summary)
                            || toText(payload.outstanding_summary) || toText(d.kind),
                        detail: toText(payload.summary) || toText(payload.outstanding_summary)
                            || toText(d.subject_ref),
                        choices: choiceWords.join(' / '),
                        /* 决定时要拿原文回给 daemon：界面上的下拉/按钮都不应该
                           自己编一个选项文本。*/
                        choiceList: choiceWords,
                        kind: d.kind,
                        /* 收尾提案（`project.complete`）在这一屏没有可答复的东西：它的按钮按
                           这个标记换成「查看详情」→ 验收与存档点那一屏。（演示数据写的是
                           `project.completion`，两种都认，见 BACKEND_SHAPE.acceptance。）*/
                        completion: ['project.complete', 'project.completion'].indexOf(toText(d.kind)) >= 0,
                        revision: d.expected_revision,
                        digest: d.input_digest
                    };
                })
            };
        },
        /* GET P/agents → render.agents。名字与厂商来自用户档案（见上面）。*/
        agents: function (raw) {
            const agents = backendItems(raw);
            const tasks = state.get('tasks', []) || [];
            const main = agents.filter(function (a) { return a.role === 'main'; })[0];
            return agents.map(function (a) {
                const vendor = agentVendor(a);
                /* 胶囊上那个字是**昵称**（人给的名字，存在用户档案里）；
                   后端代号（agent_id 的短号）是机器的事实，写在「说明」那一栏。
                   昵称还没起时胶囊才退回代号 —— 否则会是一个没字的胶囊。*/
                const nickname = toText(agentProfileEntry(a).nickname);
                const codename = shortId(a.agent_id);
                const mine = tasks.filter(function (task) {
                    return toText((task.agent || {}).id) === toText(a.agent_id);
                });
                /* 会话降级/结束时先说会话这一层：席位状态（可用/接入中）说的是"这个座位"，
                   "这条会话现在不能干活了"只有 session_status 说得出来。
                   没有会话（ready 之外本来就是 degraded，但 exit 给 null 表示读不到）时
                   还是照旧看席位状态。*/
                const sessionBroken = a.session_status === 'degraded' || a.session_status === 'ended';
                /* 在不在别的机器上 —— 只给"能不能当主 Agent"用：跨机器入席的人自报了机器名，
                   或者中间层标了 network。下面那枚「网络接入」标记另有主 Agent 的例外，
                   所以判据单独写一份在这里，别让它跟着徽标的口径走。*/
                const remoteSeat = a.network === true || Boolean(a.machine);
                return {
                    id: a.agent_id,
                    isMain: a.role === 'main',
                    role: glossText('agent_role', a.role),
                    /* 在不在别的机器上：**主 Agent 永远不算**（它必须和 daemon 同机），
                       子 Agent 看后端有没有说它是从网络接进来的；说了还得再给它一个
                       `online` 才画「网络在线」，否则是「网络离线」。两边都没说
                       就是这个 Agent 在本机 —— 那就不画徽标。*/
                    network: a.role !== 'main' && (a.network === true || Boolean(a.machine)),
                    online: a.online === true,
                    machine: toText(a.machine),
                    copy_path: toText(a.copy_path),
                    copy_baseline: toText(a.copy_baseline),
                    name: nickname || codename,
                    /* 厂商已知就给厂商的 logo，认不出来由 agentIconFor 统一摆 Tsunagou 小标
                       （见"图标"那一节；这里不再自己写第二份规则）。*/
                    icon: agentIconFor(vendor),
                    statusText: sessionBroken
                        ? glossText('session_status', a.session_status)
                        : glossText('agent_status', a.status),
                    statusOk: !sessionBroken && a.status === 'active',
                    desc: '后端代号：' + codename,
                    currentTask: mine.length ? mine[0].title : '',
                    /* 基础能力 = 4 项准入，运营能力 = 7 项运营（名单与中文都在中间层词表里）。
                       出口的 missing_admission / missing_operational 说缺哪几项；
                       没有会话（missing 为 null）就两栏都不画。*/
                    basic: glossTags('capability_admission', a.missing_admission),
                    ops: glossTags('capability_operational', a.missing_operational),
                    actions: (a.role === 'main' || !main || projectFinished() || remoteSeat
                        ? []
                        : [{ text: '设为主 Agent', action: 'agent.setMain:' + toText(a.agent_id) }]).concat([
                            /* 已退役的席位只剩"查看"（卡片本身点得开）：不能再改名字、也不能
                               再删一次 —— 否则等于把一条历史记录翻来覆去地改。
                               「修改」改昵称（存用户档案）；「删除」让他退役（后端两道拒绝：
                               当前主 Agent、手上还有活）。这两项与"项目是否已完工"无关：
                               改名字、退掉一个 Agent 是清理。*/
                            ...(a.status === 'retired' || a.role === 'main' ? [] : [
                                { text: '修改', action: 'agent.edit:' + toText(a.agent_id) },
                                { text: '删除', action: 'agent.remove:' + toText(a.agent_id) }
                            ])
                        ])
                };
            });
        },
        /* GET P/workspaces → render.workspaces */
        workspaces: function (raw) {
            return backendItems(raw).map(function (w) {
                const result = isPlainObject(w.result) ? w.result : {};
                return {
                    id: w.workspace_id,
                    name: '工作区 ' + shortId(w.workspace_id),
                    agent: null,       /* 要 join attempts */
                    isolation: glossText('isolation', w.driver_kind),
                    files: toArray(result.changed_paths),
                    states: [{ text: glossText('workspace_status', w.status), ok: w.status !== 'failed' }],
                    patch: toText(result.patch_artifact_ref) || '——'
                };
            });
        },
        /* 中间层 view=audit（意图 + 租约 + 租约冲突账本）→ render.audit */
        audits: function (raw) {
            const sources = viewSources(raw);
            const missing = viewMissing(raw);
            const agents = agentsById(sourceItems(sources, 'agents'));
            const tasks = {};
            sourceItems(sources, 'tasks').forEach(function (t) { tasks[toText(t.task_id)] = t; });
            const leases = sourceItems(sources, 'resources').map(function (l) {
                const owner = l.owner_agent_id ? agents[toText(l.owner_agent_id)] : null;
                return {
                    id: l.lease_set_id,
                    agent: owner ? { name: agentDisplayName(owner), icon: owner.vendor || owner.agent_id, id: owner.agent_id }
                        : { name: shortId(l.owner_agent_id || l.lease_set_id) },
                    scope: toArray(l.resources).map(function (r) {
                        return isPlainObject(r) ? (toText(r.key) || toText(r.resource)) : toText(r);
                    }).join('、'),
                    version: toText(l.revision),
                    lease: leaseState(l)
                };
            });
            return {
                intents: sourceItems(sources, 'intents').map(function (intent) {
                    const owner = intent.owner_agent_id ? agents[toText(intent.owner_agent_id)] : null;
                    return {
                        id: intent.intent_id,
                        agent: owner ? { name: agentDisplayName(owner), icon: owner.vendor || owner.agent_id, id: owner.agent_id }
                            : { name: shortId(intent.owner_agent_id || intent.intent_id) },
                        target: toArray(intent.resources).map(function (r) {
                            return isPlainObject(r) ? (toText(r.key) || toText(r.resource)) : toText(r);
                        }).join('、'),
                        mode: toArray(intent.resources).map(function (r) {
                            return isPlainObject(r) ? glossText('mode', r.mode) : '';
                        }).filter(Boolean).join('、'),
                        reason: toText(intent.reason),
                        version: toText(intent.revision),
                        lease: { text: tasks[toText(intent.task_id)] ? '属于任务 ' + shortId(intent.task_id) : '未开工', ok: true }
                    };
                }),
                leases: leases
            };
        },
        /* 中间层 view=collaboration（认知分歧 + 契约 + 消息 + 租约冲突）→ render.conflicts */
        conflicts: function (raw) {
            const sources = viewSources(raw);
            const missing = viewMissing(raw);
            const agents = agentsById(sourceItems(sources, 'agents'));
            const cognition = isPlainObject(sources.cognition) ? sources.cognition : {};
            const contracts = sourceItems(sources, 'contracts');
            const acceptances = isPlainObject(cognition.acceptances) ? cognition.acceptances : {};
            const confirmedOf = function (proposalId) {
                return toArray(acceptances[toText(proposalId)]).map(function (acceptance) {
                    return { name: toText(acceptance.real_actor_id) ? shortId(acceptance.real_actor_id) : '' };
                });
            };
            const proposerChips = function (proposal) {
                const actor = toText(proposal.created_by) || toText(proposal.actor_agent_id);
                return actor ? [{ name: shortId(actor) }] : [];
            };
            return {
                /* 「冲突」子标签：每次被拒的租约申请一条。
                   「影响范围」就是被占着的那些资源键 —— 冲突到底冲在哪里，
                   看键比看任务编号有用。*/
                conflicts: sourceItems(sources, 'conflicts').map(function (item) {
                    const requester = isPlainObject(item.requester) ? item.requester : {};
                    const holders = toArray(item.holders);
                    const holderNames = holders.map(function (holder) {
                        const agent = agents[toText(holder.agent_id)];
                        return agent ? agentDisplayName(agent) : shortId(holder.agent_id);
                    }).filter(Boolean);
                    return {
                        id: item.conflict_id,
                        title: toText(item.phase) + ' 被拒绝',
                        detail: holderNames.length ? ('占用方：' + holderNames.join('、')) : '',
                        scope: holders.map(function (holder) { return toText(holder.held_key); }).join('、'),
                        agents: [requester.owner_agent_id].concat(holders.map(function (holder) {
                            return holder.agent_id;
                        })).filter(Boolean).map(function (agentId) {
                            const agent = agents[toText(agentId)];
                            return { name: agent ? agentDisplayName(agent) : shortId(agentId), id: agentId };
                        }),
                        solution: glossText('conflict_resolution', item.resolution),
                        time: formatTime(item.at),
                        timePrecise: formatTime(item.at, { precise: true })
                    };
                }),
                note: [missingNote(missing, 'conflicts', '租约冲突账本')].filter(Boolean).join('；'),
                dissents: backendItems(cognition.discrepancies).map(function (d) {
                    return {
                        id: d.discrepancy_id,
                        title: toText(d.rule_id),
                        agents: toArray([d.actor_agent_id, d.subject_ref]).filter(Boolean).map(function (value) {
                            const agent = agents[toText(value)];
                            return { name: agent ? agentDisplayName(agent) : shortId(value), id: value };
                        }),
                        time: formatTime(d.updated_at || d.created_at),
                        timePrecise: formatTime(d.updated_at || d.created_at, { precise: true }),
                        scope: toText(d.subject_key) ? shortId(d.subject_key) : '',
                        understandings: [],
                        actions: []
                    };
                }),
                messages: sourceItems(sources, 'messages').map(function (m) {
                    /* 收发两侧都按"这是谁"来称呼：名单里的 Agent 用昵称；用户/后台这类
                       主体走中间层词表（`user_control` → 用户），其余退回「前缀 + 短号」。
                       以前直接把 `user_control` 截 8 个字符，页面上就写成了 user_con。*/
                    const chipName = function (agentId) {
                        const ref = toText(agentId);
                        const known = agents[ref];
                        return known ? agentDisplayName(known) : timelineActor(ref).name;
                    };
                    return {
                        id: m.message_id,
                        from: chipName(m.sender_agent_id),
                        to: chipName(m.recipient_agent_id),
                        content: toText(m.summary) || toText(m.topic),
                        answered: glossText('message_status', m.status) || '未知',
                        answeredOk: toText(m.status) === 'answered',
                        progress: toArray(m.obligations).map(function (obligation) {
                            return { text: glossText('obligation_status', isPlainObject(obligation) ? obligation.status : obligation) };
                        })
                    };
                }),
                contracts: contracts.map(function (contract) {
                    const confirmed = confirmedOf(contract.proposal_id);
                    const participants = toArray(contract.participants).map(function (participant) {
                        return { name: toText(participant) ? shortId(participant) : '' };
                    });
                    return {
                        id: contract.proposal_id,
                        title: toText(contract.proposal_id) ? ('契约 ' + shortId(contract.proposal_id)) : '契约',
                        time: formatTime(contract.updated_at || contract.created_at),
                        timePrecise: formatTime(contract.updated_at || contract.created_at, { precise: true }),
                        proposers: proposerChips(contract),
                        scope: toArray(contract.required_slots).join('、'),
                        text: toText(contract.payload) ? JSON.stringify(contract.payload) : '',
                        confirmed: confirmed,
                        unconfirmed: participants.filter(function (participant) {
                            return !confirmed.some(function (done) { return done.name === participant.name; });
                        }),
                        action: 'contract.detail:' + toText(contract.proposal_id)
                    };
                })
            };
        },
        /* 中间层 view=acceptance（完成决定 + 概况 + 任务 + 结果 + 评审）→ render.acceptance.
           后端没有"验收标准"这个概念，所以那一段已经不画了（原来只能恒空）。
           「任务验收情况」的结论来自 reviews 出口（`task.review.*` 写的轮次），
           没验过就是没验过 —— 不能拿"已提交"充当通过。*/
        acceptance: function (raw) {
            const sources = viewSources(raw);
            const agents = agentsById(sourceItems(sources, 'agents'));
            const header = isPlainObject(sources.overview) ? sources.overview : {};
            const tasks = {};
            sourceItems(sources, 'tasks').forEach(function (t) { tasks[toText(t.task_id)] = t; });
            const decisions = sourceItems(sources, 'decisions');
            const completion = decisions.filter(function (d) {
                /* 真后端的决定 kind 是 `project.complete`（handlers.py 的 completion_propose），
                   演示数据写的是 `project.completion` —— 两个都要认。拿"含有 completion"
                   去卡的话，真后端那张完成提案卡永远不显示。*/
                return ['project.complete', 'project.completion'].indexOf(toText(d.kind)) >= 0;
            })[0];
            const results = sourceItems(sources, 'results');
            /* 一份结果可能被验过好几轮（打回再交）：每个 result 只留**最高轮次**那个结论。*/
            const latestRounds = {};
            sourceItems(sources, 'reviews').forEach(function (round) {
                const id = toText(round.result_id);
                const seen = latestRounds[id];
                if (!seen || Number(round.round_no) > Number(seen.round_no)) latestRounds[id] = round;
            });
            const payload = completion && isPlainObject(completion.payload) ? completion.payload : {};
            return {
                proposal: completion ? {
                    id: completion.decision_id,
                    /* 确认时要原样带回后端要的四件套（proposal_id / digest / 期望版本）。
                       `proposal_id` 是**决定自己的 id** —— completion_confirm 就是拿它
                       去 `lifecycle.decisions` 里查的；payload 里没有这个字段时不能退回
                       `subject_ref`（那是 objective_ref），否则后端只会 404。*/
                    proposal_id: toText(payload.proposal_id) || completion.decision_id,
                    digest: toText(payload.proposal_digest) || completion.input_digest,
                    revision: completion.expected_revision,
                    title: toText(payload.title) || '项目完成提案',
                    time: formatTime(completion.updated_at || completion.created_at),
                    timePrecise: formatTime(completion.updated_at || completion.created_at, { precise: true }),
                    /* "还有哪些没完成"就是这张卡的正文本体。
                       两种 payload 形状都要认：
                       · project.completion.propose.* → {outstanding_summary, evidence_refs}
                         （handlers.py 的 completion_propose，**没有** summary/title）
                       · user_decision.propose        → {summary, choices, …} */
                    text: toText(payload.outstanding_summary) || toText(payload.summary)
                        || toText(completion.subject_ref),
                    /* 只有「确认完成」一个动作：这条提案没有可选答复（payload 里没有
                       `choices`），它要的是 `project.completion.confirm` 那条专属命令。*/
                    actions: toText(completion.status) === 'pending'
                        ? [{ text: '确认完成', kind: 'active', action: 'acceptance.confirm:' + completion.decision_id }]
                        : []
                } : {},
                taskResults: results.map(function (result) {
                    const task = tasks[toText(result.task_id)] || {};
                    const owner = agents[toText(result.submitted_by)];
                    const round = latestRounds[toText(result.result_id)] || null;
                    const reviewer = round ? agents[toText(round.reviewer_agent_id)] : null;
                    return {
                        agent: owner ? { name: agentDisplayName(owner), id: owner.agent_id } : { name: shortId(result.submitted_by) },
                        task: toText(task.title) || shortId(result.task_id),
                        /* "已提交"只是提交，不是结论：它在验收结果那一格里只当次要一行。*/
                        result: '已提交 ' + shortDigest(result.digest),
                        reviewed: !!round,
                        decision: round ? toText(round.decision) : '',
                        round: round ? Number(round.round_no) || 0 : 0,
                        reviewer: round ? (reviewer ? agentDisplayName(reviewer) : shortId(round.reviewer_agent_id)) : '',
                        reason: round ? toText(round.reason) : ''
                    };
                }),
                lifecycle: header.lifecycle,
                /* daemon 不在了、这一屏是从记录里拿的：验收与存档点这一屏最容易让人
                   以为"刚看过"，所以同样把记录时刻摆出来。*/
                record: recordNote(raw),
                recordDetail: recordDetail(raw)
            };
        },
        /* GET P/history（审计分页）→ render.timeline 需要的 [{era, items[]}]。

           真后端按 event_seq **升序**给（platform/db/sqlite.py: ORDER BY event_seq ASC），
           动作名是 command kind 去掉 "command." 前缀（container.py 的 audit 出口）。
           所以顺着数组走下去就是时间先后 —— 据此按**阶段**分代（见上面
           TIMELINE_PHASES），顺序**原样**交给渲染：从上到下就是"从一开始排到最后"。*/
        timeline: function (raw) {
            const groups = [];
            let phase = 0;
            backendItems(raw).forEach(function (event) {
                const step = timelinePhaseStep(event.action);
                if (step >= 0) phase = step;
                let group = groups[groups.length - 1];
                if (!group || group.phase !== phase) {
                    group = { phase: phase, lines: [] };
                    groups.push(group);
                }
                const at = toText(event.occurred_at) || toText(event.recorded_at);
                const ref = toText(event.subject_ref);
                const reason = reasonText(event.reason_code);
                /* 会话事件再补一句"那刻缺什么/通过了"（sessionNote）*/
                const note = sessionNote(event);
                group.lines.push({
                    id: event.event_id,
                    at: at,
                    time: formatTime(at),
                    timePrecise: formatTime(at, { precise: true }),
                    actor: timelineActor(event.actor_ref),
                    /* 「任务」列：能对上当前名单就写名字（任务是任务名、项目是项目名）；
                       对不上就按 ref 的前缀写成「任务 b71」「接入码 0」这种，
                       而不是把 `task/b71…` 整串截 8 个字符。*/
                    task: ref ? (subjectLabel(ref) || refText(ref)) : '',
                    /* 「操作」列：命令名走词表（被拒的写操作会多一句「（被拒）」），
                       后面再挂上原因码与那次会话的判定。*/
                    action: actionText(event.action) + (reason ? ('（' + reason + '）') : '')
                        + (note ? ('（' + note + '）') : '')
                });
            });
            return groups.map(function (group) {
                return {
                    era: timelineEra(group.phase, group.lines),
                    items: group.lines
                };
            });
        },
        /* GET P/checkpoints → render.acceptance 需要的 {latest,history}。
           两个出口都是同一个形状：最新那张读的是 pointer（它只有
           digest/status/through_event_seq），所以校验态得回 items 里按 digest 找 manifest ——
           不这样的话，刚校验过的最新存档点看起来反而“没校验过”。
           出口给的 created_at / reason 都要留着：卡上只剩一个摘要，等于让人信一个看不见的东西。*/
        checkpoints: function (raw) {
            const current = isPlainObject(raw) ? raw.current : null;
            const items = backendItems(raw);
            const byDigest = {};
            items.forEach(function (item) { byDigest[toText(item.digest)] = item; });
            const card = function (item) {
                const digest = toText(item.digest);
                const manifest = byDigest[digest] || {};
                const verified = item.status === 'verified' || !!manifest.verified_at;
                return {
                    id: digest,
                    title: '存档点 ' + shortDigest(digest) + (verified ? '（' + glossText('checkpoint_status', 'verified') + '）' : ''),
                    time: formatTime(manifest.created_at),
                    reason: toText(manifest.reason)
                };
            };
            return {
                latest: current ? [card(current)] : [],
                history: items.filter(function (item) {
                    return !current || toText(item.digest) !== toText(current.digest);
                }).map(card)
            };
        },
        /* GET P/checkpoint-failures → 「存档失败」那一段。
           这是记账，不是存档点：失败的存档从来没产出 manifest，所以它不可能出现在上面两份里。*/
        checkpointFailures: function (raw) {
            return {
                items: backendItems(raw).map(function (item) {
                    return {
                        id: toText(item.operation_id),
                        /* 记账里的时间是 epoch 毫秒，先换成 formatTime 认的那种。*/
                        time: formatTime(epochMillisTime(item.created_at)),
                        reason: toText(item.reason),
                        error: toText(item.error_code) || toText(item.status),
                        attempts: Number(item.attempt_count) || 0
                    };
                })
            };
        }
    };

    /* 没有适配器的键原样返回；有适配器就转换。*/
    function adaptBackend(key, raw) {
        const fn = BACKEND_SHAPE[key];
        return fn ? fn(raw) : raw;
    }

    Tsunagou.refresh = function (keys) {
        const wanted = keys ? toArray(keys) : null;
        const hasProject = !!toText(state.get('currentProjectId'));
        const skipped = [];
        const tasks = REFRESH_ROUTES.filter(function (pair) {
            /* 没选项目时不请求项目作用域的数据，免得白跑一趟错误提示 */
            if (pathNeedsProject(pair[0]) && !hasProject) return false;
            /* 后端尚未提供的接口（路径留空）直接跳过：不拼坏地址、不报错，界面保留空状态 */
            if (!toText(pathTemplate(pair[0]))) { skipped.push(pair[0]); return false; }
            return !wanted || wanted.indexOf(pair[0]) >= 0 || wanted.indexOf(pair[1]) >= 0;
        }).map(function (pair) {
            return api.get(pair[0], null, { silent: true }).then(function (raw) {
                /* 后端形状 → 界面形状，只在这里转换 */
                const result = Tsunagou.dispatch(pair[1], adaptBackend(pair[0], raw));
                return { key: pair[0], ok: result.ok };
            }, function (error) {
                return { key: pair[0], ok: false, error: error.message };
            });
        });
        return Promise.all(tasks).then(function (results) {
            const failed = results.filter(function (item) { return !item.ok; });
            if (failed.length) {
                notify.error('有 ' + failed.length + ' 项数据拉取失败：' + failed.map(function (item) { return item.key; }).join('、'));
            }
            return { results: results, failed: failed.length, skipped: skipped };
        });
    };

    /* ========================================================================
     * §7 初始（空）状态
     * ------------------------------------------------------------------------
     * 这里不再放演示数据 —— 页面上的内容一律由中间层提供。
     * 每个键对应哪个出口、回包长什么样，见 method.md §6 的接口表。
     *
     * 这份空骨架只做两件事：
     *   1) 页面在拿到数据之前有确定的形状，渲染器不会因为字段缺失而报错；
     *   2) 给 Tsunagou.state.reset() 一个"清空"的落点。
     * 字段含义见 method.md §7。
     * ====================================================================== */

    var EMPTY_STATE = {
        currentProjectId: null,
        projects: [],
        project: { pending: [] },
        agents: [],
        agentsWindow: [],
        tasks: [],
        taskDetail: {},
        conflicts: { dissents: [], conflicts: [], messages: [], contracts: [] },
        audits: { intents: [], leases: [] },
        workspaces: [],
        acceptance: { proposal: {}, taskResults: [] },
        checkpoints: { latest: [], history: [], failed: [] },
        checkpointFailures: { items: [] },
        timeline: [],
        settings: { theme: '' },
        glossary: { version: 0, domains: {} },
        hosts: [],
        agentNetwork: {},
        profile: { nickname: '', theme: '', agents: {} },
        wizard: {
            /* 第 1 步真建出来的项目、第 2 步真接上的主 Agent、第 3 步接上的子 Agent */
            project: null,
            main: null,
            draftSubAgents: [],
            detectedMainAgent: null
        }
    };


    /* ========================================================================
     * §8 启动
     * ------------------------------------------------------------------------
     * 顺序很重要：先绑事件，再把数据铺上屏，最后摆正初始界面状态。
     * 脚本在 </body> 前引入，所以这里可以直接跑；万一被挪到 <head>，
     * 也会等 DOMContentLoaded 再启动。
     * ====================================================================== */

    /* 渲染出来的按钮都带 data-tg-action，统一在这里转成动作调用 */
    function bindActionButtons() {
        delegateClick(['[data-tg-action]'], function (node) {
            runAction(node.getAttribute('data-tg-action'));
        });
    }

    /* 初始标签页以 HTML 里标了 tabSactive 的那个为准 */
    function initialTabSlug() {
        const bar = qs('.secProjPanel .tabArea');
        const list = bar ? qsa(':scope > .tabS', bar) : [];
        for (let i = 0; i < list.length; i++) {
            if (list[i].classList.contains(TAB_ACTIVE_CLASS)) {
                return (PROJECT_TABS[i] || PROJECT_TABS[0]).slug;
            }
        }
        return PROJECT_TABS[0].slug;
    }

    function init() {
        /* 0) 先认自己在哪里：中间层会在同源下给一份 /console.config.js。*/
        applyConsoleConfig();
        /* 0.5) 地址栏上的开发开关（?poll_ms=0 / ?shape=dag）—— 比配置文件优先，只影响本次打开 */
        applyUrlOverrides();

        /* 1) 事件绑定：全部走 document 级委托，动态渲染出来的元素自动生效 */
        ui.tabs.bindClicks();
        ui.blockTabs.bindClicks();
        ui.aside.bindClose();
        ui.asideDrag.bind();
        ui.choosebox.bindClicks();
        /* 总路径标题栏那两个选择框：只记值（框是 JS 画的，每次都是新元素）*/
        bindPathChoice();
        ui.window.bindBackdrop();
        /* 二次确认框必须盖在其他窗口之上（它是"先问一句"的那一层）：
           index.html 里 #delPmt 声明得比向导、添加子 Agent、加载遮罩都早，
           同样的 z-index 下后声明的会画在上面。不动 CSS、也不加元素，
           只把它挪到 body 末尾（位置：fixed，挪动不影响它怎么显示）。*/
        const confirmPanel = byId(CONFIRM_ID);
        if (confirmPanel && confirmPanel.parentNode === document.body) {
            document.body.appendChild(confirmPanel);
        }
        bindContentClicks();
        bindActionButtons();
        bindProjectCards();
        bindStaticWindowButtons();
        bindWizardDetect();
        bindSettingChooseboxes();
        form.watch(document);

        /* 2) 数据 → 页面 */
        state.hydrate();
        render.all();
        render.wizardSubAgents(state.get('wizard.draftSubAgents', []));
        ui.aside.clearAll();
        ui.blockTabs.init();

        /* 2.5) 拉一次全局数据：左侧协作列表、用户档案与后端参数值的中文对照表都不依赖"当前项目"。
              顺带把上次打开的项目接回去（只记 id，不存任何协作数据）。*/
        Tsunagou.refresh(['projects', 'settings', 'glossary', 'hosts']).then(function () {
            const remembered = lastProjectId();
            const known = toArray(state.get('projects', [])).filter(function (item) {
                return toText(item.id) === remembered;
            });
            if (known.length) return app.openProject(remembered);
            return true;
        }).then(resumeConsoleEnrollment);

        /* 3) 初始界面状态 */
        ui.workspace.home();
        ui.tabs.project(initialTabSlug());
        ui.wizard.reset();
        /* 向导第 2 步那块预览：一开页就先把"什么都没有"时的样子摆好 */
        actions.detectMainAgent();
        ui.settingTabs.personal();
        app.setTheme(state.get('settings.theme', '深色'));

        /* 4) 就绪信号：宿主脚本可以 Tsunagou.onReady(fn) 或听 'ready' 事件 */
        Tsunagou.ready = true;
        emit('ready', { version: Tsunagou.version });
        startPolling();
        return true;
    }

    /* ---- 自动重拉 --------------------------------------------------------

       间隔来自 console.config.js / 中间层（poll_ms）。只重拉已经在用的数据，
       页面在后台时不敲门；写操作后的即时重拉不靠它（那是各动作自己的事）。*/

    let pollTimer = null;

    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        return null;
    }

    function startPolling() {
        stopPolling();
        const interval = Number(config.pollMs);
        if (!isFinite(interval) || interval <= 0) return null;
        pollTimer = setInterval(function () {
            if (document.hidden) return;
            Tsunagou.refresh(['projects', 'tasks', 'agents', 'project']);
        }, interval);
        emit('poll:start', { interval: interval });
        return interval;
    }

    Object.assign(Tsunagou, {
        ready: false,
        init: init,
        on: on,
        off: off,
        once: once,
        emit: emit,
        startPolling: startPolling,
        stopPolling: stopPolling,
        onReady: function (handler) {
            if (Tsunagou.ready) { handler({ version: Tsunagou.version }); return function () {}; }
            return once('ready', handler);
        }
    });

    /* 注意：写动作不再用路径，统一走 WRITE_COMMANDS / api.command()。
       写端点由后端决定，前端不再用 config.setPath 去覆盖它们。*/

    /* 重命名这两个动作要挂在 Tsunagou.app 上：卡片菜单调 app.renameProject、
       重命名窗口的「确定」按钮（index.html 内联 onclick）调 app.submitRename。
       Tsunagou.app 是别处装配出来的，所以这里补挂上去 —— 比在那个对象里再加一行更不容易漏。*/
    Tsunagou.app.renameProject = function (id) { return actions.renameProject(id); };
    Tsunagou.app.submitRename = function () { return actions.submitRename(); };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
