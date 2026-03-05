# core/utils.py
import os
import shutil
import subprocess
from pathlib import Path

def get_ffmpeg_path() -> str:
    """
    跨平台获取 ffmpeg 路径
    - Railway/Linux: 使用 PATH 中的 ffmpeg
    - macOS 本地: 使用 Homebrew 路径
    """
    # 优先从 PATH 查找
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    # macOS Homebrew 备用路径
    macos_path = "/opt/homebrew/bin/ffmpeg"
    if os.path.exists(macos_path):
        return macos_path

    # Intel Mac 备用路径
    intel_mac_path = "/usr/local/bin/ffmpeg"
    if os.path.exists(intel_mac_path):
        return intel_mac_path

    raise RuntimeError("ffmpeg not found. Please install ffmpeg.")


def detect_aspect_ratio(video_path) -> str:
    """
    用 ffprobe 检测视频宽高比，返回 API 可用的字符串。
    竖屏 → "9:16"，横屏 → "16:9"，方形 → "1:1"
    """
    video_path = Path(video_path)
    if not video_path.exists():
        return "16:9"

    ffmpeg_path = get_ffmpeg_path()
    ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe") if "ffmpeg" in ffmpeg_path else "ffprobe"

    try:
        result = subprocess.run(
            [ffprobe_path, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             str(video_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0 or not result.stdout.strip():
            return "16:9"

        parts = result.stdout.strip().split(",")
        w, h = int(parts[0]), int(parts[1])
    except Exception:
        return "16:9"

    if h > w:
        return "9:16"
    elif abs(w - h) / max(w, h) < 0.10:
        return "1:1"
    else:
        return "16:9"


# ── API Key Pool: 429 自动切换 ──────────────────────────────
import threading, time

class _KeyPool:
    def __init__(self, env_plural, env_singular):
        raw = os.getenv(env_plural, "")
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            single = os.getenv(env_singular, "")
            if single:
                keys = [single.strip()]
        # 统一 sanitize
        self._keys = [''.join(c for c in k if c.isascii() and c.isprintable()) for k in keys]
        self._keys = [k for k in self._keys if k]
        self._index = 0
        self._cooldowns = {}
        self._lock = threading.Lock()

    def get(self) -> str:
        if not self._keys:
            raise RuntimeError("No API keys configured")
        with self._lock:
            now = time.time()
            for _ in range(len(self._keys)):
                key = self._keys[self._index]
                if self._cooldowns.get(key, 0) <= now:
                    return key
                self._index = (self._index + 1) % len(self._keys)
            return min(self._keys, key=lambda k: self._cooldowns.get(k, 0))

    def mark_exhausted(self, key, cooldown_secs=60):
        with self._lock:
            self._cooldowns[key] = time.time() + cooldown_secs
            self._index = (self._index + 1) % len(self._keys)

gemini_keys = _KeyPool("GEMINI_API_KEYS", "GEMINI_API_KEY")
seedance_keys = _KeyPool("SEEDANCE_API_KEYS", "SEEDANCE_API_KEY")
