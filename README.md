# Video Agent v2 — AI-Powered Video Remix Engine

> Intelligent video analysis, remixing, and generation platform powered by a proprietary Film Intermediate Representation (Film IR) architecture and multi-model AI pipeline.

---

## Product Overview

Video Agent v2 is an end-to-end AI video production platform that enables users to **upload any video, deeply understand its cinematic structure, and remix it with new characters, environments, and visual styles** — while preserving the original cinematography, narrative rhythm, and emotional impact.

Unlike generic AI video generators, Video Agent v2 treats video as a **structured cinematic document**: it extracts story themes, narrative arcs, shot-by-shot cinematography, and character identities into a layered intermediate representation, then applies user modifications at the semantic level before regenerating each shot with AI.

### Core Capabilities

- **Automated Video Analysis** — Upload a video and get instant breakdown of story theme, narrative structure, script analysis, and shot-by-shot cinematography
- **Identity-Preserving Remix** — Replace characters, swap environments, and change visual styles while maintaining original camera work, lighting, and pacing
- **Multi-Model AI Pipeline** — Orchestrates Gemini 3 Flash (analysis), Gemini 3 Pro Image (asset generation), Google Veo 3.1 (video generation), and Seedance 1.5 Pro (alternative video + audio)
- **Three-View Character System** — Generates consistent front/side/back reference views for each character to ensure visual coherence across all shots
- **Natural Language Storyboard Editing** — Chat with AI to modify individual shots, regenerate frames, and iterate on the storyboard
- **Smart Watermark Handling** — Automatic watermark detection, classification, and removal via intelligent cropping
- **Dynamic Aspect Ratio** — Automatically detects video orientation (landscape 16:9 / portrait 9:16 / square 1:1) and propagates to all generation stages
- **Batch Processing** — Queue multiple videos for sequential analysis and generation

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js 16)                      │
│  React 19 · TypeScript · Tailwind CSS 4 · Radix UI/shadcn   │
│  5-Step Wizard: Upload → Analysis → Asset Mgmt → Storyboard │
│                         → Video Gen                          │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
┌──────────────────────────┴──────────────────────────────────┐
│                   Backend (FastAPI + Uvicorn)                 │
│  Python 3.12 · 60+ API Endpoints · Async Task Management    │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Film IR      │  │  Meta Prompt │  │  Execution       │   │
│  │  Manager      │  │  Engine      │  │  Runner          │   │
│  │              │  │              │  │                  │   │
│  │ 4-Pillar IR  │  │ Story Theme  │  │ Frame Stylize    │   │
│  │ 6-Stage      │  │ Narrative    │  │ Video Generate   │   │
│  │ Pipeline     │  │ Shot Recipe  │  │ Audio Synthesis   │   │
│  │ Identity     │  │ Char Ledger  │  │ Video Merge      │   │
│  │ Mapping      │  │ Intent Parse │  │                  │   │
│  └──────┬───────┘  │ Intent Fuse  │  └────────┬─────────┘   │
│         │          └──────┬───────┘           │             │
│         │                 │                   │             │
├─────────┴─────────────────┴───────────────────┴─────────────┤
│                     AI Model Layer                            │
│                                                              │
│  Gemini 3 Flash    Gemini 3 Pro Image    Google Veo 3.1     │
│  (Analysis/NLU)    (Image Generation)    (Video Gen)        │
│                                                              │
│  Seedance 1.5 Pro  FFmpeg/FFprobe                           │
│  (Alt Video+Audio) (Processing)                             │
└──────────────────────────────────────────────────────────────┘
```

---

## Film IR: Four-Pillar Intermediate Representation

The proprietary Film IR architecture is the core differentiator. Each video is decomposed into four semantic pillars, each with **Concrete** (specific), **Abstract** (reusable template), and **Remixed** (user-modified) layers.

| Pillar | Name | Purpose | Key Data |
|--------|------|---------|----------|
| **I** | Story Theme | Thematic DNA | Core theme, narrative arc, character archetypes, symbolism, emotional tone |
| **II** | Narrative Template | Story skeleton | Three-act structure, character system, conflict design, dialogue patterns, character & environment ledger |
| **III** | Shot Recipe | Cinematic muscle | Per-shot: subject, scene, camera (size/angle/movement/focal), lighting, dynamics, audio, style, negative prompts |
| **IV** | Render Strategy | Execution config | Identity anchors (character three-views), visual style, sound design, product inventory |

### Three-Layer Architecture per Pillar

```
Concrete Layer    ─── Specific names, locations, exact values (UI display)
                       "John walks into McDonald's at sunset"

Abstract Layer    ─── Universal archetypes with bracketed placeholders (remixing)
                       "[PROTAGONIST] enters [COMMERCIAL_SETTING] during [GOLDEN_HOUR]"

