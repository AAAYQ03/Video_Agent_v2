import os
import json
import time
from pathlib import Path
from google import genai

PROJECT_DIR = Path(__file__).parent
VIDEO_PATH = PROJECT_DIR / "downloads" / "input.mp4"
OUT_PATH = PROJECT_DIR / "outputs" / "storyboard.json"

DIRECTOR_METAPROMPT = r"""
请你扮演一位专业的影视分镜分析师，将视频拆解为详细的分镜表。

⚠️ 【关键校准警告 - CRITICAL CALIBRATION】
内部测试表明：你检测到的镜头切换时间点通常比实际视觉变化**早 1.0-1.5 秒**。
补偿方法：输出 representative_timestamp 时，必须在你的初始估计基础上**手动加 1.0 秒**，以确保截取的帧属于正确的镜头。

📋 【核心要求 - 语义分层】
你必须将描述分为两个独立层次：

🎭 **叙事层 (Narrative Layer)** - frame_description 字段：
- 仅描述视觉内容：人物、物体、背景、环境、情节
- ❌ 禁止包含任何技术性镜头语言（如"镜头推进"、"camera pans"）
- ✅ 正确示例："A woman stands on a desolate beach at sunset, waves crashing behind her"
- ❌ 错误示例："The camera slowly pans to reveal a woman on a beach"（包含技术描述）

🎥 **技术层 (Technical Layer)** - 独立的元数据字段：
- 所有镜头技术信息必须放入专用字段，不得混入叙事描述

📐 【画幅约束】
所有描述基于 16:9 宽屏电影画幅。

🎬 【关键：摄影参数精准提取 - Cinematography Fidelity】
你必须从源视频画面中精确分析并提取以下参数，这些参数将被硬编码到生成提示中：

1️⃣ **景别 (Shot Scale)** - shot_scale 字段：
   必须严格选择以下之一：
   - "EXTREME_WIDE": 大远景，人物极小，环境为主
   - "WIDE": 全景，完整人体可见，环境占比大
   - "MEDIUM_WIDE": 中全景，膝盖以上可见
   - "MEDIUM": 中景，腰部以上可见
   - "MEDIUM_CLOSE": 中近景，胸部以上可见
   - "CLOSE_UP": 特写，面部为主
   - "EXTREME_CLOSE_UP": 大特写，眼睛/嘴唇等局部

2️⃣ **主体画面坐标 (Subject Frame Position)** - subject_frame_position 字段：
   必须精确描述主体在16:9画幅中的位置（使用九宫格坐标）：
   - "top-left", "top-center", "top-right"
   - "center-left", "center", "center-right"
   - "bottom-left", "bottom-center", "bottom-right"
   或更精确的描述如 "left-third-vertical-center", "right-third-lower"

3️⃣ **主体朝向与视线 (Orientation & Gaze)** - subject_orientation 和 gaze_direction 字段：
   subject_orientation（身体朝向）：
   - "facing-camera": 正面面对镜头
   - "back-to-camera": 背对镜头
   - "profile-left": 左侧面（面朝画面左侧）
   - "profile-right": 右侧面（面朝画面右侧）
   - "three-quarter-left": 3/4侧面朝左
   - "three-quarter-right": 3/4侧面朝右

   gaze_direction（视线方向）：
   - "looking-at-camera": 直视镜头
   - "looking-left": 看向画面左侧
   - "looking-right": 看向画面右侧
   - "looking-up": 向上看
   - "looking-down": 向下看
   - "looking-off-screen-left": 看向画外左侧
   - "looking-off-screen-right": 看向画外右侧

4️⃣ **运动矢量 (Motion Vector)** - motion_vector 字段：
   精确描述主体的运动方向和动作：
   - "static": 静止不动
   - "walking-left": 向画面左侧行走
   - "walking-right": 向画面右侧行走
   - "walking-toward-camera": 向镜头走来
   - "walking-away-from-camera": 背向镜头走去
   - "running-left/right": 奔跑方向
   - "turning-left/right": 转身方向
   - "gesturing-left/right": 手势方向
   - 复合动作如 "walking-right-while-looking-left"

你必须严格按照JSON格式输出。
根元素为包含多个分镜对象的JSON数组。

每个对象包含：
=== 叙事层字段 ===
- shot_number: 分镜序号
- frame_description: 纯视觉叙事描述（禁止包含镜头技术词汇）
- content_analysis: 场景内容与情节分析

=== 摄影参数字段（必须精确填写）===
- shot_scale: 景别（必填，从上述7个选项中选择）
- subject_frame_position: 主体在画面中的精确坐标位置
- subject_orientation: 主体身体朝向
- gaze_direction: 主体视线方向
- motion_vector: 运动矢量描述

=== 技术层字段（元数据标签）===
- camera_type: 镜头类型，如 "Static", "Dolly", "Pan", "Tilt", "Zoom", "Handheld", "Crane"
- camera_movement: 镜头运动描述，如 "Slow push in", "Pan left to right", "Static"

=== 时间与其他字段 ===
- start_time, end_time, duration_seconds: 时间信息
- representative_timestamp: 代表帧时间戳（秒，小数）【关键字段 - 必须遵守以下规则】
  * 这是新场景**100%视觉确立**的精确时刻（Peak Stability）
  * ❌ 不要选择靠近 start_time 的时间点！如果检测到切换点在 1.4s，但前一场景仍在淡出，必须选择至少 start_time + 1.0s 之后的时间
  * 📐 **短镜头规则（duration < 2秒）**：直接设置为 end_time - 0.2，这是确保快切视频场景转换完成的唯一方法
  * 📐 **正常镜头规则（duration >= 2秒）**：选择镜头时长的 70-90% 位置
  * 例如：描述"唱诗班唱歌"，分镜 3.1s-4.2s（时长 1.1s < 2s），则 representative_timestamp = 4.0（即 end_time - 0.2）
- shot_type, camera_angle: 景别与角度
- focus_and_depth: 焦点与景深描述

=== 视听层字段（SocialSaver 扩展）===
- lighting: 光线描述，如 "Natural daylight, soft shadows", "High contrast noir lighting", "Golden hour warm tones", "Neon-lit night scene"
- music_mood: 音乐/配乐氛围描述，如 "Tense orchestral", "Upbeat electronic", "Melancholic piano", "Ambient silence", "Dramatic crescendo"
- dialogue_voiceover: 对白或旁白内容（如有），直接引用原文或描述内容。无对白填 null

无信息请填 null。
仅输出纯 JSON。
""".strip()


