# core/meta_prompts/intent_fusion.py
"""
Meta Prompt: 意图融合引擎 (Intent Fusion Engine)
将 Abstract Template + Parsed Intent 融合生成 Remixed Film IR

核心职责:
1. 生成 remixedIdentityAnchors (80-120字极致细节描述) - Stage 4 资产生成的唯一文本源
2. 生成 remixedShots (每镜头的 T2I + I2V prompts)
3. 保持摄影骨架 (cameraPreserved) 的绝对继承
4. 确保 Veo 3.1 对 Imagen 首帧的绝对继承
"""

from typing import Dict, Any, Optional, List


INTENT_FUSION_PROMPT = """
# Role: AI Director & Prompt Architect (AI 导演与提示词架构师)

You are an expert at fusing creative intents with cinematic templates to produce executable generation instructions for Imagen 4.0 and Veo 3.1.

---

## Mission Critical Constraints

### 1. Cinematography Fidelity (摄影语言保真)
- **NEVER** alter the camera skeleton (cameraPreserved) unless explicitly requested
- **ALWAYS** preserve: shot size, camera angle, camera movement, focal length implications
- The new content must FIT the original framing (e.g., if original is CLOSE_UP, new subject must be framed as CLOSE_UP)

### 2. First Frame Inheritance (首帧绝对继承)
- Veo 3.1's I2V_VideoGen prompt MUST explicitly reference the Imagen-generated first frame
- Include: "maintaining exact composition, lighting, and subject position from the first frame"
- This is the KEY to visual coherence in Google's pipeline

### 3. Physical Realism (物理真实感)
- Even in stylized modes (LEGO, anime, watercolor), enforce:
  - Gravity and weight
  - Collision and contact physics
  - Fluid/particle dynamics
  - Material-appropriate motion (plastic rattles, metal clanks, fabric flows)

### 4. Aspect Ratio Lock
- ALL T2I prompts MUST end with: --ar {aspect_ratio}
- ALL descriptions must assume {aspect_ratio} framing

---

## Three-Step Fusion Workflow

### Step 1: Visual Synergy Analysis (视觉协同分析)

For each shot, analyze:
1. **Camera Skeleton Match**: How does the new subject/environment fit the original shot composition?
2. **Hook Point Identification**: What visual opportunities does the new content create with the existing rhythm?
3. **Scale Calibration**: Ensure new subjects match the implied scale of the shot size

### Step 2: Identity Anchor Generation (身份锚点生成)

For EACH new subject/environment, generate an 80-120 word "Identity Anchor" description:
- **Character Anchors**: Extreme detail on appearance, costume, distinguishing features, expression tendencies
- **Environment Anchors**: Atmosphere, architectural style, lighting conditions, ambient elements

These descriptions become the SOLE text source for Stage 4 asset generation. They must be:
- Visually exhaustive (no ambiguity)
- Consistent across all shots
- Style-appropriate (if LEGO style, describe LEGO-specific features)
- Do NOT include watermark/logo artifacts as character features (e.g., do not describe a TikTok logo on someone's cheek as a "facial marking")

**⚠️ CRITICAL — Clothing/Props Inheritance Rule:**
When `persistentAttributes` contains clothing, accessories, or interactive props inherited from the original character, the Identity Anchor description MUST incorporate ALL of them. Do NOT invent new clothing or props — use the ones from `persistentAttributes`. The new subject's identity (face, body type, species) changes, but their outfit, belongings, and nearby objects stay the same unless the user explicitly requested otherwise.

### Step 3: Executable Prompt Generation (可执行提示词生成)

For EACH shot, generate TWO distinct prompts:

#### A. T2I_FirstFrame (Imagen 4.0)
Purpose: Generate a STATIC, ultra-high-detail starting frame

Format Structure:
```
[Subject Description], [Exact Pose/Action State], [Environment Details],
[Style & Atmosphere], [Lighting Setup], [Camera Specs: shot size, angle],
[Composition: subject position using rule of thirds],
[Technical: high detail, sharp focus, cinematic quality] --ar {aspect_ratio}
```

Requirements:
- This is a FROZEN MOMENT - describe the exact state at frame 1
- Include composition position (e.g., "subject centered", "positioned on left third")
- Include the Identity Anchor's persistent attributes
- Reference image binding: If imageReference exists, include "matching reference image style and features"

#### B. I2V_VideoGen (Veo 3.1)
Purpose: Animate from the first frame with precise motion control

Format Structure:
```
[Camera Movement from cameraPreserved], [Specific Action Sequence],
[Physics Details: secondary motion, particles, fabric],
[Atmosphere Evolution: lighting shifts, environmental changes],
[Continuity Anchor: "maintaining exact composition, lighting, and subject position from the first frame"],
high motion quality, cinematic, smooth motion, [duration]s
```

Requirements:
- Start with camera movement instruction (from cameraPreserved)
- Describe motion ARC from start to end of shot
- Include secondary physics (hair, cloth, particles, reflections)
- MUST include: "inheriting the first frame's composition and lighting"
- Specify duration in seconds

---

## Output Format (Strict JSON)

{
  "fusionSuccess": true,
  "fusionTimestamp": "ISO timestamp",

  "remixedIdentityAnchors": {
    "characters": [
      {
        "anchorId": "char_01",
        "originalPlaceholder": "[PROTAGONIST_A]",
        "anchorName": "Human-readable name",
        "detailedDescription": "80-120 word exhaustive visual description...",
        "persistentAttributes": ["red cape", "metallic armor"],
        "imageReference": "path/to/ref.jpg or null",
        "styleAdaptation": "How this character looks in the target style"
      }
    ],
    "environments": [
      {
        "anchorId": "env_01",
        "originalPlaceholder": "[SETTING]",
        "anchorName": "Location name",
        "detailedDescription": "80-120 word exhaustive environment description...",
        "atmosphericConditions": "lighting, weather, time of day",
        "styleAdaptation": "How this environment looks in the target style"
      }
    ]
  },

  "remixedShots": [
    {
      "shotId": "shot_01",
      "beatTag": "HOOK",
      "startTime": "00:00:00.000",
      "endTime": "00:00:03.000",
      "durationSeconds": 3.0,

      "cameraPreserved": {
        "shotSize": "MEDIUM",
        "cameraAngle": "Eye-level",
        "cameraMovement": "Static",
        "focalLengthDepth": "50mm, shallow DOF"
      },

      "T2I_FirstFrame": "Complete Imagen 4.0 prompt string ending with --ar {aspect_ratio}",

      "I2V_VideoGen": "Complete Veo 3.1 prompt string with first-frame inheritance clause",

      "remixNotes": "Brief explanation of what changed in this shot",

      "appliedAnchors": {
        "characters": ["char_01"],
        "environments": ["env_01"]
      }
    }
  ],

  "globalRemixSummary": {
    "totalShots": 25,
    "shotsModified": 25,
    "primaryChanges": ["subject replacement", "environment change"],
    "styleApplied": "LEGO style with ray-traced reflections",
    "moodShift": "from chaotic stress to playful humor",
    "preservedElements": ["camera skeleton", "narrative rhythm", "beat structure"]
  }
}

---

## Input Data

### Parsed Intent (from Intent Parser):
{parsed_intent}

### Abstract Template (from Film IR Pillars):
{abstract_template}

### Concrete Reference (original analysis for context):
{concrete_reference}

---

## Special Instructions for Google Models

### Imagen 4.0 Composition Protection
- ALWAYS include original shot's composition position
- Use phrases: "subject centered", "positioned on left third", "rule of thirds composition"
- This preserves Cinematography Fidelity

### Veo 3.1 Motion Vector Control
- Translate cameraPreserved.cameraMovement to strong motion verbs:
  - "Static" → "camera holds steady on"
  - "Pan L/R" → "camera pans smoothly left/right revealing"
  - "Dolly In" → "camera pushes in toward"
  - "Track" → "camera tracks alongside"
  - "Handheld" → "subtle handheld motion following"
- Include: "maintaining consistent lighting from the first frame"

### Physical Detail Enhancement
- For LEGO style: "plastic textures, visible brick studs, ray-traced reflections on glossy surfaces, pieces rattling with motion"
- For realistic style: "photorealistic skin texture, natural fabric movement, atmospheric particles"
- For anime style: "cel-shaded rendering, dynamic motion lines, exaggerated expressions"

---

Output ONLY the JSON object. No markdown, no explanation.
"""


