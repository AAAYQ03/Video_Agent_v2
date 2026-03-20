# core/node_executors.py
"""
Node Executors
==============
Agent Workflow Canvas (Mode 2) 的节点执行器。

每种 NodeType 映射到一个执行函数，函数内部调用现有后端逻辑。
所有执行器签名统一：(context: ExecutionContext) -> dict

设计原则：
- 薄包装：不包含业务逻辑，只调用现有函数
- 统一异常处理：在 execute_node() 中统一 try/except
- 结果标准化：统一返回 {"status": "success/failed", ...}
"""

import time
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable

from core.graph_model import Node, NodeType


# ============================================================
# 执行上下文
# ============================================================

@dataclass
class ExecutionContext:
    """
    节点执行时的上下文环境

    封装了节点执行所需的所有外部依赖，避免在执行器内部创建对象。
    由 Agent Loop 在每次执行前构造。
    """
    job_id: str
    job_dir: Path
    node: Node
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)

    # 用户目标（INTENT_INJECTION 节点使用）
    user_goal: str = ""

    # 可选：视频文件路径（ANALYZE 节点使用）
    video_path: Optional[Path] = None


# ============================================================
# 各节点类型的执行器
# ============================================================

def _execute_input(ctx: ExecutionContext) -> dict:
    """INPUT: 视频已上传，验证文件存在即可"""
    video = ctx.job_dir / "input.mp4"
    if not video.exists():
        return {"status": "failed", "error": "input.mp4 not found"}
    return {"status": "success", "video_path": str(video)}


def _execute_analyze(ctx: ExecutionContext) -> dict:
    """
    ANALYZE: 基础 Gemini 分析 + FFmpeg 提取 + 初始化 workflow.json + film_ir.json

    对应 Mode 1 的 WorkflowManager._complete_initialization()
    """
    from core.workflow_manager import WorkflowManager

    video_path = ctx.video_path or (ctx.job_dir / "input.mp4")
    if not video_path.exists():
        return {"status": "failed", "error": f"Video not found: {video_path}"}

    wm = WorkflowManager(job_id=ctx.job_id, project_root=ctx.project_root)
    wm.job_dir = ctx.job_dir
    wm.job_id = ctx.job_id

    # 确保目录结构存在
    for subdir in ["frames", "videos", "source_segments", "stylized_frames"]:
        (ctx.job_dir / subdir).mkdir(parents=True, exist_ok=True)

    wm._complete_initialization(video_path)

    # 从 workflow.json 提取摘要信息
    wf = wm.load()
    shots = wf.get("shots", [])
    return {
        "status": "success",
        "shots_count": len(shots),
        "aspect_ratio": wf.get("global", {}).get("aspect_ratio", "16:9"),
    }


def _execute_watermark_clean(ctx: ExecutionContext) -> dict:
    """
    WATERMARK_CLEAN: 水印清理

    对应 Mode 1 的 _run_watermark_cleaning_background()
    """
    from core.film_ir_io import load_film_ir, save_film_ir
    from core.watermark_cleaner import clean_frames

    ir = load_film_ir(ctx.job_dir)
    if not ir:
        return {"status": "failed", "error": "Film IR not found"}

    shots = ir.get("pillars", {}).get("III_shotRecipe", {}).get("concrete", {}).get("shots", [])
    if not shots:
        return {"status": "success", "message": "No shots to clean", "cleaned": 0, "skipped": 0}

    # 标记 PENDING
    for s in shots:
        s["cleaningStatus"] = "PENDING"
    save_film_ir(ctx.job_dir, ir)

    # 执行清理
    cleaning_stats = clean_frames(ctx.job_dir, shots)

    # 更新状态
    shot_statuses = cleaning_stats.get("shot_statuses", {})
    ir = load_film_ir(ctx.job_dir)
    shots = ir.get("pillars", {}).get("III_shotRecipe", {}).get("concrete", {}).get("shots", [])
    for s in shots:
        sid = s.get("shotId", "")
        if sid in shot_statuses:
            s["cleaningStatus"] = shot_statuses[sid]
        elif s.get("cleaningStatus") == "PENDING":
            s["cleaningStatus"] = "SKIPPED"
    save_film_ir(ctx.job_dir, ir)

    return {
        "status": "success",
        "cleaned": cleaning_stats.get("cleaned", 0),
        "skipped": cleaning_stats.get("skipped", 0),
    }