def ensure_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "没有检测到 GEMINI_API_KEY 环境变量。\n"
            "请在当前终端执行：\n"
            '  export GEMINI_API_KEY="你的key"\n'
            "然后再运行本脚本。"
        )
    # Sanitize API key to remove non-ASCII characters (fixes encoding errors in HTTP headers)
    api_key = api_key.strip()
    api_key = ''.join(c for c in api_key if c.isascii() and c.isprintable())
    return api_key


def extract_json_array(text: str):
    import re
    if not text:
        raise ValueError("模型没有返回文本（response.text 为空）。")

    s = text.strip()

    # 🔧 Remove markdown code blocks if present
    if s.startswith("```"):
        # Find the end of the code block
        lines = s.split('\n')
        if lines[0].startswith("```"):
            lines = lines[1:]  # Remove opening ```json or ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # Remove closing ```
        s = '\n'.join(lines).strip()

    # Find JSON array bounds
    l = s.find("[")
    r = s.rfind("]")
    if l == -1 or r == -1 or r <= l:
        raise ValueError(
            "未能从模型输出中提取 JSON 数组。\n"
            "请把模型原始输出复制出来检查（它可能没有按要求输出 JSON）。"
        )

    json_str = s[l : r + 1]

    # 🔧 Fix common JSON formatting issues from LLM output
    # 1. Remove trailing commas before ] or }
    json_str = re.sub(r',\s*]', ']', json_str)
    json_str = re.sub(r',\s*}', '}', json_str)

    # 2. Remove JavaScript-style comments
    json_str = re.sub(r'//.*?\n', '\n', json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)

    # 3. Fix unquoted keys (common LLM error) - be more careful with regex
    # Only match keys that are clearly unquoted (not inside strings)
    def fix_unquoted_keys(match):
        prefix = match.group(1)
        key = match.group(2)
        return f'{prefix}"{key}":'

    json_str = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', fix_unquoted_keys, json_str)

    # 4. Fix newlines inside string values (common LLM error)
    # Replace actual newlines inside strings with \n escape
    def fix_string_newlines(s):
        result = []
        in_string = False
        escape_next = False
        for i, char in enumerate(s):
            if escape_next:
                result.append(char)
                escape_next = False
                continue
            if char == '\\':
                result.append(char)
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                result.append(char)
                continue
            if char == '\n' and in_string:
                result.append('\\n')
                continue
            result.append(char)
        return ''.join(result)

    json_str = fix_string_newlines(json_str)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Print debug info for troubleshooting
        print(f"⚠️ JSON 解析失败，尝试进一步修复...")
        print(f"错误位置: {e.msg} at line {e.lineno} col {e.colno}")

        # Print context around error
        lines = json_str.split('\n')
        error_line = e.lineno - 1
        start = max(0, error_line - 2)
        end = min(len(lines), error_line + 3)
        print(f"错误上下文:")
        for i in range(start, end):
            marker = ">>> " if i == error_line else "    "
            print(f"{marker}{i+1}: {lines[i][:100]}")

        # 5. Last resort: try to fix single quotes
        json_str_fixed = json_str.replace("'", '"')
        try:
            return json.loads(json_str_fixed)
        except:
            pass

        # 6. Try using ast.literal_eval as fallback (handles some edge cases)
        try:
            import ast
            return ast.literal_eval(json_str)
        except:
            pass

        raise ValueError(
            f"JSON 解析失败: {e.msg}\n"
            f"位置: line {e.lineno}, column {e.colno}\n"
            "请检查模型输出格式。"
        )


