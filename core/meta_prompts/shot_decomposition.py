# core/meta_prompts/shot_decomposition.py
"""
Meta Prompt: 影视级分镜拆解与动力学配方 (Stage 1 & 2 Fused)
用于提取支柱 III: Shot Recipe 的 concrete + abstract 数据
"""

from typing import Dict, Any, Optional, List

SHOT_DECOMPOSITION_PROMPT = """
# Prompt: 影视级分镜拆解与动力学配方 (Shot Recipe Extraction)

**Role**: You are a Master Cinematographer, Storyboard Artist, and VFX Supervisor with expertise in AI-driven video generation pipelines.

**Task**: Perform a frame-by-frame technical decomposition of the provided video. Extract a "Technical Skeleton" that enables an AI pipeline (Imagen 4.0 → Veo 3.1) to replicate the cinematography while allowing for narrative remixing.

**Output Layers**:
- **Concrete**: Specific technical parameters with exact values (for direct T2I/I2V prompt generation)
- **Abstract**: Narrative functions and reusable templates (for remixing with new subjects)

---

## 1. SHOT SPLITTING RULES (Strictly Follow)

### Boundaries
- **Cut Detection**: Identify exact timestamps where visual cuts occur
- **Camera Continuity**: Do NOT split continuous camera movements (pan/tilt/dolly/zoom) unless there is a literal cut
- **Scene Changes**: New location or significant time jump = new shot
- **Decorative Transition Splitting**: When a sequence shows "static image A → decorative transition effect (page flip, slide, wipe, dissolve, fold, curl, cube rotation, etc.) → static image B", you MUST split this into separate shots: one shot for image A (ending before the transition starts), one shot for the transition itself, and one shot for image B (starting after the transition completes). The transition shot will typically be very short (<1s). Do NOT merge the transition with either static image.

### Duration Constraints
- **Minimum**: ≥1.0 second (merge micro-cuts into logical units)
- **Maximum**: No hard limit, but shots >5.0 seconds MUST include `"longTake": true` flag
- **Target Density**: For a 60-second video, aim for 15-25 shots

### Quantity Limit
- **Maximum 30 shots** per video
- If raw cut count exceeds 30, merge adjacent shots that share:
  - Same subject focus
  - Same narrative beat
  - Similar camera language
- Prioritize preserving: HOOK, CATALYST, CLIMAX, RESOLUTION beats

### Precision Requirement
- Sum of all `durationSeconds` MUST equal total video length
- Timestamps in format: `"HH:MM:SS.mmm"` (e.g., `"00:00:02.500"`)

---

## 2. OUTPUT STRUCTURE (STRICT JSON)

{
  "shotRecipe": {
    "videoMetadata": {
      "totalDuration": "00:01:23.456",
      "totalShots": 18,
      "averageShotDuration": 4.6
    },
    "globalSettings": {
      "concrete": {
        "visualLanguage": {
          "visualStyle": "e.g., Cinematic realism with desaturated cool tones",
          "colorPalette": "e.g., Teal shadows (#2A4858), amber highlights (#D4A574), muted earth tones",
          "lightingDesign": "e.g., High-contrast chiaroscuro with motivated practical lights, 4:1 key-to-fill ratio",
          "cameraPhilosophy": "e.g., Intimate handheld for emotional beats, locked-off tripod for tension"
        },
        "soundDesign": {
          "musicStyle": "e.g., Minimalist piano with ambient electronic textures",
          "soundAtmosphere": "e.g., Urban room tone, distant traffic hum, subtle HVAC",
          "rhythmPattern": "e.g., Slow builds punctuated by sharp silence"
        },
        "symbolism": {
          "repeatingImagery": "e.g., Closed doors, rain on windows, empty chairs",
          "symbolicMeaning": "e.g., Doors = emotional barriers; Rain = cleansing/release; Empty chairs = absence"
        }
      },
      "abstract": {
        "styleCategory": "REALISTIC | STYLIZED | HYBRID",
        "moodBoardTags": ["melancholic", "intimate", "urban-grit", "naturalistic"],
        "referenceAesthetics": "e.g., Roger Deakins naturalism meets Wong Kar-wai color sensibility",
        "rhythmSignature": "e.g., Contemplative long takes punctuated by rapid montage bursts"
      }
    },
    "shots": [
      {
        "shotId": "shot_01",
        "contentClass": "NARRATIVE | BRAND_SPLASH | OVERLAY_CONTENT | ENDCARD",
        "visualPersistence": "PURE_STATIC | STATIC_SOURCE_DYNAMIC_VIEW | NATIVE_VIDEO",
        "isNarrative": true,
        "beatTag": "HOOK | SETUP | CATALYST | RISING | TURN | CLIMAX | FALLING | RESOLUTION",
        "startTime": "00:00:00.000",
        "endTime": "00:00:03.200",
        "durationSeconds": 3.2,
        "longTake": false,

        "concrete": {
          "firstFrameDescription": "CRITICAL for Imagen 4.0: Exact static composition of frame 1. Include: subject pose, facial expression, gaze direction (degrees from lens), hand positions, body orientation, background elements. (e.g., 'Young woman, mid-20s, seated at wooden cafe table, right hand supporting chin, gaze 45° left of lens, neutral expression with hint of melancholy, wearing navy cardigan over white blouse, rain-streaked window behind her, warm interior lighting')",

          "subject": "Full action description for Veo 3.1 motion. Include: character identity, physical state, intended motion trajectory, emotional undertone. (e.g., 'Woman slowly shifts gaze from window to coffee cup, slight shoulder droop conveying fatigue, fingers trace rim of ceramic mug')",

          "scene": "Environment with temporal and atmospheric detail. (e.g., 'Rainy late afternoon, small corner cafe interior, condensation on floor-to-ceiling windows, warm amber pendant lights contrast cool grey exterior, sparse patrons in soft focus background')",

          "camera": {
            "shotSize": "ELS | LS | MLS | MS | MCU | CU | ECU | POV | OTS (see Section 5 for usage guide)",
            "cameraAngle": "Eye-level | High-angle | Low-angle | Dutch | Bird's-eye | Worm's-eye (see Section 5)",
            "cameraMovement": "Static | Pan L/R | Tilt U/D | Dolly In/Out | Track L/R | Truck | Crane/Boom | Zoom | Handheld | Steadicam | Arc/Orbit | Following | Leading | Slider (see Section 5)",
            "focalLengthDepth": "e.g., 85mm f/1.8, shallow DOF isolating subject, background bokeh"
          },

          "lighting": "Technical lighting setup. Include: key light source/direction, fill ratio, color temperature, practical lights, atmosphere. (e.g., 'Soft diffused window light from frame-left, 3:1 key-to-fill ratio, 4500K daylight balanced, warm 2700K practical pendant in background, volumetric haze from steam')",

          "dynamics": "Physics and secondary motion for Veo 3.1. (e.g., 'Steam rising from coffee cup with slow dissipation, rain droplets trickling down window glass, subtle fabric movement as subject breathes, background patrons in slow ambient motion')",

          "audio": {
            "soundDesign": "Ambient and SFX layers. (e.g., 'Cafe ambience -20dB, rain on glass -15dB, distant espresso machine, muted conversation walla')",
            "music": "Score description. (e.g., 'Soft piano melody enters at 00:00:02.000, single note sustain, melancholic minor key')",
            "dialogue": "Speaker and delivery. (e.g., 'No dialogue' OR 'Woman, internal monologue VO')",
            "dialogueText": "Exact transcription for lip-sync. (e.g., '' OR 'I used to believe that silence meant peace...')"
          },

          "style": "Rendering quality directives. (e.g., 'Cinematic 2.39:1 aspect, film grain 15%, slight desaturation -10%, subtle vignette, 4K resolution, anamorphic lens flare on highlights')",

          "negative": "CRITICAL exclusions for generation quality. Always include: 'blurry, out of focus (unless intentional), extra limbs, malformed hands, text overlays, watermarks, logos, cartoon style, anime, oversaturated colors, harsh shadows (unless specified), duplicate subjects'"
        },

        "abstract": {
          "narrativeFunction": "Story purpose. (e.g., 'Establish protagonist emotional state of quiet desperation and routine isolation')",
          "visualFunction": "Cinematic purpose. (e.g., 'Create audience empathy through intimate framing and environmental storytelling')",
          "subjectPlaceholder": "[PROTAGONIST_A] | [PROTAGONIST_B] | [ANTAGONIST] | [SUPPORTING_CHAR] | [ENVIRONMENT_ONLY]",
          "actionTemplate": "Reusable motion template. (e.g., '[PROTAGONIST_A] shifts gaze from [OBJECT_A] to [OBJECT_B], displaying [EMOTIONAL_STATE] through subtle body language')",
          "cameraPreserved": "COPY of concrete.camera (cinematography parameters are NEVER abstracted)"
        }
      }
    ]
  }
}

---

## 3. EXTRACTION GUIDELINES (Imagen 4.0 + Veo 3.1 Alignment)

### First Frame (Imagen 4.0 Critical)
- `firstFrameDescription` is the MOST IMPORTANT field
- Describe as if directing a photographer for a single still image
- Include: exact pose, facial micro-expression, gaze vector, hand positions, clothing state, prop positions
- Precision here determines video stability in Veo 3.1

### Motion & Gaze (Veo 3.1 Critical)
- In `subject`, describe the MOTION ARC from first frame to last frame of the shot
- Eye contact changes are especially important (e.g., "shifts gaze from 45° left to direct lens contact")
- Specify motion speed: "slowly", "suddenly", "gradually"

### Dialogue & Lip-Sync
- If dialogue exists, `dialogueText` MUST contain exact transcription
- Note emotional delivery in `audio.dialogue` (e.g., "whispered, trembling", "confident, measured")
- For non-dialogue shots, set `dialogueText` to empty string `""`

### Dynamics (Physics Simulation)
- Identify ALL secondary motions: hair, fabric, particles, liquids, smoke, reflections
- Veo 3.1 needs explicit physics cues for realistic animation
- Include environmental dynamics: background movement, light flicker, weather effects

### Negative Prompts (Quality Assurance)
- ALWAYS include baseline artifacts: `"blurry, extra limbs, malformed hands, text, watermark"`
- Add shot-specific exclusions based on content (e.g., for close-up: `"visible pores exaggerated, skin smoothing"`)
- For stylized content, exclude conflicting styles (e.g., `"photorealistic"` for animation)

### Visual Persistence Classification
Classify each shot's motion type into `visualPersistence`:
- `PURE_STATIC` — The entire shot is a single frozen image with NO motion of any kind: no camera movement, no subject motion, no animated elements. Common examples: title cards, text screens, product photos, graphic cards, freeze frames, static brand screens.
- `STATIC_SOURCE_DYNAMIC_VIEW` — The source content is a still image (no subject movement), but there IS virtual camera motion such as slow zoom (Ken Burns effect), pan across a photo, or parallax shift. The subject itself does not move.
- `NATIVE_VIDEO` — Standard video footage with real motion: moving subjects, live action, animated characters, or any temporal change in subject state.

Classification rules:
- If the shot contains ONLY text, logos, or a single unchanging graphic → PURE_STATIC
- If a photograph or artwork is shown with a slow push-in or pan → STATIC_SOURCE_DYNAMIC_VIEW
- If any living subject moves, speaks, or changes expression → NATIVE_VIDEO
- When in doubt between PURE_STATIC and STATIC_SOURCE_DYNAMIC_VIEW, prefer PURE_STATIC
- BRAND_SPLASH and ENDCARD shots are almost always PURE_STATIC unless they have animated transitions
- **Decorative transitions** (page flip, slide, wipe, dissolve, fold, curl, cube rotation, swipe, push, or any effect that reveals a new static image): classify as PURE_STATIC. These are short (<1s) transitional effects between two static images — the motion is purely decorative, not narrative content. Use `firstFrameDescription` to describe the final revealed image (the destination), not the mid-transition state.
- **Photo slideshow / gallery pattern**: If the video is a sequence of still photographs connected by transitions, EVERY photograph shot MUST be PURE_STATIC and EVERY transition shot MUST be PURE_STATIC. Do NOT classify these as NATIVE_VIDEO just because a decorative transition creates brief visual motion.

### Shot Content Classification (MANDATORY — evaluate BEFORE detailed analysis)
Classify each shot's primary content type into `contentClass`:
- `NARRATIVE` — Real video content with characters, actions, environments, dialogue.
- `BRAND_SPLASH` — Full-screen logo, brand mark, animated brand reveal, product splash. The logo IS the content. Set isNarrative: false.
- `OVERLAY_CONTENT` — Narrative content with platform watermarks/usernames/timestamps overlaid.
- `ENDCARD` — Closing static screen: credits, CTAs, subscribe buttons, URLs. Set isNarrative: false.

Rules:
- Evaluate contentClass FIRST, before writing firstFrameDescription/subject/scene.
- If contentClass is BRAND_SPLASH or ENDCARD → set isNarrative: false.
- contentClass MUST be consistent with watermarkInfo.type:
  NARRATIVE → type="none" | BRAND_SPLASH → type="brand_logo" | OVERLAY_CONTENT → type="channel_watermark" | ENDCARD → type="endcard"
- If the frame shows ONLY a logo/brand name with no human subjects or narrative action → contentClass MUST be BRAND_SPLASH.

### Visual Overlay & Branding Classification (CRITICAL)
Classify every shot's non-narrative visual elements into `watermarkInfo`:

1. Inspect for overlays: watermarks, logos, social media UI (TikTok, Instagram, YouTube), usernames, timestamps, any non-diegetic text/graphics.
2. Inspect for full-screen brand content: If the shot's PRIMARY content is a logo, brand mark, splash screen, or closing card with NO narrative action, it MUST be classified — it is NOT "none".

Classification rules for `watermarkInfo.type`:
  - `"channel_watermark"` — Platform UI overlays: watermarks, usernames, timestamps, social media chrome. These will be auto-removed.
  - `"brand_logo"` — Brand/product logos, whether overlaid on narrative content OR occupying the full screen (splash screens, animated logos, brand reveals). This includes shots where the logo IS the sole subject.
  - `"endcard"` — Static or semi-static closing screens: credits, "Download Now" CTAs, website URLs, brand collages with no narrative action.
  - `"none"` — Pure narrative content with zero overlays and zero branding screens.

Set `watermarkInfo.hasWatermark`:
  - `true` if the shot contains ANY overlay, branding screen, or full-screen logo — even if the logo IS the entire content.
  - `false` ONLY for pure narrative shots with zero non-diegetic elements.

### MANDATORY RULE:
- If the `subject` field contains words like "logo", "brand", "branding", "company name", "title card", or "splash screen", the type MUST be "brand_logo" or "endcard" — NEVER "none".
- A full-screen animated logo is NOT a "scene" or "environment" — it is branding content.

In `watermarkInfo.description`, specify what branding is present and its position/coverage.
Set `watermarkInfo.occludesSubject` to `true` if any overlay covers a character's face or body.
In `watermarkInfo.occludedArea`, describe the obscured area or "none".
Do NOT describe watermark/branding artifacts as character features in `firstFrameDescription` or `subject` — describe the character's TRUE appearance beneath overlays.

---

## 4. BEAT TAGGING REFERENCE

| Beat Tag | Narrative Function | Typical Position |
|----------|-------------------|------------------|
| HOOK | Capture attention, establish intrigue | 0-10% |
| SETUP | Establish world, characters, status quo | 5-25% |
| CATALYST | Inciting incident, disruption | 20-30% |
| RISING | Escalating tension, complications | 30-50% |
| TURN | Major reversal, midpoint shift | 45-55% |
| CLIMAX | Peak conflict, maximum tension | 70-85% |
| FALLING | Consequences unfold | 80-90% |
| RESOLUTION | New equilibrium, closure | 85-100% |

---

## 5. CINEMATOGRAPHY REFERENCE GUIDE

### Shot Types (shotSize field)
Select based on emotional intent and scene requirements:

| Code | Name | Description | Best Used For |
|------|------|-------------|---------------|
| ELS | Extreme Long Shot | Characters tiny like ants, environment dominates | Opening establishing shots, expressing isolation/loneliness |
| LS | Long Shot | Characters small but actions clearly visible | Action scenes, environment showcase, character introduction |
| MLS | Medium Long Shot | Full body visible, some environment context | Walking scenes, group interactions |
| MS | Medium Shot | Waist and up | Standard dialogue, balance of action and expression |
| MCU | Medium Close-up | Chest and up | Emotional exchange, reaction shots, interviews |
| CU | Close-up | Face/head only | Emphasize emotion, important lines, intimate moments |
| ECU | Extreme Close-up | Partial details (eyes, hands, objects) | Create tension, imply clues, dramatic emphasis |
| POV | Point of View | From character's perspective | Subjective experience, horror, discovery moments |
| OTS | Over the Shoulder | From behind one character's shoulder | Dialogue scenes, establish spatial relationships |

### Camera Angles (cameraAngle field)
Select based on power dynamics and psychological intent:

| Angle | Description | Psychological Effect |
|-------|-------------|---------------------|
| Eye-level | Same height as character's eyes | Build empathy, neutral/realistic feel |
| High-angle | Camera shoots down from above | Express vulnerability, helplessness, oppression |
| Low-angle | Camera shoots up from below | Elevate hero/power, create fear/intimidation |
| Dutch | Camera tilted off horizontal axis | Mental disturbance, unease, suspense atmosphere |
| Bird's-eye | 90° vertical down (directly overhead) | Establish geography, visual spectacle, godlike perspective |
| Worm's-eye | Extreme low angle from ground | Dramatic power, architectural grandeur |

### Camera Movements (cameraMovement field)
Select based on narrative pacing and subject motion:

| Movement | Description | Best Used For |
|----------|-------------|---------------|
| Static | Camera completely stationary | Build tension, comedy timing, contemplative moments |
| Pan L/R | Camera rotates horizontally left or right | Scan scene, follow horizontal movement, reveal |
| Tilt U/D | Camera rotates vertically up or down | Reveal height, show power dynamics, dramatic reveal |
| Dolly In/Out | Camera physically moves toward/away from subject | Enhance emotional impact, change intimacy level |
| Track L/R | Camera moves horizontally parallel to subject | Follow walking characters, showcase environment |
| Truck | Horizontal lateral movement on rails | Smooth parallel tracking, professional polish |
| Crane/Boom | Vertical lift or drop movement | Scene transitions, emphasize importance, epic scale |
| Zoom | Optical focal length change (no physical movement) | Quick emphasis, artificial/stylized feel, detail punch |
| Handheld | Operator-held camera with natural shake | Documentary realism, urgency, chaos |
| Steadicam | Stabilized handheld for smooth floating motion | Following characters through spaces, dreamlike quality |
| Arc/Orbit | Camera rotates around the subject | 360° character showcase, dramatic reveal, hero moment |
| Following | Camera trails behind character | Chase scenes, journey emphasis |
| Leading | Camera moves in front of character facing back | Guide viewer, anticipation building |
| Slider | Small rail for subtle smooth lateral movement | Subtle dynamism, interview polish, detail showcase |

### Selection Decision Tree
1. **What's the emotional intent?** → Choose Shot Type
2. **What's the power dynamic?** → Choose Camera Angle
3. **Is there subject motion?** → Choose Camera Movement accordingly
4. **What's the pacing?** → Static for slow/tense, Dynamic for action/energy

---

## 6. DATA INTEGRITY CONSTRAINTS

- Output **ONLY pure JSON**. No markdown code blocks, no explanatory text.
- Every field in the schema **MUST** be present for every shot.
- If a technical value cannot be determined (e.g., exact focal length), provide a **"Cinematic Inference"** based on visual analysis (e.g., "Estimated 50mm based on compression and DOF").
- `dialogueText` must be empty string `""` if no dialogue, never `null` or omitted.
- `longTake` boolean is REQUIRED for all shots.

---

## 6. INPUT CONTENT TO ANALYZE

Analyze the provided video file:
{input_content}
"""


