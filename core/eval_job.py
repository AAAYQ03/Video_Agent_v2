# core/eval_job.py
"""
Job Quality Evaluator
=====================
一个脚本跑完全部评估指标，输出 eval_report.json。

使用方式：
    python -m core.eval_job --job_id job_283ce290
    python -m core.eval_job --job_dir jobs/job_283ce290

五层评估：
    1. 基础质量（SSIM、黑帧、静帧、时长）— 零成本
    2. Prompt 遵从度（CLIP text-image）— 本地模型
    3. 跨镜头一致性（CLIP image-image + Face Embedding + 色调）— 本地模型
    4. 视频运动质量（帧间差异分析）— 零成本
    5. LLM-as-Judge（可选，调 Gemini API）— 有成本
"""

import json
import os
import sys
import time
import argparse
import traceback
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
from PIL import Image


# ============================================================
# 数据类
# ============================================================

@dataclass
class ShotScore:
    """单镜头评分"""
    shot_id: str
    ssim_first_frame: Optional[float] = None       # 首帧保持度
    clip_prompt_score: Optional[float] = None       # prompt 遵从度
    clip_style_score: Optional[float] = None        # 与全局风格的 CLIP 相似度
    face_similarity: Optional[float] = None         # 角色人脸一致性（vs 参考）
    has_black_frames: bool = False
    has_static_frames: bool = False
    motion_score: Optional[float] = None            # 运动幅度
    duration_match: bool = True                     # 时长是否匹配预期
    llm_anatomy: Optional[int] = None               # LLM 评分 1-5
    llm_style: Optional[int] = None
    llm_overall: Optional[int] = None
    issues: List[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """完整评估报告"""
    job_id: str
    evaluated_at: str
    shots: List[ShotScore] = field(default_factory=list)

    # 聚合指标
    avg_ssim: Optional[float] = None
    avg_clip_prompt: Optional[float] = None
    style_consistency: Optional[float] = None       # CLIP embedding 方差（越小越一致）
    face_consistency: Optional[float] = None         # 人脸 embedding 平均相似度
    color_consistency: Optional[float] = None        # LAB 色调方差
    black_frame_count: int = 0
    static_frame_count: int = 0
    avg_motion: Optional[float] = None
    total_issues: int = 0

    def to_dict(self):
        d = asdict(self)
        return d


# ============================================================
# Layer 1: 基础质量（零成本）
# ============================================================

def _load_image(path: Path) -> Optional[np.ndarray]:
    """加载图片为 numpy array"""
    if not path.exists():
        return None
    try:
        return np.array(Image.open(path).convert("RGB"))
    except Exception:
        return None


def _extract_video_frames(video_path: Path, count: int = 5) -> List[np.ndarray]:
    """从视频中均匀提取 N 帧"""
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return []
        indices = np.linspace(0, total - 1, count, dtype=int)
        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        cap.release()
        return frames
    except ImportError:
        # 没有 cv2，用 ffmpeg 提取
        return _extract_frames_ffmpeg(video_path, count)


def _extract_frames_ffmpeg(video_path: Path, count: int) -> List[np.ndarray]:
    """用 ffmpeg 提取帧（cv2 不可用时的 fallback）"""
    import tempfile
    frames = []
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vf", f"select='not(mod(n\\,{max(1, 30//count)}))'",
            "-vsync", "vfn",
            "-frames:v", str(count),
            f"{tmpdir}/frame_%03d.png",
            "-y", "-loglevel", "error"
        ]
        subprocess.run(cmd, capture_output=True)
        for f in sorted(Path(tmpdir).glob("frame_*.png")):
            img = _load_image(f)
            if img is not None:
                frames.append(img)
    return frames


def compute_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """计算两张图的 SSIM"""
    from skimage.metrics import structural_similarity
    # 确保尺寸一致
    h = min(img1.shape[0], img2.shape[0])
    w = min(img1.shape[1], img2.shape[1])
    img1 = Image.fromarray(img1).resize((w, h))
    img2 = Image.fromarray(img2).resize((w, h))
    return structural_similarity(
        np.array(img1), np.array(img2),
        channel_axis=2, data_range=255
    )


def check_black_frames(frames: List[np.ndarray], threshold: float = 10.0) -> int:
    """检测黑帧数量"""
    return sum(1 for f in frames if np.mean(f) < threshold)