def wait_until_file_active(client: genai.Client, file_obj, timeout_s: int = 120, poll_s: int = 2):
    """
    Files API 上传后，文件可能处于 PROCESSING 状态，必须等到 ACTIVE 才能使用。
    """
    file_name = getattr(file_obj, "name", None)
    if not file_name:
        # 极少数情况下对象结构不同，直接返回试试
        return file_obj

    start = time.time()
    last_state = None

    while True:
        f = client.files.get(name=file_name)
        state = getattr(f, "state", None)

        if state != last_state:
            print(f"文件状态：{state}")
            last_state = state

        if state == "ACTIVE":
            return f

        if time.time() - start > timeout_s:
            raise TimeoutError(
                f"等待文件变为 ACTIVE 超时（>{timeout_s}s）。"
                "你可以重试一次，或者换更小/更常见编码的 mp4。"
            )

        time.sleep(poll_s)


def main():
    api_key = ensure_api_key()

    if not VIDEO_PATH.exists():
        raise FileNotFoundError(
            f"找不到视频文件：{VIDEO_PATH}\n"
            "请确认你已把视频放到 downloads/ 里，并命名为 input.mp4"
        )

    size_mb = VIDEO_PATH.stat().st_size / (1024 * 1024)
    print(f"准备处理视频：{VIDEO_PATH.name} ({size_mb:.1f} MB)")

    client = genai.Client(api_key=api_key)

    print("开始上传视频到 Files API…")
    uploaded = client.files.upload(file=str(VIDEO_PATH))
    print(f"✅ 上传完成：{uploaded.name}")

    print("等待文件变为 ACTIVE…")
    video_file = wait_until_file_active(client, uploaded, timeout_s=180, poll_s=2)
    print("✅ 文件已 ACTIVE，可以开始分析")

    print("开始分析视频（生成分镜 JSON）…")
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[DIRECTOR_METAPROMPT, video_file],
    )

    raw_text = getattr(response, "text", None) or ""
    storyboard = extract_json_array(raw_text)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n✅ 已生成分镜 JSON：{OUT_PATH}")
    print(f"分镜数量：{len(storyboard)}")


if __name__ == "__main__":
    main()


