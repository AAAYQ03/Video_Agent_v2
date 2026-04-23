# Safety MVP — 使用与运维文档

Batch 1 已交付。本篇说明：**如何用、日志在哪、下一步要做什么**。

---

## 1. 一分钟理解

四层结构，对应代码模块：

| 层 | 职责 | 模块 |
|---|---|---|
| 身份底座 | 谁在调用 | `core/safety/auth.py` |
| 输入防护 | 文件白名单 + 素材分级 + 敏感词 | `core/safety/input_guard.py` |
| 执行管控 | 限流 + 脱敏 + 审计（网关壳子已建，**业务代码尚未全量迁移**） | `core/safety/llm_gateway.py` |
| 输出审核 | HMAC 签名链接 + 路径穿越防护 | `core/safety/signed_url.py` |
| 基础设施 | 结构化 JSONL 审计日志 | `core/safety/audit_log.py` |

---

## 2. 首次上手

### 2.1 配置 `.env`

```bash
cp .env.example .env
# 生成一个随机密钥
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# 把结果填到 .env 的 SAFETY_SECRET=
```

### 2.2 新建用户

编辑 `config/users.json`：

```json
{
  "users": [
    {
      "email": "alice@yourcompany.com",
      "token": "sk-retake-<用 python3 -c 'import secrets; print(secrets.token_urlsafe(32))' 生成>",
      "role": "creator",
      "active": true
    }
  ]
}
```

**role 说明**：
- `admin` — 全权，可导出保密素材、查看全量审计
- `creator` — 正常生产（上传、生成、导出非保密素材）
- `viewer` — 只读

### 2.3 前端集成（给前端同学）

- 登录页让用户输入 token，存 `localStorage.retake_token`
- 所有 API 请求带 `Authorization: Bearer <token>` header
- 打开应用先调 `GET /api/auth/whoami`，返回 `authenticated: false` 就跳登录页
- 资源 URL 不能再直接拼 `BASE_URL + /assets/...`，要调 `POST /api/asset/sign` 换签名链接

### 2.4 本地开发关闭认证

```bash
# .env
SAFETY_AUTH_ENABLED=false
```

关闭后所有请求自动以 `dev@local` / admin 身份通过——**仅用于本地调试，生产必须 true**。

---

## 3. 素材分级业务规则

上传时 `material_tag` 必填，两选一：

### INTERNAL — 内部自制
- 默认，无额外管控
- 可选勾 `contains_confidential=true` 把素材标为保密
  - 勾选后：审计日志标红；**未来版本** admin 才能导出

### VIRAL_REF — 爆款参考
- **必填** `reference_url`（原片链接）
- **必填** `reference_dimensions`（参考维度，多选，逗号分隔）
  - 可选值：`structure` / `pacing` / `visual_style` / `script_hook`
  - 至少 1 个
- 为什么强制填？**留下"学习不是抄袭"的证据链**，应对版权纠纷

---

## 4. 审计日志

### 4.1 位置
`logs/audit/YYYY-MM-DD.jsonl`，一天一个文件，每行一条 JSON。

### 4.2 事件类型
| event | 触发时机 |
|---|---|
| `auth_failure` | 无效 token / 缺 token |
| `upload` | `/api/upload`，outcome = ok / denied / error |
| `asset_sign` | 申请签名链接 |
| `asset_access` | 访问资源文件 |
| `llm_call` | 走网关的大模型调用（Batch 2 之后才全量） |

### 4.3 字段
```json
{
  "ts": "2026-04-17T02:33:10.511+00:00",
  "event": "upload",
  "user": "alice@yourcompany.com",
  "job_id": "job_abc12345",
  "resource": "jobs/job_abc12345/input.mp4",
  "outcome": "ok",
  "details": {
    "tag": "VIRAL_REF",
    "reference_url": "https://tiktok.com/xxx",
    "reference_dimensions": ["structure", "pacing"]
  },
  "pid": 87321
}
```

### 4.4 常用查询
```bash
# 今日所有被拒事件
jq 'select(.outcome == "denied")' logs/audit/$(date -u +%F).jsonl

# 某用户本周的上传
jq 'select(.user == "alice@yourcompany.com" and .event == "upload")' logs/audit/*.jsonl

# 爆款参考的使用记录
jq 'select(.details.tag == "VIRAL_REF")' logs/audit/*.jsonl
```

---

## 5. 签名链接机制

- **URL 形态**：`/assets/{job_id}/{path}?exp=<unix_ts>&u=<base64_email>&sig=<hmac_sha256>`
- **绑定**：签发时的用户 email + 过期时间 + 路径 + job_id 一起签
- **默认有效期**：1 小时（`config/safety_config.json` 可调，最长 24 小时）
- **强绑定**：访问时签名里的 email 必须等于当前请求身份——转发给别人就失效
- **路径穿越**：`../` 等越出 `jobs/` 目录的路径会被 400 拒绝

---

## 6. 跑测试

```bash
SAFETY_SECRET=test-secret-for-hmac-signing-long-enough \
  SAFETY_AUTH_ENABLED=true \
  python3 -m pytest tests/test_safety.py -v
```

预期 29/29 通过。

---

## 7. 下一步（Batch 2）

Batch 1 的**限流、审计、脱敏**这三项目前**对业务代码里的 12 处 Gemini 直调完全失效**——这些调用点绕过了网关：

| 文件 | 行号 |
|---|---|
| `core/agent_engine.py` | 13 |
| `core/film_ir_manager.py` | 527, 1721, 1834, 1979, 2120 |
| `core/workflow_manager.py` | 448 |
| `core/asset_generator.py` | 101, 1216 |
| `core/runner.py` | 274, 494 |
| `core/eval_job.py` | 452 |

Batch 2 的唯一工作就是把这 12 处替换为：

```python
from core.safety.llm_gateway import llm_gateway, GatewayRequest

resp = llm_gateway().call(GatewayRequest(
    user_email=current_user.email,
    task="film_ir_build",
    material_tag=material_tag_from_job_meta,
    job_id=job_id,
    prompt=prompt,
    model_name="gemini-2.5-pro",
    call=lambda p: client.models.generate_content(model="gemini-2.5-pro", contents=[p]),
))
```

**Batch 2 未完成前，不要对外宣称"大模型调用有限流与审计"**——现状是只有"有接口没调用"。

---

## 8. 已知暂不做（MVP 取舍）

按产品决策，下列事项**刻意推迟**，等真实事故样本出来再加：

- 全量 DLP（数据防泄漏系统）
- 密钥自动轮换 / HSM
- 红队对抗演练
- 输出端 PII 扫描（Batch 2 之后补）
- 爆款参考的 logo / 人脸 / 台词相似度比对（Batch 2 之后补）
- CORS `allow_origins=["*"]` 收紧（生产部署前必改）

---

## 9. 相关文件索引

```
config/
  safety_config.json    运行时策略（限流阈值、白名单扩展名等）
  users.json            用户白名单 + token
  sensitive_terms.json  敏感词库

core/safety/
  __init__.py
  config.py             惰性单例配置加载
  auth.py               Bearer + 反代 header + 白名单
  audit_log.py          JSONL 结构化审计
  input_guard.py        文件 / 素材分级 / 敏感词
  signed_url.py         HMAC 签名
  llm_gateway.py        大模型网关（壳子，待 Batch 2 接入）

tests/test_safety.py    29 个单测覆盖主要路径

logs/audit/             按日 JSONL 审计日志（运行时生成）
```