def convert_to_remixed_layer(ai_output: dict) -> dict:
    """
    将 AI 输出转换为 Film IR 的 remixed 层格式

    Args:
        ai_output: Gemini 返回的融合结果

    Returns:
        可直接存入 pillars.*.remixed 的数据结构
    """
    return {
        "identityAnchors": ai_output.get("remixedIdentityAnchors", {
            "characters": [],
            "environments": []
        }),
        "shots": ai_output.get("remixedShots", []),
        "summary": ai_output.get("globalRemixSummary", {}),
        "fusionTimestamp": ai_output.get("fusionTimestamp", ""),
        "fusionSuccess": ai_output.get("fusionSuccess", False)
    }


def extract_identity_anchors(ai_output: dict) -> dict:
    """
    提取 Identity Anchors，用于 Stage 4 资产生成

    Returns:
        {characters: [...], environments: [...]}
    """
    anchors = ai_output.get("remixedIdentityAnchors", {})

    return {
        "characters": [
            {
                "anchorId": c.get("anchorId"),
                "anchorName": c.get("anchorName"),
                "detailedDescription": c.get("detailedDescription", ""),
                "persistentAttributes": c.get("persistentAttributes", []),
                "imageReference": c.get("imageReference"),
                "styleAdaptation": c.get("styleAdaptation", "")
            }
            for c in anchors.get("characters", [])
        ],
        "environments": [
            {
                "anchorId": e.get("anchorId"),
                "anchorName": e.get("anchorName"),
                "detailedDescription": e.get("detailedDescription", ""),
                "atmosphericConditions": e.get("atmosphericConditions", ""),
                "styleAdaptation": e.get("styleAdaptation", "")
            }
            for e in anchors.get("environments", [])
        ]
    }


