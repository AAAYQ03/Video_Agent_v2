# core/asset_generator.py
"""
Asset Generator - Gemini 3 Pro Image 资产生成器

使用 Gemini 3 Pro Image Preview 生成角色三视图和环境参考图。
支持参考图片输入以保持角色一致性。
"""

import os
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
from PIL import Image
import io

from core.safety.llm_gateway import gateway_client


class AssetType(Enum):
    """资产类型"""
    # Character three-views
    CHARACTER_FRONT = "front"
    CHARACTER_SIDE = "side"
    CHARACTER_BACK = "back"
    # Environment/Scene three-views
    ENVIRONMENT = "reference"  # Legacy: single reference image
    ENVIRONMENT_WIDE = "wide"  # Wide shot (全景)
    ENVIRONMENT_DETAIL = "detail"  # Detail view (细节)
    ENVIRONMENT_ALT = "alt"  # Alternative angle (备选角度)
    # Product three-views
    PRODUCT_FRONT = "front"
    PRODUCT_SIDE = "side"
    PRODUCT_BACK = "back"


class AssetStatus(Enum):
    """资产生成状态"""
    NOT_STARTED = "NOT_STARTED"
    GENERATING = "GENERATING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass
class GeneratedAsset:
    """生成的资产"""
    anchor_id: str
    asset_type: AssetType
    file_path: Optional[str]
    status: AssetStatus
    error_message: Optional[str] = None