def _execute_film_ir_analysis(ctx: ExecutionContext) -> dict:
    """
    FILM_IR_ANALYSIS: Film IR Stage 1 — 深度分析

    包含：Story Theme + Narrative + Shot Recipe 两阶段 + Character Ledger 三遍扫描
    对应 Mode 1 的 FilmIRManager.run_stage("specificAnalysis")
    """
    from core.film_ir_manager import FilmIRManager

    ir_manager = FilmIRManager(ctx.job_id, project_root=ctx.project_root)
    result = ir_manager.run_stage("specificAnalysis")
    return {
        "status": "success" if result.get("status") == "success" else "failed",
        "detail": result,
    }


def _execute_abstraction(ctx: ExecutionContext) -> dict:
    """
    ABSTRACTION: Film IR Stage 2 — 逻辑抽象

    从 Concrete 层提取 Abstract 层（带占位符的可复用模板）
    对应 Mode 1 的 FilmIRManager.run_stage("abstraction")
    """
    from core.film_ir_manager import FilmIRManager

    ir_manager = FilmIRManager(ctx.job_id, project_root=ctx.project_root)
    result = ir_manager.run_stage("abstraction")
    return {
        "status": "success" if result.get("status") == "success" else "failed",
        "detail": result,
    }


def _execute_intent_injection(ctx: ExecutionContext) -> dict:
    """
    INTENT_INJECTION: Film IR Stage 3 — 意图注入

    解析用户自然语言 → 融合抽象模板 → 生成 Remixed Layer（含 T2I/I2V prompts）
    对应 Mode 1 的 FilmIRManager.run_stage("intentInjection")
    """
    from core.film_ir_manager import FilmIRManager
    from core.film_ir_io import load_film_ir, save_film_ir

    # 从节点 config 或上下文获取用户意图
    intent = ctx.node.config.get("intent", "") or ctx.user_goal
    if not intent:
        return {"status": "failed", "error": "No user intent provided"}

    # 写入 userIntent.rawPrompt
    ir = load_film_ir(ctx.job_dir)
    ir["userIntent"]["rawPrompt"] = intent
    save_film_ir(ctx.job_dir, ir)

    ir_manager = FilmIRManager(ctx.job_id, project_root=ctx.project_root)
    result = ir_manager.run_stage("intentInjection")
    return {
        "status": "success" if result.get("status") == "success" else "failed",
        "detail": result,
    }


def _execute_asset_generation(ctx: ExecutionContext) -> dict:
    """
    ASSET_GENERATION: 生成角色三视图 + 环境参考图

    对应 Mode 1 的 run_asset_generation_background() → FilmIRManager._run_asset_generation()

    特殊处理：纯风格转换（无角色/环境替换）时，没有 identity anchors，
    此步骤无需执行，直接返回 success。
    """
    from core.film_ir_manager import FilmIRManager
    from core.film_ir_io import load_film_ir

    # 检查是否有 identity anchors（纯风格转换时可能没有）
    ir = load_film_ir(ctx.job_dir)
    identity_anchors = ir.get("pillars", {}).get("IV_renderStrategy", {}).get("identityAnchors", {})
    characters = identity_anchors.get("characters", [])
    environments = identity_anchors.get("environments", [])

    if not characters and not environments:
        print(f"ℹ️ [ASSET_GENERATION] No identity anchors — pure style transfer, skipping")
        return {
            "status": "success",
            "message": "Skipped — no identity anchors (pure style transfer)",
            "characters": 0,
            "environments": 0,
        }

    ir_manager = FilmIRManager(ctx.job_id, project_root=ctx.project_root)
    result = ir_manager._run_asset_generation()
    return {
        "status": "success" if result.get("status") == "success" else "failed",
        "detail": result,
    }


def _execute_storyboard(ctx: ExecutionContext) -> dict:
    """
    STORYBOARD: 生成分镜定妆图（T2I）

    对应 Mode 1 的 run_stylize()
    """
    from core.runner import run_stylize
    from core.workflow_io import load_workflow

    wf = load_workflow(ctx.job_dir)
    if not wf:
        return {"status": "failed", "error": "workflow.json not found"}

    run_stylize(ctx.job_dir, wf)

    # 统计结果
    wf = load_workflow(ctx.job_dir)
    shots = wf.get("shots", [])
    success = sum(1 for s in shots if s.get("status", {}).get("stylize") == "SUCCESS")
    failed = sum(1 for s in shots if s.get("status", {}).get("stylize") == "FAILED")

    if success == 0 and failed > 0:
        status = "failed"
    elif failed > 0:
        status = "partial"
    else:
        status = "success"

    return {
        "status": status,
        "total": len(shots),
        "success": success,
        "failed": failed,
    }