Remixed Layer     ─── User intent applied to abstract template
                       "LEGO minifigure enters toy store during warm lighting"
```

### Six-Stage Pipeline

| Stage | Name | Input | Output |
|-------|------|-------|--------|
| 1 | Specific Analysis | Raw video | Concrete + Abstract layers across all 4 pillars |
| 2 | Abstraction | Concrete layers | Abstract templates with archetypal placeholders |
| 3 | Intent Injection | User prompt + Abstract | Remixed layer with T2I/I2V prompts |
| 4 | Asset Generation | Identity anchors | Character three-views, environment references |
| 5 | Shot Refinement | Remixed shots | Storyboard frames with identity-consistent characters |
| 6 | Execution | Storyboard frames + I2V prompts | Final generated videos per shot |

---

## AI Model Pipeline

### Analysis & Reasoning — Gemini 3 Flash Preview

- **Story Theme Analysis**: 9-dimensional thematic extraction (core theme, narrative structure, character dynamics, visual style, symbolism, emotional tone, real-world significance)
- **Narrative Extraction**: Script structure, three-act breakdown, character bios (80-120 words per character), dialogue analysis
- **Shot Decomposition**: Two-phase batched analysis avoiding JSON truncation
  - Phase 1: Lightweight shot boundary detection with representative timestamps
  - Phase 2: Batched detail extraction (8 shots/batch) with 8 core cinematic fields
- **Character Ledger**: Three-pass discovery architecture
  - Pass 1: Character identification from key frames
  - Pass 2: Shot-level presence audit (single API call for O(1) complexity)
  - Pass 3: Continuity gap-filling with surgical re-checks
- **Intent Parsing**: Natural language → structured entity-aware modifications with three-step fuzzy entity matching
- **Intent Fusion**: Abstract templates + parsed intent → shot-level T2I/I2V prompts with identity anchor injection

### Image Generation — Gemini 3 Pro Image Preview

- **Character Three-Views**: Front, side, back reference images (2K resolution)
- **Environment References**: Wide establishing shot, detail view, alternate angle
- **Product Three-Views**: E-commerce product reference images from multiple angles
- **Storyboard Frame Generation**: Per-shot first frames with identity-consistent characters and environments
- **Watermark Inpainting**: Content-aware removal for interior watermarks

### Video Generation — Google Veo 3.1

- **Image-to-Video (I2V)**: Takes storyboard first frame + narrative/motion prompt
- **Reference Frame Anchoring**: Preserves character appearance and scene composition from the first frame
- **Cinematography Preservation**: Camera movement, shot scale, and gaze direction encoded in generation prompt
- **Output**: 1280×720, variable FPS, per-shot clips
- **Rate Management**: RPM-limited pipeline with automatic cooldown between shots

### Alternative Video Pipeline — Seedance 1.5 Pro

- **Text-to-Video / Image-to-Video**: Configurable per job
- **Built-in Audio Synthesis**: AI-generated voiceover, music, and sound effects
- **Resolution Options**: 480p / 720p
- **Duration Options**: 4 / 8 / 12 seconds per shot

### Video Processing — FFmpeg

- **Frame Extraction**: Keyframe extraction at AI-determined representative timestamps
- **Smart Watermark Cropping**: Directional crop + upscale for edge watermarks
- **Video Segment Splitting**: Per-shot source segments
- **Final Merge**: Concatenate all shot videos with audio sync
- **Metadata Probing**: Resolution detection, duration calculation, aspect ratio detection (16:9 / 9:16 / 1:1) via FFprobe

---

## Character & Identity Anchor System

The identity anchor system ensures visual consistency across all remixed shots.

### Character Lifecycle

```
Discovery (3-pass)  →  Ledger Entry  →  User Binding  →  Three-View Gen  →  Shot Injection
                                              ↑
                                     Upload custom asset
                                     or AI-generate