def check_static_frames(frames: List[np.ndarray], threshold: float = 2.0) -> int:
    """检测静帧（相邻帧几乎相同）"""
    count = 0
    for i in range(len(frames) - 1):
        diff = np.mean(np.abs(frames[i].astype(float) - frames[i + 1].astype(float)))
        if diff < threshold:
            count += 1
    return count


def compute_motion_score(frames: List[np.ndarray]) -> float:
    """计算平均帧间运动量（像素级差异均值）"""
    if len(frames) < 2:
        return 0.0
    diffs = []
    for i in range(len(frames) - 1):
        diff = np.mean(np.abs(frames[i].astype(float) - frames[i + 1].astype(float)))
        diffs.append(diff)
    return float(np.mean(diffs))


def eval_layer1_basic(job_dir: Path, shots: List[dict]) -> Dict[str, ShotScore]:
    """Layer 1: 基础质量检查"""
    print("  [Layer 1] 基础质量检查...")
    results = {}

    for shot in shots:
        sid = shot.get("shot_id", "")
        score = ShotScore(shot_id=sid)

        # 首帧保持度（分镜帧 vs 视频第一帧）
        storyboard_frame = _load_image(job_dir / "stylized_frames" / f"{sid}.png")
        video_path = job_dir / "videos" / f"{sid}.mp4"

        if video_path.exists():
            video_frames = _extract_video_frames(video_path, count=5)
            if video_frames and storyboard_frame is not None:
                score.ssim_first_frame = round(compute_ssim(storyboard_frame, video_frames[0]), 3)
                if score.ssim_first_frame < 0.5:
                    score.issues.append(f"首帧保持度低: SSIM={score.ssim_first_frame}")

            if video_frames:
                # 黑帧
                black = check_black_frames(video_frames)
                score.has_black_frames = black > 0
                if black > 0:
                    score.issues.append(f"检测到 {black} 个黑帧")

                # 静帧
                static = check_static_frames(video_frames)
                score.has_static_frames = static >= len(video_frames) - 1
                if score.has_static_frames:
                    motion = shot.get("cinematography", {}).get("motion_vector", "")
                    if motion and motion != "static":
                        score.issues.append("应有运动但视频静止")

                # 运动量
                score.motion_score = round(compute_motion_score(video_frames), 2)

        results[sid] = score

    return results


# ============================================================
# Layer 2: Prompt 遵从度（本地 CLIP）
# ============================================================

_clip_model = None
_clip_preprocess = None
_clip_tokenizer = None


def _get_clip():
    """懒加载 CLIP 模型"""
    global _clip_model, _clip_preprocess, _clip_tokenizer
    if _clip_model is None:
        import open_clip
        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        tokenizer = open_clip.get_tokenizer("ViT-B-32")
        model.eval()
        _clip_model = model
        _clip_preprocess = preprocess
        _clip_tokenizer = tokenizer
    return _clip_model, _clip_preprocess, _clip_tokenizer


def clip_text_image_score(image: np.ndarray, text: str) -> float:
    """计算图片和文本的 CLIP 相似度"""
    import torch
    model, preprocess, tokenizer = _get_clip()

    img_tensor = preprocess(Image.fromarray(image)).unsqueeze(0)
    text_tensor = tokenizer([text[:77]])  # CLIP 最大 77 token

    with torch.no_grad():
        img_feat = model.encode_image(img_tensor)
        txt_feat = model.encode_text(text_tensor)
        img_feat /= img_feat.norm(dim=-1, keepdim=True)
        txt_feat /= txt_feat.norm(dim=-1, keepdim=True)
        score = (img_feat @ txt_feat.T).item()

    return float(score)


def clip_image_embeddings(images: List[np.ndarray]) -> np.ndarray:
    """批量计算图片的 CLIP embedding"""
    import torch
    model, preprocess, _ = _get_clip()

    tensors = torch.stack([preprocess(Image.fromarray(img)) for img in images])
    with torch.no_grad():
        features = model.encode_image(tensors)
        features /= features.norm(dim=-1, keepdim=True)
    return features.numpy()


