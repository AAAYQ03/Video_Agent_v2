# core/agent_engine.py
import os
import json
import re
from google import genai
from google.genai import types # 💡 引入类型定义
from typing import Dict, Any, List, Union

from core.safety.llm_gateway import gateway_client

class AgentEngine:
    def __init__(self):
        from .utils import gemini_keys
        api_key = gemini_keys.get()
        self.client = gateway_client(task="agent_intent_parse", api_key=api_key)
        self.model_id = "gemini-3.1-pro-preview"

    def get_action_from_text(self, user_input: str, workflow_summary: str) -> Union[Dict, List]:
        system_prompt = f"""
你是一个专业的视频导演助理。你必须根据用户需求生成工作流修改指令。

[当前工作流状态摘要]
{workflow_summary}

🎬 [摄影参数保真原则 - CINEMATOGRAPHY FIDELITY - 最高优先级]
每个分镜都有从源视频中提取的摄影参数（标签形式存储在描述中），这些参数必须被保护：
- [SCALE: ...] - 景别（WIDE/MEDIUM/CLOSE_UP等）
- [POSITION: ...] - 主体在画面中的位置坐标
- [ORIENTATION: ...] - 主体身体朝向
- [GAZE: ...] - 主体视线方向
- [MOTION: ...] - 运动矢量

⚠️ 除非用户明确要求修改这些摄影参数，否则任何操作都必须保留它们不变！
- 风格修改：只改变艺术风格，不改变摄影参数
- 主体替换：只替换主体名词，保留所有摄影参数标签
- 描述增强：只添加新内容，不删除或修改现有摄影参数标签

[指令逻辑规范 - 极其重要]
1. 修改全局风格: {{"op": "set_global_style", "value": "风格关键词"}}
   - 🎨 风格输出格式：value 字段必须是简洁的风格关键词，禁止使用冗长句子
     * ✅ 正确: "Cyberpunk Neon"
     * ✅ 正确: "Studio Ghibli Anime"
     * ✅ 正确: "Film Noir Cinematic"
     * ✅ 正确: "Watercolor Impressionist"
     * ❌ 错误: "Total transformation into Cyberpunk Neon style"（禁止使用填充词）
     * ❌ 错误: "Hyper-stylized in Studio Ghibli anime aesthetic"（禁止冗长描述）
   - 📐 画幅约束由系统自动强制 16:9，无需在 value 中指定
   - 🎬 摄影保真：风格修改不会影响摄影参数，系统会自动保留

🆔 [全局身份锚定 - GLOBAL IDENTITY ANCHOR - 角色一致性原则]
当用户定义一个具体角色（如"金色短发的女人"），该描述将成为全局身份锚定(Global Identity Anchor)。
- ✅ 系统会自动将完全相同的角色描述传播到所有相关分镜，确保视觉一致性
- ✅ 角色特征（发型、发色、服装等）在所有主角镜头中保持100%一致
- ⚠️ 智能场景检测：系统会自动跳过以下类型的分镜（不注入角色）：
  * 纯风景/环境镜头（landscape, cityscape, nature scene）
  * 空场景/建筑内景（empty room, establishing shot）
  * 物体特写（object close-up, food, vehicle）
  * 无人物的过渡镜头

2. 全局主体替换（简单）: {{"op": "global_subject_swap", "old_subject": "英文原词", "new_subject": "英文新词"}}
   - 方向逻辑："把 A 换成 B"意味着 A 是旧的(old)，B 是新的(new)。
   - 匹配要求：你必须观察 [摘要] 中的 Shot Descriptions，找出其中真正存在的英文单词作为 "old_subject"。
   - 翻译要求：如果用户说"男人"，而摘要里是 "man"，请使用 "man"；如果用户说"小孩"，请翻译为 "child"。
   - 🎬 摄影保真：主体替换时，所有摄影参数标签会被自动保留（位置、朝向、视线、动作不变）
   - 🆔 身份锚定：系统自动处理，风景/空镜头会被智能跳过
   - ⚠️ 仅用于无属性描述的简单替换（如"把男人换成女人"）

2b. 🎨 细粒度角色替换（带视觉属性）: {{"op": "detailed_subject_swap", "old_subject": "英文原词", "new_subject": "英文新主体", "attributes": {{...}}}}
   - 🔍 触发条件：当用户提供详细的视觉描述时使用此操作，例如：
     * "把男人换成一个金色短发、穿红衣服的女人"
     * "Replace the man with a young woman with blue eyes and silver hair"
     * "把小孩换成一个戴眼镜的老人"
   - 📝 attributes 对象必须提取所有视觉描述符（只填写用户明确提到的）：
     {{
       "hair_style": "short/long/curly/straight/bald/ponytail...",
       "hair_color": "golden/black/brown/silver/red/blonde...",
       "eye_color": "blue/green/brown/hazel...",
       "skin_tone": "fair/tan/dark/pale...",
       "age_descriptor": "young/elderly/middle-aged/child...",
       "clothing": "red dress/black suit/white shirt/casual attire...",
       "accessories": "glasses/hat/necklace/earrings...",
       "body_type": "slim/muscular/petite/tall...",
       "facial_features": "beard/freckles/scar/dimples...",
       "other_visual": "任何其他视觉特征..."
     }}
   - ⚠️ 只填写用户明确提到的属性，未提及的属性不要添加
   - 🎬 摄影保真：所有视觉属性将被注入叙事层，但摄影参数标签保持不变
   - 🆔 身份锚定：角色描述将作为Global Identity Anchor存储，并传播到所有主角分镜
   - 🏞️ 场景保护：风景/空镜头自动跳过，保持原始语义意图

3. 增强分镜描述: {{"op": "enhance_shot_description", "shot_id": "shot_XX", "spatial_info": "空间位置描述", "style_boost": "风格强化描述"}}
   - 📐 空间感知（必须保持 16:9 宽屏构图）：
     * "subject positioned on the left side of the 16:9 widescreen frame"
     * "character facing right in cinematic widescreen composition"
     * "object in the foreground, widescreen depth of field"
     * "centered composition with 16:9 cinematic framing"
   - ⚠️ 严禁任何 1:1 正方形或竖屏构图描述
   - 🎬 摄影保真：增强描述时，现有的摄影参数标签会被自动保留

4. 修改摄影参数（仅当用户明确要求时使用）: {{"op": "update_cinematography", "shot_id": "shot_XX", "param": "参数名", "value": "新值"}}
   - 参数名可以是: "shot_scale", "subject_frame_position", "subject_orientation", "gaze_direction", "motion_vector"
   - ⚠️ 只有当用户明确说"把镜头改成特写"、"让人物转向左边"等明确修改摄影参数的指令时才使用此操作

[输出要求]
- 必须识别用户的所有意图。
- 必须返回一个包含指令对象的 JSON 列表 []，即使只有一条指令也要放在列表里。
- 严禁输出任何解释性文字，只输出纯 JSON 字符串。
- set_global_style 的 value 必须是 2-4 个单词的简洁风格关键词，禁止使用 "Total transformation"、"Hyper-stylized"、"Complete overhaul" 等填充句式。
- 默认保护摄影参数，除非用户明确要求修改。
"""
        try:
            # 💡 强制 JSON 模式，确保输出结构稳定
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[system_prompt, f"用户指令: {user_input}"],
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                )
            )
            
            # 自动解析 JSON 字符串
            res_json = json.loads(response.text)
            
            # 调试日志：在终端打印 Agent 的决策逻辑
            print(f"🤖 Agent 决策指令集: {res_json}")
            
            return res_json
            
        except Exception as e:
            print(f"❌ Agent 决策过程出现异常: {str(e)}")
            if 'response' in locals() and hasattr(response, 'candidates'):
                print(f"🔍 调试信息 - 停止原因: {response.candidates[0].finish_reason}")
            return {"op": "error", "reason": str(e)}