```

### Per-Character Data Model

| Field | Description |
|-------|-------------|
| `entityId` | Canonical ID (e.g., `orig_char_01`) |
| `displayName` | Human-readable name |
| `visualSignature` | Appearance description (50-100 words) |
| `detailedDescription` | Full character bio (80-120 words) |
| `persistentAttributes` | Traits that don't change (hair color, accessories, clothing) |
| `appearsInShots` | Shot-level presence tracking |
| `threeViews` | Front / side / back reference images |
| `importance` | PRIMARY / SECONDARY / BACKGROUND |

### Smart Scene Detection

- Skips identity injection for pure landscapes, empty rooms, object close-ups
- Only narrative shots (`isNarrative: true`) with human subjects receive character injection
- Non-narrative shots (brand splashes, endcards) become **graphic scene** assets — users replace them entirely via the asset management UI

---

## Watermark & Branding Intelligence

### Detection

Each extracted frame is analyzed by Gemini vision for:
- Watermark presence and position (edge vs. interior vs. center)
- Content classification: `NARRATIVE` | `BRAND_SPLASH` | `OVERLAY_CONTENT` | `ENDCARD`
- Subject occlusion detection (does the watermark cover the character?)

### Two-Tier Cleaning

| Tier | Condition | Action |
|------|-----------|--------|
| **COPY** | No watermark or non-narrative shot | Keep frame as-is |
| **SMART CROP** | Edge watermark (corner/bar) | Directional FFmpeg crop + upscale to original resolution |

Non-narrative shots (brand splashes, endcards) are automatically classified as **graphic scenes** with dedicated environment entries in the ledger, allowing users to upload replacement graphics via the UI.

---

## Frontend Application

### Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Framework | Next.js (App Router, RSC) | 16.0.10 |
| UI Library | React | 19.2.0 |
| Language | TypeScript | 5.x |
| Styling | Tailwind CSS | 4.1.9 |
| Component System | shadcn/ui + Radix UI | 40+ components |
| Icons | Lucide React | 0.454.0 |
| Forms | React Hook Form + Zod | 7.60.0 / 3.25.76 |
| Charts | Recharts | 2.15.4 |
| File Upload | React Dropzone | 14.3.8 |
| Notifications | Sonner | 1.7.4 |
| Theme | next-themes (dark mode) | 0.4.6 |
| Analytics | Vercel Analytics | 1.3.1 |

### User Workflow (5-Step Wizard)

```
Step 1: Upload & Analysis
  └─ Drag-drop video → automatic AI analysis (theme, script, storyboard, characters)

Step 2: Generate Remix Script
  └─ Enter modification instructions → AI generates remixed script with diff view

Step 3: Asset Management
  └─ Configure character three-views, environment refs, products, visual style, sound design

Step 4: Generate Storyboard
  └─ AI generates per-shot frames → chat interface for iterative refinement

Step 5: Generate Video
  └─ Serial shot-by-shot generation → automatic merge → download final output
```

### Key UI Features

- **Real-Time Polling**: Exponential backoff for long-running AI tasks (analysis, generation)
- **Storyboard Chat**: Natural language shot modification with live frame regeneration
- **Drag-Drop Asset Binding**: Bind uploaded images to character/environment slots
- **Before/After Diff View**: Side-by-side comparison of original vs. remixed storyboard
- **Batch Processing Queue**: Upload and process multiple videos sequentially
- **Progressive Generation Tracking**: Shot-by-shot progress with time estimates

---

## Backend Architecture

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI (async, ASGI) |
| Runtime | Python 3.12 + Uvicorn |
| AI SDK | google-genai (Gemini / Veo / Imagen) |
| Image Processing | Pillow |
| Video Processing | FFmpeg / FFprobe |
| File Upload | python-multipart |
| HTTP Client | requests |

### API Surface — 60+ REST Endpoints

| Category | Count | Key Endpoints |
|----------|-------|---------------|
| Upload & Analysis | 4 | `/api/upload`, `/api/job/{id}/storyboard`, `/api/job/{id}/upload-status` |
| Film IR | 6 | `/api/job/{id}/film_ir`, `/api/job/{id}/film_ir/story_theme`, `.../narrative`, `.../shots` |
| Remix (M4) | 5 | `/api/job/{id}/remix`, `.../remix/status`, `.../remix/diff`, `.../remix/prompts` |
| Asset Management (M5) | 12 | `/api/job/{id}/generate-assets`, `.../assets`, `.../upload-view/{id}/{view}`, `.../generate-views/{id}` |
| Character Ledger | 4 | `/api/job/{id}/character-ledger`, `.../bind-asset`, `.../entity/{id}` |
| Storyboard | 6 | `.../generate-remix-storyboard`, `.../storyboard/chat`, `.../storyboard/finalize` |
| Video Generation | 3 | `.../generate-videos-batch`, `/api/run/{node_type}` |
| Sound & Visual Style | 5 | `.../sound-design`, `.../visual-style`, `.../visual-style-reference` |
| Product Management | 7 | `.../products`, `.../products/{id}/views/{view}`, `.../generate-product-views/{id}` |
| Asset Library | 4 | `/api/library-assets` (CRUD) |
| Agent Chat | 1 | `/api/agent/chat` |

### Data Persistence

File-based JSON storage — zero database infrastructure overhead:

```
jobs/{job_id}/
├── input.mp4                    # Original uploaded video
├── film_ir.json                 # Complete Film IR (all 4 pillars + stages)
├── workflow.json                # Shot-level execution state
├── frames/                      # Cleaned extracted frames
├── frames_original/             # Backup of pre-cleaning frames
├── storyboard/                  # Generated storyboard frames
├── storyboard_frames/           # Identity-anchor-injected frames
├── videos/                      # Generated shot videos
├── source_segments/             # Original video clips per shot
├── assets/                      # Character/environment three-views
│   ├── {char_id}_front.png
│   ├── {char_id}_side.png
│   ├── {char_id}_back.png
│   └── {env_id}_wide.png
└── final_output.mp4             # Merged final video
```

---

## Meta-Prompt Engineering

The Meta Prompt Engine drives all AI analysis with carefully engineered prompt templates.

### Design Principles

1. **Dual-Layer Output**: Every analysis produces both Concrete (specific, displayable) and Abstract (reusable, remixable) layers simultaneously
2. **Watermark Awareness**: All prompts explicitly instruct AI to ignore logos, overlays, and branding elements when describing subjects
3. **Cinematography Fidelity**: Camera parameters (shot size, angle, movement, focal length) are NEVER abstracted — they are preserved verbatim through all layers
4. **Resilient Batching**: Two-phase shot analysis avoids JSON truncation; automatic batch splitting and degradation handling for large videos
5. **Entity-Aware Processing**: Three-step fuzzy matching links user natural language to canonical entity IDs in the character/environment ledger

### Degradation Handling

```
Batch analysis attempt
  ├─ Success → merge with Phase 1
  ├─ JSON truncation → auto-repair (bracket counting, partial extraction)
  ├─ Repair failed → split batch in half, retry each half
  └─ All retries failed → fall back to Phase 1 basic data (marked degraded)