class AssetGenerator:
    """
    Gemini 3 Pro Image 资产生成器

    Features:
    - 角色三视图生成（链式生成保持一致性）
    - 环境参考图生成
    - 支持用户参考图片输入
    - 自动保存到 jobs/{job_id}/assets/
    """

    MODEL_NAME = "gemini-3-pro-image-preview"
    DEFAULT_RESOLUTION = "2K"
    ASPECT_RATIO = "16:9"

    def __init__(self, job_id: str, project_root: str):
        """
        初始化资产生成器

        Args:
            job_id: 任务 ID
            project_root: 项目根目录
        """
        self.job_id = job_id
        self.project_root = Path(project_root)
        self.assets_dir = self.project_root / "jobs" / job_id / "assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        # 初始化 Gemini 客户端
        self._init_client()

        # 生成状态追踪
        self.generation_status: Dict[str, AssetStatus] = {}

    def _init_client(self):
        """初始化 Gemini 客户端"""
        try:
            from google import genai
            from google.genai import types

            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable not set")
            # Sanitize API key to remove non-ASCII characters (fixes encoding errors in HTTP headers)
            api_key = api_key.strip()
            api_key = ''.join(c for c in api_key if c.isascii() and c.isprintable())

            self.client = gateway_client(task="asset_generation_init", api_key=api_key)
            self.types = types
            print(f"✅ Gemini client initialized for asset generation")

        except ImportError:
            raise ImportError("Please install google-genai: pip install google-genai")

    def _build_character_prompt(
        self,
        view: AssetType,
        detailed_description: str,
        anchor_name: str,
        style_adaptation: str = "",
        persistent_attributes: List[str] = None,
        visual_style: Dict[str, str] = None,
        has_reference: bool = False
    ) -> str:
        """
        构建角色视图 prompt

        Args:
            view: 视图类型 (front/side/back)
            detailed_description: 80-120字详细描述
            anchor_name: 角色名称
            style_adaptation: 风格适配说明
            persistent_attributes: 持久属性列表
            visual_style: Visual Style 配置 (artStyle, colorPalette, lightingMood, cameraStyle)
            has_reference: 是否有用户上传的参考图片
        """
        view_instructions = {
            AssetType.CHARACTER_FRONT: "front facing view, looking directly at camera",
            AssetType.CHARACTER_SIDE: "side profile view, facing left, same character as reference",
            AssetType.CHARACTER_BACK: "back view, facing away from camera, same character as reference"
        }

        attributes_str = ""
        if persistent_attributes:
            attributes_str = f"Key visual features: {', '.join(persistent_attributes)}. "

        style_str = ""
        if style_adaptation:
            style_str = f"Style: {style_adaptation}. "

        # Build visual style instructions
        visual_style_str = ""
        if visual_style:
            vs_parts = []
            if visual_style.get("artStyle"):
                vs_parts.append(f"Art style: {visual_style['artStyle']}")
            if visual_style.get("colorPalette"):
                vs_parts.append(f"Color palette: {visual_style['colorPalette']}")
            if visual_style.get("lightingMood"):
                vs_parts.append(f"Lighting: {visual_style['lightingMood']}")
            if vs_parts:
                visual_style_str = "\n".join(vs_parts) + "\n"

        if has_reference and detailed_description:
            # Has reference image + text description: prioritize the reference image
            prompt = f"""Cinematic character reference image, {view_instructions[view]}.

Subject: {anchor_name}
The attached reference image shows the EXACT target character. Generate this character from the specified view angle.
Use the following description only as supplementary context; if there is any conflict between the reference image and the text, the reference image takes priority.
Description: {detailed_description}

{attributes_str}{style_str}
{visual_style_str}
Technical requirements:
- ONLY draw the single character shown in the reference image
- Do NOT add any other characters even if mentioned in the description
- Match the reference image character's appearance exactly (color, shape, features, clothing)
- Maintain the pose, action, and setting described (e.g., sitting in car, standing in room)
- Professional cinematic lighting
- High detail, sharp focus
- No text, no watermarks, no logos
- Consistent character appearance across all views
- 16:9 widescreen composition
"""
        elif detailed_description:
            # Has text description only (no reference image): use original logic
            prompt = f"""Cinematic character reference image, {view_instructions[view]}.

Subject: {anchor_name}
{detailed_description}

{attributes_str}{style_str}
{visual_style_str}
Technical requirements:
- Keep all characters, objects, and environment mentioned in the description
- Maintain the pose, action, and setting described (e.g., sitting in car, standing in room)
- Professional cinematic lighting
- High detail, sharp focus
- No text, no watermarks, no logos
- Consistent character appearance across all views
- 16:9 widescreen composition
- If multiple characters are described, show all of them in the scene
"""
        else:
            # No text description: rely entirely on the reference image
            prompt = f"""Cinematic character reference image, {view_instructions[view]}.

CRITICAL: Generate the EXACT SAME character/subject as shown in the provided reference image.
Match every visual detail: colors, textures, proportions, clothing, features, and overall appearance.
Do NOT change the character's appearance in any way.

{attributes_str}{style_str}
{visual_style_str}
Technical requirements:
- The character must look IDENTICAL to the reference image
- Only change the viewing angle as specified above
- Professional cinematic lighting
- High detail, sharp focus
- No text, no watermarks, no logos
- 16:9 widescreen composition
"""
        return prompt.strip()

    def _build_environment_prompt(
        self,
        detailed_description: str,
        anchor_name: str,
        atmospheric_conditions: str = "",
        style_adaptation: str = ""
    ) -> str:
        """
        构建环境参考图 prompt (Legacy: single reference)

        Args:
            detailed_description: 80-120字详细描述
            anchor_name: 环境名称
            atmospheric_conditions: 大气条件（光照/天气/时间）
            style_adaptation: 风格适配说明
        """
        atmosphere_str = ""
        if atmospheric_conditions:
            atmosphere_str = f"Lighting and atmosphere: {atmospheric_conditions}. "

        style_str = ""
        if style_adaptation:
            style_str = f"Style: {style_adaptation}. "

        prompt = f"""Cinematic environment establishing shot, wide angle composition.

Location: {anchor_name}
{detailed_description}

{atmosphere_str}{style_str}

Technical requirements:
- Wide angle lens perspective
- Rich environmental detail
- Cinematic color grading
- High detail, sharp focus throughout
- No people, no characters
- No text, no watermarks, no logos
- 16:9 widescreen composition
- Suitable as background reference for video production
"""
        return prompt.strip()

    def _build_environment_view_prompt(
        self,
        view: AssetType,
        detailed_description: str,
        anchor_name: str,
        atmospheric_conditions: str = "",
        style_adaptation: str = "",
        visual_style: Dict[str, str] = None
    ) -> str:
        """
        构建环境三视图 prompt

        Args:
            view: 视图类型 (wide/detail/alt)
            detailed_description: 80-120字详细描述
            anchor_name: 环境名称
            atmospheric_conditions: 大气条件
            style_adaptation: 风格适配说明
            visual_style: Visual Style 配置 (artStyle, colorPalette, lightingMood, cameraStyle)
        """
        view_instructions = {
            AssetType.ENVIRONMENT_WIDE: {
                "shot_type": "extreme wide establishing shot",
                "lens": "14-24mm ultra wide angle lens",
                "focus": "Capture the full scope and scale of the environment, showing spatial relationships and overall layout",
                "composition": "Environment fills the frame, emphasizing vastness and context",
                "camera_position": "Camera positioned far back to show entire scene, eye-level or slightly elevated"
            },
            AssetType.ENVIRONMENT_DETAIL: {
                "shot_type": "close-up detail shot",
                "lens": "85-135mm macro lens",
                "focus": "IMPORTANT: This is a CLOSE-UP shot focusing on textures, materials, and small distinctive features. Show surface details like wood grain, stone texture, fabric weave, metal patina, or natural patterns",
                "composition": "Fill frame with interesting textures and details. Show wear marks, reflections, or intricate patterns. This should look completely different from a wide shot",
                "camera_position": "Camera very close to surfaces, shooting textures and small objects at near-macro distance"
            },
            AssetType.ENVIRONMENT_ALT: {
                "shot_type": "dramatic low angle or high angle shot",
                "lens": "24-35mm wide angle lens",
                "focus": "IMPORTANT: Shoot from a dramatically DIFFERENT angle - either looking UP from ground level or looking DOWN from above. Show the environment from an unexpected perspective",
                "composition": "Use strong diagonal lines, dramatic perspective distortion, or bird's eye / worm's eye view. This should feel like a completely different vantage point",
                "camera_position": "Camera either very low (ground level looking up) or very high (looking down), creating dramatic perspective"
            }
        }

        instructions = view_instructions.get(view, view_instructions[AssetType.ENVIRONMENT_WIDE])

        atmosphere_str = ""
        if atmospheric_conditions:
            atmosphere_str = f"Lighting and atmosphere: {atmospheric_conditions}. "

        style_str = ""
        if style_adaptation:
            style_str = f"Style: {style_adaptation}. "

        camera_position = instructions.get('camera_position', '')

        # Build visual style instructions
        visual_style_str = ""
        if visual_style:
            vs_parts = []
            if visual_style.get("artStyle"):
                vs_parts.append(f"Art style: {visual_style['artStyle']}")
            if visual_style.get("colorPalette"):
                vs_parts.append(f"Color palette: {visual_style['colorPalette']}")
            if visual_style.get("lightingMood"):
                vs_parts.append(f"Lighting mood: {visual_style['lightingMood']}")
            if vs_parts:
                visual_style_str = "VISUAL STYLE:\n" + "\n".join(vs_parts) + "\n\n"

        prompt = f"""Cinematic environment {instructions['shot_type']}, {instructions['lens']} perspective.

Location: {anchor_name}
{detailed_description}

SHOT REQUIREMENTS:
{instructions['focus']}
{instructions['composition']}
{camera_position}

{atmosphere_str}{style_str}
{visual_style_str}
Technical requirements:
- {instructions['lens']} perspective
- Rich environmental detail
- Cinematic color grading
- High detail, sharp focus throughout
- No people, no characters
- No text, no watermarks, no logos
- 16:9 widescreen composition
- Suitable as background reference for video production
"""
        return prompt.strip()

    async def _generate_image(
        self,
        prompt: str,
        reference_images: List[Image.Image] = None
    ) -> Tuple[Optional[Image.Image], Optional[str]]:
        """
        调用 Gemini API 生成图片

        Args:
            prompt: 生成 prompt
            reference_images: 参考图片列表

        Returns:
            (生成的图片, 错误信息)
        """
        try:
            # 构建 contents
            contents = [prompt]
            if reference_images:
                for ref_img in reference_images:
                    contents.append(ref_img)

            # 配置生成参数
            config = self.types.GenerateContentConfig(
                response_modalities=['IMAGE'],
            )

            # 调用 API
            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=contents,
                config=config
            )

            # 提取生成的图片
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data is not None:
                    # 从 bytes 创建 PIL Image
                    image_data = part.inline_data.data
                    image = Image.open(io.BytesIO(image_data))
                    return image, None

            return None, "No image generated in response"

        except Exception as e:
            return None, str(e)

    def _generate_image_sync(
        self,
        prompt: str,
        reference_images: List[Image.Image] = None
    ) -> Tuple[Optional[Image.Image], Optional[str]]:
        """
        同步版本的图片生成

        When reference images are provided, uses TEXT+IMAGE mode (image editing)
        so Gemini actually references the input images.
        Without reference images, uses IMAGE-only mode (text-to-image).
        """
        try:
            # 构建 contents
            contents = [prompt]
            if reference_images:
                for ref_img in reference_images:
                    contents.append(ref_img)

            # 有参考图时用 TEXT+IMAGE 模式（图片编辑），Gemini 才会真正参考输入图片
            # 无参考图时用纯 IMAGE 模式（文生图）
            if reference_images:
                config = self.types.GenerateContentConfig(
                    response_modalities=['TEXT', 'IMAGE'],
                )
            else:
                config = self.types.GenerateContentConfig(
                    response_modalities=['IMAGE'],
                )

            # 调用 API
            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=contents,
                config=config
            )

            # 提取生成的图片
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data is not None:
                    image_data = part.inline_data.data
                    image = Image.open(io.BytesIO(image_data))
                    return image, None

            return None, "No image generated in response"

        except Exception as e:
            return None, str(e)

    def generate_character_assets(
        self,
        anchor_id: str,
        anchor_name: str,
        detailed_description: str,
        style_adaptation: str = "",
        persistent_attributes: List[str] = None,
        user_reference_path: str = None,
        on_progress: callable = None
    ) -> Dict[str, GeneratedAsset]:
        """
        生成角色三视图资产（链式生成）

        Args:
            anchor_id: 锚点 ID (如 char_01)
            anchor_name: 角色名称
            detailed_description: 详细描述
            style_adaptation: 风格适配
            persistent_attributes: 持久属性
            user_reference_path: 用户上传的参考图路径
            on_progress: 进度回调函数

        Returns:
            {view: GeneratedAsset} 三视图资产字典
        """
        results = {}
        reference_images = []

        # 加载用户参考图（如果有）
        if user_reference_path and os.path.exists(user_reference_path):
            try:
                user_ref = Image.open(user_reference_path)
                reference_images.append(user_ref)
                print(f"   📷 Loaded user reference image: {user_reference_path}")
            except Exception as e:
                print(f"   ⚠️ Failed to load reference image: {e}")

        # 生成三视图（链式生成）
        views = [
            AssetType.CHARACTER_FRONT,
            AssetType.CHARACTER_SIDE,
            AssetType.CHARACTER_BACK
        ]

        front_image = None  # 用于后续视图的参考

        for i, view in enumerate(views):
            view_name = view.value
            self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.GENERATING

            if on_progress:
                on_progress(anchor_id, view_name, "GENERATING")

            print(f"   🎨 Generating {anchor_name} - {view_name} view ({i+1}/3)...")

            # 构建 prompt
            prompt = self._build_character_prompt(
                view=view,
                detailed_description=detailed_description,
                anchor_name=anchor_name,
                style_adaptation=style_adaptation,
                persistent_attributes=persistent_attributes,
                has_reference=bool(reference_images)
            )

            # 准备参考图片
            refs_for_this_view = reference_images.copy()
            if front_image and view != AssetType.CHARACTER_FRONT:
                # 对于侧面和背面，加入正面图作为参考
                refs_for_this_view.append(front_image)

            # 生成图片
            image, error = self._generate_image_sync(prompt, refs_for_this_view)

            if image and not error:
                # 保存图片
                file_name = f"{anchor_id}_{view_name}.png"
                file_path = self.assets_dir / file_name
                image.save(file_path, "PNG")

                # 保存正面图供后续参考
                if view == AssetType.CHARACTER_FRONT:
                    front_image = image

                results[view_name] = GeneratedAsset(
                    anchor_id=anchor_id,
                    asset_type=view,
                    file_path=str(file_path),
                    status=AssetStatus.SUCCESS
                )
                self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.SUCCESS
                print(f"   ✅ Saved: {file_path}")

                if on_progress:
                    on_progress(anchor_id, view_name, "SUCCESS", str(file_path))
            else:
                results[view_name] = GeneratedAsset(
                    anchor_id=anchor_id,
                    asset_type=view,
                    file_path=None,
                    status=AssetStatus.FAILED,
                    error_message=error
                )
                self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.FAILED
                print(f"   ❌ Failed: {error}")

                if on_progress:
                    on_progress(anchor_id, view_name, "FAILED", None, error)

        return results

    def generate_character_views_selective(
        self,
        anchor_id: str,
        anchor_name: str,
        detailed_description: str,
        style_adaptation: str = "",
        persistent_attributes: List[str] = None,
        visual_style: Dict[str, str] = None,
        views_to_generate: List[str] = None,
        existing_views: Dict[str, str] = None,
        user_reference_path: str = None,
        on_progress: callable = None
    ) -> Dict[str, GeneratedAsset]:
        """
        选择性生成角色视图（只生成缺失的槽位）

        Args:
            anchor_id: 锚点 ID
            anchor_name: 角色名称
            detailed_description: 详细描述
            style_adaptation: 风格适配
            persistent_attributes: 持久属性
            visual_style: Visual Style 配置 (artStyle, colorPalette, lightingMood, cameraStyle)
            views_to_generate: 需要生成的视图列表 ["front", "side", "back"]
            existing_views: 已存在的视图路径 {"front": "/path/to/front.png", ...}
            user_reference_path: 用户上传的参考图路径
            on_progress: 进度回调

        Returns:
            {view: GeneratedAsset} 生成的资产字典
        """
        if views_to_generate is None:
            views_to_generate = ["front", "side", "back"]

        if existing_views is None:
            existing_views = {}

        results = {}
        reference_images = []

        # 加载用户参考图
        if user_reference_path and os.path.exists(user_reference_path):
            try:
                user_ref = Image.open(user_reference_path)
                reference_images.append(user_ref)
                print(f"   📷 Loaded user reference image: {user_reference_path}")
            except Exception as e:
                print(f"   ⚠️ Failed to load reference image: {e}")

        # 加载已存在的视图作为参考
        existing_images = {}
        for view_name, path in existing_views.items():
            if path and os.path.exists(path):
                try:
                    existing_images[view_name] = Image.open(path)
                    print(f"   📷 Loaded existing {view_name} view as reference")
                except Exception as e:
                    print(f"   ⚠️ Failed to load existing {view_name}: {e}")

        # 视图类型映射
        view_type_map = {
            "front": AssetType.CHARACTER_FRONT,
            "side": AssetType.CHARACTER_SIDE,
            "back": AssetType.CHARACTER_BACK
        }

        # 按顺序生成（front -> side -> back），每一步把已生成的视图作为后续参考
        ordered_views = ["front", "side", "back"]
        front_image = existing_images.get("front")
        generated_views = {}  # Track all successfully generated views for chaining

        for view_name in ordered_views:
            if view_name not in views_to_generate:
                continue

            view = view_type_map[view_name]
            self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.GENERATING

            if on_progress:
                on_progress(anchor_id, view_name, "GENERATING")

            print(f"   🎨 Generating {anchor_name} - {view_name} view...")

            # 构建 prompt
            prompt = self._build_character_prompt(
                view=view,
                detailed_description=detailed_description,
                anchor_name=anchor_name,
                style_adaptation=style_adaptation,
                persistent_attributes=persistent_attributes,
                visual_style=visual_style,
                has_reference=bool(reference_images)
            )

            # 准备参考图片：user reference + front image + all previously generated views
            refs = reference_images.copy()
            if front_image and view != AssetType.CHARACTER_FRONT:
                refs.append(front_image)
            for prev_view_name, prev_image in generated_views.items():
                if prev_image not in refs:
                    refs.append(prev_image)

            print(f"   📸 Passing {len(refs)} reference images for {view_name}")

            # 生成图片
            image, error = self._generate_image_sync(prompt, refs)

            if image and not error:
                file_name = f"{anchor_id}_{view_name}.png"
                file_path = self.assets_dir / file_name
                image.save(file_path, "PNG")

                # 保存生成的视图供后续参考
                if view == AssetType.CHARACTER_FRONT:
                    front_image = image
                generated_views[view_name] = image

                results[view_name] = GeneratedAsset(
                    anchor_id=anchor_id,
                    asset_type=view,
                    file_path=str(file_path),
                    status=AssetStatus.SUCCESS
                )
                self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.SUCCESS
                print(f"   ✅ Saved: {file_path}")

                if on_progress:
                    on_progress(anchor_id, view_name, "SUCCESS", str(file_path))
            else:
                results[view_name] = GeneratedAsset(
                    anchor_id=anchor_id,
                    asset_type=view,
                    file_path=None,
                    status=AssetStatus.FAILED,
                    error_message=error
                )
                self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.FAILED
                print(f"   ❌ Failed: {error}")

                if on_progress:
                    on_progress(anchor_id, view_name, "FAILED", None, error)

        return results

    def generate_environment_views_selective(
        self,
        anchor_id: str,
        anchor_name: str,
        detailed_description: str,
        atmospheric_conditions: str = "",
        style_adaptation: str = "",
        visual_style: Dict[str, str] = None,
        views_to_generate: List[str] = None,
        existing_views: Dict[str, str] = None,
        user_reference_path: str = None,
        on_progress: callable = None
    ) -> Dict[str, GeneratedAsset]:
        """
        选择性生成场景视图（只生成缺失的槽位）

        Args:
            anchor_id: 锚点 ID
            anchor_name: 场景名称
            detailed_description: 详细描述
            atmospheric_conditions: 大气条件
            style_adaptation: 风格适配
            visual_style: Visual Style 配置 (artStyle, colorPalette, lightingMood, cameraStyle)
            views_to_generate: 需要生成的视图列表 ["wide", "detail", "alt"]
            existing_views: 已存在的视图路径
            user_reference_path: 用户上传的参考图路径
            on_progress: 进度回调

        Returns:
            {view: GeneratedAsset} 生成的资产字典
        """
        if views_to_generate is None:
            views_to_generate = ["wide", "detail", "alt"]

        if existing_views is None:
            existing_views = {}

        results = {}
        reference_images = []

        # 加载用户参考图
        if user_reference_path and os.path.exists(user_reference_path):
            try:
                user_ref = Image.open(user_reference_path)
                reference_images.append(user_ref)
                print(f"   📷 Loaded user reference image: {user_reference_path}")
            except Exception as e:
                print(f"   ⚠️ Failed to load reference image: {e}")

        # 加载已存在的视图作为参考
        existing_images = {}
        for view_name, path in existing_views.items():
            if path and os.path.exists(path):
                try:
                    existing_images[view_name] = Image.open(path)
                    print(f"   📷 Loaded existing {view_name} view as reference")
                except Exception as e:
                    print(f"   ⚠️ Failed to load existing {view_name}: {e}")

        # 视图类型映射
        view_type_map = {
            "wide": AssetType.ENVIRONMENT_WIDE,
            "detail": AssetType.ENVIRONMENT_DETAIL,
            "alt": AssetType.ENVIRONMENT_ALT
        }

        view_names_cn = {
            "wide": "Wide Shot (全景)",
            "detail": "Detail View (细节)",
            "alt": "Alt Angle (备选角度)"
        }

        # 按顺序生成（wide -> detail -> alt）
        ordered_views = ["wide", "detail", "alt"]
        wide_image = existing_images.get("wide")

        for view_name in ordered_views:
            if view_name not in views_to_generate:
                continue

            view = view_type_map[view_name]
            self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.GENERATING

            if on_progress:
                on_progress(anchor_id, view_name, "GENERATING")

            print(f"   🏞️ Generating {anchor_name} - {view_names_cn[view_name]}...")

            # 构建 prompt
            prompt = self._build_environment_view_prompt(
                view=view,
                detailed_description=detailed_description,
                anchor_name=anchor_name,
                atmospheric_conditions=atmospheric_conditions,
                style_adaptation=style_adaptation,
                visual_style=visual_style
            )

            # 准备参考图片 - use wide shot as reference to maintain location consistency
            refs = reference_images.copy()
            if wide_image and view != AssetType.ENVIRONMENT_WIDE:
                refs.append(wide_image)

            # 生成图片
            image, error = self._generate_image_sync(prompt, refs)

            if image and not error:
                file_name = f"{anchor_id}_{view_name}.png"
                file_path = self.assets_dir / file_name
                image.save(file_path, "PNG")

                # 保存全景图供后续参考
                if view == AssetType.ENVIRONMENT_WIDE:
                    wide_image = image

                results[view_name] = GeneratedAsset(
                    anchor_id=anchor_id,
                    asset_type=view,
                    file_path=str(file_path),
                    status=AssetStatus.SUCCESS
                )
                self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.SUCCESS
                print(f"   ✅ Saved: {file_path}")

                if on_progress:
                    on_progress(anchor_id, view_name, "SUCCESS", str(file_path))
            else:
                results[view_name] = GeneratedAsset(
                    anchor_id=anchor_id,
                    asset_type=view,
                    file_path=None,
                    status=AssetStatus.FAILED,
                    error_message=error
                )
                self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.FAILED
                print(f"   ❌ Failed: {error}")

                if on_progress:
                    on_progress(anchor_id, view_name, "FAILED", None, error)

        return results

    def generate_environment_assets(
        self,
        anchor_id: str,
        anchor_name: str,
        detailed_description: str,
        atmospheric_conditions: str = "",
        style_adaptation: str = "",
        user_reference_path: str = None,
        on_progress: callable = None
    ) -> Dict[str, GeneratedAsset]:
        """
        生成环境/场景三视图资产（Wide Shot / Detail View / Alt Angle）

        Args:
            anchor_id: 锚点 ID (如 env_01)
            anchor_name: 环境名称
            detailed_description: 详细描述
            atmospheric_conditions: 大气条件
            style_adaptation: 风格适配
            user_reference_path: 用户上传的参考图路径
            on_progress: 进度回调函数

        Returns:
            {view: GeneratedAsset} 三视图资产字典
        """
        results = {}
        reference_images = []

        # 加载用户参考图（如果有）
        if user_reference_path and os.path.exists(user_reference_path):
            try:
                user_ref = Image.open(user_reference_path)
                reference_images.append(user_ref)
                print(f"   📷 Loaded user reference image: {user_reference_path}")
            except Exception as e:
                print(f"   ⚠️ Failed to load reference image: {e}")

        # 生成三视图
        views = [
            AssetType.ENVIRONMENT_WIDE,
            AssetType.ENVIRONMENT_DETAIL,
            AssetType.ENVIRONMENT_ALT
        ]

        view_names_cn = {
            AssetType.ENVIRONMENT_WIDE: "Wide Shot (全景)",
            AssetType.ENVIRONMENT_DETAIL: "Detail View (细节)",
            AssetType.ENVIRONMENT_ALT: "Alt Angle (备选角度)"
        }

        wide_image = None  # 用于后续视图的参考保持一致性

        for i, view in enumerate(views):
            view_name = view.value
            self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.GENERATING

            if on_progress:
                on_progress(anchor_id, view_name, "GENERATING")

            print(f"   🏞️ Generating {anchor_name} - {view_names_cn[view]} ({i+1}/3)...")

            # 构建 prompt
            prompt = self._build_environment_view_prompt(
                view=view,
                detailed_description=detailed_description,
                anchor_name=anchor_name,
                atmospheric_conditions=atmospheric_conditions,
                style_adaptation=style_adaptation
            )

            # 准备参考图片 - use wide shot as reference to maintain location consistency
            refs_for_this_view = reference_images.copy()
            if wide_image and view != AssetType.ENVIRONMENT_WIDE:
                refs_for_this_view.append(wide_image)

            # 生成图片
            image, error = self._generate_image_sync(prompt, refs_for_this_view)

            if image and not error:
                # 保存图片
                file_name = f"{anchor_id}_{view_name}.png"
                file_path = self.assets_dir / file_name
                image.save(file_path, "PNG")

                # 保存全景图供后续参考
                if view == AssetType.ENVIRONMENT_WIDE:
                    wide_image = image

                results[view_name] = GeneratedAsset(
                    anchor_id=anchor_id,
                    asset_type=view,
                    file_path=str(file_path),
                    status=AssetStatus.SUCCESS
                )
                self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.SUCCESS
                print(f"   ✅ Saved: {file_path}")

                if on_progress:
                    on_progress(anchor_id, view_name, "SUCCESS", str(file_path))
            else:
                results[view_name] = GeneratedAsset(
                    anchor_id=anchor_id,
                    asset_type=view,
                    file_path=None,
                    status=AssetStatus.FAILED,
                    error_message=error
                )
                self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.FAILED
                print(f"   ❌ Failed: {error}")

                if on_progress:
                    on_progress(anchor_id, view_name, "FAILED", None, error)

        return results

    def generate_environment_asset(
        self,
        anchor_id: str,
        anchor_name: str,
        detailed_description: str,
        atmospheric_conditions: str = "",
        style_adaptation: str = "",
        on_progress: callable = None
    ) -> GeneratedAsset:
        """
        生成环境参考图

        Args:
            anchor_id: 锚点 ID (如 env_01)
            anchor_name: 环境名称
            detailed_description: 详细描述
            atmospheric_conditions: 大气条件
            style_adaptation: 风格适配
            on_progress: 进度回调

        Returns:
            GeneratedAsset
        """
        view_name = AssetType.ENVIRONMENT.value
        self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.GENERATING

        if on_progress:
            on_progress(anchor_id, view_name, "GENERATING")

        print(f"   🏞️ Generating environment: {anchor_name}...")

        # 构建 prompt
        prompt = self._build_environment_prompt(
            detailed_description=detailed_description,
            anchor_name=anchor_name,
            atmospheric_conditions=atmospheric_conditions,
            style_adaptation=style_adaptation
        )

        # 生成图片（环境图不需要参考图）
        image, error = self._generate_image_sync(prompt)

        if image and not error:
            file_name = f"{anchor_id}_{view_name}.png"
            file_path = self.assets_dir / file_name
            image.save(file_path, "PNG")

            result = GeneratedAsset(
                anchor_id=anchor_id,
                asset_type=AssetType.ENVIRONMENT,
                file_path=str(file_path),
                status=AssetStatus.SUCCESS
            )
            self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.SUCCESS
            print(f"   ✅ Saved: {file_path}")

            if on_progress:
                on_progress(anchor_id, view_name, "SUCCESS", str(file_path))

            return result
        else:
            result = GeneratedAsset(
                anchor_id=anchor_id,
                asset_type=AssetType.ENVIRONMENT,
                file_path=None,
                status=AssetStatus.FAILED,
                error_message=error
            )
            self.generation_status[f"{anchor_id}_{view_name}"] = AssetStatus.FAILED
            print(f"   ❌ Failed: {error}")

            if on_progress:
                on_progress(anchor_id, view_name, "FAILED", None, error)

            return result

    def get_generation_status(self) -> Dict[str, str]:
        """获取所有资产的生成状态"""
        return {k: v.value for k, v in self.generation_status.items()}

    def get_asset_paths(self) -> Dict[str, Dict[str, str]]:
        """
        获取所有已生成资产的路径

        Returns:
            {anchor_id: {view: path}}
        """
        paths = {}

        for file_path in self.assets_dir.glob("*.png"):
            # 解析文件名: char_01_front.png -> anchor_id=char_01, view=front
            parts = file_path.stem.rsplit("_", 1)
            if len(parts) == 2:
                anchor_id = parts[0]
                view = parts[1]

                if anchor_id not in paths:
                    paths[anchor_id] = {}
                paths[anchor_id][view] = str(file_path)

        return paths

    def _build_product_prompt(
        self,
        view: str,
        description: str,
        name: str
    ) -> str:
        """
        构建产品视图 prompt

        Args:
            view: 视图类型 (front/side/back)
            description: 产品描述
            name: 产品名称
        """
        view_instructions = {
            "front": "front view, product facing directly toward camera, centered composition",
            "side": "side profile view, product rotated 90 degrees, same product as reference",
            "back": "back view, product facing away from camera, showing rear details, same product as reference"
        }

        prompt = f"""Professional product photography, {view_instructions.get(view, view_instructions['front'])}.

Product: {name}
{description}

Technical requirements:
- Clean white/light gray studio background
- Professional three-point lighting with soft shadows
- Same lighting setup across all views
- High detail, sharp focus
- Product centered in frame
- No text, no watermarks, no logos
- Consistent scale and proportions across all views
- 16:9 widescreen composition
- E-commerce quality product shot
- Subtle reflection on surface for premium look
"""
        return prompt.strip()

    def generate_product_views(
        self,
        product_id: str,
        name: str,
        description: str,
        output_dir: str = None,
        on_progress: callable = None
    ) -> Dict[str, Optional[str]]:
        """
        生成产品三视图资产

        Args:
            product_id: 产品 ID (如 product_001)
            name: 产品名称
            description: 产品描述
            output_dir: 输出目录 (如果为 None，使用默认 assets 目录)
            on_progress: 进度回调

        Returns:
            {view: file_path} 三视图路径字典
        """
        if output_dir:
            save_dir = Path(output_dir)
        else:
            save_dir = self.assets_dir

        save_dir.mkdir(parents=True, exist_ok=True)

        results = {}
        views = ["front", "side", "back"]
        front_image = None

        for i, view in enumerate(views):
            self.generation_status[f"{product_id}_{view}"] = AssetStatus.GENERATING

            if on_progress:
                on_progress(product_id, view, "GENERATING")

            print(f"   📦 Generating {name} - {view} view ({i+1}/3)...")

            # Build prompt
            prompt = self._build_product_prompt(
                view=view,
                description=description,
                name=name
            )

            # Prepare reference images
            refs = []
            if front_image and view != "front":
                refs.append(front_image)

            # Generate image
            image, error = self._generate_image_sync(prompt, refs if refs else None)

            if image and not error:
                file_name = f"{view}.png"
                file_path = save_dir / file_name
                image.save(file_path, "PNG")

                # Save front image for reference
                if view == "front":
                    front_image = image

                results[view] = str(file_path)
                self.generation_status[f"{product_id}_{view}"] = AssetStatus.SUCCESS
                print(f"   ✅ Saved: {file_path}")

                if on_progress:
                    on_progress(product_id, view, "SUCCESS", str(file_path))
            else:
                results[view] = None
                self.generation_status[f"{product_id}_{view}"] = AssetStatus.FAILED
                print(f"   ❌ Failed: {error}")

                if on_progress:
                    on_progress(product_id, view, "FAILED", None, error)

        return results