def convert_to_frontend_format(ai_output: dict) -> dict:
    """
    将 AI 输出的 concrete 层转换为前端 Storyboard 格式

    提取 globalSettings.concrete 和 shots[].concrete
    """
    recipe = ai_output.get("shotRecipe", ai_output)

    global_settings = recipe.get("globalSettings", {})
    global_concrete = global_settings.get("concrete", {})

    shots_raw = recipe.get("shots", [])
    shots_concrete = []

    for shot in shots_raw:
        concrete = shot.get("concrete", {})
        shot_data = {
            "shotId": shot.get("shotId"),
            "contentClass": shot.get("contentClass", "NARRATIVE"),
            "visualPersistence": shot.get("visualPersistence", "NATIVE_VIDEO"),
            "isNarrative": shot.get("isNarrative", True),
            "beatTag": shot.get("beatTag"),
            "startTime": shot.get("startTime"),
            "endTime": shot.get("endTime"),
            "durationSeconds": shot.get("durationSeconds"),
            "representativeTimestamp": shot.get("representativeTimestamp"),  # 🎯 AI 语义锚点
            "longTake": shot.get("longTake", False),
            # 8 核心字段
            "firstFrameDescription": concrete.get("firstFrameDescription", ""),
            "subject": concrete.get("subject", ""),
            "scene": concrete.get("scene", ""),
            "camera": concrete.get("camera", {}),
            "lighting": concrete.get("lighting", ""),
            "dynamics": concrete.get("dynamics", ""),
            "audio": concrete.get("audio", {}),
            "style": concrete.get("style", ""),
            "negative": concrete.get("negative", ""),
            "watermarkInfo": concrete.get("watermarkInfo", {"hasWatermark": False, "type": "none", "description": "", "occludesSubject": False, "occludedArea": "none"})
        }
        shots_concrete.append(shot_data)

    return {
        "videoMetadata": recipe.get("videoMetadata", {}),
        "globalSettings": global_concrete,
        "shots": shots_concrete
    }