```

Degraded shots are tracked in `_analysisMetadata` and can be retried independently.

---

## Deployment

### Infrastructure

| Component | Platform |
|-----------|----------|
| Backend | Railway (Nixpacks, auto-scaling) |
| Frontend | Vercel / Railway |
| AI Models | Google Cloud (Gemini API) |
| Video Gen | Google Cloud (Veo API) + Seedance API |

### Configuration

**`nixpacks.toml`** — Railway build configuration:
```toml
[phases.setup]
nixPkgs = ["python312", "ffmpeg"]

[phases.install]
cmds = ["python -m venv --copies /opt/venv",
        ". /opt/venv/bin/activate",
        "pip install -r requirements.txt"]

[start]
cmd = "uvicorn app:app --host 0.0.0.0 --port $PORT"
```

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GEMINI_API_KEYS` | Yes | Comma-separated Gemini API keys (auto-rotating pool with 429 cooldown) |
| `GEMINI_API_KEY` | Fallback | Single Gemini key (used if `GEMINI_API_KEYS` not set) |
| `SEEDANCE_API_KEYS` | Optional | Comma-separated Seedance API keys (auto-rotating pool) |
| `SEEDANCE_API_KEY` | Fallback | Single Seedance key |
| `BASE_URL` | Production | Public URL for asset serving |
| `PORT` | Auto-set | Server port (Railway) |
| `NEXT_PUBLIC_API_URL` | Frontend | Backend API base URL |

---

## Technical Differentiators

| Capability | Video Agent v2 | Generic AI Video Tools |
|-----------|----------------|----------------------|
| Cinematography Preservation | Preserves shot scale, camera angle, movement, gaze direction per-shot | Generates from text description only |
| Structural Understanding | Four-pillar semantic decomposition (story → narrative → shots → render) | Flat prompt → video |
| Character Consistency | Three-pass ledger + three-view reference system | No cross-shot consistency |
| Remix Granularity | Entity-level: replace specific characters/environments while keeping others | All-or-nothing regeneration |
| Narrative Fidelity | Preserves beat structure, pacing rhythm, emotional arc | No narrative awareness |
| Watermark Intelligence | Auto-detect, classify, and remove with position-aware cropping | Manual preprocessing required |
| Multi-Model Orchestration | Gemini Flash + Pro Image + Veo 3.1 + Seedance with automatic fallback | Single model dependency |
| Abstraction Layer | Reusable templates enable style transfer without losing narrative spine | No abstraction capability |

---

## Project Scale

| Metric | Value |
|--------|-------|
| Backend Source | ~8,000 lines Python |
| Frontend Source | ~15,000 lines TypeScript/React |
| API Endpoints | 60+ REST endpoints |
| AI Models Integrated | 4 (Gemini Flash, Gemini Pro Image, Veo 3.1, Seedance) |
| Meta Prompt Templates | 15+ engineered prompt templates |
| UI Components | 40+ (shadcn/ui + custom) |
| Core Modules | 12 Python modules |
| Frontend Components | 30+ React components |

---

## License

Proprietary. All rights reserved.
