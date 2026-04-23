# Video Agent v2 — Claude 工作上下文

> 企业内部海外广告团队素材生产工具（风格迁移 / 角色替换 / 批量视频生成）。
> 威胁模型偏"无意泄露 / 合规"，不是"恶意攻击"——安全设计与公网产品完全不同。

---

## 未完成工作

### ⏳ Batch 2（高优）：迁移 12 个 Gemini 直调点到统一网关

**为什么必须做：**
Batch 1 已经把 `core/safety/llm_gateway.py` 网关壳子建好，**但业务代码里 12 处 `genai.Client()` 直调绕过了网关**——限流、审计、脱敏三个管控对大模型调用**目前全部失效**。

**不做的代价：**
不能对外宣称"大模型调用有限流与审计"。

**12 个迁移点**（grep 过，精确到行）：

| 文件 | 行号 | 场景 |
|---|---|---|
| `core/agent_engine.py` | 13 | agent 意图解析 |
| `core/film_ir_manager.py` | 527, 1721, 1834, 1979, 2120 | Film IR 四支柱构建（5 处） |
| `core/workflow_manager.py` | 448 | 工作流编排 |
| `core/asset_generator.py` | 101, 1216 | 资产生成（图像） |
| `core/runner.py` | 274, 494 | Runner 执行器 |
| `core/eval_job.py` | 452 | 质量评估 |

**迁移模板：**

```python
# Before
from google import genai
client = genai.Client(api_key=api_key)
resp = client.models.generate_content(model="gemini-2.5-pro", contents=[prompt])

# After
from core.safety.llm_gateway import llm_gateway, GatewayRequest
resp = llm_gateway().call(GatewayRequest(
    user_email=current_user_email,        # 从 request.state.user 传下来
    task="film_ir_build",                 # 本次调用的业务含义
    material_tag=material_tag_from_job,   # 从 jobs/{id}/material_metadata.json 读
    job_id=job_id,
    model_name="gemini-2.5-pro",
    prompt=prompt,
    call=lambda p: genai.Client(api_key=api_key).models.generate_content(
        model="gemini-2.5-pro", contents=[p]
    ),
))
```

**改完要跑端到端：**
```bash
SAFETY_AUTH_ENABLED=false python3 -m pytest tests/test_safety.py -q
# 然后本地起服务跑一次完整上传→生成 smoke
```

---

### 其他待办（P2，可延后）

- CORS `allow_origins=["*"]` 收紧（生产前必改，见 `app.py:163`）
- 输出端 PII 正则扫描接入 eval_job 流水线
- 爆款参考的 logo / 人脸 / 标志台词相似度比对（产出端版权管控）
- 审计日志可视化接口 `/api/admin/audit`（admin 查询）

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