def extract_t2i_prompts(ai_output: dict) -> List[dict]:
    """
    提取所有 T2I 首帧提示词，用于 Imagen 4.0 批量生成

    Returns:
        List of {shotId, prompt, cameraPreserved}
    """
    shots = ai_output.get("remixedShots", [])

    return [
        {
            "shotId": shot.get("shotId"),
            "prompt": shot.get("T2I_FirstFrame", ""),
            "cameraPreserved": shot.get("cameraPreserved", {}),
            "appliedAnchors": shot.get("appliedAnchors", {})
        }
        for shot in shots
    ]


def extract_i2v_prompts(ai_output: dict) -> List[dict]:
    """
    提取所有 I2V 视频生成提示词，用于 Veo 3.1 批量生成

    Returns:
        List of {shotId, prompt, durationSeconds, cameraPreserved}
    """
    shots = ai_output.get("remixedShots", [])

    return [
        {
            "shotId": shot.get("shotId"),
            "prompt": shot.get("I2V_VideoGen", ""),
            "durationSeconds": shot.get("durationSeconds", 3.0),
            "cameraPreserved": shot.get("cameraPreserved", {}),
            "firstFrameInheritance": True  # 标记需要首帧继承
        }
        for shot in shots
    ]


def _compose_original_first_frame(shot: dict) -> str:
    """
    从 concrete 层的分散字段组合原始首帧描述
    """
    parts = []

    # Subject
    subject = shot.get("subject", "")
    if subject:
        parts.append(subject)

    # Scene
    scene = shot.get("scene", "")
    if scene:
        parts.append(scene)

    # Camera
    camera = shot.get("camera", "")
    if camera:
        parts.append(f"Camera: {camera}")

    # Lighting
    lighting = shot.get("lighting", "")
    if lighting:
        parts.append(f"Lighting: {lighting}")

    # Style
    style = shot.get("style", "")
    if style:
        parts.append(f"Style: {style}")

    return ". ".join(parts) if parts else ""


def get_remix_diff(concrete: dict, remixed: dict) -> List[dict]:
    """
    生成 concrete vs remixed 的差异对比，用于前端 Diff View

    Args:
        concrete: 原始 concrete 层数据
        remixed: 融合后的 remixed 层数据

    Returns:
        List of diff entries for each shot
    """
    concrete_shots = concrete.get("shots", [])
    remixed_shots = remixed.get("shots", [])

    # 建立 shotId 索引
    concrete_map = {s.get("shotId"): s for s in concrete_shots}
    remixed_map = {s.get("shotId"): s for s in remixed_shots}

    diffs = []

    for shot_id in remixed_map.keys():
        original = concrete_map.get(shot_id, {})
        modified = remixed_map.get(shot_id, {})

        # 从 concrete 层字段组合原始首帧描述
        original_first_frame = _compose_original_first_frame(original)

        diff_entry = {
            "shotId": shot_id,
            "beatTag": modified.get("beatTag", original.get("beatTag", "")),
            "changes": [],
            "originalFirstFrame": original_first_frame,
            "remixedFirstFrame": modified.get("T2I_FirstFrame", ""),
            "remixNotes": modified.get("remixNotes", "")
        }

        # 检测主体变化
        if modified.get("appliedAnchors", {}).get("characters"):
            diff_entry["changes"].append({
                "type": "SUBJECT_CHANGE",
                "description": f"Applied character anchors: {modified['appliedAnchors']['characters']}"
            })

        # 检测环境变化
        if modified.get("appliedAnchors", {}).get("environments"):
            diff_entry["changes"].append({
                "type": "ENVIRONMENT_CHANGE",
                "description": f"Applied environment anchors: {modified['appliedAnchors']['environments']}"
            })

        diffs.append(diff_entry)

    return diffs