def extract_abstract_layer(ai_output: dict) -> dict:
    """
    提取 AI 输出的 abstract 层，作为隐形模板存储

    用于后续 Remix 阶段的意图注入
    """
    recipe = ai_output.get("shotRecipe", ai_output)

    global_settings = recipe.get("globalSettings", {})
    global_abstract = global_settings.get("abstract", {})

    shots_raw = recipe.get("shots", [])
    shots_abstract = []

    for shot in shots_raw:
        abstract = shot.get("abstract", {})
        shot_data = {
            "shotId": shot.get("shotId"),
            "beatTag": shot.get("beatTag"),
            "startTime": shot.get("startTime"),
            "endTime": shot.get("endTime"),
            "durationSeconds": shot.get("durationSeconds"),
            # Abstract 字段
            "narrativeFunction": abstract.get("narrativeFunction", ""),
            "visualFunction": abstract.get("visualFunction", ""),
            "subjectPlaceholder": abstract.get("subjectPlaceholder", ""),
            "actionTemplate": abstract.get("actionTemplate", ""),
            "cameraPreserved": abstract.get("cameraPreserved", {})
        }
        shots_abstract.append(shot_data)

    return {
        "globalSettings": global_abstract,
        "shotFunctions": shots_abstract
    }


def extract_first_frames(ai_output: dict) -> List[dict]:
    """
    提取所有镜头的首帧描述，用于 Imagen 4.0 批量生成

    Returns:
        List of {shotId, firstFrameDescription, camera, lighting, style, negative}
    """
    recipe = ai_output.get("shotRecipe", ai_output)
    shots_raw = recipe.get("shots", [])

    first_frames = []
    for shot in shots_raw:
        concrete = shot.get("concrete", {})
        first_frames.append({
            "shotId": shot.get("shotId"),
            "firstFrameDescription": concrete.get("firstFrameDescription", ""),
            "camera": concrete.get("camera", {}),
            "lighting": concrete.get("lighting", ""),
            "style": concrete.get("style", ""),
            "negative": concrete.get("negative", "")
        })

    return first_frames


