/* ============================================================================
 * 模拟后端 —— assets/js/mock-backend.js
 * ----------------------------------------------------------------------------
 * 这是**真后端 Tsunagou 的忠实替身**，不是产品代码。它遵守三条纪律：
 *
 *   1. 路径、响应形状、错误体全部照抄真后端：
 *        · 前缀 /api/v1（baseUrl）
 *        · 读取类返回**裸 JSON**（不是 {code,message,data}），例如 {"items":[...]}
 *        · 错误体是 {"detail":{"code":"..."}}，HTTP 状态码也跟着变
 *   2. 真后端**已经实现**的接口才有数据；真后端没有的一律 404
 *      {"detail":{"code":"not_implemented"}} —— 这样界面上的空状态和接真后端时一致，
 *      不会掩盖后端缺口。
 *   3. 命令（POST /api/v1/commands/{kind}）本替身**不执行**，一律 501。
 *      它没有 Domain 逻辑，假装成功等于伪造结果。
 *
 * 和真后端的差距（写在这里免得被当成"后端已支持"）：
 *   · GET /api/v1/projects 真 daemon **没有**这个路由（规范里是 ProjectRegistrationPage/U）。
 *     真部署里由**中间层**提供（一个 daemon 只服务一个项目，回答不了"本机有哪些项目"），
 *     形状见下面 PROJECTS。
 *   · 所有写命令真 daemon 大部分是能执行的，这里统一 501。
 *
 * 接入方式（不需要改这个文件，也不需要删掉 index.html 的那一行）：
 *   · 由中间层托管页面（`tsunagou web start`）→ 中间层给的 /console.config.js 说 live，
 *     本文件开机就 return，一个请求都不拦。
 *   · 要单独连某个 daemon → 把 console.config.js 里的 mode 改成 'live' 并写上 baseUrl。
 * ========================================================================== */