def eval_layer2_prompt(job_dir: Path, shots: List[dict], film_ir: dict,
                       results: Dict[str, ShotScore]) -> Dict[str, ShotScore]:
    """Layer 2: Prompt 遵从度"""
    print("  [Layer 2] Prompt 遵从度 (CLIP)...")

    # 获取每个镜头的 T2I prompt
    remixed = film_ir.get("userIntent", {}).get("remixedLayer", {})
    remixed_shots = {s.get("shotId"): s for s in remixed.get("shots", [])}

    for shot in shots:
        sid = shot.get("shot_id", "")
        if sid not in results:
            continue

        frame = _load_image(job_dir / "stylized_frames" / f"{sid}.png")
        if frame is None:
            continue

        # 获取 prompt
        r_shot = remixed_shots.get(sid, {})
        prompt = (r_shot.get("T2I_FirstFrame", "") or
                  r_shot.get("visualDescription", "") or
                  shot.get("description", ""))

        if prompt:
            score = clip_text_image_score(frame, prompt)
            results[sid].clip_prompt_score = round(score, 3)
            if score < 0.2:
                results[sid].issues.append(f"Prompt 遵从度低: CLIP={score:.3f}")

    return results


# ============================================================
# Layer 3: 跨镜头一致性（CLIP + Face + 色调）
# ============================================================

def eval_layer3_consistency(job_dir: Path, shots: List[dict],
                            results: Dict[str, ShotScore]) -> Tuple[Dict[str, ShotScore], dict]:
    """Layer 3: 跨镜头一致性"""
    print("  [Layer 3] 跨镜头一致性...")
    consistency = {}

    # 收集所有分镜帧
    frames = []
    frame_sids = []
    for shot in shots:
        sid = shot.get("shot_id", "")
        img = _load_image(job_dir / "stylized_frames" / f"{sid}.png")
        if img is not None:
            frames.append(img)
            frame_sids.append(sid)

    if len(frames) < 2:
        return results, consistency

    # --- CLIP 风格一致性 ---
    embeddings = clip_image_embeddings(frames)
    # 计算两两余弦相似度
    sim_matrix = embeddings @ embeddings.T
    # 取上三角（排除自身）
    n = len(frames)
    sims = [sim_matrix[i][j] for i in range(n) for j in range(i + 1, n)]
    style_mean = float(np.mean(sims))
    style_std = float(np.std(sims))
    consistency["clip_style_mean"] = round(style_mean, 3)
    consistency["clip_style_std"] = round(style_std, 3)

    # 每帧相对于全局均值的偏离
    mean_embedding = np.mean(embeddings, axis=0, keepdims=True)
    mean_embedding /= np.linalg.norm(mean_embedding)
    for i, sid in enumerate(frame_sids):
        cos_sim = float(np.dot(embeddings[i], mean_embedding.flatten()))
        results[sid].clip_style_score = round(cos_sim, 3)
        if cos_sim < style_mean - 2 * style_std:
            results[sid].issues.append(f"风格偏离: CLIP={cos_sim:.3f}, 均值={style_mean:.3f}")

    # --- 色调一致性 (LAB 色彩空间) ---
    lab_means = []
    for img in frames:
        from skimage.color import rgb2lab
        lab = rgb2lab(img)
        lab_means.append([float(lab[:, :, 0].mean()), float(lab[:, :, 1].mean()), float(lab[:, :, 2].mean())])
    lab_means = np.array(lab_means)
    color_std = float(np.mean(np.std(lab_means, axis=0)))
    consistency["color_std"] = round(color_std, 2)

    # --- 人脸一致性 (insightface) ---
    try:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(320, 320))

        face_embeddings = {}
        for i, (img, sid) in enumerate(zip(frames, frame_sids)):
            import cv2
            bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            faces = app.get(bgr)
            if faces:
                face_embeddings[sid] = faces[0].embedding

        if len(face_embeddings) >= 2:
            sids = list(face_embeddings.keys())
            embeds = [face_embeddings[s] for s in sids]
            face_sims = []
            for i in range(len(embeds)):
                for j in range(i + 1, len(embeds)):
                    cos = np.dot(embeds[i], embeds[j]) / (
                        np.linalg.norm(embeds[i]) * np.linalg.norm(embeds[j]))
                    face_sims.append(float(cos))

            face_mean = float(np.mean(face_sims))
            consistency["face_mean_sim"] = round(face_mean, 3)
            consistency["face_min_sim"] = round(float(np.min(face_sims)), 3)

            # 标记人脸一致性低的镜头
            if face_mean < 0.5:
                for sid in sids:
                    results[sid].issues.append(f"角色人脸一致性低: 均值={face_mean:.3f}")

            for sid in sids:
                results[sid].face_similarity = round(face_mean, 3)

    except Exception as e:
        print(f"    ⚠️ 人脸检测跳过: {e}")

    return results, consistency