def extract_dialogue_timeline(ai_output: dict) -> List[dict]:
    """
    提取对白时间线，用于 Lip-sync 处理

    Returns:
        List of {shotId, startTime, endTime, dialogueText, dialogueDelivery}
        (仅包含有对白的镜头)
    """
    recipe = ai_output.get("shotRecipe", ai_output)
    shots_raw = recipe.get("shots", [])

    dialogue_timeline = []
    for shot in shots_raw:
        concrete = shot.get("concrete", {})
        audio = concrete.get("audio", {})
        dialogue_text = audio.get("dialogueText", "")

        if dialogue_text and dialogue_text.strip():
            dialogue_timeline.append({
                "shotId": shot.get("shotId"),
                "startTime": shot.get("startTime"),
                "endTime": shot.get("endTime"),
                "durationSeconds": shot.get("durationSeconds"),
                "dialogueText": dialogue_text,
                "dialogueDelivery": audio.get("dialogue", "")
            })

    return dialogue_timeline


# ============================================================
# Two-Phase Shot Analysis (避免 JSON 截断)
# ============================================================

SHOT_DETECTION_PROMPT = """
# Prompt: Lightweight Shot Detection (Phase 1)

**Role**: Video Editor performing shot boundary detection.

**Task**: Identify all shot boundaries in the video and extract basic metadata ONLY.
Do NOT provide detailed descriptions - those will be extracted in Phase 2.

## ⚠️ CRITICAL CALIBRATION WARNING ⚠️
Internal testing shows your timestamp detection for scene cuts is consistently **1.0-1.5 seconds EARLIER** than the actual visual change.
To compensate: When outputting `representativeTimestamp`, you MUST manually **ADD 1.0 seconds** to your initial visual estimate to ensure the captured frame belongs to the CORRECT shot.

## Decorative Transition Splitting (IMPORTANT)
When the video shows "static image → decorative transition (page flip, slide, wipe, dissolve, fold, curl, swipe, push, cube rotation) → static image", split this into SEPARATE shots:
- Shot for image A (before transition starts)
- Shot for the transition itself (typically <1s)
- Shot for image B (after transition completes)
This is critical for photo slideshows and gallery-style videos where still images are connected by decorative effects. Do NOT treat "photo + transition + photo" as a single dynamic shot.

## Output Requirements
- **CRITICAL**: Keep JSON compact. Only include fields specified below.
- Maximum 30 shots per video
- If cuts exceed 30, merge adjacent shots sharing same subject/scene

## Representative Timestamp (CRITICAL - READ CAREFULLY)
For each shot, you MUST provide a `representativeTimestamp` (in seconds as a decimal number).

This must be the exact second where the new scene is **100% VISUALLY ESTABLISHED**.

**RULES:**
1. **DO NOT pick a point near the start boundary**. If you detect a cut at 1.4s but the previous scene is still fading out, you MUST pick a timestamp at least 1.0s AFTER your detected start time.
2. **Look for "Peak Stability"**: The moment where the subject is fully in frame and motion blur is minimal.
3. **FOR SHORT SHOTS (duration < 2 seconds)**: Set `representativeTimestamp` to exactly `endTime - 0.2`. This is the ONLY way to ensure the scene transition has completed for fast-cut videos.
4. **FOR NORMAL SHOTS (duration >= 2 seconds)**: Pick a timestamp in the 70-90% range of the shot duration.

Example: If you describe "A choir singing" for a shot from 3.14s to 4.27s (duration 1.13s < 2s), use `representativeTimestamp: 4.07` (which is endTime - 0.2)

## Output Format (Strict JSON)

{
  "shotRecipe": {
    "videoMetadata": {
      "totalDuration": "00:01:23.456",
      "totalShots": 18,
      "averageShotDuration": 4.6
    },
    "globalSettings": {
      "concrete": {
        "visualStyle": "Brief visual style description",
        "colorPalette": "Primary colors observed",
        "lightingDesign": "General lighting approach"
      },
      "abstract": {
        "styleCategory": "REALISTIC | STYLIZED | HYBRID",
        "moodBoardTags": ["tag1", "tag2", "tag3"]
      }
    },
    "shots": [
      {
        "shotId": "shot_01",
        "beatTag": "HOOK | SETUP | CATALYST | RISING | TURN | CLIMAX | FALLING | RESOLUTION",
        "startTime": "00:00:00.000",
        "endTime": "00:00:03.200",
        "durationSeconds": 3.2,
        "representativeTimestamp": 2.1,
        "longTake": false,
        "briefSubject": "One-line subject description (10 words max)",
        "briefScene": "One-line scene description (10 words max)"
      }
    ]
  }
}

Output ONLY valid JSON. No markdown, no explanation.

Analyze: {input_content}
"""