def _execute_video_generation(ctx: ExecutionContext) -> dict:
    """
    VIDEO_GENERATION: 生成视频（I2V）

    对应 Mode 1 的 run_video_generate()
    """
    from core.runner import run_video_generate
    from core.workflow_io import load_workflow

    wf = load_workflow(ctx.job_dir)
    if not wf:
        return {"status": "failed", "error": "workflow.json not found"}

    run_video_generate(ctx.job_dir, wf)

    # 统计结果
    wf = load_workflow(ctx.job_dir)
    shots = wf.get("shots", [])
    success = sum(1 for s in shots if s.get("status", {}).get("video_generate") == "SUCCESS")
    failed = sum(1 for s in shots if s.get("status", {}).get("video_generate") == "FAILED")

    if success == 0 and failed > 0:
        status = "failed"
    elif failed > 0:
        status = "partial"
    else:
        status = "success"

    return {
        "status": status,
        "total": len(shots),
        "success": success,
        "failed": failed,
    }


def _execute_merge(ctx: ExecutionContext) -> dict:
    """
    MERGE: 合并所有镜头视频

    对应 Mode 1 的 WorkflowManager.merge_videos()
    """
    from core.workflow_manager import WorkflowManager

    wm = WorkflowManager(job_id=ctx.job_id, project_root=ctx.project_root)
    output_path = wm.merge_videos()

    if output_path and (ctx.job_dir / output_path).exists():
        return {"status": "success", "output": output_path}
    else:
        return {"status": "failed", "error": "Merge produced no output"}


def _execute_output(ctx: ExecutionContext) -> dict:
    """OUTPUT: 终节点，验证最终产物存在"""
    final = ctx.job_dir / "final_output.mp4"
    # 也检查 videos 目录下的输出
    if not final.exists():
        final = ctx.job_dir / "videos" / "final_output.mp4"
    return {
        "status": "success" if final.exists() else "failed",
        "output_path": str(final) if final.exists() else None,
    }


# ============================================================
# 执行器注册表
# ============================================================

NODE_EXECUTORS: Dict[NodeType, Callable[[ExecutionContext], dict]] = {
    NodeType.INPUT:             _execute_input,
    NodeType.ANALYZE:           _execute_analyze,
    NodeType.WATERMARK_CLEAN:   _execute_watermark_clean,
    NodeType.FILM_IR_ANALYSIS:  _execute_film_ir_analysis,
    NodeType.ABSTRACTION:       _execute_abstraction,
    NodeType.INTENT_INJECTION:  _execute_intent_injection,
    NodeType.ASSET_GENERATION:  _execute_asset_generation,
    NodeType.STORYBOARD:        _execute_storyboard,
    NodeType.VIDEO_GENERATION:  _execute_video_generation,
    NodeType.MERGE:             _execute_merge,
    NodeType.OUTPUT:            _execute_output,
}


# ============================================================
# 统一执行入口
# ============================================================

def execute_node(ctx: ExecutionContext) -> dict:
    """
    统一节点执行入口

    - 查找对应的执行器
    - 包装 try/except
    - 记录执行时间
    - 返回标准化结果

    Returns:
        {"status": "success"|"failed"|"partial", "duration_ms": int, ...}
    """
    node_type = ctx.node.type
    executor = NODE_EXECUTORS.get(node_type)

    if not executor:
        return {
            "status": "failed",
            "error": f"No executor registered for node type: {node_type.value}",
            "duration_ms": 0,
        }

    start = time.time()
    try:
        result = executor(ctx)
        elapsed = int((time.time() - start) * 1000)
        result["duration_ms"] = elapsed
        print(f"✅ [{node_type.value}] completed in {elapsed}ms — {result.get('status')}")
        return result
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"❌ [{node_type.value}] failed in {elapsed}ms — {error_msg}")
        traceback.print_exc()
        return {
            "status": "failed",
            "error": error_msg,
            "duration_ms": elapsed,
        }
