# Video Agent v2 — Claude 工作上下文

> 企业内部海外广告团队素材生产工具（风格迁移 / 角色替换 / 批量视频生成）。
> 威胁模型偏"无意泄露 / 合规"，不是"恶意攻击"——安全设计与公网产品完全不同。

---

## 未完成工作

### 🐛 P0 BUG（明天第一件事）：意图注入实际未生效

**症状**：`jobs/job_eb99d7a4/film_ir.json` 里 `userIntent` 所有字段都是 null
（rawPrompt / parsedIntent / remixedLayer 都是 null），但 INTENT_INJECTION
节点显示绿色 SUCCESS。说明执行器**显示成功但实际没融合用户意图**——下游
STORYBOARD 用的是原视频分析数据，不是被改写的版本。

**怀疑路径**：
1. `_execute_intent_injection` 调 `ir_manager.run_stage("intentInjection")`
   内部撞 503 但被 catch 掉，没真跑 intent_parse + intent_fusion
2. Mode 1 后台 ANALYZE 任务和 Mode 2 agent_loop 并发写 film_ir.json，
   覆盖了刚写的 rawPrompt（写竞态）
3. plan_workflow → build_minimal_dag → create_default 链路某处把 intent
   传丢了（node.config["intent"] 实际是空）

**调试步骤**：
1. 在 `core/node_executors.py:_execute_intent_injection` 加 print 打印 intent 值
2. 手动跑：`python3 -c "from core.film_ir_manager import FilmIRManager;
   m = FilmIRManager('job_xxx'); m.run_stage('intentInjection')"` 看单独能否工作
3. 检查 `core/film_ir_manager.py:run_stage("intentInjection")` 内部异常处理

---



### 已完成 Batch 2 ✅：12 个 Gemini 直调点已全部迁移到 `gateway_client()`

迁移采用**透明代理**模式（`core/safety/llm_gateway.py:GatewayClient`）——
`client.models.generate_content(...)` 走网关（限流+审计+脱敏），
其他方法（`files.upload` 等）原样透传，业务代码改动最小：

```python
# 迁移前
client = genai.Client(api_key=api_key)
# 迁移后
client = gateway_client(task="film_ir_build", api_key=api_key, job_id=...)
```

**已迁移的 12 处**（commit 时一次性完成）：
- `core/agent_engine.py:13` → task="agent_intent_parse"
- `core/film_ir_manager.py:527,1721,1834,1979,2120` → task="film_ir_*"
- `core/workflow_manager.py:448` → task="workflow_director_analysis"
- `core/asset_generator.py:101,1216` → task="asset_*"
- `core/runner.py:274,494` → task="runner_*"
- `core/eval_job.py:452` → task="eval_llm_judge"

**当前已生效的管控**：审计日志（每次调用记录 user/task/job_id/model/耗时）、限流（每用户/小时/天）、脱敏钩子。

**当前的限定**：后台任务仍用 `user_email="system"` 占位——把 request 上下文（真实用户）下沉到这些函数是独立任务，未列入 Batch 2 范围。

---

### 其他待办（P2，可延后）

- CORS `allow_origins=["*"]` 收紧（生产前必改，见 `app.py:163`）
- 输出端 PII 正则扫描接入 eval_job 流水线
- 爆款参考的 logo / 人脸 / 标志台词相似度比对（产出端版权管控）
- 审计日志可视化接口 `/api/admin/audit`（admin 查询）

### Mode 1 反哺：节点级重试历史（独立任务）

**为什么**：Mode 1 任何一步失败 → 整个任务失败重来，浪费前面跑过的分析和抽帧。
Mode 2 设计的"节点级 retry_history"概念可以反哺到 Mode 1，让失败节点能带着失败原因重跑（换提示词重试而非盲目重跑）。

**改造点**：
- `core/workflow_manager.py` 给每个 stage 加 `retry_history` 字段
- `core/runner.py` 失败时记录 reason，下次重跑时作为 prompt 上下文
- 不重跑成功节点（节流复用 Mode 1 的产物）

**为什么不放进 Mode 2 计划**：这是 Mode 1 的局部增强，不依赖 Mode 2 任何新组件，可以独立完成。等 Mode 2 Phase 2 设计稳定后再做，复用其 retry_history 数据结构。

---

## 已完成 Batch 1（安全合规 MVP）

- 身份验证（Bearer + 反代 header + allowlist）
- 输入防护（文件白名单、素材分级 INTERNAL/VIRAL_REF、敏感词）
- 签名链接（HMAC + 过期 + 用户绑定 + 路径穿越防护）
- 审计日志（`logs/audit/YYYY-MM-DD.jsonl`）
- 29/29 单测通过

完整文档：`docs/Safety_MVP.md`

---

## 跑测试的正确方式

```bash
# 只跑安全体系单测（29 个）
SAFETY_SECRET=test-secret-for-hmac-signing-long-enough \
  SAFETY_AUTH_ENABLED=true \
  python3 -m pytest tests/test_safety.py -v

# 跑全量（注意：test_shot_filtering.py 预先存在 sys.exit 问题，test_workflow_logic.py 有 3 个 _is_scenery_shot 预先失败，和安全体系无关）
python3 -m pytest tests/ --ignore=tests/test_shot_filtering.py
```

---

## 关键文件索引

```
core/safety/          安全合规模块（Batch 1 产物）
config/               users.json / safety_config.json / sensitive_terms.json
docs/Safety_MVP.md    安全体系完整文档
.env.example          环境变量模板
```