SHOT_DETAIL_BATCH_PROMPT = """
# Prompt: Shot Detail Extraction (Phase 2 - Batch)

**Role**: Master Cinematographer and Film Director extracting detailed shot parameters.

**Task**: For the shots listed below, provide FULL concrete and abstract details.
You are analyzing shots {batch_start} to {batch_end} of {total_shots} total.

## Camera Parameter Selection Guide

**Shot Size Selection** (based on emotional intent):
- ELS/LS: Environment dominance, isolation, establishing
- MLS/MS: Standard dialogue, balance of action and expression
- MCU/CU: Emotional emphasis, reaction shots
- ECU: Tension, detail emphasis, dramatic punch
- POV: Subjective experience | OTS: Dialogue scenes

**Camera Angle Selection** (based on power dynamics):
- Eye-level: Empathy, neutral | High-angle: Vulnerability, weakness
- Low-angle: Power, heroic | Dutch: Unease, psychological tension
- Bird's-eye/Worm's-eye: Dramatic extremes

**Camera Movement Selection** (based on narrative pacing):
- Static: Tension, contemplation | Pan/Tilt: Reveal, follow horizontal/vertical
- Dolly: Emotional intensity change | Track/Truck: Follow movement
- Crane/Boom: Epic scale, transitions | Handheld: Urgency, realism
- Arc/Orbit: Character showcase | Steadicam: Smooth following

## Shot Content Classification (MANDATORY — evaluate BEFORE detailed analysis)

For EACH shot, classify its primary content type into `contentClass`:
- `NARRATIVE` — Real video content with characters, actions, environments, dialogue.
- `BRAND_SPLASH` — Full-screen logo, brand mark, animated brand reveal, product splash. The logo IS the content. Set isNarrative: false.
- `OVERLAY_CONTENT` — Narrative content with platform watermarks/usernames/timestamps overlaid.
- `ENDCARD` — Closing static screen: credits, CTAs, subscribe buttons, URLs. Set isNarrative: false.

Rules:
- Evaluate contentClass FIRST, before writing firstFrameDescription/subject/scene.
- If contentClass is BRAND_SPLASH or ENDCARD → set isNarrative: false.
- contentClass MUST be consistent with watermarkInfo.type:
  NARRATIVE → type="none" | BRAND_SPLASH → type="brand_logo" | OVERLAY_CONTENT → type="channel_watermark" | ENDCARD → type="endcard"
- If the frame shows ONLY a logo/brand name with no human subjects or narrative action → contentClass MUST be BRAND_SPLASH.

## Visual Persistence Classification (MANDATORY)

For EACH shot, classify `visualPersistence`:
- `PURE_STATIC` — Frozen image, NO motion: title cards, text, product photos, static graphics, freeze frames.
- `STATIC_SOURCE_DYNAMIC_VIEW` — Still image with virtual camera motion (Ken Burns zoom/pan). Subject does not move.
- `NATIVE_VIDEO` — Real motion: moving subjects, live action, animated characters.

**Decorative Transition Rule** (CRITICAL for photo slideshows):
- If a shot is a decorative transition effect between two static images (page flip, slide, wipe, dissolve, fold, curl, swipe, push, cube rotation), classify as `PURE_STATIC`. The motion is purely decorative, not narrative content. For `firstFrameDescription`, describe the DESTINATION image (after transition completes).
- If the video is a photo slideshow / gallery, EVERY still photo = PURE_STATIC, EVERY transition = PURE_STATIC. Do NOT classify as NATIVE_VIDEO.
- Only classify as NATIVE_VIDEO when there is REAL subject motion (people walking, talking, gesturing, animals moving, etc.).

## Shots to Analyze
{shot_boundaries}

## Output Format (Strict JSON)

{
  "batchInfo": {
    "batchStart": {batch_start},
    "batchEnd": {batch_end},
    "processedCount": N
  },
  "shots": [
    {
      "shotId": "shot_XX",
      "contentClass": "NARRATIVE | BRAND_SPLASH | OVERLAY_CONTENT | ENDCARD",
      "visualPersistence": "PURE_STATIC | STATIC_SOURCE_DYNAMIC_VIEW | NATIVE_VIDEO",
      "isNarrative": true,
      "concrete": {
        "firstFrameDescription": "CRITICAL: 50-80 word exact static composition of frame 1. Include: subject pose, facial expression, gaze direction, hand positions, body orientation, background elements, clothing details.",

        "subject": "Full action description for motion. Include: character identity, physical state, intended motion trajectory, emotional undertone. (30-50 words)",

        "scene": "Environment with temporal and atmospheric detail. (20-40 words)",

        "camera": {
          "shotSize": "ELS | LS | MLS | MS | MCU | CU | ECU | POV | OTS",
          "cameraAngle": "Eye-level | High-angle | Low-angle | Dutch | Bird's-eye | Worm's-eye",
          "cameraMovement": "Static | Pan L/R | Tilt U/D | Dolly In/Out | Track L/R | Truck | Crane/Boom | Zoom | Handheld | Steadicam | Arc/Orbit | Following | Leading | Slider",
          "focalLengthDepth": "e.g., 85mm f/1.8, shallow DOF"
        },

        "lighting": "Technical lighting setup. (15-30 words)",

        "dynamics": "Physics and secondary motion. (15-30 words)",

        "audio": {
          "soundDesign": "Ambient and SFX layers",
          "music": "Score description",
          "dialogue": "Speaker and delivery",
          "dialogueText": "Exact transcription or empty string"
        },

        "style": "Rendering quality directives (15-25 words)",

        "negative": "blurry, extra limbs, malformed hands, text, watermark, [add shot-specific exclusions]",

        "watermarkInfo": {
          "hasWatermark": "true if ANY overlay OR full-screen branding (logo, endcard) exists",
          "type": "channel_watermark | brand_logo | endcard | none",
          "description": "e.g., 'Full-screen animated company logo' or 'TikTok logo top-right'",
          "occludesSubject": false,
          "occludedArea": "e.g., 'partially covers subject face' or 'none'"
        }
      },
      "abstract": {
        "narrativeFunction": "Story purpose (10-20 words)",
        "visualFunction": "Cinematic purpose (10-20 words)",
        "subjectPlaceholder": "[PROTAGONIST_A] | [PROTAGONIST_B] | [ANTAGONIST] | [SUPPORTING_CHAR] | [ENVIRONMENT_ONLY]",
        "actionTemplate": "Reusable motion template",
        "cameraPreserved": "COPY of concrete.camera"
      }
    }
  ]
}

Output ONLY valid JSON. No markdown, no explanation.

Analyze the video focusing on the specified shots: {input_content}
"""