(function () {
    'use strict';

    if (!window.Tsunagou) {
        console.warn('[演示后端] 没有找到 Tsunagou（behavior.js 还没加载？），已跳过。');
        return;
    }

    /* 中间层（tsunagou web start）会在同源下给出 /console.config.js。
       它说 live（或明确 demo: false），本文件就**完全不介入**，页面请求直达中间层。
       其余情况（双击打开 index.html、`web start --demo`）都由本文件接管。

       注意："演示"是**本文件在不在**决定的，不是把页面改成另一种模式。
       behavior.js 的 mode:'demo' 意思是"不发任何请求"，那样页面只会停在空骨架。*/
    const consoleConfig = window.TSUNAGOU_CONSOLE_CONFIG || {};
    const consoleSaysLive = (consoleConfig.mode === 'live') || (consoleConfig.demo === false);
    if (consoleSaysLive) {
        console.info('[演示后端] 当前是 live 模式（连真后端），本文件不接入。');
        return;
    }

    const DELAY = 120;
    const realFetch = window.fetch ? window.fetch.bind(window) : null;

    /* ========================================================================
     * 一、数据 —— 全部照真后端的响应形状写
     * ====================================================================== */

    const PROJECT_ID = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b44';
    const MAIN_ID = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b45';
    const WORKER_ID = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b46';
    const TASK_A = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b47';
    const TASK_B = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b48';
    const TASK_C = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b49';
    const ATT_A = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b4a';
    const ATT_B = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b4b';
    const ATT_C = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b4c';
    const WS_A = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b4d';
    const WS_B = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b4e';
    const LEASE_A = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b4f';
    const CP_DIGEST = 'sha256:9ab41c7d3e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef';
    /* 再给一条旧的：真后端现在有"最新 / 历史"两段，演示里只给一条就永远看不到第二段。*/
    const CP_OLD_DIGEST = 'sha256:bdf995f9e28b8b4c303d06bd18b67211695857ed8bd6ff328bc3d11aab976129';
    const PATCH_A = 'sha256:3c9f21aa4b5c6d7e8f90123456789abcdef0123456789abcdef0123456789abcd';
    const PATCH_B = 'sha256:55aa10bb4b5c6d7e8f90123456789abcdef0123456789abcdef0123456789abcd';

    /* 项目列表：GET /api/v1/projects 的形状（左栏卡片用得到的那几个字段是前端自己加的，
       后端目前没有 name/status 之外的展示字段，所以这里只给后端真有的。*/
    const PROJECTS = [
        {
            project_id: PROJECT_ID,
            name: '[演示] 用户服务重构',
            /* 演示模式没有真 daemon（也没有真目录）：把这件事写在数据里，
               卡片就会显示"演示中"，而不是看起来像忘了起服务。*/
            path: '',
            available: true,
            sources: ['console'],
            daemon: { running: true, demo: true },
            objective: '让两个 Agent 就「用户信息里的 status 字段能不能为空」达成一致，并交付带测试的实现',
            lifecycle: 'active',
            current_lineage_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b50',
            runtime_epoch: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b51',
            policy_revision: 7,
            /* 中间层带上 agents=1 时会给的名单（只有 id/status/role，名字厂商在用户档案里）。
               真中间层自己维护这份名单，只在首次读到与 daemon 存储变动时去问项目。*/
            main_agent_id: MAIN_ID,
            agents: [
                { agent_id: MAIN_ID, status: 'active', role: 'main' },
                /* 与 AGENTS 那张表保持一致：会话降级的那个 Agent 是 provisioning。*/
                { agent_id: WORKER_ID, status: 'provisioning', role: 'worker' }
            ],
            agents_fetched_at: new Date().toISOString()
        }
    ];

    const AGENTS = [
        {
            agent_id: MAIN_ID, status: 'active', role: 'main',
            nickname: '[演示] 主 Agent', vendor: 'codex',
            conversation_digest: 'sha256:1111111111111111111111111111111111111111111111111111111111111111',
            /* 能力基线：真出口给的是"缺哪几项"（名字表），名单与中文在中间层词表里。*/
            session_status: 'ready', connection_epoch: 3,
            missing_admission: [], missing_operational: []
        },
        {
            /* 降级的那个：会话不 ready ⇒ 真后端会把 agent.status 写成 `provisioning`
               （authority.py：`active if session.status == "ready" else "provisioning"`），
               卡片上因此是「接入中」（灰杠）+ 缺哪几项就是灰的那几个勾。
               这两处必须自洽 —— 一个"degraded 会话 + active Agent"的演示会教错人。*/
            agent_id: WORKER_ID, status: 'provisioning', role: 'worker',
            nickname: '[演示] 子 Agent', vendor: 'claudecode',
            conversation_digest: 'sha256:2222222222222222222222222222222222222222222222222222222222222222',
            session_status: 'degraded', connection_epoch: 1,
            missing_admission: ['identity.continuity_evidence'],
            missing_operational: ['contract.participation', 'delivery.deduplicate']
        }
    ];

    /* status 取值就是后端 Task 的 13 态字符串（前端适配层负责转成 .st-1..13）。
       blocks 是**下游名单**（真出口 /tasks 会给 `sorted(task.blocks)`，见 container.py）：
       「统一用户返回字段」还差一口气（running），所以挡着「调用方适配层」（blocked）；
       「契约回归测试」是独立任务。总路径的 DAG 图就靠这个字段连边。*/
    const TASKS = [
        {
            task_id: TASK_A, title: '[演示] 统一用户返回字段', objective: '把 user.status 的返回口径统一到一个契约上',
            status: 'running', revision: 4, current_attempt_id: ATT_A, blocks: [TASK_B]
        },
        {
            task_id: TASK_B, title: '[演示] 调用方适配层', objective: '按契约调整调用方的字段解析',
            status: 'blocked', revision: 3, current_attempt_id: ATT_B, blocks: []
        },
        {
            task_id: TASK_C, title: '[演示] 契约回归测试', objective: '为 status 字段补一组回归用例',
            status: 'submitted', revision: 2, current_attempt_id: ATT_C, blocks: []
        }
    ];

    /* 时间写 **epoch 秒**，与真出口一致（`container.py` 的 attempts 出口原样给
       `attempt.started_at`，而任务自己**没有**时间字段）。*/
    const ATTEMPTS = [
        { attempt_id: ATT_A, task_id: TASK_A, owner_agent_id: WORKER_ID, status: 'running', execution_epoch: 2, revision: 3,
            started_at: Math.floor((Date.now() - 42 * 3600 * 1000) / 1000) },
        { attempt_id: ATT_B, task_id: TASK_B, owner_agent_id: WORKER_ID, status: 'blocked', execution_epoch: 1, revision: 2,
            started_at: Math.floor((Date.now() - 30 * 3600 * 1000) / 1000) },
        { attempt_id: ATT_C, task_id: TASK_C, owner_agent_id: WORKER_ID, status: 'submitted', execution_epoch: 1, revision: 1,
            started_at: Math.floor((Date.now() - 14 * 3600 * 1000) / 1000) }
    ];

    const RESULTS = [
        {
            result_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b52', task_id: TASK_C, attempt_id: ATT_C,
            digest: 'sha256:3c9f21aa4b5c6d7e8f90123456789abcdef0123456789abcdef0123456789abcd',
            submitted_by: WORKER_ID,
            workspace_result_ref: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b53'
        }
    ];

    /* 任务级验收的轮次（真品在 `tasks.reviews`，由 `task.review.*` 写）。
       演示里给第一条结果一个「打回」的结论 —— 不这么给，那一列永远只能显示“还没验收”。*/
    const REVIEWS = [
        {
            task_id: TASK_C, result_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b52',
            round_no: 1, reviewer_agent_id: MAIN_ID, decision: 'changes_requested',
            reason: '缺一组边界用例'
        }
    ];

    /* 注意 result 只有 changed_paths / patch_artifact_ref / baseline_conflict 三项被查询暴露 */
    const WORKSPACES = [
        {
            workspace_id: WS_A, attempt_id: ATT_A, driver_kind: 'shared', status: 'ready',
            baseline_manifest_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b54', result_manifest_id: null
        },
        {
            workspace_id: WS_B, attempt_id: ATT_C, driver_kind: 'shared', status: 'result_recorded',
            baseline_manifest_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b55',
            result_manifest_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b53',
            result: {
                changed_paths: ['backend/api/user.py', 'backend/api/tests/test_user.py'],
                patch_artifact_ref: PATCH_A,
                baseline_conflict: false
            }
        }
    ];

    /* 资源租约（查询出口 resources 的形状）。owner 与 revision 是真出口带的字段，
       少了它们"Agent 权限"那一栏的负责人列会是空的。*/
    const RESOURCES = [
        {
            lease_set_id: LEASE_A, attempt_id: ATT_A, owner_agent_id: WORKER_ID,
            status: 'active', revision: 2,
            expires_at: Math.floor(Date.now() / 1000) + 754,
            /* 真出口给的是资源键字符串（container.py 的 resources 出口）。*/
            resources: ['repo:backend/api/**']
        }
    ];

    /* 资源意图（查询出口 intents 的形状）：申请过什么、为了哪个任务。*/
    const INTENTS = [
        {
            intent_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b60',
            task_id: TASK_A, attempt_id: ATT_A, owner_agent_id: WORKER_ID, revision: 2,
            reason: '[演示] 要改 user 接口的返回字段',
            resources: [{ key: 'repo:backend/api/**', mode: 'write' }]
        },
        {
            intent_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b61',
            task_id: TASK_B, attempt_id: ATT_B, owner_agent_id: WORKER_ID, revision: 1,
            reason: '[演示] 只读契约文档，不改文件',
            resources: [{ key: 'repo:docs/contract.md', mode: 'read' }]
        }
    ];

    /* 租约冲突账本（查询出口 conflicts 的形状）：一次被拒一条。
       resolution 是真后端按当前租约与 Attempt 状态机械推断出来的，不是谁报上来的。*/
    const CONFLICT_LEDGER = [
        {
            conflict_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b62',
            at: new Date(Date.now() - 42 * 60 * 1000).toISOString(),
            phase: 'resource.acquire',
            requester: {
                attempt_id: ATT_B, owner_agent_id: WORKER_ID, task_id: TASK_B,
                intent_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b61',
                resource_keys: ['repo:backend/api/**']
            },
            holders: [{
                resource: 'repo:backend/api/**', held_key: 'repo:backend/api/**', mode: 'write',
                holder_attempt_id: ATT_A, holder_lease_set_id: LEASE_A,
                holder_expires_at: Math.floor(Date.now() / 1000) + 754
            }],
            resolution: 'open'
        },
        {
            conflict_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b63',
            at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
            phase: 'resource.acquire',
            requester: {
                attempt_id: ATT_C, owner_agent_id: WORKER_ID, task_id: TASK_C,
                intent_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b60',
                resource_keys: ['repo:backend/api/user.py']
            },
            holders: [{
                resource: 'repo:backend/api/user.py', held_key: 'repo:backend/api/user.py', mode: 'write',
                holder_attempt_id: ATT_A, holder_lease_set_id: LEASE_A,
                holder_expires_at: Math.floor(Date.now() / 1000) - 60
            }],
            /* 占用方后来释放了，申请方重试拿到 —— 两种结局都摆出来给人看。*/
            resolution: 'retried_and_won'
        }
    ];

    const ROOTS = [
        {
            root_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b56', name: '后端接口目录',
            root_kind: 'directory', required: true, binding: { status: 'bound', case_mode: 'insensitive' }
        }
    ];

    const REPOSITORIES = [
        {
            repository_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b57', name: 'coord-repo',
            root_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b56',
            git_common_dir_identity: 'sha256:3333333333333333333333333333333333333333333333333333333333333333'
        }
    ];

    const CONTRACTS = [
        {
            proposal_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b58',
            digest: 'sha256:9d41aa4b5c6d7e8f90123456789abcdef0123456789abcdef0123456789abcdef',
            status: 'accepted',
            created_by: MAIN_ID,
            participants: [MAIN_ID, WORKER_ID],
            required_slots: ['user.status 可空性'],
            /* 契约内容里写明覆盖哪个任务（真后端的规矩，见 cognition.linked_contracts）；
               任务区的「契约」那一格就是拿它连的。*/
            payload: { task_id: TASK_A, summary: '[演示] user.status 允许为空，调用方必须判空' },
            created_at: new Date(Date.now() - 90 * 60 * 1000).toISOString(),
            updated_at: new Date(Date.now() - 60 * 60 * 1000).toISOString()
        }
    ];

    /* 逐槽接受记录：键是 proposal_id，值是"谁签了哪个槽"。*/
    const ACCEPTANCES = {
        '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b58': [
            {
                proposal_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b58', participant_slot: 'main',
                real_actor_id: MAIN_ID, represented_participant: 'main', via_proxy: false
            }
        ]
    };

    const COGNITION_REPORTS = [
        {
            report_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b59', task_id: TASK_A, attempt_id: ATT_A,
            actor_agent_id: WORKER_ID,
            digest: 'sha256:4444444444444444444444444444444444444444444444444444444444444444',
            claims: [
                { subject_key: 'user.status', claim_type: 'field', equality_key: 'nullable', value: true }
            ]
        }
    ];

    const DISCREPANCIES = [
        {
            discrepancy_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b5a', subject_key: 'user.status',
            rule_id: 'claim.value_conflict',
            actor_agent_id: MAIN_ID, subject_ref: WORKER_ID,
            severity: 'hard', status: 'clarifying', claim_ids: ['0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b59'],
            input_digest: 'sha256:5555555555555555555555555555555555555555555555555555555555555555',
            created_at: new Date(Date.now() - 50 * 60 * 1000).toISOString(),
            updated_at: new Date(Date.now() - 20 * 60 * 1000).toISOString()
        }
    ];

    /* 消息本身**没有** status 字段（真后端也是）：它有一条投递记录，以及"发件方要了答复"
       时才有的回应义务。展示用的那个状态是**派生**出来的 —— 规矩与真后端
       `bootstrap/container.py` 的 `message_status()` 逐条一致，改一边就要改另一边。
       这里只写 obligations，status 由下面算，免得演示数据跟后端规矩两说。*/
    function messageStatus(obligations) {
        const rows = obligations || [];
        if (!rows.length) return 'none';                       /* 没人欠答复 */
        return rows.some(function (row) { return row.status === 'open'; }) ? 'pending' : 'answered';
    }

    const MESSAGES = [
        {
            message_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b5b', sender_agent_id: MAIN_ID,
            recipient_agent_id: WORKER_ID, kind: 'request', subject_ref: TASK_A,
            summary: '[演示] 请认领「统一用户返回字段」，先给出字段约定草案',
            obligations: [{ obligation_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b60', status: 'responded' }]
        },
        {
            message_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b64', sender_agent_id: WORKER_ID,
            recipient_agent_id: MAIN_ID, kind: 'response', subject_ref: TASK_B,
            summary: '[演示] 契约里 status 为空的分支要不要写用例？',
            obligations: [{ obligation_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b61', status: 'open' }]
        },
        {
            /* 纯通知：没附带 response_contract，所以一条义务也没有 → 状态是「无需答复」。*/
            message_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b62', sender_agent_id: MAIN_ID,
            recipient_agent_id: WORKER_ID, kind: 'notice', subject_ref: TASK_A,
            summary: '[演示] 已收到你的草案，接下来按契约走，无需回复',
            obligations: []
        }
    ].map(function (message) {
        return Object.assign({}, message, { status: messageStatus(message.obligations) });
    });

    /* 待用户决定 / 验收提案都来自 decisions 出口。payload 里带齐确认时
       要原样回传的四件套（proposal_id / digest / project_revision）。*/
    const DECISIONS = [
        {
            decision_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b65',
            kind: 'project.completion', subject_ref: 'project/' + PROJECT_ID,
            expected_revision: 7, status: 'pending',
            input_digest: 'sha256:6666666666666666666666666666666666666666666666666666666666666666',
            decision: null, reason: null,
            payload: {
                title: '[演示] 确认项目完成',
                summary: '三个任务都已交付，主 Agent 提议收尾并新建存档点',
                choices: ['确认完成', '再补一轮回归'],
                proposal_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b66',
                proposal_digest: 'sha256:7777777777777777777777777777777777777777777777777777777777777777',
                project_revision: 7
            },
            created_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
            updated_at: new Date(Date.now() - 15 * 60 * 1000).toISOString()
        }
    ];

    /* 用户档案：放在中间层（daemon 没有"昵称/厂商/主题"这套模型）。*/
    const PROFILE = {
        version: 1,
        nickname: '[演示] 我',
        theme: '深色',
        agents: {
            [MAIN_ID]: { nickname: '[演示] 主 Agent', vendor: 'codex' },
            [WORKER_ID]: { nickname: '[演示] 子 Agent', vendor: 'claudecode' }
        }
    };

    /* 总路径（GET P/history）—— 真后端的规矩照抄：
         · 顺序是 event_seq **升序**（platform/db/sqlite.py: ORDER BY event_seq ASC），
           不是"最新在前"；前端适配层负责按阶段分代、再倒过来显示。
         · 动作名是 command kind 去掉 "command." 前缀（container.py 的 audit 出口）。
         · subject_ref 的写法是 `类别/<id>`（task/、project/；见 container.py 的
           task_subject_refs），所以前端能拿它换成人看的标题；
           指向 Agent 的那些（authority.appoint）本来就是裸 id，照抄。
         · 被拒绝的写命令也是一条真事件：actor 是 runtime，subject 是刚落库的那个实体，
           拒绝原因存在事件里的 **payload.code** 上（不在 reason_code 字段）；
           审计出口会把它兜底填进 reason_code（container.py），前端读的就是这个字段。
           这里让输出走的就是那条兜底路径 —— 输入只有 payload.code，输出必须有 reason_code。
       这里只用一小时的粒度写到"开始总验收"为止：收尾提案已经发出、用户还没决定，
       与上面那条 pending 的 project.completion decision 对得上。*/
    const MINUTE = 60 * 1000;
    const HOUR = 60 * MINUTE;
    const AUDIT_EVENTS = [
        { ago: 49 * HOUR, actor: 'user_control', action: 'project.initialize', subject: 'project/' + PROJECT_ID },
        { ago: 48 * HOUR, actor: 'user_control', action: 'agent.ticket.create.user', subject: 'project/' + PROJECT_ID },
        { ago: 47 * HOUR, actor: WORKER_ID, action: 'agent.enroll', subject: 'project/' + PROJECT_ID,
            /* 与 AGENTS 里那个降级的 worker 对得上：就是入会话那刻缺的身份续接 */
            session_status: 'degraded', missing_admission: ['identity.continuity_evidence'] },
        { ago: 46 * HOUR, actor: 'user_control', action: 'authority.appoint', subject: MAIN_ID },
        { ago: 45 * HOUR, actor: MAIN_ID, action: 'root.register', subject: 'project/' + PROJECT_ID },
        { ago: 44 * HOUR, actor: MAIN_ID, action: 'task.create', subject: 'task/' + TASK_A },
        { ago: 43 * HOUR, actor: MAIN_ID, action: 'task.publish', subject: 'task/' + TASK_A },
        { ago: 42 * HOUR, actor: WORKER_ID, action: 'task.claim', subject: 'task/' + TASK_A },
        { ago: 41 * HOUR, actor: WORKER_ID, action: 'workspace.prepare', subject: 'task/' + TASK_A },
        { ago: 40 * HOUR, actor: WORKER_ID, action: 'resource.intent', subject: 'task/' + TASK_A },
        {
            ago: 3 * HOUR, actor: 'runtime', action: 'resource.lease.expired',
            subject: 'project/' + PROJECT_ID, reason: 'lease_expired'
        },
        { ago: 2 * HOUR, actor: WORKER_ID, action: 'task.submit', subject: 'task/' + TASK_A },
        { ago: 90 * MINUTE, actor: MAIN_ID, action: 'task.review.accept', subject: 'task/' + TASK_A },
        {
            ago: 42 * MINUTE, actor: 'runtime', action: 'resource.acquire.denied', subject: 'task/' + TASK_C,
            payload: { code: 'resource_conflict:file:backend/api/user.py' }
        },
        { ago: 15 * MINUTE, actor: MAIN_ID, action: 'project.completion.propose.main', subject: 'project/' + PROJECT_ID }
    ].map(function (row, index) {
        const id = '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1' + (0xb70 + index).toString(16);
        const code = row.reason || (row.payload && row.payload.code) || null;
        return {
            event_id: id, event_seq: 398 + index, source_event_id: id, source_event_seq: 398 + index,
            actor_ref: row.actor, action: row.action, subject_ref: row.subject,
            outcome: 'committed', reason_code: code, evidence_refs: [],
            /* 会话事件才有的两个字段（真后端也是：别的命令不做会话判定）*/
            session_status: row.session_status || null,
            missing_admission: row.missing_admission || [],
            projection_version: 'v1', occurred_at: new Date(Date.now() - row.ago).toISOString()
        };
    });

    const CHECKPOINT_CURRENT = {
        digest: CP_DIGEST, status: 'sealed', through_event_seq: 412,
        created_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
        reason: 'console:manual_checkpoint',
        verified_at: new Date(Date.now() - 30 * 60 * 1000).toISOString()
    };

    const CHECKPOINT_HISTORY = {
        digest: CP_OLD_DIGEST, status: 'sealed', through_event_seq: 120,
        created_at: new Date(Date.now() - 26 * 60 * 60 * 1000).toISOString(),
        reason: 'genesis'
    };

    /* 「存档失败」是**记账**而不是存档点：没存成的存档从来没产出 manifest，所以它不可能
       出现在存档点列表里。真后端从 `operations` 里筛 kind=checkpoint.create 的
       failed/retry_wait（daemon 的 checkpoint-failures 出口）。*/
    const CHECKPOINT_FAILURES = {
        operation_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b50',
        status: 'failed', error_code: 'checkpoint_materialization_failed',
        requested_by: 'runtime', reason: 'user_requested', revision: 2,
        attempt_count: 2, max_attempts: 3,
        created_at: Date.now() - 40 * 60 * 1000, updated_at: Date.now() - 40 * 60 * 1000
    };

    /* 临时（2026-09-28） */
    /* 后端参数值的中文对照表。真品在 `src/tsunagou/console/glossary.py`，
       经 GET /console/glossary 给出；这里是**逐条照抄**的替身 —— 改一边就要改另一边。
       （形状与那份一一对应：{version, domains:{域:{token:中文}}}。）*/
    const GLOSSARY = {
        version: 5,
        domains: {
            lifecycle: { active: '进行中', completed: '已完成', archived: '已归档' },
            agent_status: { active: '可用', provisioning: '接入中', retired: '已退役' },
            agent_role: { main: '主 Agent', worker: '子 Agent' },
            session_status: { ready: '已就绪', degraded: '降级中', ended: '已结束' },
            task_status: {
                draft: '草稿', ready: '待发布', open: '待领取', claimed: '已领取', running: '执行中',
                blocked: '受阻', submitted: '待评审', changes_requested: '待返工',
                cancel_requested: '待取消', cancelled: '已取消', failed: '失败',
                orphaned: '已失联', completed: '已完成'
            },
            attempt_status: {
                claimed: '已领取', running: '执行中', blocked: '受阻', submitted: '已提交',
                completed: '已完成', cancelled: '已取消', failed: '失败', orphaned: '已失联'
            },
            lease_status: { active: '生效中', expired: '已过期', released: '已释放' },
            workspace_status: {
                requested: '待准备', preparing: '准备中', ready: '就绪',
                result_recorded: '已记录结果', cleanup_pending: '待清理'
            },
            message_status: { answered: '已答复', pending: '等待中', none: '无需答复', unknown: '未知' },
            obligation_status: { open: '待回应', responded: '已回应', waived: '已豁免', superseded: '已作废' },
            delivery_status: { pending: '待投递', leased: '投递中', acked: '已确认' },
            contract_status: {
                proposed: '提议中', accepted: '已接受', rejected: '已拒绝',
                withdrawn: '已撤回', superseded: '已被替代'
            },
            decision_status: { pending: '待决定', resolved: '已决定', cancelled: '已取消', superseded: '已被替代' },
            discrepancy_status: { open: '未处理', clarifying: '澄清中', negotiating: '协商中' },
            discrepancy_severity: { soft: '轻微', hard: '严重', critical: '致命' },
            checkpoint_status: { sealed: '已封存', verified: '已校验', pending: '待落盘', failed: '失败' },
            review_decision: { accepted: '通过', changes_requested: '打回', rejected: '拒绝' },
            isolation: { shared: '共享目录', worktree: '独立检出', external: '外部准备' },
            mode: { read: '只读', write: '可写' },
            conflict_resolution: {
                retried_and_won: '重试后拿到', gave_up: '放弃/失败',
                holder_released: '占用方释放', open: '仍未解决'
            },
            /* Agent 管理那两栏（基础能力 4 项 / 运营能力 7 项）：名字与顺序都跟词表走 */
            capability_admission: {
                'identity.session_isolation': '会话隔离',
                'identity.continuity_evidence': '身份续接',
                'context.project_read': '读取项目',
                'command.typed_tools': '类型化工具'
            },
            capability_operational: {
                'task.lifecycle': '任务流转',
                'cognition.report': '认知报告',
                'contract.participation': '契约参与',
                'inbox.pull_fetch_ack': '收件确认',
                'response.structured': '结构化答复',
                'recovery.idempotent_reconnect': '断线重连',
                'delivery.deduplicate': '投递去重'
            },
            denial_reason: {
                resource_conflict: '资源被占用',
                lease_expired: '租约已过期',
                capability_denied: '没有该能力',
                ready_session_required: '会话未就绪',
                invalid_session_or_grant: '会话已失效',
                unknown_payload_field: '多了未知字段',
                malformed_command_envelope: '信封不完整',
                stale_authority_epoch: '权威代次过期',
                stale_runtime_epoch: '运行代次过期',
                stale_execution_epoch: '执行代次过期',
                stale_connection_epoch: '连接代次过期',
                authentication_failed: '身份验证失败',
                project_not_found: '找不到项目',
                session_not_rebindable: '会话不可重接',
                task_not_claimable: '任务不可认领'
            }
        }
    };

    /* 中间层能注册进哪些宿主。真品在 `src/tsunagou/platform/host_registration.py`，
       经 GET /console/hosts 给出；这里是**逐条照抄**的替身 —— 改一边就要改另一边。
       supported=false = 中间层还没有这个宿主的注册命令。*/
    const HOSTS = [
        { adapter: 'codex', label: 'Codex', supported: true, note: '' },
        { adapter: 'claudecode', label: 'Claude Code', supported: false, note: 'Claude Code 的 MCP 注册还没实现（首版明确排除）。' },
        { adapter: 'deepseek', label: 'DeepSeek Harness', supported: false, note: '这个宿主的 MCP 注册还没实现。' },
        { adapter: 'opencode', label: 'OpenCode', supported: false, note: 'OpenCode 的 MCP 注册还没实现。' },
        { adapter: 'zcode', label: 'ZCode', supported: false, note: '这个宿主的 MCP 注册还没实现。' }
    ];

    /* ========================================================================
     * 二、应答helper —— 裸 JSON 与真后端的错误体
     * ====================================================================== */

    function respond(payload, status) {
        return new Response(JSON.stringify(payload), {
            status: status || 200,
            headers: { 'Content-Type': 'application/json;charset=utf-8' }
        });
    }

    /* 真后端的错误体：FastAPI HTTPException(detail={"code": ...}) */
    function fail(status, code) {
        return { status: status, body: { detail: { code: code } } };
    }

    function notImplemented(what) {
        console.warn('[模拟后端] 真后端没有这个接口，按缺口返回 404：' + what);
        return fail(404, 'not_implemented');
    }

    function projectExists(pid) {
        return PROJECTS.some(function (p) { return p.project_id === pid; });
    }

    /* 真出口的形状：项目概况（src/tsunagou/bootstrap/container.py 的 overview 出口）*/
    function overviewExit(projectId) {
        const project = PROJECTS.filter(function (p) { return p.project_id === projectId; })[0] || {};
        return {
            project_id: projectId,
            name: project.name, objective: project.objective, lifecycle: project.lifecycle,
            policy_revision: project.policy_revision,
            roots: ROOTS.map(function (root) {
                return { root_id: root.root_id, name: root.name, root_kind: root.root_kind, required: root.required };
            }),
            repositories: REPOSITORIES.map(function (repo) {
                return { repository_id: repo.repository_id, name: repo.name, root_id: repo.root_id };
            })
        };
    }

    /* 中间层聚合视图的内容：一次把一屏要的几个出口装进 sources。
       键与 src/tsunagou/console/app.py 的 CONSOLE_VIEWS 一一对应 —— 只搬运、不解释。*/
    function consoleViewSources(view, projectId) {
        const agents = { project_id: projectId, items: AGENTS };
        const tasks = { project_id: projectId, items: TASKS };
        const results = { project_id: projectId, items: RESULTS };
        const decisions = { items: DECISIONS };
        const cognition = {
            project_id: projectId, reports: COGNITION_REPORTS,
            discrepancies: DISCREPANCIES, acceptances: ACCEPTANCES
        };
        const checkpoints = { project_id: projectId, current: CHECKPOINT_CURRENT, items: [CHECKPOINT_CURRENT] };
        const views = {
            overview: {
                overview: overviewExit(projectId), tasks: tasks, agents: agents,
                cognition: cognition, checkpoints: checkpoints, decisions: decisions
            },
            tasks: {
                tasks: tasks, attempts: { project_id: projectId, items: ATTEMPTS },
                agents: agents, results: results,
                /* 开工条件（认知报告/契约/工作空间/租约）与改动范围要看这四个 ——
                   与 src/tsunagou/console/app.py 的 CONSOLE_VIEWS["tasks"] 一致。*/
                cognition: cognition, contracts: { project_id: projectId, items: CONTRACTS },
                workspaces: { project_id: projectId, items: WORKSPACES },
                resources: { project_id: projectId, items: RESOURCES }
            },
            audit: {
                intents: { project_id: projectId, items: INTENTS },
                resources: { project_id: projectId, items: RESOURCES }, agents: agents
            },
            collaboration: {
                cognition: cognition, contracts: { project_id: projectId, items: CONTRACTS },
                messages: { project_id: projectId, items: MESSAGES },
                agents: agents, conflicts: { project_id: projectId, items: CONFLICT_LEDGER }
            },
            acceptance: {
                overview: overviewExit(projectId), decisions: decisions,
                tasks: tasks, results: results, reviews: { project_id: projectId, items: REVIEWS },
                agents: agents
            }
        };
        return views[view] || null;
    }

    /* 中间层 GET /console/agents：一行 = 一个 (项目, Agent)，跨项目汇总。
       真中间层还会逐个问项目"它现在在做什么"（console/agents.py 的 current_tasks），
       替身直接拿本文件里的 ATTEMPTS × TASKS 现算 —— 口径照抄：Attempt 的 owner 指向任务，
       只算还没结束的状态，同一人多个未结束 Attempt 取先出现的那个。*/
    function agentRows() {
        const open = ['claimed', 'running', 'blocked', 'submitted'];
        const titles = {};
        TASKS.forEach(function (task) { titles[task.task_id] = task.title; });
        const working = {};
        ATTEMPTS.forEach(function (attempt) {
            const title = titles[attempt.task_id];
            if (title && open.indexOf(attempt.status) >= 0 && !working[attempt.owner_agent_id]) {
                working[attempt.owner_agent_id] = title;
            }
        });
        const rows = [];
        PROJECTS.forEach(function (project) {
            (project.agents || []).forEach(function (agent) {
                rows.push({
                    agent_id: agent.agent_id, role: agent.role, status: agent.status,
                    project_id: project.project_id, project_name: project.name,
                    task: working[agent.agent_id] || ''
                });
            });
        });
        return rows;
    }

    /* ========================================================================
     * 三、路由表 —— 与真 daemon 的 api/app.py 一一对应
     * ====================================================================== */

    const ROUTES = [
        /* ---- 全局 ---- */
        {
            method: 'GET', pattern: /^\/api\/v1\/health$/,
            handle: function () { return { status: 'ok' }; }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/recovery$/,
            handle: function () {
                return { project_id: PROJECT_ID, status: 'ready', runtime_epoch: PROJECTS[0].runtime_epoch };
            }
        },
        /* 规范里是 ProjectRegistrationPage/U；真 daemon 目前还没装配这个路由。
           替身必须实现它，否则左栏为空、进不了任何项目面板。*/
        {
            method: 'GET', pattern: /^\/api\/v1\/projects$/,
            handle: function () { return { items: PROJECTS }; }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/decisions$/,
            handle: function () { return { items: [] }; }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/checkpoints$/,
            handle: function () {
                return { current: CHECKPOINT_CURRENT, items: [CHECKPOINT_CURRENT] };
            }
        },

        /* ---- 中间层（tsunagou web start）的路由 ----
           前端的路径表现在指向 /console/views/* 与 /console/profile，所以演示模式也得
           像中间层那样应答，否则整屏都是空的。形状与 console/app.py 一一对应。*/
        {
            method: 'GET', pattern: /^\/api\/v1\/console\/profile$/,
            handle: function () { return PROFILE; }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/console\/glossary$/,
            handle: function () { return GLOSSARY; }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/console\/agents$/,
            handle: function () {
                return { items: agentRows(), unreadable: [], fetched_at: new Date().toISOString() };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/console\/hosts$/,
            handle: function () { return { items: HOSTS }; }
        },
        {
            /* Agent 接入准备：真中间层会签票、写本机私有文件、按厂商注册进宿主。
               替身不干这些事（也干不了）——假装成功等于让人以为已经接入了一个 Agent。*/
            method: 'POST', pattern: /^\/api\/v1\/console\/projects\/([^/]+)\/agents:prepare$/,
            handle: function () {
                console.warn('[模拟后端] 不执行 Agent 接入准备（要签票、写本机文件、改宿主配置）');
                return fail(501, 'mock_backend_does_not_prepare_enrollment');
            }
        },
        {
            method: 'PUT', pattern: /^\/api\/v1\/console\/profile$/,
            handle: function (m, url, body) {
                const patch = (body && typeof body === 'object') ? body : {};
                if (patch.theme !== undefined) PROFILE.theme = patch.theme;
                if (patch.nickname !== undefined) PROFILE.nickname = patch.nickname;
                if (patch.agents && typeof patch.agents === 'object') {
                    Object.keys(patch.agents).forEach(function (agentId) {
                        PROFILE.agents[agentId] = Object.assign({}, PROFILE.agents[agentId], patch.agents[agentId]);
                    });
                }
                return PROFILE;
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/console\/views\/([a-z]+)$/,
            handle: function (m, url) {
                const projectId = url.searchParams.get('project_id') || PROJECT_ID;
                if (!projectExists(projectId)) return fail(404, 'project_not_found');
                const sources = consoleViewSources(m[1], projectId);
                if (!sources) return fail(404, 'console_view_unknown');
                return {
                    project_id: projectId, view: m[1], sources: sources, missing: {},
                    gathered_at: new Date().toISOString()
                };
            }
        },
        /* 登记 / 新建项目：中间层掌管的写入口（daemon 没装配 project.initialize）。*/
        {
            method: 'POST', pattern: /^\/api\/v1\/projects$/,
            handle: function (m, url, body) {
                const draft = (body && typeof body === 'object') ? body : {};
                const name = draft.name || draft.path || '[演示] 新协作';
                const created = {
                    project_id: 'demo-' + Date.now().toString(36),
                    name: '[演示] ' + name,
                    objective: draft.objective || '刚登记的演示项目',
                    lifecycle: 'active', policy_revision: 1,
                    current_lineage_id: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b50',
                    runtime_epoch: '0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b51',
                    path: draft.path || '（演示模式没有真目录）',
                    available: true, sources: ['console'], daemon: null,
                    /* 刚建/刚登记的项目还没有任何 Agent 接入：这里是真值 []，
                       不是 null（null 的含义是"中间层读不到"）。*/
                    main_agent_id: null, agents: [], agents_fetched_at: new Date().toISOString()
                };
                PROJECTS.push(created);
                return { status: draft.path ? 'registered' : 'created', project: created };
            }
        },
        /* 一次性删掉整个项目：中间层会停 daemon、注销宿主登记、删索引条目与目录。
           替身能做的只有"把它从列表里拿掉"，所以它不假装删了文件/注销了宿主登记，
           如实把 files 写成"没删"。*/
        {
            method: 'POST', pattern: /^\/api\/v1\/console\/projects\/([^/]+):forget$/,
            handle: function (m) {
                const at = PROJECTS.findIndex(function (item) { return item.project_id === m[1]; });
                if (at < 0) return fail(404, 'project_not_found');
                const gone = PROJECTS.splice(at, 1)[0];
                return {
                    status: 'forgotten', project_id: gone.project_id, name: gone.name,
                    path: gone.path, daemon: { status: 'not_running' },
                    host_registrations: [], enrollments_dropped: [],
                    index: { removed: true },
                    files: { path: gone.path, deleted: false, reason: '演示模式没有真目录' }
                };
            }
        },

        /* ---- 项目作用域：真 daemon 已实现的那些 ---- */
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/tasks$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: TASKS };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/attempts$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: ATTEMPTS };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/results$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: RESULTS };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/jobs$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: [] };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/roots$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: ROOTS };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/repositories$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: REPOSITORIES };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/contracts$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { items: CONTRACTS };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/cognition$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { reports: COGNITION_REPORTS, discrepancies: DISCREPANCIES, contracts: CONTRACTS };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/agents$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { items: AGENTS, main_agent_id: MAIN_ID };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/messages$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { items: MESSAGES };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/resources$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { items: RESOURCES };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/workspaces$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { items: WORKSPACES };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/audit$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: AUDIT_EVENTS, next_cursor: null };
            }
        },

        /* ---- 总路径（历史）与存档点：读的是项目作用域的真实路由 ---- */
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/history$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return {
                    project_id: m[1], items: AUDIT_EVENTS, next_cursor: null,
                    projection_version: 'v1', as_of_event_seq: 412
                };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/checkpoints$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return {
                    project_id: m[1], current: CHECKPOINT_CURRENT,
                    items: [CHECKPOINT_HISTORY, CHECKPOINT_CURRENT],
                    projection_version: 'v1', as_of_event_seq: 412
                };
            }
        },
        {
            /* 失败记账是另一份（与真后端同形：{project_id, items[]}）。*/
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/checkpoint-failures$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: [CHECKPOINT_FAILURES] };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/intents$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: INTENTS };
            }
        },
        {
            method: 'GET', pattern: /^\/api\/v1\/projects\/([^/]+)\/conflicts$/,
            handle: function (m) {
                if (!projectExists(m[1])) return fail(404, 'project_not_found');
                return { project_id: m[1], items: CONFLICT_LEDGER };
            }
        },

        /* ---- 写：命令通道。替身不执行命令，一律 501 ---- */
        {
            method: 'POST', pattern: /^\/api\/v1\/commands\/([a-z_]+(?:\.[a-z_]+)+)$/,
            handle: function (m) {
                console.warn('[模拟后端] 不执行命令：' + m[1] + '（替身没有领域逻辑，假装成功等于伪造结果）');
                return fail(501, 'mock_backend_does_not_execute_commands');
            }
        }
    ];

    /* ========================================================================
     * 四、拦 fetch
     * ====================================================================== */

    function abortError() {
        const error = new Error('请求被中止');
        error.name = 'AbortError';
        return error;
    }

    window.fetch = function (input, init) {
        const target = (typeof input === 'string') ? input : (input && input.url) || '';
        let url;
        try {
            url = new URL(target, window.location.href);
        } catch (error) {
            return realFetch ? realFetch(input, init) : Promise.reject(error);
        }

        /* file:// 下 new URL('/api/x', href) 的 pathname 会带盘符（/E:/api/x），
           所以不能拿 pathname 直接和 /api/ 比前缀 —— 改成"找到 /api 之后的部分"。*/
        const at = url.pathname.indexOf('/api');
        if (at < 0) {
            return realFetch ? realFetch(input, init) : Promise.reject(new Error('没有可用的 fetch'));
        }
        const routePath = url.pathname.slice(at);

        const method = String((init && init.method) || 'GET').toUpperCase();
        let body = null;
        if (init && init.body) {
            try { body = JSON.parse(init.body); } catch (error) { body = init.body; }
        }

        const route = ROUTES.filter(function (item) {
            return item.method === method && item.pattern.test(routePath);
        })[0];

        let status = 200;
        let payload;
        if (!route) {
            const miss = notImplemented(method + ' ' + routePath);
            status = miss.status;
            payload = miss.body;
        } else {
            try {
                const out = route.handle(routePath.match(route.pattern), url, body);
                if (out && out.status && out.body !== undefined) {
                    status = out.status;
                    payload = out.body;
                } else {
                    payload = out;
                }
            } catch (error) {
                console.error('[模拟后端] 处理出错：' + routePath, error);
                status = 500;
                payload = { detail: { code: 'mock_backend_error' } };
            }
        }

        const response = respond(payload, status);
        const signal = init && init.signal;
        if (signal && signal.aborted) return Promise.reject(abortError());

        return new Promise(function (resolve, reject) {
            const timer = setTimeout(function () { resolve(response); }, DELAY);
            if (signal) {
                signal.addEventListener('abort', function () {
                    clearTimeout(timer);
                    reject(abortError());
                });
            }
        });
    };

    /* ========================================================================
     * 五、挂上去
     * ====================================================================== */

    Tsunagou.config.setBaseUrl(String(consoleConfig.baseUrl || '/api/v1'));
    /* 页面照旧走"真请求"那条路（mode: 'live'），只是请求被本文件截下 ——
       于是渲染/解包/状态更新与连真后端时是同一条代码路径。*/
    Tsunagou.config.setMode('live');

    window.MockBackend = {
        /* 它是演示数据：所有展示用的名字都带 [演示] 前缀，
           免得有人把截图当成真后端跑出来的结果。*/
        demo: true,
        projects: PROJECTS,
        tasks: TASKS,
        agents: AGENTS,
        workspaces: WORKSPACES,
        resources: RESOURCES,
        checkpoints: { current: CHECKPOINT_CURRENT, items: [CHECKPOINT_HISTORY, CHECKPOINT_CURRENT] },
        checkpointFailures: { items: [CHECKPOINT_FAILURES] },
        /** 改完数据后重新渲染：MockBackend.refresh() */
        refresh: function (keys) { return Tsunagou.refresh(keys); },
        /** 打开项目：MockBackend.open() */
        open: function (id) { return Tsunagou.app.openProject(id || PROJECT_ID); },
        /** 当前项目 id */
        current: function () { return Tsunagou.state.get('currentProjectId'); }
    };

    /* 启动时只拉能拉的东西。projects 是进项目的唯一入口，先把它拉回来。*/
    Tsunagou.refresh(['projects']).then(function (result) {
        console.info('[演示后端] 已就绪（前缀 ' + Tsunagou.config.get().baseUrl + '）。' +
            '可用 MockBackend.open() 进项目。跳过的后端缺口：' +
            (result.skipped || []).join('、'), result);
    });
})();