# ============================================================
# Layer 4: 视频运动质量（零成本）
# ============================================================

def eval_layer4_motion(job_dir: Path, shots: List[dict],
                       results: Dict[str, ShotScore]) -> Dict[str, ShotScore]:
    """Layer 4: 视频运动质量分析"""
    print("  [Layer 4] 视频运动质量...")
    # 已在 Layer 1 中计算了 motion_score、black_frames、static_frames
    # 这里做额外的帧间一致性检查

    for shot in shots:
        sid = shot.get("shot_id", "")
        video_path = job_dir / "videos" / f"{sid}.mp4"
        if not video_path.exists() or sid not in results:
            continue

        frames = _extract_video_frames(video_path, count=8)
        if len(frames) < 3:
            continue

        # 帧间差异的方差 — 高方差说明运动不均匀（可能有突然跳变）
        diffs = []
        for i in range(len(frames) - 1):
            diff = np.mean(np.abs(frames[i].astype(float) - frames[i + 1].astype(float)))
            diffs.append(diff)

        diff_std = float(np.std(diffs))
        diff_mean = float(np.mean(diffs))
        if diff_mean > 0 and diff_std / diff_mean > 1.5:
            results[sid].issues.append("运动不均匀，可能有跳变")

    return results


# ============================================================
# Layer 5: LLM-as-Judge（可选，调 API）
# ============================================================

def eval_layer5_llm(job_dir: Path, shots: List[dict],
                    results: Dict[str, ShotScore],
                    style_description: str = "") -> Dict[str, ShotScore]:
    """Layer 5: LLM 视觉评估（可选）"""
    print("  [Layer 5] LLM-as-Judge (Gemini Vision)...")

    try:
        from google import genai
        from google.genai import types
        from core.utils import gemini_keys
        from core.safety.llm_gateway import gateway_client
        api_key = gemini_keys.get()
        client = gateway_client(
            task="eval_llm_judge",
            api_key=api_key,
            job_id=job_dir.name if job_dir else None,
        )
    except Exception as e:
        print(f"    ⚠️ LLM 评估跳过（无 API Key）: {e}")
        return results

    # 只抽查 3 个镜头（控制成本）
    eval_shots = [s for s in shots if (job_dir / "stylized_frames" / f"{s.get('shot_id', '')}.png").exists()]
    import random
    eval_shots = random.sample(eval_shots, min(3, len(eval_shots)))

    for shot in eval_shots:
        sid = shot.get("shot_id", "")
        frame_path = job_dir / "stylized_frames" / f"{sid}.png"

        try:
            uploaded = client.files.upload(file=str(frame_path))
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    uploaded,
                    f"""Rate this AI-generated image. Target style: "{style_description or 'cinematic'}".

Score each dimension 1-5 (5=perfect):
1. anatomy: Human body proportions, no extra limbs, natural hands/face
2. style: Match with target style description
3. overall: Overall visual quality and aesthetic appeal

Output ONLY JSON: {{"anatomy": N, "style": N, "overall": N, "issues": ["issue1", ...]}}"""
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )

            scores = json.loads(response.text)
            results[sid].llm_anatomy = scores.get("anatomy")
            results[sid].llm_style = scores.get("style")
            results[sid].llm_overall = scores.get("overall")
            for issue in scores.get("issues", []):
                results[sid].issues.append(f"LLM: {issue}")

        except Exception as e:
            print(f"    ⚠️ {sid} LLM 评估失败: {e}")

    return results


# ============================================================
# 主入口
# ============================================================