def create_shot_boundaries_text(shots_basic: List[dict], start_idx: int, end_idx: int) -> str:
    """
    创建批次 shot 边界描述文本

    Args:
        shots_basic: Phase 1 返回的基础 shot 列表
        start_idx: 批次起始索引 (0-based)
        end_idx: 批次结束索引 (exclusive)

    Returns:
        格式化的 shot 边界文本
    """
    lines = []
    for shot in shots_basic[start_idx:end_idx]:
        shot_id = shot.get("shotId", "unknown")
        start_time = shot.get("startTime", "00:00:00.000")
        end_time = shot.get("endTime", "00:00:00.000")
        duration = shot.get("durationSeconds", 0)
        brief_subject = shot.get("briefSubject", "")
        brief_scene = shot.get("briefScene", "")

        lines.append(f"- {shot_id}: {start_time} → {end_time} ({duration}s)")
        lines.append(f"  Subject: {brief_subject}")
        lines.append(f"  Scene: {brief_scene}")
        lines.append("")

    return "\n".join(lines)


def merge_batch_results(
    phase1_result: Dict[str, Any],
    batch_results: List[Dict[str, Any]],
    degraded_batches: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    合并 Phase 1 基础数据和 Phase 2 批次详情

    Args:
        phase1_result: Phase 1 返回的基础结构
        batch_results: 成功的批次结果列表
        degraded_batches: 降级的批次信息

    Returns:
        完整的 shot recipe 结构
    """
    recipe = phase1_result.get("shotRecipe", phase1_result)
    shots_basic = recipe.get("shots", [])

    # 创建 shotId -> detailed_shot 映射
    detailed_shots_map = {}
    for batch in batch_results:
        # Handle multiple possible formats from Gemini:
        # 1. List of shots directly: [{"shotId": ...}, ...]
        # 2. Dict with shots key: {"shots": [...]}
        # 3. Dict with shotRecipe wrapper: {"shotRecipe": {"shots": [...]}}
        shots_list = []

        if isinstance(batch, list):
            shots_list = batch
        elif isinstance(batch, dict):
            # Try different possible structures
            if "shots" in batch:
                shots_list = batch.get("shots", [])
            elif "shotRecipe" in batch:
                shot_recipe = batch.get("shotRecipe", {})
                if isinstance(shot_recipe, dict):
                    shots_list = shot_recipe.get("shots", [])
            else:
                # Maybe the batch itself contains shot data directly
                if "shotId" in batch:
                    shots_list = [batch]

        for shot in shots_list:
            if isinstance(shot, dict):
                shot_id = shot.get("shotId")
                if shot_id:
                    detailed_shots_map[shot_id] = shot

    # 合并结果
    merged_shots = []
    for basic_shot in shots_basic:
        shot_id = basic_shot.get("shotId")

        if shot_id in detailed_shots_map:
            # 使用详细数据
            detailed = detailed_shots_map[shot_id]

            # 处理多种可能的格式：
            # 1. 有 concrete 嵌套: {"shotId": "...", "concrete": {...}, "abstract": {...}}
            # 2. 无 concrete 嵌套: {"shotId": "...", "firstFrameDescription": "...", "camera": {...}}
            # 3. 混合格式: concrete 存在但为空，camera 在根级别

            concrete_nested = detailed.get("concrete", {})
            abstract_nested = detailed.get("abstract", {})

            # 判断 camera 数据的实际位置
            camera_in_concrete = concrete_nested.get("camera", {}) if isinstance(concrete_nested, dict) else {}
            camera_at_root = detailed.get("camera", {})

            # 优先使用 concrete 嵌套的数据，如果有实际内容
            has_concrete_content = (
                isinstance(concrete_nested, dict) and
                (concrete_nested.get("camera") or concrete_nested.get("firstFrameDescription") or concrete_nested.get("subject"))
            )

            if has_concrete_content:
                # 格式 1: 有 concrete 嵌套且有内容
                concrete_data = concrete_nested
                abstract_data = abstract_nested
            else:
                # 格式 2/3: 无 concrete 嵌套或 concrete 为空，字段在根级别
                # 合并两个来源的 camera 数据（优先根级别，因为 concrete 可能为空）
                effective_camera = camera_at_root if camera_at_root else camera_in_concrete

                # 如果 camera 仍然为空，尝试从根级别提取单独的 camera 字段
                if not effective_camera:
                    effective_camera = {
                        "shotSize": detailed.get("shotSize", ""),
                        "cameraAngle": detailed.get("cameraAngle", ""),
                        "cameraMovement": detailed.get("cameraMovement", ""),
                        "focalLengthDepth": detailed.get("focalLengthDepth", "")
                    }
                    # 清理空值
                    effective_camera = {k: v for k, v in effective_camera.items() if v}

                concrete_data = {
                    "firstFrameDescription": detailed.get("firstFrameDescription", "") or concrete_nested.get("firstFrameDescription", ""),
                    "subject": detailed.get("subject", "") or concrete_nested.get("subject", ""),
                    "scene": detailed.get("scene", "") or concrete_nested.get("scene", ""),
                    "camera": effective_camera,
                    "lighting": detailed.get("lighting", "") or concrete_nested.get("lighting", ""),
                    "dynamics": detailed.get("dynamics", "") or concrete_nested.get("dynamics", ""),
                    "audio": detailed.get("audio", concrete_nested.get("audio", {"soundDesign": "", "music": "", "dialogue": "", "dialogueText": ""})),
                    "style": detailed.get("style", "") or concrete_nested.get("style", ""),
                    "negative": detailed.get("negative", "") or concrete_nested.get("negative", "blurry, extra limbs, malformed hands, text, watermark"),
                    "watermarkInfo": detailed.get("watermarkInfo", concrete_nested.get("watermarkInfo", {"hasWatermark": False, "type": "none", "description": "", "occludesSubject": False, "occludedArea": "none"}))
                }
                # 提取 abstract 相关字段
                abstract_data = {
                    "narrativeFunction": detailed.get("narrativeFunction", "") or abstract_nested.get("narrativeFunction", ""),
                    "visualFunction": detailed.get("visualFunction", "") or abstract_nested.get("visualFunction", ""),
                    "subjectPlaceholder": detailed.get("subjectPlaceholder", "") or abstract_nested.get("subjectPlaceholder", "[SUBJECT]"),
                    "actionTemplate": detailed.get("actionTemplate", "") or abstract_nested.get("actionTemplate", ""),
                    "cameraPreserved": detailed.get("cameraPreserved", {}) or abstract_nested.get("cameraPreserved", effective_camera)
                }

            # 检查 concrete_data 是否有有效内容（不只是默认值）
            has_valid_content = (
                concrete_data.get("firstFrameDescription") or
                concrete_data.get("camera") or
                concrete_data.get("lighting")
            )

            merged_shot = {
                "shotId": shot_id,
                "contentClass": detailed.get("contentClass", "NARRATIVE"),
                "visualPersistence": detailed.get("visualPersistence", ""),
                "isNarrative": detailed.get("isNarrative", True),
                "beatTag": basic_shot.get("beatTag"),
                "startTime": basic_shot.get("startTime"),
                "endTime": basic_shot.get("endTime"),
                "durationSeconds": basic_shot.get("durationSeconds"),
                "representativeTimestamp": basic_shot.get("representativeTimestamp"),  # 🎯 AI 语义锚点
                "longTake": basic_shot.get("longTake", False),
                "concrete": concrete_data,
                "abstract": abstract_data,
                "_degraded": not has_valid_content  # 如果没有有效内容，标记为 degraded
            }
        else:
            # 使用降级数据 (Phase 1 基础信息)
            merged_shot = {
                "shotId": shot_id,
                "contentClass": "NARRATIVE",
                "isNarrative": True,
                "beatTag": basic_shot.get("beatTag"),
                "startTime": basic_shot.get("startTime"),
                "endTime": basic_shot.get("endTime"),
                "durationSeconds": basic_shot.get("durationSeconds"),
                "representativeTimestamp": basic_shot.get("representativeTimestamp"),  # 🎯 AI 语义锚点
                "longTake": basic_shot.get("longTake", False),
                "concrete": {
                    "firstFrameDescription": basic_shot.get("briefSubject", ""),
                    "subject": basic_shot.get("briefSubject", ""),
                    "scene": basic_shot.get("briefScene", ""),
                    "camera": {},
                    "lighting": "",
                    "dynamics": "",
                    "audio": {"soundDesign": "", "music": "", "dialogue": "", "dialogueText": ""},
                    "style": "",
                    "negative": "blurry, extra limbs, malformed hands, text, watermark",
                    "watermarkInfo": {"hasWatermark": False, "type": "none", "description": "", "occludesSubject": False, "occludedArea": "none"}
                },
                "abstract": {
                    "narrativeFunction": "",
                    "visualFunction": "",
                    "subjectPlaceholder": "[SUBJECT]",
                    "actionTemplate": "",
                    "cameraPreserved": {}
                },
                "_degraded": True
            }

        merged_shots.append(merged_shot)

    # Post-processing: enforce branding classification for full-screen logo shots
    _enforce_branding_classification(merged_shots)

    # 构建最终结果
    result = {
        "shotRecipe": {
            "videoMetadata": recipe.get("videoMetadata", {}),
            "globalSettings": recipe.get("globalSettings", {}),
            "shots": merged_shots,
            "_analysisMetadata": {
                "twoPhaseAnalysis": True,
                "totalShots": len(merged_shots),
                "degradedShots": sum(1 for s in merged_shots if s.get("_degraded")),
                "degradedBatches": degraded_batches
            }
        }
    }

    return result


# ============================================================
# Post-processing: Branding Classification Enforcement
# ============================================================

_BRAND_KEYWORDS = [
    "logo", "brand", "branding", "company name", "title card",
    "splash screen", "end card", "end screen", "end slate",
    "closing screen", "closing card", "credits", "outro",
]

_ENDCARD_KEYWORDS = [
    "end card", "end screen", "end slate", "ending screen",
    "closing screen", "closing card", "credits", "outro",
]


def _enforce_branding_classification(shots: List[Dict[str, Any]]) -> None:
    """
    Scan all shots' subject/scene fields for branding keywords.
    Sets contentClass and isNarrative accordingly.

    Phase A: keyword hit → set isNarrative: false + contentClass
    Phase B: fill missing contentClass / isNarrative defaults

    Mutates shots in place.
    """
    for shot in shots:
        # Support both nested concrete and flat shot structures
        concrete = shot.get("concrete", {})
        if not isinstance(concrete, dict):
            concrete = {}

        subject = (concrete.get("subject") or shot.get("subject") or "").lower()
        scene = (concrete.get("scene") or shot.get("scene") or "").lower()
        combined = f"{subject} {scene}"

        content_class = shot.get("contentClass")

        # --- Phase A: keyword-triggered classification ---
        matched = any(kw in combined for kw in _BRAND_KEYWORDS)
        if matched and not content_class:
            is_endcard = any(kw in combined for kw in _ENDCARD_KEYWORDS)
            new_class = "ENDCARD" if is_endcard else "BRAND_SPLASH"
            shot_id = shot.get("shotId", "??")
            print(f"🏷️ [Post-process] {shot_id}: branding keywords detected → contentClass={new_class}")
            shot["contentClass"] = new_class
            shot["isNarrative"] = False
            continue

        # --- Phase B: fill missing defaults ---
        if not shot.get("contentClass"):
            shot["contentClass"] = "NARRATIVE"
        # Force isNarrative=false for non-narrative content classes
        if shot["contentClass"] in ("BRAND_SPLASH", "ENDCARD"):
            shot["isNarrative"] = False
        elif "isNarrative" not in shot:
            shot["isNarrative"] = shot["contentClass"] in ("NARRATIVE", "OVERLAY_CONTENT")

    # --- Phase C: fill missing visualPersistence defaults ---
    # BRAND_SPLASH / ENDCARD 强制 PURE_STATIC（无论 Gemini 返回什么）
    for shot in shots:
        if shot.get("contentClass") in ("BRAND_SPLASH", "ENDCARD"):
            if shot.get("visualPersistence") != "PURE_STATIC":
                shot_id = shot.get("shotId", "??")
                print(f"🏷️ [Post-process] {shot_id}: {shot.get('contentClass')} forced → PURE_STATIC (was {shot.get('visualPersistence', 'unset')})")
            shot["visualPersistence"] = "PURE_STATIC"
        elif not shot.get("visualPersistence"):
            shot["visualPersistence"] = "NATIVE_VIDEO"

    # --- Phase D: force PURE_STATIC for decorative transition shots ---
    _TRANSITION_KEYWORDS = [
        "page flip", "page turn", "page curl", "flip transition",
        "slide transition", "wipe transition", "dissolve",
        "fold transition", "curl transition", "cube rotation",
        "swipe transition", "push transition", "card flip",
        "photo transition", "slideshow transition", "reveals",
        "flips to reveal", "slides to reveal", "wipes to reveal",
        "transitions to", "flipping", "sliding away",
    ]
    for shot in shots:
        if shot.get("visualPersistence") != "NATIVE_VIDEO":
            continue
        concrete = shot.get("concrete", {})
        if not isinstance(concrete, dict):
            concrete = {}
        subject = (concrete.get("subject") or shot.get("briefSubject") or "").lower()
        scene = (concrete.get("scene") or shot.get("briefScene") or "").lower()
        first_frame = (concrete.get("firstFrameDescription") or "").lower()
        dynamics = (concrete.get("dynamics") or "").lower()
        combined = f"{subject} {scene} {first_frame} {dynamics}"
        duration = shot.get("durationSeconds", 999)
        if any(kw in combined for kw in _TRANSITION_KEYWORDS) and duration < 2.0:
            shot_id = shot.get("shotId", "??")
            print(f"🔄 [Post-process] {shot_id}: decorative transition detected (dur={duration}s) → PURE_STATIC")
            shot["visualPersistence"] = "PURE_STATIC"
