# core/workflow_manager.py
import json
import time
import os
import re
import uuid
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

from core.workflow_io import load_workflow, save_workflow
from core.changes import apply_global_style, replace_entity_reference
from core.runner import run_pipeline, run_stylize, run_video_generate
from core.utils import get_ffmpeg_path, detect_aspect_ratio

# Film IR 集成
from core.film_ir_schema import create_empty_film_ir
from core.film_ir_io import save_film_ir, load_film_ir, film_ir_exists
from core.film_ir_manager import FilmIRManager

# 引入拆解所需的库和逻辑
from google import genai
from analyze_video import DIRECTOR_METAPROMPT, wait_until_file_active, extract_json_array
from extract_frames import to_seconds

class WorkflowManager:
    def __init__(self, job_id: Optional[str] = None, project_root: Optional[Path] = None):
        self.project_dir = project_root or Path(__file__).parent.parent
        self.job_id = job_id
        self.workflow: Dict[str, Any] = {}
        
        if job_id:
            self.job_dir = self.project_dir / "jobs" / job_id
            if (self.job_dir / "workflow.json").exists():
                self.load()

    def initialize_from_file(self, temp_video_path: Path) -> str:
        """全自动初始化管线：完成拆解与原始素材提取"""
        new_id = f"job_{uuid.uuid4().hex[:8]}"
        self.job_id = new_id
        self.job_dir = self.project_dir / "jobs" / new_id
        
        self.job_dir.mkdir(parents=True, exist_ok=True)
        (self.job_dir / "frames").mkdir(exist_ok=True)
        (self.job_dir / "videos").mkdir(exist_ok=True)
        (self.job_dir / "source_segments").mkdir(exist_ok=True)
        (self.job_dir / "stylized_frames").mkdir(exist_ok=True)
        
        final_video_path = self.job_dir / "input.mp4"
        shutil.move(str(temp_video_path), str(final_video_path))
        
        print(f"🚀 [Phase 1] 正在通过 Gemini 拆解视频: {new_id}...")
        storyboard = self._run_gemini_analysis(final_video_path)
        
        print(f"🚀 [Phase 2] 正在提取关键帧与原始分镜短片...")
        self._run_ffmpeg_extraction(final_video_path, storyboard)
        
        shots = []
        for s in storyboard:
            shot_num = int(s.get("shot_number", 1))
            sid = f"shot_{shot_num:02d}"

            # 📋 Semantic Split: Narrative Layer (plot) + Technical Layer (metadata tags)
            # Narrative Layer - Pure visual/plot description (no camera technical terms)
            narrative_desc = s.get("frame_description") or s.get("content_analysis") or ""

            # 🎬 Cinematography Fidelity Parameters - Hard-coded constraints from source analysis
            shot_scale = s.get("shot_scale", "")
            subject_frame_position = s.get("subject_frame_position", "")
            subject_orientation = s.get("subject_orientation", "")
            gaze_direction = s.get("gaze_direction", "")
            motion_vector = s.get("motion_vector", "")
            camera_type = s.get("camera_type") or s.get("camera_movement", "")

            # Build structured description with HARD-CODED cinematography constraints
            desc_lines = [narrative_desc]

            # 🎯 CRITICAL: These are non-negotiable constraints that MUST be preserved
            if shot_scale:
                desc_lines.append(f"[SCALE: {shot_scale}]")
            if subject_frame_position:
                desc_lines.append(f"[POSITION: {subject_frame_position}]")
            if subject_orientation:
                desc_lines.append(f"[ORIENTATION: {subject_orientation}]")
            if gaze_direction:
                desc_lines.append(f"[GAZE: {gaze_direction}]")
            if motion_vector:
                desc_lines.append(f"[MOTION: {motion_vector}]")
            if camera_type:
                desc_lines.append(f"[CAMERA: {camera_type}]")

            # Join with newlines for clear separation
            full_description = "\n".join(desc_lines)

            # 💾 Store raw cinematography data for downstream enforcement
            cinematography_data = {
                "shot_scale": shot_scale,
                "subject_frame_position": subject_frame_position,
                "subject_orientation": subject_orientation,
                "gaze_direction": gaze_direction,
                "motion_vector": motion_vector,
                "camera_type": camera_type
            }

            # 🎬 SocialSaver 扩展字段：视听层信息
            lighting = s.get("lighting", "")
            music_mood = s.get("music_mood", "")
            dialogue_voiceover = s.get("dialogue_voiceover", "")
            content_analysis = s.get("content_analysis", narrative_desc)

            shots.append({
                "shot_id": sid,
                "start_time": s.get("start_time"),
                "end_time": s.get("end_time"),
                "description": full_description,
                "content_analysis": content_analysis,  # 🎬 场景内容分析
                "lighting": lighting,  # 🎬 SocialSaver: 光线描述
                "music_mood": music_mood,  # 🎬 SocialSaver: 音乐氛围
                "dialogue_voiceover": dialogue_voiceover,  # 🎬 SocialSaver: 对白/旁白
                "cinematography": cinematography_data,  # 🎬 Hard-coded source cinematography for fidelity enforcement
                "entities": [],
                "assets": {
                    "first_frame": f"frames/{sid}.png",
                    "source_video_segment": f"source_segments/{sid}.mp4",
                    "stylized_frame": None, # 💡 PM逻辑：初始化为空，强制触发 AI 生图流程
                    "video": None
                },
                "status": {
                    "stylize": "NOT_STARTED",
                    "video_generate": "NOT_STARTED"
                }
            })
            
        self.workflow = {
            "job_id": new_id,
            "source_video": "input.mp4",
            "film_ir_path": "film_ir.json",  # 🎬 Film IR 关联
            "global": {
                "style_prompt": "Cinematic Realistic",
                "video_model": "seedance",
                "aspect_ratio": detect_aspect_ratio(self.job_dir / "input.mp4"),
            },
            "global_stages": {
                "analyze": "SUCCESS", "extract": "SUCCESS",
                "stylize": "NOT_STARTED", "video_gen": "NOT_STARTED", "merge": "NOT_STARTED"
            },
            "shots": shots,
            "meta": {"attempts": 0, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        }

        self.save()

        # 🎬 初始化 Film IR (电影逻辑中间层)
        self._initialize_film_ir(new_id, storyboard)

        print(f"✅ [Done] 视频拆解与切片完成，Job ID: {new_id}")
        return new_id

    def _complete_initialization(self, video_path: Path) -> None:
        """
        完成初始化的后半部分（用于异步模式）
        假设 job_id 和 job_dir 已经设置好，视频已经在 job_dir/input.mp4
        """
        print(f"🚀 [Phase 1] 正在通过 Gemini 拆解视频: {self.job_id}...")
        storyboard = self._run_gemini_analysis(video_path)

        print(f"🚀 [Phase 2] 正在提取关键帧与原始分镜短片...")
        self._run_ffmpeg_extraction(video_path, storyboard)

        shots = []
        for s in storyboard:
            shot_num = int(s.get("shot_number", 1))
            sid = f"shot_{shot_num:02d}"

            narrative_desc = s.get("frame_description") or s.get("content_analysis") or ""

            shot_scale = s.get("shot_scale", "")
            subject_frame_position = s.get("subject_frame_position", "")
            subject_orientation = s.get("subject_orientation", "")
            gaze_direction = s.get("gaze_direction", "")
            motion_vector = s.get("motion_vector", "")
            camera_type = s.get("camera_type") or s.get("camera_movement", "")

            desc_lines = [narrative_desc]
            if shot_scale:
                desc_lines.append(f"[SCALE: {shot_scale}]")
            if subject_frame_position:
                desc_lines.append(f"[POSITION: {subject_frame_position}]")
            if subject_orientation:
                desc_lines.append(f"[ORIENTATION: {subject_orientation}]")
            if gaze_direction:
                desc_lines.append(f"[GAZE: {gaze_direction}]")
            if motion_vector:
                desc_lines.append(f"[MOTION: {motion_vector}]")
            if camera_type:
                desc_lines.append(f"[CAMERA: {camera_type}]")

            full_description = "\n".join(desc_lines)

            cinematography_data = {
                "shot_scale": shot_scale,
                "subject_frame_position": subject_frame_position,
                "subject_orientation": subject_orientation,
                "gaze_direction": gaze_direction,
                "motion_vector": motion_vector,
                "camera_type": camera_type
            }

            lighting = s.get("lighting", "")
            music_mood = s.get("music_mood", "")
            dialogue_voiceover = s.get("dialogue_voiceover", "")
            content_analysis = s.get("content_analysis", narrative_desc)

            shots.append({
                "shot_id": sid,
                "start_time": s.get("start_time"),
                "end_time": s.get("end_time"),
                "description": full_description,
                "content_analysis": content_analysis,
                "lighting": lighting,
                "music_mood": music_mood,
                "dialogue_voiceover": dialogue_voiceover,
                "cinematography": cinematography_data,
                "entities": [],
                "assets": {
                    "first_frame": f"frames/{sid}.png",
                    "source_video_segment": f"source_segments/{sid}.mp4",
                    "stylized_frame": None,
                    "video": None
                },
                "status": {
                    "stylize": "NOT_STARTED",
                    "video_generate": "NOT_STARTED"
                }
            })

        self.workflow = {
            "job_id": self.job_id,
            "source_video": "input.mp4",
            "film_ir_path": "film_ir.json",
            "global": {
                "style_prompt": "Cinematic Realistic",
                "video_model": "seedance",
                "aspect_ratio": detect_aspect_ratio(self.job_dir / "input.mp4"),
            },
            "global_stages": {
                "analyze": "SUCCESS", "extract": "SUCCESS",
                "stylize": "NOT_STARTED", "video_gen": "NOT_STARTED", "merge": "NOT_STARTED"
            },
            "shots": shots,
            "meta": {"attempts": 0, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        }

        self.save()

        # 初始化 Film IR
        self._initialize_film_ir(self.job_id, storyboard)

        print(f"✅ [Done] 视频拆解与切片完成，Job ID: {self.job_id}")

    def _initialize_film_ir(self, job_id: str, storyboard: List[Dict]) -> None:
        """
        初始化 Film IR 结构
        将原始分析数据填充到支柱 III (Shot Recipe) 的 concrete 层
        """
        ir = create_empty_film_ir(job_id, "input.mp4")

        # 构建 Shot Recipe concrete 数据
        shots_data = []
        for s in storyboard:
            shot_num = int(s.get("shot_number", 1))
            sid = f"shot_{shot_num:02d}"

            # 提取分镜数据
            narrative_desc = s.get("frame_description") or s.get("content_analysis") or ""

            shot_item = {
                "shotId": sid,
                "beatTag": self._infer_beat_tag(shot_num, len(storyboard)),
                "startTime": s.get("start_time", "0:00"),
                "endTime": s.get("end_time", "0:00"),
                "durationSeconds": to_seconds(s.get("end_time", "0")) - to_seconds(s.get("start_time", "0")),

                # 8 核心字段
                "subject": narrative_desc,
                "scene": s.get("content_analysis", ""),
                "camera": {
                    "shotSize": s.get("shot_scale", ""),
                    "cameraAngle": s.get("subject_orientation", ""),
                    "cameraMovement": s.get("camera_movement") or s.get("camera_type", ""),
                    "focalLengthDepth": s.get("camera_type", "")
                },
                "lighting": s.get("lighting", "Natural lighting"),
                "dynamics": s.get("motion_vector", ""),
                "audio": {
                    "soundDesign": "",
                    "music": s.get("music_mood", ""),
                    "dialogue": s.get("dialogue_voiceover", "")
                },
                "style": "",
                "negative": "",

                # 资产路径
                "assets": {
                    "firstFrame": f"frames/{sid}.png",
                    "sourceSegment": f"source_segments/{sid}.mp4",
                    "stylizedFrame": None,
                    "video": None
                }
            }
            shots_data.append(shot_item)

        # 填充支柱 III concrete
        ir["pillars"]["III_shotRecipe"]["concrete"] = {
            "globalVisualLanguage": {
                "visualStyle": "",
                "colorPalette": "",
                "lightingDesign": "",
                "cameraPhilosophy": ""
            },
            "globalSoundDesign": {
                "musicStyle": "",
                "soundAtmosphere": "",
                "rhythmPattern": ""
            },
            "symbolism": {
                "repeatingImagery": "",
                "symbolicMeaning": ""
            },
            "shots": shots_data
        }

        # 保存 Film IR
        save_film_ir(self.job_dir, ir)
        print(f"🎬 [Film IR] Initialized with {len(shots_data)} shots")

        # 🎬 触发 Stage 1: Specific Analysis (Story Theme)
        try:
            ir_manager = FilmIRManager(job_id, self.project_dir)
            result = ir_manager.run_stage("specificAnalysis")
            if result.get("status") == "success":
                print(f"✅ [Film IR] Story Theme analysis completed")
                # 🎯 关键：Film IR 分析完成后，根据 representativeTimestamp 重新提取帧
                video_path = self.job_dir / "input.mp4"
                self._reextract_frames_from_film_ir(video_path)
                # Note: Watermark cleaning now runs asynchronously after upload completes (see app.py)
            else:
                print(f"⚠️ [Film IR] Story Theme analysis: {result.get('reason', 'unknown error')}")
        except Exception as e:
            print(f"⚠️ [Film IR] Story Theme analysis failed: {e}")
            # 不阻塞主流程，继续执行

    def _reextract_frames_from_film_ir(self, video_path: Path):
        """
        🎯 根据 Film IR 的 representativeTimestamp 重新提取帧
        这是在 Film IR 分析完成后调用的，用于修正初始帧提取的时间偏差

        物理对位法：
        1. 短镜头规则（duration < 2s）：强制使用 endTime - 0.2
        2. 偏差保护：safe_ts = max(rep_ts, startTime + 1.2)
        3. 边界保护：min(safe_ts, endTime - 0.1)
        """
        try:
            ir = load_film_ir(self.job_dir)
            if not ir:
                print(f"⚠️ [Frame Re-extract] Film IR not found, skipping")
                return

            # 获取 concrete shots
            shots = ir.get("pillars", {}).get("III_shotRecipe", {}).get("concrete", {}).get("shots", [])
            if not shots:
                print(f"⚠️ [Frame Re-extract] No shots in Film IR, skipping")
                return

            ffmpeg_path = get_ffmpeg_path()
            frames_dir = self.job_dir / "frames"
            reextracted_count = 0

            for shot in shots:
                shot_id = shot.get("shotId", "shot_01")
                rep_ts = shot.get("representativeTimestamp")
                start_time = shot.get("startTime", "00:00:00.000")
                end_time = shot.get("endTime", "00:00:00.000")

                # 转换时间格式
                start_sec = to_seconds(start_time) or 0
                end_sec = to_seconds(end_time) or start_sec + 1
                duration = end_sec - start_sec

                extract_ts = None

                # 🎯 规则 1：短镜头强制规则（duration < 2s）
                # 对于快切视频，直接使用 endTime - 0.2，这是确保场景转换完成的唯一方法
                if duration < 2.0:
                    extract_ts = end_sec - 0.2
                    print(f"⚡ [Re-extract] {shot_id}: 短镜头规则 {extract_ts:.2f}s (endTime - 0.2, duration={duration:.2f}s)")

                # 🎯 规则 2：正常镜头 - AI 锚点 + 偏差保护
                elif rep_ts is not None:
                    # 偏差保护：确保至少在 startTime + 1.2s 之后
                    safe_ts = max(rep_ts, start_sec + 1.2)
                    # 边界保护：确保不超出镜头范围
                    extract_ts = min(safe_ts, end_sec - 0.1)
                    if safe_ts != rep_ts:
                        print(f"🛡️ [Re-extract] {shot_id}: 偏差保护 {extract_ts:.2f}s (AI给{rep_ts:.2f}s, 修正到startTime+1.2)")
                    else:
                        print(f"🎯 [Re-extract] {shot_id}: AI 语义锚点 {extract_ts:.2f}s")

                # 🎯 规则 3：保底逻辑
                if extract_ts is None:
                    extract_ts = start_sec + (duration * 0.8)
                    print(f"📐 [Re-extract] {shot_id}: 数学保底 {extract_ts:.2f}s (80% 位置)")

                # 重新提取帧
                frame_path = frames_dir / f"{shot_id}.png"
                subprocess.run([
                    ffmpeg_path, "-y",
                    "-i", str(video_path),
                    "-ss", str(extract_ts),
                    "-frames:v", "1",
                    "-q:v", "2",
                    str(frame_path)
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                reextracted_count += 1

            print(f"✅ [Frame Re-extract] 已根据物理对位法重新提取 {reextracted_count} 帧")

        except Exception as e:
            print(f"⚠️ [Frame Re-extract] Failed: {e}")

    def _infer_beat_tag(self, shot_num: int, total_shots: int) -> str:
        """推断分镜的节拍标签"""
        ratio = shot_num / total_shots
        if ratio <= 0.15:
            return "HOOK"
        elif ratio <= 0.4:
            return "SETUP"
        elif ratio <= 0.75:
            return "TURN"
        else:
            return "CTA"

    def _run_gemini_analysis(self, video_path: Path):
        from google.genai import types
        from .utils import gemini_keys
        api_key = gemini_keys.get()
        client = genai.Client(api_key=api_key)
        uploaded = client.files.upload(file=str(video_path))
        video_file = wait_until_file_active(client, uploaded)
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[DIRECTOR_METAPROMPT, video_file],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        raw_shots = extract_json_array(response.text)

        # 语义化合并：减少过度分镜
        merged_shots = self._merge_semantic_shots(raw_shots, client)
        return merged_shots

    def _merge_semantic_shots(self, shots: List[Dict], client) -> List[Dict]:
        """
        语义化合并：将连续的、背景/角度/主体相似的分镜合并为一个完整分镜。
        使用 AI 判断哪些连续分镜应该合并。
        """
        if len(shots) <= 1:
            return shots

        # 构建合并判断提示
        shots_summary = []
        for i, s in enumerate(shots):
            shots_summary.append({
                "index": i,
                "start_time": s.get("start_time"),
                "end_time": s.get("end_time"),
                "description": s.get("frame_description") or s.get("content_analysis"),
                "shot_type": s.get("shot_type"),
                "camera_angle": s.get("camera_angle"),
                "camera_movement": s.get("camera_movement")
            })

        merge_prompt = f"""你是一位专业的影视剪辑师。请分析以下分镜列表，判断哪些**连续的**分镜应该合并。

合并条件（必须同时满足）：
1. 分镜是**连续的**（index 相邻）
2. 场景/背景没有显著变化
3. 主体/角色没有切换
4. 机位角度没有明显变化
5. 属于同一个完整动作或事件

分镜列表：
{json.dumps(shots_summary, ensure_ascii=False, indent=2)}

请输出需要合并的分镜组，格式为纯JSON数组，每个元素是一个需要合并的index数组。
例如：[[0,1,2], [5,6]] 表示将0-1-2合并为一个分镜，5-6合并为一个分镜。
如果没有需要合并的，输出空数组 []。
仅输出纯JSON，不要任何解释。"""

        try:
            merge_response = client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=[merge_prompt],
            )
            merge_text = merge_response.text.strip()

            # 提取JSON数组
            if merge_text.startswith("["):
                merge_groups = json.loads(merge_text)
            else:
                l = merge_text.find("[")
                r = merge_text.rfind("]")
                if l != -1 and r != -1:
                    merge_groups = json.loads(merge_text[l:r+1])
                else:
                    merge_groups = []

            if not merge_groups:
                print(f"📊 语义分析：无需合并，保留 {len(shots)} 个分镜")
                return shots

            # 🛡️ 防止过度合并：检查合并后是否会少于2个镜头
            total_merged = sum(len(g) - 1 for g in merge_groups if isinstance(g, list) and len(g) > 1)
            result_count = len(shots) - total_merged
            if result_count < 2:
                print(f"⚠️ 合并后只剩 {result_count} 个分镜，取消合并以保留原始分镜结构")
                return shots

            # 🛡️ 防止单组过度合并：如果单个合并组超过3个镜头，拆分或跳过
            safe_merge_groups = []
            for group in merge_groups:
                if isinstance(group, list) and len(group) > 1:
                    if len(group) > 3:
                        print(f"⚠️ 合并组 {group} 过大（{len(group)}个镜头），跳过此合并")
                        continue
                    safe_merge_groups.append(group)
            merge_groups = safe_merge_groups

            if not merge_groups:
                print(f"📊 所有合并组被过滤，保留原始 {len(shots)} 个分镜")
                return shots

            # 执行合并
            merged_indices = set()
            for group in merge_groups:
                if isinstance(group, list) and len(group) > 1:
                    merged_indices.update(group[1:])  # 除了第一个，其余标记为被合并

            result = []
            i = 0
            new_shot_num = 1
            while i < len(shots):
                shot = shots[i].copy()

                # 检查是否是合并组的起始
                merge_group = None
                for group in merge_groups:
                    if isinstance(group, list) and len(group) > 1 and group[0] == i:
                        merge_group = group
                        break

                if merge_group:
                    # 合并该组的所有分镜
                    last_idx = merge_group[-1]
                    shot["end_time"] = shots[last_idx].get("end_time")

                    # 合并描述
                    descriptions = []
                    for idx in merge_group:
                        if idx < len(shots):
                            desc = shots[idx].get("frame_description") or shots[idx].get("content_analysis")
                            if desc and desc not in descriptions:
                                descriptions.append(desc)
                    shot["frame_description"] = " → ".join(descriptions[:3])  # 最多保留3段描述
                    shot["content_analysis"] = shot["frame_description"]

                    print(f"🔗 合并分镜 {[s+1 for s in merge_group]} -> shot_{new_shot_num:02d}")
                    i = last_idx + 1
                else:
                    if i not in merged_indices:
                        i += 1
                    else:
                        i += 1
                        continue

                shot["shot_number"] = new_shot_num
                result.append(shot)
                new_shot_num += 1

            print(f"📊 语义合并完成：{len(shots)} 个分镜 -> {len(result)} 个分镜")
            return result

        except Exception as e:
            print(f"⚠️ 语义合并分析失败 ({e})，保留原始分镜")
            return shots

    def _run_ffmpeg_extraction(self, video_path: Path, storyboard: List):
        """
        毫秒级精准提取：
        - 关键帧提取：优先使用 AI 语义锚点 (representativeTimestamp)，保底使用数学逻辑
        - 视频片段：使用精准切割模式
        """
        ffmpeg_path = get_ffmpeg_path()
        for s in storyboard:
            ts = to_seconds(s.get("start_time")) or 0
            end_ts = to_seconds(s.get("end_time")) or (ts + 3)  # 默认 3 秒
            duration = end_ts - ts if end_ts > ts else 3  # 防止负数或零
            sid = f"shot_{int(s['shot_number']):02d}"

            # 🎯 关键帧提取：AI 语义锚点 + 数学保底
            # 优先级：representativeTimestamp > startTime + duration * 0.8
            extract_ts = None
            extraction_method = "fallback"

            # 首选：AI 提供的代表帧时间戳
            rep_ts = s.get("representativeTimestamp") or s.get("representative_timestamp")
            if rep_ts is not None:
                rep_ts = to_seconds(rep_ts)
                # 校验：时间戳必须在 [startTime + 0.1, endTime - 0.1] 范围内
                min_valid = ts + 0.1
                max_valid = end_ts - 0.1
                if rep_ts is not None and min_valid <= rep_ts <= max_valid:
                    extract_ts = rep_ts
                    extraction_method = "ai_anchor"
                    print(f"🎯 {sid}: 使用 AI 语义锚点 {extract_ts:.2f}s")

            # 保底：数学修正 (startTime + duration * 0.8)
            if extract_ts is None:
                extract_ts = ts + (duration * 0.8)
                print(f"📐 {sid}: 使用数学保底 {extract_ts:.2f}s (80% 位置)")

            img_out = self.job_dir / "frames" / f"{sid}.png"
            subprocess.run([
                ffmpeg_path, "-y",
                "-i", str(video_path),
                "-ss", str(extract_ts),
                "-frames:v", "1",
                "-q:v", "2",
                str(img_out)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 🎯 精准视频片段切割
            video_segment_out = self.job_dir / "source_segments" / f"{sid}.mp4"
            subprocess.run([
                ffmpeg_path, "-y",
                "-i", str(video_path),
                "-ss", str(ts),           # 视频片段从起始点开始
                "-t", str(duration),
                "-c:v", "libx264",        # 重新编码以确保精准切割
                "-c:a", "aac",
                "-avoid_negative_ts", "make_zero",
                str(video_segment_out)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def load(self):
        """加载状态并对齐物理文件状态"""
        self.workflow = load_workflow(self.job_dir)
        if "global_stages" not in self.workflow:
            self.workflow["global_stages"] = {"analyze": "SUCCESS", "extract": "SUCCESS", "stylize": "NOT_STARTED", "video_gen": "NOT_STARTED", "merge": "NOT_STARTED"}

        updated = False
        shots = self.workflow.get("shots", [])
        for shot in shots:
            sid = shot.get("shot_id")
            status_node = shot.get("status", {})
            
            # 1. 风格化参考图物理对齐
            stylized_path = self.job_dir / "stylized_frames" / f"{sid}.png"
            if stylized_path.exists() and status_node.get("stylize") != "SUCCESS":
                status_node["stylize"] = "SUCCESS"
                shot["assets"]["stylized_frame"] = f"stylized_frames/{sid}.png"
                updated = True

            # 2. 视频产物物理对齐
            video_output_path = self.job_dir / "videos" / f"{sid}.mp4"
            current_video_status = status_node.get("video_generate")
            if video_output_path.exists() and current_video_status != "SUCCESS":
                status_node["video_generate"] = "SUCCESS"
                shot.setdefault("assets", {})["video"] = f"videos/{sid}.mp4"
                updated = True
            elif not video_output_path.exists() and current_video_status == "SUCCESS":
                status_node["video_generate"] = "NOT_STARTED"
                shot.setdefault("assets", {})["video"] = None
                updated = True
        
        # 💡 核心新增：计算合并就绪状态统计
        failed_count = sum(1 for s in shots if s["status"].get("video_generate") == "FAILED")
        pending_count = sum(1 for s in shots if s["status"].get("video_generate") in ["NOT_STARTED", "RUNNING"])
        
        self.workflow["merge_info"] = {
            "can_merge": failed_count == 0 and pending_count == 0 and len(shots) > 0,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "message": ""
        }
        
        if failed_count > 0:
            self.workflow["merge_info"]["message"] = f"⚠️ {failed_count} shots failed and cannot be assembled."
        elif pending_count > 0:
            self.workflow["merge_info"]["message"] = "⏳ Waiting for the shot list to be generated..."
        elif len(shots) > 0:
            self.workflow["merge_info"]["message"] = "✅ All shots are ready and can be assembled into the final film."
        
        if updated: self.save()
        return self.workflow

    def save(self):
        self.workflow.setdefault("meta", {})["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_workflow(self.job_dir, self.workflow)

    def apply_agent_action(self, action: Union[Dict, List]) -> Dict[str, Any]:
        """处理修改意图：强制重置后续所有依赖节点"""
        actions = action if isinstance(action, list) else [action]
        total_affected = 0
        for act in actions:
            op = act.get("op")
            
            if op == "set_global_style":
                affected = apply_global_style(self.workflow, act.get("value"), cascade=True)
                if affected > 0:
                    for s in self.workflow.get("shots", []):
                        v_path = self.job_dir / "videos" / f"{s['shot_id']}.mp4"
                        if v_path.exists(): os.remove(v_path)
                        i_path = self.job_dir / "stylized_frames" / f"{s['shot_id']}.png"
                        if i_path.exists(): os.remove(i_path)
                        s["status"]["stylize"] = "NOT_STARTED"
                        s["status"]["video_generate"] = "NOT_STARTED"
                        s["assets"]["video"] = None
                        s["assets"]["stylized_frame"] = None
                total_affected += affected
                
            elif op == "global_subject_swap":
                old_subject = act.get("old_subject", "").lower()
                new_subject = act.get("new_subject", "").lower()
                if old_subject and new_subject:
                    for s in self.workflow.get("shots", []):
                        # 🏞️ Intelligent Scene Detection: Skip scenery/landscape shots
                        if self._is_scenery_shot(s["description"]):
                            print(f"🏞️ Scenery shot skipped (no character injection): {s['shot_id']}")
                            continue

                        if old_subject in s["description"].lower():
                            desc = s["description"]

                            # 🧹 STEP 1: STRICT ATTRIBUTE PURGING for gender conflicts
                            # For simple swaps, purge gender-conflicting attributes
                            purged_desc = self._purge_conflicting_attributes(desc, old_subject, {})
                            print(f"🧹 Purged conflicting attributes from {s['shot_id']}")

                            # 🔍 STEP 2: Separate narrative layer from technical tags
                            tag_pattern = r'\[([A-Z]+): ([^\]]+)\]'
                            tags = re.findall(tag_pattern, purged_desc)
                            narrative_part = re.sub(tag_pattern, '', purged_desc).strip()

                            # 🔄 STEP 3: Replace SUBJECT_PLACEHOLDER with new subject
                            if 'SUBJECT_PLACEHOLDER' in narrative_part:
                                # Replace ONLY the first placeholder with the subject
                                new_narrative = narrative_part.replace('SUBJECT_PLACEHOLDER', new_subject, 1)
                                # Replace remaining placeholders with "the [subject]"
                                new_narrative = new_narrative.replace('SUBJECT_PLACEHOLDER', f'the {new_subject}')
                            else:
                                # Fallback: direct replacement
                                new_narrative = re.sub(
                                    rf'\b{re.escape(old_subject)}\b',
                                    new_subject,
                                    narrative_part,
                                    flags=re.IGNORECASE
                                )

                            # 🧹 STEP 4: Semantic Sanitization for pronouns
                            new_narrative = self._semantic_sanitize_gender(new_narrative, old_subject, new_subject)

                            # 🧹 STEP 5: Clean up duplicates and grammar
                            new_narrative = re.sub(r',\s*,', ',', new_narrative)
                            new_narrative = re.sub(r'\s{2,}', ' ', new_narrative)
                            new_narrative = new_narrative.strip()
                            if new_narrative:
                                new_narrative = new_narrative[0].upper() + new_narrative[1:]

                            # Reconstruct description: narrative + preserved tags
                            tag_lines = [f"[{tag}: {value}]" for tag, value in tags]
                            s["description"] = new_narrative + ("\n" + "\n".join(tag_lines) if tag_lines else "")

                            s["status"]["stylize"] = "NOT_STARTED"
                            s["status"]["video_generate"] = "NOT_STARTED"
                            v_path = self.job_dir / "videos" / f"{s['shot_id']}.mp4"
                            if v_path.exists(): os.remove(v_path)
                            i_path = self.job_dir / "stylized_frames" / f"{s['shot_id']}.png"
                            if i_path.exists(): os.remove(i_path)
                            s["assets"]["video"] = None
                            s["assets"]["stylized_frame"] = None
                            total_affected += 1
                            print(f"🧹 Clean swap applied: {s['shot_id']}")

            elif op == "detailed_subject_swap":
                # 🎨 Fine-Grained Attribute Propagation: Detailed character replacement with visual attributes
                # 🆔 Global Identity Anchor: Store and propagate consistent character identity
                old_subject = act.get("old_subject", "").lower()
                new_subject = act.get("new_subject", "").lower()
                attributes = act.get("attributes", {})

                if old_subject and new_subject:
                    # Build the detailed character description from attributes
                    attr_parts = []

                    # Order attributes for natural reading: age, body, hair, eyes, skin, clothing, accessories, other
                    if attributes.get("age_descriptor"):
                        attr_parts.append(attributes["age_descriptor"])
                    if attributes.get("body_type"):
                        attr_parts.append(attributes["body_type"])

                    # Hair description (combine style and color)
                    hair_parts = []
                    if attributes.get("hair_color"):
                        hair_parts.append(attributes["hair_color"])
                    if attributes.get("hair_style"):
                        hair_parts.append(attributes["hair_style"])
                    if hair_parts:
                        attr_parts.append(" ".join(hair_parts) + " hair")

                    if attributes.get("eye_color"):
                        attr_parts.append(f"{attributes['eye_color']} eyes")
                    if attributes.get("skin_tone"):
                        attr_parts.append(f"{attributes['skin_tone']} skin")
                    if attributes.get("facial_features"):
                        attr_parts.append(f"with {attributes['facial_features']}")
                    if attributes.get("clothing"):
                        attr_parts.append(f"wearing {attributes['clothing']}")
                    if attributes.get("accessories"):
                        attr_parts.append(f"with {attributes['accessories']}")
                    if attributes.get("other_visual"):
                        attr_parts.append(attributes["other_visual"])

                    # Construct full character description
                    if attr_parts:
                        # Format: "a [attributes] [subject]" e.g., "a young golden short hair woman wearing red attire"
                        full_character_desc = f"a {' '.join(attr_parts)} {new_subject}"
                    else:
                        full_character_desc = new_subject

                    # 🆔 Store Global Identity Anchor in workflow for consistency tracking
                    self.workflow.setdefault("global", {})["identity_anchor"] = {
                        "base_subject": new_subject,
                        "full_description": full_character_desc,
                        "attributes": attributes,
                        "replaced_from": old_subject
                    }
                    print(f"🆔 Global Identity Anchor set: '{full_character_desc}'")

                    shots_modified = 0
                    shots_skipped = 0

                    for s in self.workflow.get("shots", []):
                        # 🏞️ Intelligent Scene Detection: Skip scenery/landscape shots
                        if self._is_scenery_shot(s["description"]):
                            print(f"🏞️ Scenery shot preserved (identity not injected): {s['shot_id']}")
                            shots_skipped += 1
                            continue

                        if old_subject in s["description"].lower():
                            desc = s["description"]

                            # 🧹 STEP 1: STRICT ATTRIBUTE PURGING
                            # Completely remove ALL conflicting descriptors before applying new Visual DNA
                            purged_desc = self._purge_conflicting_attributes(desc, old_subject, attributes)
                            print(f"🧹 Purged conflicting attributes from {s['shot_id']}")

                            # 🔍 STEP 2: Separate narrative layer from technical tags (tags preserved by purge)
                            tag_pattern = r'\[([A-Z]+): ([^\]]+)\]'
                            tags = re.findall(tag_pattern, purged_desc)
                            narrative_part = re.sub(tag_pattern, '', purged_desc).strip()

                            # 🆔 STEP 3: Replace SUBJECT_PLACEHOLDER with new identity
                            # The purge method leaves SUBJECT_PLACEHOLDER where the old subject was
                            if 'SUBJECT_PLACEHOLDER' in narrative_part:
                                # Replace ONLY the first placeholder with full description
                                new_narrative = narrative_part.replace('SUBJECT_PLACEHOLDER', full_character_desc, 1)
                                # Replace remaining placeholders with simple pronoun or "the [subject]"
                                new_narrative = new_narrative.replace('SUBJECT_PLACEHOLDER', f'the {new_subject}')
                            else:
                                # Fallback: append identity if placeholder not found
                                new_narrative = f"{full_character_desc}, {narrative_part}" if narrative_part else full_character_desc

                            # 🧹 STEP 4: Semantic Sanitization for pronouns
                            new_narrative = self._semantic_sanitize_gender(new_narrative, old_subject, new_subject)

                            # 🧹 STEP 5: Clean up duplicates and grammar
                            # Remove duplicate "a [subject]" patterns that may have been created
                            new_narrative = re.sub(rf'\b(a\s+{re.escape(new_subject)})\s*,\s*a\s+{re.escape(new_subject)}\b', r'\1', new_narrative, flags=re.IGNORECASE)
                            # Remove duplicate consecutive words
                            new_narrative = re.sub(r'\b(\w+)\s+\1\b', r'\1', new_narrative, flags=re.IGNORECASE)
                            # Clean up multiple commas/spaces
                            new_narrative = re.sub(r',\s*,', ',', new_narrative)
                            new_narrative = re.sub(r'\s{2,}', ' ', new_narrative)
                            # Capitalize first letter of sentence
                            new_narrative = new_narrative.strip()
                            if new_narrative:
                                new_narrative = new_narrative[0].upper() + new_narrative[1:]

                            # Reconstruct description: narrative + preserved tags
                            tag_lines = [f"[{tag}: {value}]" for tag, value in tags]
                            s["description"] = new_narrative + ("\n" + "\n".join(tag_lines) if tag_lines else "")

                            # Reset generation status
                            s["status"]["stylize"] = "NOT_STARTED"
                            s["status"]["video_generate"] = "NOT_STARTED"
                            v_path = self.job_dir / "videos" / f"{s['shot_id']}.mp4"
                            if v_path.exists(): os.remove(v_path)
                            i_path = self.job_dir / "stylized_frames" / f"{s['shot_id']}.png"
                            if i_path.exists(): os.remove(i_path)
                            s["assets"]["video"] = None
                            s["assets"]["stylized_frame"] = None
                            shots_modified += 1
                            print(f"🆔 Clean identity applied: {s['shot_id']}")

                    total_affected += shots_modified
                    print(f"🎨 Identity Anchoring complete: {shots_modified} protagonist shots updated, {shots_skipped} scenery shots preserved")
                            
            elif op == "update_shot_params":
                sid = act.get("shot_id")
                for s in self.workflow.get("shots", []):
                    if s["shot_id"] == sid:
                        if "description" in act: s["description"] = act["description"]
                        s["status"]["stylize"] = "NOT_STARTED"
                        s["status"]["video_generate"] = "NOT_STARTED"
                        v_path = self.job_dir / "videos" / f"{sid}.mp4"
                        if v_path.exists(): os.remove(v_path)
                        i_path = self.job_dir / "stylized_frames" / f"{sid}.png"
                        if i_path.exists(): os.remove(i_path)
                        s["assets"]["video"] = None
                        s["assets"]["stylized_frame"] = None
                        total_affected += 1
                        break

            elif op == "enhance_shot_description":
                # 📐 空间感知 + 🎬 风格强化：增强分镜描述
                sid = act.get("shot_id")
                spatial_info = act.get("spatial_info", "")
                style_boost = act.get("style_boost", "")
                for s in self.workflow.get("shots", []):
                    if s["shot_id"] == sid:
                        original_desc = s.get("description", "")
                        enhanced_parts = [original_desc]
                        if spatial_info:
                            enhanced_parts.append(f"[Spatial: {spatial_info}]")
                        if style_boost:
                            enhanced_parts.append(f"[Style: {style_boost}]")
                        s["description"] = " ".join(enhanced_parts)
                        s["status"]["stylize"] = "NOT_STARTED"
                        s["status"]["video_generate"] = "NOT_STARTED"
                        v_path = self.job_dir / "videos" / f"{sid}.mp4"
                        if v_path.exists(): os.remove(v_path)
                        i_path = self.job_dir / "stylized_frames" / f"{sid}.png"
                        if i_path.exists(): os.remove(i_path)
                        s["assets"]["video"] = None
                        s["assets"]["stylized_frame"] = None
                        total_affected += 1
                        print(f"📐 增强分镜描述: {sid} -> {s['description'][:80]}...")
                        break

            elif op == "update_cinematography":
                # 🎬 摄影参数修改（仅当用户明确要求时）
                sid = act.get("shot_id")
                param = act.get("param", "")
                new_value = act.get("value", "")
                valid_params = ["shot_scale", "subject_frame_position", "subject_orientation", "gaze_direction", "motion_vector"]
                if param in valid_params and new_value:
                    for s in self.workflow.get("shots", []):
                        if s["shot_id"] == sid:
                            # Update the cinematography dict
                            s.setdefault("cinematography", {})[param] = new_value

                            # Update the description tags to match
                            tag_map = {
                                "shot_scale": "SCALE",
                                "subject_frame_position": "POSITION",
                                "subject_orientation": "ORIENTATION",
                                "gaze_direction": "GAZE",
                                "motion_vector": "MOTION"
                            }
                            tag_name = tag_map.get(param, param.upper())
                            desc = s.get("description", "")

                            # Replace existing tag or append new one
                            tag_pattern = rf'\[{tag_name}: [^\]]+\]'
                            new_tag = f"[{tag_name}: {new_value}]"
                            if re.search(tag_pattern, desc):
                                desc = re.sub(tag_pattern, new_tag, desc)
                            else:
                                desc = desc + f"\n{new_tag}"
                            s["description"] = desc

                            # Reset generation status
                            s["status"]["stylize"] = "NOT_STARTED"
                            s["status"]["video_generate"] = "NOT_STARTED"
                            v_path = self.job_dir / "videos" / f"{sid}.mp4"
                            if v_path.exists(): os.remove(v_path)
                            i_path = self.job_dir / "stylized_frames" / f"{sid}.png"
                            if i_path.exists(): os.remove(i_path)
                            s["assets"]["video"] = None
                            s["assets"]["stylized_frame"] = None
                            total_affected += 1
                            print(f"🎬 摄影参数更新: {sid} [{param}] -> {new_value}")
                            break

        if total_affected > 0: self.save()
        return {"status": "success", "affected_shots": total_affected}

    def run_node(self, node_type: str, shot_id: Optional[str] = None):
        """逻辑编排引擎。确保‘先有图，后有视频’且无死锁"""
        self.workflow.setdefault("meta", {}).setdefault("attempts", 0)
        self.workflow["meta"]["attempts"] += 1
        
        target_shots = [s for s in self.workflow.get("shots", []) if not shot_id or s["shot_id"] == shot_id]

        if node_type == "video_generate":
            for s in target_shots:
                # 确保 status 字段存在
                if "status" not in s:
                    s["status"] = {"stylize": "NOT_STARTED", "video_generate": "NOT_STARTED"}
                if s["status"].get("stylize") != "SUCCESS":
                    print(f"🔗 [Dependency] 分镜 {s['shot_id']} 缺少定妆图，正在前置生成...")
                    run_stylize(self.job_dir, self.workflow, target_shot=s["shot_id"])
                    i_file = self.job_dir / "stylized_frames" / f"{s['shot_id']}.png"
                    if i_file.exists(): 
                        s["status"]["stylize"] = "SUCCESS"
                        s["assets"]["stylized_frame"] = f"stylized_frames/{s['shot_id']}.png"

        stage_key = "video_gen" if node_type == "video_generate" else "stylize"
        # 确保 global_stages 存在
        if "global_stages" not in self.workflow:
            self.workflow["global_stages"] = {
                "analyze": "SUCCESS",
                "extract": "SUCCESS",
                "stylize": "NOT_STARTED",
                "video_gen": "NOT_STARTED",
                "merge": "NOT_STARTED"
            }
        self.workflow["global_stages"][stage_key] = "RUNNING"

        for s in target_shots:
            if node_type == "video_generate":
                v_file = self.job_dir / "videos" / f"{s['shot_id']}.mp4"
                if v_file.exists(): os.remove(v_file)
                s["status"]["video_generate"] = "NOT_STARTED" 
                s["assets"]["video"] = None
            elif node_type == "stylize":
                i_file = self.job_dir / "stylized_frames" / f"{s['shot_id']}.png"
                if i_file.exists(): os.remove(i_file)
                s["status"]["stylize"] = "NOT_STARTED" 
                s["assets"]["stylized_frame"] = None

        self.save()

        if node_type == "stylize": 
            run_stylize(self.job_dir, self.workflow, target_shot=shot_id)
        elif node_type == "video_generate": 
            run_video_generate(self.job_dir, self.workflow, target_shot=shot_id)
        
        self.load() 

    def _is_scenery_shot(self, description: str) -> bool:
        """
        🏞️ Intelligent Scene Detection: Determine if a shot is a scenery/landscape shot with no human protagonist.
        Returns True if the shot should be SKIPPED during character replacement.
        """
        desc_lower = description.lower()

        # Human subject indicators - if ANY of these are present, it's NOT a scenery shot
        human_indicators = [
            # Generic human terms
            'man', 'woman', 'person', 'people', 'human', 'figure', 'silhouette',
            'boy', 'girl', 'child', 'kid', 'baby', 'infant', 'toddler',
            'teenager', 'adult', 'elder', 'elderly', 'senior',
            # Relationship terms
            'father', 'mother', 'dad', 'mom', 'parent', 'son', 'daughter',
            'brother', 'sister', 'husband', 'wife', 'couple',
            'friend', 'stranger', 'visitor', 'guest',
            # Professional/role terms
            'worker', 'employee', 'boss', 'doctor', 'nurse', 'teacher', 'student',
            'driver', 'passenger', 'pedestrian', 'commuter',
            'actor', 'actress', 'performer', 'singer', 'dancer',
            'protagonist', 'character', 'hero', 'heroine',
            # Body parts (indicating human presence)
            'face', 'hand', 'hands', 'arm', 'arms', 'leg', 'legs',
            'head', 'body', 'shoulder', 'back', 'chest',
            'eye', 'eyes', 'hair', 'lips', 'mouth', 'nose',
            # Actions that imply human
            'walking', 'running', 'sitting', 'standing', 'talking', 'speaking',
            'looking', 'watching', 'holding', 'carrying', 'wearing',
            # Pronouns
            'he ', 'she ', 'his ', 'her ', 'him ', 'they ', 'their ',
        ]

        # Check for human presence
        has_human = any(indicator in desc_lower for indicator in human_indicators)

        if has_human:
            return False  # Not a scenery shot - has human protagonist

        # Scenery/landscape indicators - if these dominate without humans, it's scenery
        scenery_indicators = [
            # Nature scenes
            'landscape', 'scenery', 'vista', 'panorama', 'horizon',
            'mountain', 'valley', 'forest', 'woods', 'jungle', 'desert',
            'ocean', 'sea', 'lake', 'river', 'waterfall', 'beach', 'coast',
            'sky', 'clouds', 'sunset', 'sunrise', 'dawn', 'dusk', 'night sky',
            'field', 'meadow', 'prairie', 'grassland', 'garden', 'park',
            # Urban scenes without people
            'cityscape', 'skyline', 'building', 'architecture', 'street view',
            'empty room', 'interior', 'exterior', 'establishing shot',
            'aerial view', 'drone shot', 'bird\'s eye',
            # Object focus
            'close-up of object', 'food', 'vehicle', 'car ', 'train ', 'plane ',
            'furniture', 'decoration', 'artifact',
            # Transition/ambient
            'transition', 'time lapse', 'ambient', 'atmosphere', 'mood shot',
        ]

        # Check for scenery dominance
        has_scenery = any(indicator in desc_lower for indicator in scenery_indicators)

        return has_scenery  # Is scenery if indicators present and no humans

    def _semantic_sanitize_gender(self, description: str, old_subject: str, new_subject: str) -> str:
        """
        🧹 Semantic Sanitization: Clean gender-conflicting attributes when swapping subjects.
        - Strips incompatible physical attributes (beard, mustache, Adam's apple, etc.)
        - Remaps gendered pronouns (he/him/his → she/her/hers and vice versa)
        """
        # Define gender categories - expanded to catch variations
        male_keywords = {'man', 'men', 'boy', 'boys', 'male', 'males', 'gentleman', 'gentlemen',
                        'guy', 'guys', 'father', 'dad', 'husband', 'brother', 'son', 'uncle',
                        'grandfather', 'protagonist', 'protagonists', 'hero', 'heroes', 'actor'}
        female_keywords = {'woman', 'women', 'girl', 'girls', 'female', 'females', 'lady', 'ladies',
                         'mother', 'mom', 'wife', 'sister', 'daughter', 'aunt', 'grandmother',
                         'heroine', 'heroines', 'actress'}

        # Check if any male/female keyword appears in the subject string
        old_lower = old_subject.lower()
        new_lower = new_subject.lower()

        old_is_male = any(kw in old_lower for kw in male_keywords)
        old_is_female = any(kw in old_lower for kw in female_keywords)
        new_is_male = any(kw in new_lower for kw in male_keywords)
        new_is_female = any(kw in new_lower for kw in female_keywords)

        # Only sanitize if there's a gender change
        if (old_is_male and new_is_female) or (old_is_female and new_is_male):
            if old_is_male and new_is_female:
                # Male → Female: Remove male-specific attributes
                male_attributes = [
                    # Mustache - ALL variations (most comprehensive)
                    r'\bwith\s+(?:a\s+)?(?:\w+\s+)*mustache\b',  # "with a thick mustache", "with a handlebar mustache"
                    r'\bwith\s+(?:a\s+)?(?:\w+\s+)*moustache\b', # British spelling
                    r'\bhas\s+(?:a\s+)?(?:\w+\s+)*mustache\b',   # "has a mustache"
                    r'\bhas\s+(?:a\s+)?(?:\w+\s+)*moustache\b',
                    r'\bhaving\s+(?:a\s+)?(?:\w+\s+)*mustache\b', # "having a mustache"
                    r'\bsporting\s+(?:a\s+)?(?:\w+\s+)*mustache\b', # "sporting a mustache"
                    r'\b(?:his|the|a)\s+(?:\w+\s+)*mustache\b',  # "his thick mustache", "the mustache"
                    r'\b(?:his|the|a)\s+(?:\w+\s+)*moustache\b',
                    r'\b\w+\s+mustache\b',  # "thick mustache", "handlebar mustache"
                    r'\b\w+\s+moustache\b',
                    r'\bmustached\b', r'\bmoustached\b',
                    r'\bmustache\b', r'\bmoustache\b',  # standalone as last resort
                    # Beard - ALL variations
                    r'\bwith\s+(?:a\s+)?(?:\w+\s+)*beard\b',
                    r'\bhas\s+(?:a\s+)?(?:\w+\s+)*beard\b',
                    r'\b(?:his|the|a)\s+(?:\w+\s+)*beard\b',
                    r'\b\w+\s+beard\b',  # "thick beard", "full beard"
                    r'\bbearded\b', r'\bbeard\b',
                    # Goatee
                    r'\bwith\s+(?:a\s+)?(?:\w+\s+)*goatee\b',
                    r'\b(?:his|the|a)\s+(?:\w+\s+)*goatee\b',
                    r'\bgoatee\b',
                    # Stubble
                    r'\bwith\s+(?:\w+\s+)*stubble\b',
                    r'\b\w+\s+stubble\b',  # "five o'clock stubble"
                    r'\bstubbled\b', r'\bstubble\b',
                    # Facial hair general
                    r'\bfacial\s+hair\b', r'\bwith\s+facial\s+hair\b',
                    # Other male-specific
                    r'\bAdam\'s\s+apple\b',
                    r'\bbald\b', r'\bbalding\b',
                    r'\bmuscular\b', r'\bbuff\b',
                    r'\bbroad[- ]shouldered\b',
                    r'\bchest\s+hair\b', r'\bwith\s+chest\s+hair\b',
                ]
                for attr in male_attributes:
                    description = re.sub(attr, '', description, flags=re.IGNORECASE)

                # Remap pronouns: he/him/his → she/her/hers
                description = re.sub(r'\bhe\b', 'she', description, flags=re.IGNORECASE)
                description = re.sub(r'\bhim\b', 'her', description, flags=re.IGNORECASE)
                description = re.sub(r'\bhis\b', 'her', description, flags=re.IGNORECASE)
                description = re.sub(r'\bhimself\b', 'herself', description, flags=re.IGNORECASE)

            elif old_is_female and new_is_male:
                # Female → Male: Remove female-specific attributes
                female_attributes = [
                    r'\b(lipstick)\b', r'\b(makeup|make-up)\b', r'\b(long eyelashes)\b',
                    r'\b(feminine)\b', r'\b(pregnant)\b', r'\b(nursing)\b',
                    r'\b(wearing a dress)\b', r'\b(in a skirt)\b'
                ]
                for attr in female_attributes:
                    description = re.sub(attr, '', description, flags=re.IGNORECASE)

                # Remap pronouns: she/her/hers → he/him/his
                description = re.sub(r'\bshe\b', 'he', description, flags=re.IGNORECASE)
                description = re.sub(r'\bher\b(?!\s+\w+ing)', 'him', description, flags=re.IGNORECASE)  # Avoid "her walking"
                description = re.sub(r'\bhers\b', 'his', description, flags=re.IGNORECASE)
                description = re.sub(r'\bherself\b', 'himself', description, flags=re.IGNORECASE)

            # Clean up any double spaces left from attribute removal
            description = re.sub(r'\s{2,}', ' ', description).strip()

        return description

    def _purge_conflicting_attributes(self, description: str, old_subject: str, new_attributes: Dict) -> str:
        """
        🧹 Strict Attribute Purging: Completely remove ALL conflicting descriptors before applying new Visual DNA.
        This ensures a CLEAN transformation with zero residues from the original subject.

        Purge Categories:
        1. Old subject name and variants
        2. Hair descriptions (color, style, length)
        3. Clothing descriptions
        4. Physical features and accessories
        5. Age descriptors
        6. Body type descriptors
        """
        # 🔍 Separate technical tags from narrative (preserve tags)
        tag_pattern = r'\[([A-Z]+): ([^\]]+)\]'
        tags = re.findall(tag_pattern, description)
        narrative = re.sub(tag_pattern, '', description).strip()

        # ============================================
        # 1️⃣ PURGE OLD SUBJECT NAME AND VARIANTS
        # ============================================
        old_lower = old_subject.lower()
        subject_variants = {
            'man': ['man', 'men', 'male', 'gentleman', 'guy', 'fellow', 'dude'],
            'woman': ['woman', 'women', 'female', 'lady', 'girl'],
            'boy': ['boy', 'boys', 'lad', 'young man', 'male child'],
            'girl': ['girl', 'girls', 'lass', 'young woman', 'female child'],
            'child': ['child', 'children', 'kid', 'kids', 'youngster'],
            'person': ['person', 'people', 'individual', 'figure'],
        }

        # Find which category the old subject belongs to
        variants_to_remove = [old_subject]
        for category, variants in subject_variants.items():
            if old_lower in variants or old_lower == category:
                variants_to_remove.extend(variants)
                break

        # Remove old subject and its variants (but keep the position for replacement)
        for variant in set(variants_to_remove):
            # Use word boundary to avoid partial matches
            narrative = re.sub(rf'\ba\s+{re.escape(variant)}\b', 'SUBJECT_PLACEHOLDER', narrative, flags=re.IGNORECASE)
            narrative = re.sub(rf'\bthe\s+{re.escape(variant)}\b', 'SUBJECT_PLACEHOLDER', narrative, flags=re.IGNORECASE)
            narrative = re.sub(rf'\b{re.escape(variant)}\b', 'SUBJECT_PLACEHOLDER', narrative, flags=re.IGNORECASE)

        # ============================================
        # 2️⃣ PURGE ALL HAIR DESCRIPTIONS
        # ============================================
        hair_colors = [
            'black', 'brown', 'blonde', 'blond', 'golden', 'silver', 'gray', 'grey',
            'white', 'red', 'auburn', 'ginger', 'brunette', 'chestnut', 'platinum',
            'dark', 'light', 'dirty blonde', 'strawberry blonde', 'jet black',
            'salt and pepper', 'highlighted', 'dyed', 'colored'
        ]
        hair_styles = [
            'short', 'long', 'medium', 'curly', 'straight', 'wavy', 'frizzy',
            'bald', 'balding', 'shaved', 'buzz cut', 'crew cut', 'mohawk',
            'ponytail', 'bun', 'braided', 'braids', 'dreadlocks', 'dreads',
            'afro', 'pixie', 'bob', 'shoulder-length', 'flowing', 'slicked back',
            'messy', 'neat', 'tousled', 'spiky', 'receding', 'thinning',
            'thick', 'fine', 'wispy', 'layered'
        ]

        # Remove hair color + "hair" combinations
        for color in hair_colors:
            narrative = re.sub(rf'\b{color}\s+hair(ed)?\b', '', narrative, flags=re.IGNORECASE)
            narrative = re.sub(rf'\b{color}-hair(ed)?\b', '', narrative, flags=re.IGNORECASE)

        # Remove hair style + "hair" combinations
        for style in hair_styles:
            narrative = re.sub(rf'\b{style}\s+hair(ed)?\b', '', narrative, flags=re.IGNORECASE)
            narrative = re.sub(rf'\b{style}-hair(ed)?\b', '', narrative, flags=re.IGNORECASE)

        # Remove complex hair descriptions
        narrative = re.sub(r'\bwith\s+[\w\s]+\s+hair\b', '', narrative, flags=re.IGNORECASE)
        narrative = re.sub(r'\b[\w\s]+\s+haired\b', '', narrative, flags=re.IGNORECASE)

        # ============================================
        # 3️⃣ PURGE ALL CLOTHING DESCRIPTIONS
        # ============================================
        clothing_patterns = [
            r'\bwearing\s+[\w\s,]+(?:shirt|dress|suit|jacket|coat|pants|jeans|skirt|blouse|sweater|hoodie|t-shirt|tee|top|shorts|trousers|uniform|outfit|attire|clothes|clothing|garment)\b',
            r'\bin\s+(?:a\s+)?[\w\s]+(?:shirt|dress|suit|jacket|coat|pants|jeans|skirt|blouse|sweater|hoodie|t-shirt|tee|top|shorts|trousers|uniform|outfit|attire)\b',
            r'\bdressed\s+in\s+[\w\s,]+\b',
            r'\bclad\s+in\s+[\w\s,]+\b',
            # Specific clothing items with colors
            r'\b(?:red|blue|black|white|green|yellow|pink|purple|orange|brown|gray|grey)\s+(?:shirt|dress|suit|jacket|coat|pants|jeans|skirt|blouse|sweater|hoodie|t-shirt|top)\b',
        ]
        for pattern in clothing_patterns:
            narrative = re.sub(pattern, '', narrative, flags=re.IGNORECASE)

        # ============================================
        # 4️⃣ PURGE PHYSICAL FEATURES & ACCESSORIES
        # ============================================
        # Facial features - comprehensive patterns for mustache/beard/goatee
        facial_features = [
            # Mustache - ALL variations
            r'\bwith\s+(?:a\s+)?(?:\w+\s+)*mustache\b',
            r'\bwith\s+(?:a\s+)?(?:\w+\s+)*moustache\b',
            r'\bhas\s+(?:a\s+)?(?:\w+\s+)*mustache\b',
            r'\bhas\s+(?:a\s+)?(?:\w+\s+)*moustache\b',
            r'\bhaving\s+(?:a\s+)?(?:\w+\s+)*mustache\b',
            r'\bsporting\s+(?:a\s+)?(?:\w+\s+)*mustache\b',
            r'\b(?:his|the|a)\s+(?:\w+\s+)*mustache\b',
            r'\b(?:his|the|a)\s+(?:\w+\s+)*moustache\b',
            r'\b\w+\s+mustache\b',
            r'\b\w+\s+moustache\b',
            r'\bmustached\b', r'\bmoustached\b',
            r'\bmustache\b', r'\bmoustache\b',
            # Beard - ALL variations
            r'\bwith\s+(?:a\s+)?(?:\w+\s+)*beard\b',
            r'\bhas\s+(?:a\s+)?(?:\w+\s+)*beard\b',
            r'\b(?:his|the|a)\s+(?:\w+\s+)*beard\b',
            r'\b\w+\s+beard\b',
            r'\bbearded\b', r'\bbeard\b',
            # Goatee
            r'\bwith\s+(?:a\s+)?(?:\w+\s+)*goatee\b',
            r'\b(?:his|the|a)\s+(?:\w+\s+)*goatee\b',
            r'\bgoatee\b',
            r'\bwith\s+stubble\b', r'\bstubbled\b',
            r'\bwith\s+freckles\b', r'\bfreckled\b',
            r'\bwith\s+(?:a\s+)?scar\b', r'\bscarred\b',
            r'\bwith\s+dimples\b',
            r'\bwith\s+wrinkles\b', r'\bwrinkled\b',
            r'\bwith\s+(?:a\s+)?tattoo\b', r'\btattooed\b',
        ]
        for pattern in facial_features:
            narrative = re.sub(pattern, '', narrative, flags=re.IGNORECASE)

        # Eye descriptions
        eye_colors = ['blue', 'green', 'brown', 'hazel', 'gray', 'grey', 'black', 'amber', 'violet']
        for color in eye_colors:
            narrative = re.sub(rf'\b{color}\s+eyes?\b', '', narrative, flags=re.IGNORECASE)
            narrative = re.sub(rf'\b{color}-eyed\b', '', narrative, flags=re.IGNORECASE)
        narrative = re.sub(r'\bwith\s+[\w\s]+\s+eyes\b', '', narrative, flags=re.IGNORECASE)

        # Accessories
        accessories = [
            r'\bwearing\s+(?:a\s+)?(?:glasses|sunglasses|spectacles)\b',
            r'\bwith\s+(?:a\s+)?(?:glasses|sunglasses|spectacles)\b',
            r'\bwearing\s+(?:a\s+)?(?:hat|cap|beanie|helmet)\b',
            r'\bwith\s+(?:a\s+)?(?:hat|cap|beanie|helmet)\b',
            r'\bwearing\s+(?:a\s+)?(?:necklace|earrings|bracelet|watch|ring)\b',
            r'\bwith\s+(?:a\s+)?(?:necklace|earrings|bracelet|watch|ring)\b',
            r'\bwearing\s+(?:a\s+)?(?:scarf|tie|bowtie|bow tie)\b',
            r'\bwith\s+(?:a\s+)?(?:scarf|tie|bowtie|bow tie)\b',
        ]
        for pattern in accessories:
            narrative = re.sub(pattern, '', narrative, flags=re.IGNORECASE)

        # ============================================
        # 5️⃣ PURGE AGE DESCRIPTORS
        # ============================================
        age_patterns = [
            r'\byoung\b', r'\bold\b', r'\belderly\b', r'\bmiddle-aged\b', r'\bmiddle aged\b',
            r'\bteenage\b', r'\bteen\b', r'\badult\b', r'\bsenior\b', r'\bjuvenile\b',
            r'\bin (?:his|her|their) (?:20s|30s|40s|50s|60s|70s|80s|90s|twenties|thirties|forties|fifties|sixties|seventies|eighties|nineties)\b',
        ]
        for pattern in age_patterns:
            narrative = re.sub(pattern, '', narrative, flags=re.IGNORECASE)

        # ============================================
        # 6️⃣ PURGE BODY TYPE DESCRIPTORS
        # ============================================
        body_patterns = [
            r'\b(?:tall|short|slim|slender|thin|skinny|fat|heavy|overweight|muscular|athletic|petite|stocky|lanky|burly|chubby|plump)\b',
            r'\bwell-built\b', r'\bwell built\b',
            r'\bbroad[- ]shouldered\b',
        ]
        for pattern in body_patterns:
            narrative = re.sub(pattern, '', narrative, flags=re.IGNORECASE)

        # ============================================
        # 7️⃣ PURGE SKIN TONE DESCRIPTORS
        # ============================================
        skin_patterns = [
            r'\bfair[- ]skinned\b', r'\bfair skin\b',
            r'\bdark[- ]skinned\b', r'\bdark skin\b',
            r'\bpale[- ]skinned\b', r'\bpale skin\b',
            r'\btan[- ]skinned\b', r'\btanned skin\b', r'\btanned\b',
            r'\bolive[- ]skinned\b', r'\bolive skin\b',
        ]
        for pattern in skin_patterns:
            narrative = re.sub(pattern, '', narrative, flags=re.IGNORECASE)

        # ============================================
        # CLEANUP
        # ============================================
        # Remove orphaned articles and prepositions
        narrative = re.sub(r'\ba\s+,', ',', narrative)
        narrative = re.sub(r'\bthe\s+,', ',', narrative)
        narrative = re.sub(r'\bwith\s+,', ',', narrative)
        narrative = re.sub(r'\bwearing\s+,', ',', narrative)
        narrative = re.sub(r'\bin\s+,', ',', narrative)

        # Remove multiple spaces and clean up
        narrative = re.sub(r'\s{2,}', ' ', narrative)
        narrative = re.sub(r'\s+,', ',', narrative)
        narrative = re.sub(r',\s*,', ',', narrative)
        narrative = re.sub(r'^\s*,\s*', '', narrative)
        narrative = re.sub(r'\s*,\s*$', '', narrative)
        narrative = narrative.strip()

        # Reconstruct with preserved tags
        if tags:
            tag_lines = [f"[{tag}: {value}]" for tag, value in tags]
            return narrative + "\n" + "\n".join(tag_lines)
        return narrative

    def _get_shot_by_id(self, shot_id: str) -> Optional[Dict]:
        for s in self.workflow.get("shots", []):
            if s.get("shot_id") == shot_id: return s
        return None

    def merge_videos(self) -> str:
        """执行无损合并（包含所有生成成功的镜头，含 ENDCARD/BRAND_SPLASH 静态视频）"""
        ffmpeg_path = get_ffmpeg_path()
        success_shots = [
            s for s in self.workflow.get("shots", [])
            if s["status"].get("video_generate") == "SUCCESS"
        ]
        if not success_shots: raise RuntimeError("没有可合并的分镜视频。")
        success_shots.sort(key=lambda x: x["shot_id"])
        concat_list_path = self.job_dir / "concat_list.txt"
        output_video_path = self.job_dir / "final_output.mp4"
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for s in success_shots:
                v_rel_path = s["assets"].get("video")
                if v_rel_path:
                    abs_v_path = (self.job_dir / v_rel_path).absolute()
                    f.write(f"file '{abs_v_path}'\n")
        cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_path), "-c", "copy", str(output_video_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0: raise RuntimeError(f"合并失败: {result.stderr}")
        if "global_stages" in self.workflow:
            self.workflow["global_stages"]["merge"] = "SUCCESS"
        self.save()
        return "final_output.mp4"

    # ============================================================
    # Film IR 集成
    # ============================================================

    def get_film_ir_manager(self) -> FilmIRManager:
        """
        获取 Film IR 管理器实例

        Returns:
            FilmIRManager 实例
        """
        if not self.job_id:
            raise RuntimeError("Job ID not set")
        return FilmIRManager(self.job_id, self.project_dir)

    def has_film_ir(self) -> bool:
        """检查是否存在 Film IR"""
        if not self.job_id:
            return False
        return film_ir_exists(self.job_dir)