def validate_fusion_output(ai_output: dict) -> tuple:
    """
    验证融合输出的完整性和合规性

    Returns:
        (is_valid: bool, issues: List[str])
    """
    issues = []

    # 检查必要字段
    if not ai_output.get("fusionSuccess"):
        issues.append("Fusion reported as unsuccessful")

    # 检查 Identity Anchors
    anchors = ai_output.get("remixedIdentityAnchors", {})
    if not anchors.get("characters") and not anchors.get("environments"):
        issues.append("No identity anchors generated")

    # 检查 remixed shots
    shots = ai_output.get("remixedShots", [])
    if not shots:
        issues.append("No remixed shots generated")

    for i, shot in enumerate(shots):
        # 检查 T2I prompt
        t2i = shot.get("T2I_FirstFrame", "")
        if not t2i:
            issues.append(f"Shot {shot.get('shotId', i)}: Missing T2I_FirstFrame prompt")
        elif "--ar " not in t2i:
            issues.append(f"Shot {shot.get('shotId', i)}: T2I prompt missing --ar aspect ratio suffix")

        # 检查 I2V prompt
        i2v = shot.get("I2V_VideoGen", "")
        if not i2v:
            issues.append(f"Shot {shot.get('shotId', i)}: Missing I2V_VideoGen prompt")
        elif "first frame" not in i2v.lower() and "maintaining" not in i2v.lower():
            issues.append(f"Shot {shot.get('shotId', i)}: I2V prompt missing first-frame inheritance clause")

        # 检查 cameraPreserved
        if not shot.get("cameraPreserved"):
            issues.append(f"Shot {shot.get('shotId', i)}: Missing cameraPreserved")

    return (len(issues) == 0, issues)


def generate_fusion_summary(ai_output: dict) -> str:
    """
    生成人类可读的融合摘要

    Returns:
        Summary string for logging/display
    """
    summary = ai_output.get("globalRemixSummary", {})

    total = summary.get("totalShots", 0)
    modified = summary.get("shotsModified", 0)
    changes = summary.get("primaryChanges", [])
    style = summary.get("styleApplied", "None")
    mood = summary.get("moodShift", "unchanged")

    anchors = ai_output.get("remixedIdentityAnchors", {})
    char_count = len(anchors.get("characters", []))
    env_count = len(anchors.get("environments", []))

    lines = [
        f"=== Fusion Summary ===",
        f"Shots: {modified}/{total} modified",
        f"Identity Anchors: {char_count} characters, {env_count} environments",
        f"Primary Changes: {', '.join(changes) if changes else 'None'}",
        f"Style Applied: {style}",
        f"Mood Shift: {mood}",
        f"======================"
    ]

    return "\n".join(lines)


def clean_prompt_artifacts(prompt: str) -> str:
    """
    清理 Gemini 输出中的残留字符和格式问题

    Args:
        prompt: 原始 prompt 字符串

    Returns:
        清理后的 prompt
    """
    import re

    if not prompt:
        return ""

    # 移除箭头符号及其周围内容（如 "A → B" 变成 "B"）
    # 这种情况通常是 Gemini 生成了 "原始 → 修改" 格式
    if "→" in prompt:
        # 尝试提取箭头后面的内容
        parts = prompt.split("→")
        if len(parts) == 2:
            # 取箭头后面的部分，去除前导空格
            prompt = parts[1].strip()

    # 移除其他常见残留
    prompt = prompt.replace("➡️", "")
    prompt = prompt.replace("➜", "")
    prompt = prompt.replace("=>", "")

    # 移除多余的空格
    prompt = re.sub(r'\s+', ' ', prompt).strip()

    return prompt