def evaluate(job_dir: Path, enable_llm: bool = False) -> EvalReport:
    """
    评估一个 job 的全部质量指标

    Args:
        job_dir: job 目录路径
        enable_llm: 是否启用 LLM-as-Judge（需要 API Key，有成本）

    Returns:
        EvalReport
    """
    job_id = job_dir.name
    print(f"\n{'='*60}")
    print(f"  Quality Evaluation: {job_id}")
    print(f"{'='*60}")

    # 加载数据
    wf_path = job_dir / "workflow.json"
    ir_path = job_dir / "film_ir.json"

    if not wf_path.exists():
        print("  ❌ workflow.json not found")
        return EvalReport(job_id=job_id, evaluated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"))

    with open(wf_path, "r", encoding="utf-8") as f:
        wf = json.load(f)
    shots = wf.get("shots", [])

    film_ir = {}
    if ir_path.exists():
        with open(ir_path, "r", encoding="utf-8") as f:
            film_ir = json.load(f)

    # Layer 1: 基础质量
    results = eval_layer1_basic(job_dir, shots)

    # Layer 2: Prompt 遵从度
    try:
        results = eval_layer2_prompt(job_dir, shots, film_ir, results)
    except Exception as e:
        print(f"  ⚠️ Layer 2 failed: {e}")

    # Layer 3: 跨镜头一致性
    consistency = {}
    try:
        results, consistency = eval_layer3_consistency(job_dir, shots, results)
    except Exception as e:
        print(f"  ⚠️ Layer 3 failed: {e}")
        traceback.print_exc()

    # Layer 4: 视频运动质量
    try:
        results = eval_layer4_motion(job_dir, shots, results)
    except Exception as e:
        print(f"  ⚠️ Layer 4 failed: {e}")

    # Layer 5: LLM-as-Judge（可选）
    if enable_llm:
        style = film_ir.get("userIntent", {}).get("parsedIntent", {}).get(
            "styleInstruction", {}).get("artStyle", "")
        try:
            results = eval_layer5_llm(job_dir, shots, results, style)
        except Exception as e:
            print(f"  ⚠️ Layer 5 failed: {e}")

    # 聚合
    report = EvalReport(
        job_id=job_id,
        evaluated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        shots=list(results.values()),
    )

    ssim_scores = [s.ssim_first_frame for s in results.values() if s.ssim_first_frame is not None]
    clip_scores = [s.clip_prompt_score for s in results.values() if s.clip_prompt_score is not None]
    motion_scores = [s.motion_score for s in results.values() if s.motion_score is not None]

    report.avg_ssim = round(float(np.mean(ssim_scores)), 3) if ssim_scores else None
    report.avg_clip_prompt = round(float(np.mean(clip_scores)), 3) if clip_scores else None
    report.style_consistency = consistency.get("clip_style_std")
    report.face_consistency = consistency.get("face_mean_sim")
    report.color_consistency = consistency.get("color_std")
    report.black_frame_count = sum(1 for s in results.values() if s.has_black_frames)
    report.static_frame_count = sum(1 for s in results.values() if s.has_static_frames)
    report.avg_motion = round(float(np.mean(motion_scores)), 2) if motion_scores else None
    report.total_issues = sum(len(s.issues) for s in results.values())

    # 保存报告
    report_path = job_dir / "eval_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

    # 打印摘要
    print(f"\n  {'─'*50}")
    print(f"  📊 评估摘要")
    print(f"  {'─'*50}")
    print(f"  镜头数:           {len(shots)}")
    print(f"  平均首帧 SSIM:    {report.avg_ssim or 'N/A'}")
    print(f"  平均 CLIP 遵从:   {report.avg_clip_prompt or 'N/A'}")
    print(f"  风格一致性(std):  {report.style_consistency or 'N/A'} (越小越好)")
    print(f"  人脸一致性:       {report.face_consistency or 'N/A'} (>0.5为好)")
    print(f"  色调一致性(std):  {report.color_consistency or 'N/A'} (越小越好)")
    print(f"  黑帧镜头数:       {report.black_frame_count}")
    print(f"  静帧镜头数:       {report.static_frame_count}")
    print(f"  平均运动量:       {report.avg_motion or 'N/A'}")
    print(f"  问题总数:         {report.total_issues}")
    print(f"  报告已保存:       {report_path}")
    print(f"  {'─'*50}\n")

    return report


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Quality Evaluator")
    parser.add_argument("--job_id", type=str, help="Job ID")
    parser.add_argument("--job_dir", type=str, help="Job directory path")
    parser.add_argument("--llm", action="store_true", help="Enable LLM-as-Judge (costs API)")
    args = parser.parse_args()

    if args.job_dir:
        job_dir = Path(args.job_dir)
    elif args.job_id:
        job_dir = Path(__file__).parent.parent / "jobs" / args.job_id
    else:
        print("Error: provide --job_id or --job_dir")
        sys.exit(1)

    if not job_dir.exists():
        print(f"Error: {job_dir} not found")
        sys.exit(1)

    evaluate(job_dir, enable_llm=args.llm)
