# Mode 2 Agent Canvas — 前端重构规格说明

> **目的**：给前端开发者（或前端 AI）的完整规格，可以从零重新设计/实现一个产品级 UI，无需阅读代码。
> **状态**：后端 Phase 0 / 1 / 1.5 / 2.3 / 2.4 / 3.4 + Batch 1 / 2 已全部完成；当前前端为可工作但视觉粗糙版本，等待重做。
> **版本**：2026-04-27

---

## 目录

1. [产品定位](#一产品定位)
2. [核心能力](#二核心能力5-个)
3. [用户主流程](#三用户主流程10-步)
4. [界面整体布局](#四界面整体布局)
5. [各区块详细规格](#五各区块详细规格)
6. [SSE 事件契约](#六sse-事件契约)
7. [API 端点清单](#七api-端点清单)
8. [UI 设计原则](#八ui-设计原则给前端开发者的指引)
9. [特别注意事项](#九特别注意事项)
10. [关联文档](#十关联文档)

---

## 一、产品定位

**Video Agent v2 — Mode 2 Agent Canvas**：企业内部海外广告团队素材生产工具。

**典型场景**：用户上传一支已有视频，输入一句话改写意图（例："改成日系清新风" / "主角换成女战士"），系统自动用 LLM 规划最小执行 DAG，并行执行各节点（视频分析 / 风格迁移 / 角色替换 / 视频重生成等），用户可在关键节点审批，也可任意 SUCCESS 节点之后**分叉**做 AB 探索，末端对比选定一版。

**威胁模型**：偏"无意泄露 / 合规"——内部员工使用，不是公网产品。安全合规约束已在后端落地（身份验证 / 输入防护 / 签名链接 / 审计日志）。

---

## 二、核心能力（5 个）

| 能力 | 用户感知 | 后端实现 |
|---|---|---|
| **意图驱动最小 DAG** | "我说改风格，它只跑该跑的，不重新分析剧情" | LLM 规划器分类意图 + 查代码硬编码依赖表 |
| **Gate 审批** | 关键节点暂停等用户确认（默认 INTENT_INJECTION / ASSET_GENERATION / STORYBOARD 三个 Gate） | 后端 asyncio.Event 阻塞 + 前端审批接口 |
| **质量评估自重试** | 视觉生成节点产出后自动 LLM 打分，不达标自动换提示词重试 | LLM-as-Judge 多维 rubric + decide_retry_strategy |
| **AB 分支并行探索** | 任意 SUCCESS 节点之后"从此处分叉"建分支，主路径与分支并行执行 | DAG 深拷贝 + 物理目录隔离 |
| **末端 AB 对比** | 多分支全部完成时自动弹对比视图，并排预览选一版 | BranchCompare 组件 |

---

## 三、用户主流程（10 步）

```
1. 打开 /dashboard/agent-canvas
2. 上传视频 + 必选素材分级（INTERNAL / VIRAL_REF）
3. 等待 Mode 1 后台分析（30s-2min，进度条 / spinner）
4. 输入意图 + 可选「跳过 Gate 全自动」
5. 启动 Agent → LLM 规划器分类意图 → 画布显示最小 DAG
6. 节点逐个/并行执行，状态实时同步（SSE）
7. 遇到 Gate 节点暂停 → 用户在节点详情面板点「确认通过」
8. 任意 SUCCESS 节点 → 详情面板「从此处分叉」打开 fork 对话框
9. 多分支并行执行（画布上分支节点带 🌿 分支色徽章）
10. 全部 OUTPUT 节点 SUCCESS → 自动弹 BranchCompare 选最终版
```

---

## 四、界面整体布局

```
┌─────────────────────────────────────────────────────────────┐
│ 顶栏 (h:48px)                                                 │
│ [<] [LOGO] Agent Canvas | Job: job_abc12345                  │
│ ─────────────────────────────  [对比3分支] [Wifi] [暂停][停止]│
├─────────────────────────────────────────┬───────────────────┤
│                                          │                    │
│         主画布区（React Flow）            │   右侧面板 320px    │
│                                          │                    │
│   ┌─────┐                                │  ┌─ 切换 ─┐       │
│   │INPUT│─...                            │  │Chat |Detail│   │
│   └─────┘                                │  └────────┘       │
│                                          │                    │
│   覆盖层 1: 上传卡（无 jobId 时）         │  Chat: Agent 事件 │
│   覆盖层 2: 输入意图卡（分析完后）        │      流（消息列表） │
│   覆盖层 3: BranchCompare 模态           │                    │
│                                          │  Detail: 选中节点   │
│                                          │      详情/操作      │
└─────────────────────────────────────────┴───────────────────┘
```

---

## 五、各区块详细规格

### 5.1 上传卡（首屏，无 jobId 时）

**结构**：上半部"素材分级表单" + 下半部"拖拽区"

**上半部表单**（必填）：

```
素材类别 *  [大按钮 1: 内部自制]  [大按钮 2: 爆款参考]
            ↓ 单选互斥

[INTERNAL 选中时显示]:
  ☐ 含未公开信息（保密级，加强审计与导出审批）

[VIRAL_REF 选中时显示]:
  原片链接 *  [URL 输入框，placeholder="https://www.tiktok.com/..."]
  参考维度 *（至少选 1 项）
    [chip: 结构]  [chip: 节奏]  [chip: 视觉风格]  [chip: 脚本钩子]
  说明文字：这是合规留证字段——出现版权疑问时能证明"参考学习不是抄袭"
```

**下半部拖拽区**：
- 状态 1：素材信息未填齐 → 灰显 + 提示"请先完成素材信息再上传"
- 状态 2：填齐 → 高亮可拖拽 + Upload 图标 + "拖拽视频或点击选择"
- 状态 3：上传中 → spinner + "上传中..."

**API**：`POST /api/upload` (multipart/form-data)

```ts
{
  file: File,
  material_tag: "INTERNAL" | "VIRAL_REF",
  contains_confidential?: boolean,    // 仅 INTERNAL
  reference_url?: string,              // 仅 VIRAL_REF
  reference_dimensions?: string,       // 仅 VIRAL_REF, 逗号分隔
}
```

返回：`{ job_id, status, material_tag }`

---

### 5.2 等待分析卡（已上传，分析中）

**位置**：覆盖层中心，但不阻塞画布预览（可看到 11 个 PENDING 节点）

**内容**：
- 上传成功的视频缩略图
- 状态文字（轮询 `/api/job/{id}/upload-status` 拿到）：
  - "视频已上传，AI 正在分析..."
  - "提取分镜中..."
  - "构建 Film IR 中..."
- spinner

**画布同步**：随分析进度自动把 INPUT/ANALYZE/WATERMARK_CLEAN/FILM_IR_ANALYSIS 节点变 SUCCESS

---

### 5.3 输入意图卡（分析完毕，Agent 未启动）

**结构**：

```
✓ 视频分析完成
┌──────────────────────────────────────┐
│ 启动 Agent                            │
│                                       │
│ 描述你想要的效果                       │
│ [大文本框 4 行]                        │
│ placeholder: "改成日系清新风格..."     │
│                                       │
│ ☐ 跳过确认节点（全自动模式）           │
│                                       │
│ [开始执行 - 大蓝色按钮]                │
└──────────────────────────────────────┘
```

**API**：`POST /api/job/{id}/agent/start` body: `{ goal, skip_gates }`

---

### 5.4 主画布（React Flow，永久可见）

**节点视觉系统**（重点设计区）

每个节点显示：
- **图标**：根据 nodeType 不同（11 种类型对应 11 个 lucide 图标）
- **标签**：节点中文名（"AI 分析视频" / "水印清理" / "Film IR 深度分析" 等）
- **状态色边框**（最重要的视觉信号）：
  - PENDING：灰色虚线
  - RUNNING：蓝色 + spinner 动画
  - SUCCESS：绿色 + ✓ 图标
  - FAILED：红色 + ✗ 图标
  - WAITING_APPROVAL：琥珀色 + 🔒 图标
  - SKIPPED：灰色 + ↪ 图标
- **耗时**（SUCCESS 时显示）："3.2s"
- **重试次数**（>0 时）："重试 1/2"
- **Gate 标识**（gate=true 且未通过时）："🔒 需确认"
- **可展开标识**（FILM_IR_ANALYSIS SUCCESS 时）："查看分析详情 ›"
- **分支徽章**（branch != "main" 时）：右上角 "🌿 cyberpunk" 小标签，**5 色调色板按分支名稳定哈希**

**边视觉**：
- 默认：灰色细线
- 父节点 SUCCESS：绿色变粗
- 父节点 RUNNING：蓝色动画线（流动效果）

**子节点展开**（FILM_IR_ANALYSIS 特殊功能）：
- 节点点击 → 展开右侧 4 个子节点：主题分析 / 脚本分析 / 分镜切割 / 角色发现
- 每个子节点点击 → 拉取对应数据 API 显示具体内容（GET `/api/job/{id}/film_ir/story_theme` 等）
- 再次点击父节点 → 收起

**多分支布局**：
- main 在左
- 分支节点已经在后端 `create_branch` 时计算好 x 偏移（350 + hash * 20）
- 前端只需正确渲染 position

---

### 5.5 顶栏

```
左：[< 返回] [LOGO] Agent Canvas  Job: job_xxxxxxxx
中：(空)
右：动态显示 →
   • 分析中：[黄色 spinner + 文字]
   • 分析完成：[绿色 ✓ + "视频分析完成"]
   • 多分支：[琥珀色按钮 "对比 N 个分支"] ← 手动打开 BranchCompare
   • Agent 运行中：[Wifi icon] [暂停按钮] [停止按钮]
   • SSE 断线：[红色 WifiOff]
```

---

### 5.6 资产预览（节点详情面板的关键能力，当前缺失）

⚠️ **当前 UI 的最大产品缺陷** — 节点详情面板只显示 raw JSON，**没把产物可视化**。
重做时这是必须补齐的核心能力。

每类节点的"产物 + Gate 决策依据"应该这样展示：

#### INTENT_INJECTION（Gate）— 决策依据：注入后的镜头脚本

```
┌─ 产物：remix prompts ────────────────────────┐
│ 共 4 个镜头的注入结果（折叠展示）              │
│                                                │
│ ▼ shot_01: 日系清新风格（含原镜头描述对照）    │
│   原: "A man walking through forest at dawn"   │
│   新: "[STYLE: 日系清新] A young man in        │
│        soft morning light walking through a    │
│        misty forest, pastel tones, ..."       │
│                                                │
│ ▼ shot_02: ... (默认折叠)                      │
│ ▼ shot_03: ...                                 │
│ ▼ shot_04: ...                                 │
└──────────────────────────────────────────────┘
```

#### ASSET_GENERATION（Gate）— 决策依据：将要生成的资产清单

```
┌─ 即将生成的资产 ─────────────────────────────┐
│ 角色（2 个）                                    │
│   • char_001: 男主，金发短发，蓝色衬衫          │
│     → 待生成：front / side / back 三视图       │
│   • char_002: 路人甲，黑发                      │
│     → 待生成：front / side / back 三视图       │
│                                                │
│ 环境（3 个）                                    │
│   • env_001: 黄昏森林                          │
│   • env_002: 室内咖啡馆                        │
│   • env_003: ...                               │
│                                                │
│ 预估调用次数: 9 次 (Imagen 4)                  │
│ 预估耗时: ~3-5 分钟                            │
└──────────────────────────────────────────────┘
```

**ASSET_GENERATION 跑完之后**，节点详情面板应展示已生成的图：

```
┌─ 角色三视图 ─────────────────────────────────┐
│ char_001 (男主)                                │
│   [front.png] [side.png] [back.png]           │
│   每张 120×120 缩略，单击放大                  │
│                                                │
│ char_002 (路人甲)                              │
│   [front.png] [side.png] [back.png]           │
└──────────────────────────────────────────────┘
┌─ 环境参考图 ─────────────────────────────────┐
│ [env_001 缩略] [env_002 缩略] [env_003 缩略]   │
└──────────────────────────────────────────────┘
```

#### STORYBOARD（Gate）— 决策依据：每个分镜的定妆图

```
┌─ 分镜定妆图 ─────────────────────────────────┐
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐         │
│ │ S01  │ │ S02  │ │ S03  │ │ S04  │         │
│ │ img  │ │ img  │ │ img  │ │ img  │         │
│ └──────┘ └──────┘ └──────┘ └──────┘         │
│ 每张点击放大 + 显示对应 shot 的描述           │
└──────────────────────────────────────────────┘
```

#### VIDEO_GENERATION — 每个分镜的视频片段

```
┌─ 视频片段 ───────────────────────────────────┐
│ shot_01.mp4  [▶ 播放]  3.2s                   │
│ shot_02.mp4  [▶ 播放]  2.8s                   │
│ ...                                            │
│ 每个 inline <video> 控件                       │
└──────────────────────────────────────────────┘
```

#### MERGE / OUTPUT — 完整合成视频

```
┌─ 最终视频 ───────────────────────────────────┐
│ ┌──────────────────────────────────────────┐│
│ │       完整 <video> 大画面预览              ││
│ │       带控制条 + 全屏按钮                  ││
│ └──────────────────────────────────────────┘│
│ 时长: 12.3s  |  分辨率: 1920×1080           │
│ [下载] [分享]                                  │
└──────────────────────────────────────────────┘
```

**实现要点**：
1. 数据从节点 `result` 字段提取（如 `result.assets.character.char_001.front` 是相对路径 `character_anchors/char_001_front.png`）
2. **必须通过 `/api/asset/sign` 接口换签名 URL** 后再放进 `<img src=>` / `<video src=>`
3. 签名 URL 默认有效期 1 小时，长会话页面在 video onError 时自动刷新签名
4. 预览图统一 lazy load + 失败时显示占位图
5. 单击缩略图弹模态大图（含 zoom / 翻页）

---

### 5.7 右侧面板（320px 固定宽）

**两种模式互斥**：

#### 模式 A：Chat 面板（默认 / 无节点选中时）

```
┌────────────────────────────┐
│ 🤖 Agent       [运行中标签]  │
├────────────────────────────┤
│ 滚动消息列表（自动到底）：    │
│                              │
│  🤖 LLM 规划器已生成最小 DAG │
│     16:32:01                 │
│  🤖 正在执行: AI 分析视频    │
│     16:32:03                 │
│  🤖 ↳ 主题分析...            │
│     16:32:08                 │
│  🤖 AI 分析视频 完成 (3.2s)  │
│     16:32:14                 │
│  🤖 等待确认: 意图注入       │
│     16:32:20  [🔒]           │
│  🤖 🌿 分支 "cyberpunk"      │
│     已创建（5 个节点）        │
│  ⚠ 评估失败: 角色一致性 5/10 │
│     重试 (1/2)                │
└────────────────────────────┘
```

每条消息根据关键词标色：完成=绿色 / 失败=红色 / 等待=琥珀色 / 普通=灰色。

#### 模式 B：节点详情面板（点击画布节点时）

```
┌────────────────────────────┐
│ ⚙ Film IR 深度分析    [X]   │
├────────────────────────────┤
│ 状态: SUCCESS               │
│ 节点类型: FILM_IR_ANALYSIS   │
│ 耗时: 1.2 min                │
│ 开始时间: 16:32:14           │
│ 重试次数: 0 / 2              │
│                              │
│ 配置:                        │
│ ┌─ JSON 块（折叠）─────┐     │
│ │ { "intent": "日系" } │     │
│ └─────────────────────┘     │
│                              │
│ 执行结果:                    │
│ ┌─ JSON 块（带视觉摘要） ─┐  │
│ │ { "shots_count": 9 }  │  │
│ └─────────────────────┘     │
│                              │
│ ─── 评估结果（如果有） ───   │
│ 整体加权分: 8.4 / 10 ✓       │
│ ├ 角色一致性: 9.0 ████      │
│ ├ 风格一致性: 8.5 ████      │
│ ├ 残留检测: 9.5 █████       │
│ ├ 解剖质量: 7.5 ███         │
│ └ 光照一致性: 7.0 ███       │
│                              │
│ ─── 重试历史（如果有） ───    │
│ 第 1 次: 角色一致性 5.0 ✗    │
│ 应用策略: strengthen_char... │
│                              │
│ ─── 操作按钮 ───              │
│ [WAITING_APPROVAL 时]:       │
│   [✓ 确认通过 - 大琥珀按钮]   │
│ [SUCCESS 且非 OUTPUT]:        │
│   [🌿 从此处分叉 - 描边按钮]  │
└────────────────────────────┘
```

---

### 5.8 Fork 对话框（点击「从此处分叉」时弹出）

居中模态：

```
┌──────────────────────────────────┐
│ 🌿 从「Film IR 深度分析」分叉  [X]│
│                                    │
│ 复制此节点之后的所有下游节点为新   │
│ 分支，与主路径并行执行；产物写入   │
│ 独立目录 jobs/.../branches/cyberpunk│
│                                    │
│ 分支名 *                            │
│ [cyberpunk_alt________________]   │
│ 仅字母数字下划线，不能是 "main"    │
│                                    │
│ 改写意图（可选）                   │
│ [文本框 3 行___________________]   │
│ 例："把风格改成赛博朋克霓虹"      │
│ 不填则沿用主分支意图               │
│                                    │
│ [错误信息红框（如有）]              │
│                                    │
│ [取消]              [创建分支]      │
└──────────────────────────────────┘
```

**API**：`POST /api/job/{id}/agent/fork-branch`

```ts
{ fork_node_id: string, branch_name: string, intent_override?: string }
```

---

### 5.9 AB 对比视图（多分支完成时）

**触发**：所有分支的 OUTPUT 节点都 SUCCESS 时**自动**弹出（也可顶栏按钮手动）

**布局**：居中大模态，max-width: 1200px

```
┌────────────────────────────────────────────────────┐
│ 🏆 分支对比 — 选一版保留          3 个分支已完成 [X]│
├──────────┬──────────┬──────────────────────────────┤
│ 🌿 main  │🌿 exp1   │🌿 exp2                        │
│ 主分支    │          │                              │
├──────────┼──────────┼──────────────────────────────┤
│ 意图     │ 意图     │ 意图                          │
│ 日系清新 │ 赛博朋克 │ 复古胶片                      │
├──────────┼──────────┼──────────────────────────────┤
│ ┌────┐  │ ┌────┐  │ ┌────┐                       │
│ │视频│  │ │视频│  │ │视频│                       │
│ │预览│  │ │预览│  │ │预览│                       │
│ └────┘  │ └────┘  │ └────┘                       │
├──────────┼──────────┼──────────────────────────────┤
│ [选这版] │ [✓ 已选中]│ [选这版]                     │
├──────────┴──────────┴──────────────────────────────┤
│ 选定的版本会保留为最终结果；其他分支可在 branches/  │
│ 目录下保留参考                                       │
│                       [稍后再说]  [确认选择「exp1」]│
└────────────────────────────────────────────────────┘
```

**视频源**：从节点 `result.video` / `result.output_path` / `result.assets.video` 提取，拼成 `/assets/{job_id}/{path}` URL（**生产应通过 `/api/asset/sign` 换签名 URL**，dev 模式可直接访问）。

---

## 六、SSE 事件契约

订阅 `GET /api/job/{job_id}/agent/stream`（EventSource）。所有事件 data 是 JSON。

| 事件类型 | data 关键字段 | 前端动作 |
|---|---|---|
| `graph_created` | nodeCount, edgeCount, plannerUsed, reusedCount, pendingCount | 拉新 graph |
| `graph_resumed` | progress | 拉新 graph |
| `node_started` | nodeId, nodeType, label, branch | 节点状态→RUNNING |
| `node_progress` | nodeId, substep, substepStatus, substeps | 子步骤进度更新 |
| `node_completed` | nodeId, label, result, duration_ms | 节点状态→SUCCESS |
| `node_failed` | nodeId, error, retryCount, finalScores? | 节点状态→FAILED |
| `node_retrying` | nodeId, attempt, maxRetries, error | 节点状态→RUNNING + 重试计数 |
| `gate_reached` | nodeId, label | 节点状态→WAITING_APPROVAL，弹通知 |
| `planner_succeeded` | userGoal | Chat 提示 |
| `planner_failed` | error, fallback | Chat 警告 |
| `evaluation_done` | nodeId, scores, weightedScore, passed | 节点详情面板显示分数 |
| `quality_issue` | nodeId, scores, issues, strategyApplied, attempt | Chat 提示 + 节点详情显示重试历史 |
| `evaluation_skipped` | nodeId, reason | 静默或 debug log |
| `branch_created` | branchName, forkNodeId, intentOverride, newNodeCount, newNodeIds | 拉新 graph + Chat 提示 |
| `workflow_complete` | status | 顶栏状态变化，触发 BranchCompare 检查 |
| `workflow_blocked` | - | Chat 警告 |
| `workflow_paused` / `resumed` / `stopped` | - | 顶栏状态变化 |

---

## 七、API 端点清单

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/upload` | 上传视频 + 素材分级 |
| GET  | `/api/job/{id}/upload-status` | 轮询 Mode 1 分析进度 |
| POST | `/api/job/{id}/agent/start` | 启动 Agent (LLM 规划) |
| GET  | `/api/job/{id}/agent/stream` | SSE 事件订阅 |
| GET  | `/api/job/{id}/agent/graph` | 获取当前 DAG 完整状态 |
| POST | `/api/job/{id}/agent/approve-gate` | Gate 审批 (`{node_id}`) |
| POST | `/api/job/{id}/agent/fork-branch` | 创建分支 |
| POST | `/api/job/{id}/agent/pause` | 暂停 |
| POST | `/api/job/{id}/agent/resume` | 恢复 |
| GET  | `/api/job/{id}/agent/log` | 历史事件回放 |
| POST | `/api/asset/sign` | 换签名链接 (`{job_id, path, ttl_seconds?}`) |
| GET  | `/api/job/{id}/film_ir/story_theme` | Film IR 子节点数据 |
| GET  | `/api/job/{id}/film_ir/narrative` | 同上 |
| GET  | `/api/job/{id}/film_ir/shots` | 同上 |
| GET  | `/api/job/{id}/character-ledger` | 角色账本 |

---

## 八、UI 设计原则（给前端开发者的指引）

1. **暗色专业风** — 参考 Vercel / Linear / Cursor 的现代 AI 工具美学；主背景 `#0a0a0f`，边线 `#1f2937`
2. **状态色一致** — 全局复用 6 状态调色板（PENDING / RUNNING / SUCCESS / FAILED / WAITING_APPROVAL / SKIPPED），所有提示与节点用同一组色
3. **信息层次** — 节点上展示密度要克制（≤3 条信息），详细信息在右侧详情面板展开
4. **动画语言** — RUNNING 节点 spinner 动画 / 边线流动 / 状态切换平滑过渡
5. **空状态友好** — 没启动 Agent 时画布显示静态 11 节点预览（PENDING 灰色），不是"Loading..."
6. **错误可恢复** — 失败节点点开能看到 error 详情 + 重试历史，不是黑盒
7. **多分支视觉差异** — 5 色调色板（amber / purple / cyan / rose / lime）按 branch_name 哈希分配；main 不带徽章保持中性
8. **响应式宽度** — 主画布自适应，右侧面板固定 320px；< 1024px 时面板可折叠为底部抽屉
9. **键盘可达** — Esc 关闭模态 / Cmd+Enter 提交对话框 / Tab 顺序合理
10. **i18n** — 当前所有文案中文，但保留 i18n 钩子（next-intl 或类似），未来可英文化

---

## 九、特别注意事项

- **节点 position 已由后端计算好**（含分支偏移），前端 React Flow 直接用 `node.position.{x,y}` 即可，不要前端再算布局
- **OUTPUT 节点不允许 fork**（`canFork = node.status === "SUCCESS" && node.type !== "OUTPUT"`）
- **Gate 审批后端无需重启**，前端 POST `/approve-gate` 后等 SSE `node_started` 事件
- **同一个节点可能多次进入 RUNNING**（评估失败重试场景），UI 需要正确处理状态来回切换
- **签名 URL 过期默认 1 小时**，长会话要定期刷新（前端在视频播放器 onError 时重新调 `/asset/sign` 拉新 URL）
- **NODE_TYPE 完整枚举**（共 19 种，主流水线 + 二级 + 扩展）：
  - 主流水线：`INPUT` / `ANALYZE` / `FILM_IR_ANALYSIS` / `ABSTRACTION` / `INTENT_INJECTION` / `ASSET_GENERATION` / `STORYBOARD` / `VIDEO_GENERATION` / `MERGE` / `OUTPUT`
  - 二级：`CHARACTER_LEDGER` / `WATERMARK_CLEAN` / `SINGLE_SHOT_STYLIZE` / `SINGLE_SHOT_VIDEO` / `QUALITY_CHECK` / `BRANCH_MERGE`
  - 扩展（用户可拖入）：`CUSTOM_PROMPT` / `STYLE_OVERRIDE`
- **STATUS 完整枚举**：`PENDING` / `QUEUED` / `RUNNING` / `SUCCESS` / `FAILED` / `WAITING_APPROVAL` / `SKIPPED`

---

## 十、关联文档

- `docs/Mode2_Development_Plan.md` — 完整 Phase 拆解 + ADR 架构决策
- `docs/PRD_Agent_Workflow_Canvas.md` — 产品 PRD（含数据模型）
- `docs/Frontend_Canvas_Design_Spec.md` — 旧版前端设计规范（参考用，本文档已覆盖更新版本）
- `docs/Canvas_Editing_Guide.md` — 画布编辑交互（Phase 3.1-3.3，未实施）
- `docs/Quality_Audit_Architecture_TODO.md` — 评估器 5 检查点详细设计
- `docs/Safety_MVP.md` — 安全合规体系（身份验证 / 输入防护 / 签名链接 / 审计）
- `CLAUDE.md` — 项目工作上下文（含未完成工作清单）