def resolve_anchor_placeholders(
    prompt: str,
    identity_anchors: dict,
    mode: str = "name"  # "name" 或 "description"
) -> str:
    """
    解析 prompt 中的占位符，替换为实际的 anchor 信息

    Args:
        prompt: 包含占位符的 prompt（如 [PROTAGONIST], [SETTING]）
        identity_anchors: {characters: [...], environments: [...]}
        mode:
            - "name": 用 anchorName 替换（简洁，适合 prompt）
            - "description": 用 detailedDescription 替换（详细，适合资产生成）

    Returns:
        替换后的 prompt
    """
    import re

    if not prompt:
        return ""

    result = prompt

    # 构建占位符映射
    placeholder_map = {}

    # 处理角色 anchors
    for char in identity_anchors.get("characters", []):
        original_ph = char.get("originalPlaceholder", "")
        anchor_name = char.get("anchorName", "")
        description = char.get("detailedDescription", "")

        if original_ph:
            placeholder_map[original_ph] = anchor_name if mode == "name" else description

        # 也处理通用占位符
        placeholder_map["[PROTAGONIST]"] = anchor_name if mode == "name" else description
        placeholder_map["[PROTAGONIST_A]"] = anchor_name if mode == "name" else description
        placeholder_map["[CHARACTER]"] = anchor_name if mode == "name" else description

    # 处理环境 anchors
    for env in identity_anchors.get("environments", []):
        original_ph = env.get("originalPlaceholder", "")
        anchor_name = env.get("anchorName", "")
        description = env.get("detailedDescription", "")

        if original_ph:
            placeholder_map[original_ph] = anchor_name if mode == "name" else description

        # 也处理通用占位符
        placeholder_map["[SETTING]"] = anchor_name if mode == "name" else description
        placeholder_map["[ENVIRONMENT]"] = anchor_name if mode == "name" else description
        placeholder_map["[LOCATION]"] = anchor_name if mode == "name" else description

    # 执行替换
    for placeholder, replacement in placeholder_map.items():
        if placeholder and replacement:
            result = result.replace(placeholder, replacement)

    return result


def normalize_camera_field(value: str) -> str:
    """
    规范化相机字段值，处理 null/None 等情况

    Args:
        value: 原始值

    Returns:
        规范化后的值
    """
    if not value or value.lower() in ["null", "none", "undefined", ""]:
        return "facing-camera"  # 默认值
    return value


def post_process_remixed_layer(remixed_layer: dict) -> dict:
    """
    对整个 remixed_layer 进行后处理，修复所有已知问题

    Args:
        remixed_layer: 原始融合结果

    Returns:
        清理后的 remixed_layer
    """
    identity_anchors = remixed_layer.get("identityAnchors", {})
    shots = remixed_layer.get("shots", [])

    processed_shots = []
    for shot in shots:
        processed_shot = shot.copy()

        # 1. 清理 prompt artifacts
        if "T2I_FirstFrame" in processed_shot:
            processed_shot["T2I_FirstFrame"] = clean_prompt_artifacts(
                processed_shot["T2I_FirstFrame"]
            )
        if "I2V_VideoGen" in processed_shot:
            processed_shot["I2V_VideoGen"] = clean_prompt_artifacts(
                processed_shot["I2V_VideoGen"]
            )

        # 2. 解析占位符
        if "T2I_FirstFrame" in processed_shot:
            processed_shot["T2I_FirstFrame"] = resolve_anchor_placeholders(
                processed_shot["T2I_FirstFrame"],
                identity_anchors,
                mode="name"
            )
        if "I2V_VideoGen" in processed_shot:
            processed_shot["I2V_VideoGen"] = resolve_anchor_placeholders(
                processed_shot["I2V_VideoGen"],
                identity_anchors,
                mode="name"
            )

        # 3. 规范化 cameraPreserved 字段
        camera = processed_shot.get("cameraPreserved", {})
        if camera:
            processed_shot["cameraPreserved"] = {
                "shotSize": camera.get("shotSize", "MEDIUM"),
                "cameraAngle": normalize_camera_field(camera.get("cameraAngle", "")),
                "cameraMovement": camera.get("cameraMovement", "Static"),
                "focalLengthDepth": camera.get("focalLengthDepth", "Standard")
            }

        processed_shots.append(processed_shot)

    # 返回处理后的结果
    return {
        **remixed_layer,
        "shots": processed_shots
    }