def generate_product_views_with_imagen(
    description: str,
    output_dir: str,
    name: str = "Product"
) -> Dict[str, bool]:
    """
    独立函数：使用 Imagen 生成产品三视图

    Args:
        description: 产品描述
        output_dir: 输出目录
        name: 产品名称

    Returns:
        {view: success} 每个视图是否生成成功
    """
    # Create a temporary generator
    generator = AssetGenerator.__new__(AssetGenerator)
    generator.generation_status = {}

    # Initialize client
    try:
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")
        # Sanitize API key to remove non-ASCII characters (fixes encoding errors in HTTP headers)
        api_key = api_key.strip()
        api_key = ''.join(c for c in api_key if c.isascii() and c.isprintable())

        generator.client = gateway_client(task="asset_three_views", api_key=api_key)
        generator.types = types
    except Exception as e:
        print(f"❌ Failed to initialize Gemini client: {e}")
        return {"front": False, "side": False, "back": False}

    # Generate views
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = {"front": False, "side": False, "back": False}
    views = ["front", "side", "back"]
    front_image = None

    for view in views:
        print(f"   📦 Generating product - {view} view...")

        prompt = generator._build_product_prompt(
            view=view,
            description=description,
            name=name
        )

        refs = [front_image] if front_image and view != "front" else None
        image, error = generator._generate_image_sync(prompt, refs)

        if image and not error:
            file_path = output_path / f"{view}.png"
            image.save(file_path, "PNG")
            results[view] = True
            print(f"   ✅ Saved: {file_path}")

            if view == "front":
                front_image = image
        else:
            print(f"   ❌ Failed: {error}")

    return results
