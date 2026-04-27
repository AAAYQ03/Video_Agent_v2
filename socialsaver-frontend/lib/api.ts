// lib/api.ts
// SocialSaver frontend API configuration and call functions

// Backend API base URL
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ============================================================
// Type Definitions
// ============================================================

export interface UploadResponse {
  status: string;
  job_id: string;
}

export interface JobStatus {
  jobId: string;
  totalShots: number;
  stylizedCount: number;
  videoGeneratedCount: number;
  runningCount: number;
  canMerge: boolean;
  globalStages: Record<string, string>;
  globalStyle: string;
}

export interface SocialSaverStoryboard {
  jobId: string;
  sourceVideo: string;
  globalStyle: string;
  storyboard: SocialSaverShot[];
  status: {
    analyze: string;
    stylize: string;
    videoGen: string;
    merge: string;
  };
}

export interface SocialSaverShot {
  shotNumber: number;
  firstFrameImage: string;
  visualDescription: string;
  contentDescription: string;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  shotSize: string;
  cameraAngle: string;
  cameraMovement: string;
  focalLengthDepth: string;
  lighting: string;
  music: string;
  dialogueVoiceover: string;
}

export interface AgentChatResponse {
  action: any;
  result: {
    status: string;
    affected_shots?: number;
  };
}

// ============================================================
// API Call Functions
// ============================================================

/**
 * Upload status response
 */
interface UploadStatus {
  status: "queued" | "analyzing" | "completed" | "failed" | "unknown";
  stage: string;
  message: string;
}

/**
 * Upload video (async mode - returns immediately)
 *
 * material_tag 默认 "INTERNAL"——Batch 1 设计原意是让用户显式选择
 * "内部自制 / 爆款参考"，agent-canvas 上传 UI 已实装这个选择器
 * (app/dashboard/agent-canvas/page.tsx)。其他调用点（如 Mode 1 的 remix）
 * 仍走默认值。
 *
 * VIRAL_REF 的两个必填字段（referenceUrl / referenceDimensions）由
 * 调用方在 UI 收集后传入；后端 input_guard 会做最终校验。
 */
export interface UploadOptions {
  materialTag?: "INTERNAL" | "VIRAL_REF";
  containsConfidential?: boolean;
  referenceUrl?: string;
  referenceDimensions?: string[];   // 仅 VIRAL_REF 必填
}

export async function uploadVideo(
  file: File,
  options: UploadOptions = {},
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("material_tag", options.materialTag ?? "INTERNAL");
  if (options.containsConfidential) {
    formData.append("contains_confidential", "true");
  }
  if (options.referenceUrl) {
    formData.append("reference_url", options.referenceUrl);
  }
  if (options.referenceDimensions && options.referenceDimensions.length > 0) {
    formData.append("reference_dimensions", options.referenceDimensions.join(","));
  }

  const response = await fetch(`${API_BASE_URL}/api/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Upload failed" }));
    // FastAPI 422 校验错误 detail 是 array, 单字符串错误是 string
    const message = typeof error.detail === "string"
      ? error.detail
      : Array.isArray(error.detail)
      ? error.detail.map((d: { msg: string; loc: string[] }) => `${d.loc.join(".")}: ${d.msg}`).join("; ")
      : "Upload failed";
    throw new Error(message);
  }

  return response.json();
}

/**
 * Poll upload analysis status
 */
export async function getUploadStatus(jobId: string): Promise<UploadStatus> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/upload-status`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch upload status" }));
    throw new Error(error.detail || "Failed to fetch upload status");
  }

  return response.json();
}

/**
 * Upload video and wait for analysis to complete (polling)
 */
export async function uploadVideoAndWaitForAnalysis(
  file: File,
  onProgress?: (status: UploadStatus) => void
): Promise<{ jobId: string }> {
  // 1. Upload file (returns immediately with job_id)
  console.log("📤 Uploading video:", file.name);
  const uploadResult = await uploadVideo(file);
  const jobId = uploadResult.job_id;

  console.log("📋 Job created:", jobId, "- Polling for analysis completion...");

  // 2. Poll for analysis completion
  const maxAttempts = 420; // 35 minutes max (5s interval)
  const pollInterval = 5000; // 5 seconds

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const status = await getUploadStatus(jobId);

      if (onProgress) {
        onProgress(status);
      }

      if (status.status === "completed") {
        console.log("✅ Analysis completed for job:", jobId);
        return { jobId };
      }

      if (status.status === "failed") {
        throw new Error(`Analysis failed: ${status.message}`);
      }

      // Still processing, wait and retry
      console.log(`⏳ Analysis in progress (${attempt + 1}/${maxAttempts}): ${status.message}`);
      await new Promise(resolve => setTimeout(resolve, pollInterval));

    } catch (error) {
      // On network error, wait and retry
      console.warn(`⚠️ Status check failed, retrying...`, error);
      await new Promise(resolve => setTimeout(resolve, pollInterval));
    }
  }

  throw new Error("Analysis timed out after 35 minutes");
}

/**
 * Get storyboard in SocialSaver format
 */
export async function getStoryboard(jobId: string): Promise<SocialSaverStoryboard> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/storyboard`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch storyboard" }));
    throw new Error(error.detail || "Failed to fetch storyboard");
  }

  return response.json();
}

/**
 * Get job status
 */
export async function getJobStatus(jobId: string, maxRetries: number = 3): Promise<JobStatus> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/status`);

      if (!response.ok) {
        // For 5xx errors, retry
        if (response.status >= 500 && attempt < maxRetries - 1) {
          console.warn(`[getJobStatus] Server error (${response.status}), retrying in ${(attempt + 1) * 500}ms...`);
          await new Promise(resolve => setTimeout(resolve, (attempt + 1) * 500));
          continue;
        }
        const error = await response.json().catch(() => ({ detail: "Failed to fetch status" }));
        throw new Error(error.detail || "Failed to fetch status");
      }

      return response.json();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error("Unknown error");

      // Network errors or fetch failures - retry
      if (attempt < maxRetries - 1) {
        console.warn(`[getJobStatus] Fetch error, retrying in ${(attempt + 1) * 500}ms...`, error);
        await new Promise(resolve => setTimeout(resolve, (attempt + 1) * 500));
        continue;
      }
    }
  }

  // All retries failed - return a default status instead of throwing
  // This prevents the UI from showing "Failed" when the backend is just temporarily busy
  console.error("[getJobStatus] All retries failed, returning default status");
  return {
    status: "unknown",
    globalStages: { video_gen: "RUNNING" }, // Assume still running
    totalShots: 0,
    videoGeneratedCount: 0,
    runningCount: 1, // Assume something is running
  } as JobStatus;
}

/**
 * Get original workflow (ReTake format)
 */
export async function getWorkflow(jobId?: string): Promise<any> {
  const url = jobId
    ? `${API_BASE_URL}/api/workflow?job_id=${jobId}`
    : `${API_BASE_URL}/api/workflow`;

  const response = await fetch(url);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch workflow" }));
    throw new Error(error.detail || "Failed to fetch workflow");
  }

  return response.json();
}

/**
 * Send Agent chat message (modify storyboard, style, etc.)
 */
export async function sendAgentChat(message: string, jobId: string): Promise<AgentChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/agent/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      job_id: jobId,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Chat request failed" }));
    throw new Error(error.detail || "Chat request failed");
  }

  return response.json();
}

/**
 * Run task node (stylize, video_generate, merge)
 */
export async function runTask(
  nodeType: "stylize" | "video_generate" | "merge",
  jobId: string,
  shotId?: string
): Promise<{ status: string; job_id: string; file?: string }> {
  const params = new URLSearchParams();
  params.append("job_id", jobId);
  if (shotId) {
    params.append("shot_id", shotId);
  }

  const response = await fetch(`${API_BASE_URL}/api/run/${nodeType}?${params.toString()}`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Task failed" }));
    throw new Error(error.detail || "Task failed");
  }

  return response.json();
}

/**
 * Batch serial video generation (to prevent Veo RPM throttling)
 *
 * Features:
 * - Serial execution: one at a time to avoid concurrent bombardment
 * - Cooldown interval: 30 seconds wait between each shot
 * - Random jitter: adds 5-15 seconds random delay on retry
 * - Circuit breaker: pauses after 3 consecutive failures
 */
export async function generateVideosBatch(
  jobId: string
): Promise<{ status: string; message: string; job_id: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/generate-videos-batch`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Batch video generation failed" }));
    throw new Error(error.detail || "Batch video generation failed");
  }

  return response.json();
}

/**
 * Update a single shot
 */
export async function updateShot(
  jobId: string,
  shotId: string,
  description: string
): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/api/shot/update`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      job_id: jobId,
      shot_id: shotId,
      description,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Update failed" }));
    throw new Error(error.detail || "Update failed");
  }

  return response.json();
}

/**
 * Get full asset URL
 */
export function getAssetUrl(jobId: string, assetPath: string): string {
  if (!assetPath) return "";
  // If already a full URL, return as is
  if (assetPath.startsWith("http")) return assetPath;
  // Build full URL
  return `${API_BASE_URL}/assets/${jobId}/${assetPath}`;
}

/**
 * Get Film IR Story Theme analysis result
 */
export async function getStoryTheme(jobId: string): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/film_ir/story_theme`);

  if (!response.ok) {
    if (response.status === 404) {
      return null; // Story theme not ready yet
    }
    const error = await response.json().catch(() => ({ detail: "Failed to fetch story theme" }));
    throw new Error(error.detail || "Failed to fetch story theme");
  }

  return response.json();
}

/**
 * Get Film IR Narrative/Script Analysis result
 */
export async function getScriptAnalysis(jobId: string): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/film_ir/narrative`);

  if (!response.ok) {
    if (response.status === 404) {
      return null; // Script analysis not ready yet
    }
    const error = await response.json().catch(() => ({ detail: "Failed to fetch script analysis" }));
    throw new Error(error.detail || "Failed to fetch script analysis");
  }

  return response.json();
}

/**
 * Poll job status until completion
 */
export async function pollJobStatus(
  jobId: string,
  onUpdate: (status: JobStatus) => void,
  intervalMs: number = 3000,
  maxAttempts: number = 200
): Promise<JobStatus> {
  let attempts = 0;

  while (attempts < maxAttempts) {
    const status = await getJobStatus(jobId);
    onUpdate(status);

    // Check if all tasks are complete
    const allDone = status.runningCount === 0 &&
      (status.globalStages.analyze === "SUCCESS" || status.globalStages.analyze === "FAILED");

    if (allDone) {
      return status;
    }

    await new Promise(resolve => setTimeout(resolve, intervalMs));
    attempts++;
  }

  throw new Error("Polling timeout");
}

// ============================================================
// M4: Intent Injection (Remix) API
// ============================================================

export interface RemixResponse {
  status: string;
  jobId: string;
  message: string;
  userPrompt: string;
  referenceImages: string[];
}

export interface RemixStatusResponse {
  jobId: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface RemixDiffEntry {
  shotId: string;
  beatTag: string;
  changes: { type: string; description: string }[];
  originalFirstFrame: string;
  remixedFirstFrame: string;
  remixNotes: string;
}

export interface RemixDiffResponse {
  jobId: string;
  hasDiff: boolean;
  diff: RemixDiffEntry[];
  summary: {
    totalShots: number;
    shotsModified: number;
    primaryChanges: string[];
    styleApplied: string | null;
    moodShift: string | null;
    preservedElements: string[];
  };
}

export interface T2IPrompt {
  shotId: string;
  prompt: string;
  cameraPreserved: {
    shotSize: string;
    cameraAngle: string;
    cameraMovement: string;
    focalLengthDepth: string;
  };
  appliedAnchors: {
    characters: string[];
    environments: string[];
  };
}

export interface I2VPrompt {
  shotId: string;
  prompt: string;
  durationSeconds: number;
  cameraPreserved: {
    shotSize: string;
    cameraAngle: string;
    cameraMovement: string;
    focalLengthDepth: string;
  };
  firstFrameInheritance: boolean;
}

export interface IdentityAnchor {
  anchorId: string;
  anchorName: string;
  detailedDescription: string;
  originalPlaceholder?: string;
  persistentAttributes?: string[];
  imageReference?: string | null;
  styleAdaptation?: string;
  atmosphericConditions?: string;
}

export interface RemixPromptsResponse {
  jobId: string;
  t2iPrompts: T2IPrompt[];
  i2vPrompts: I2VPrompt[];
  identityAnchors: {
    characters: IdentityAnchor[];
    environments: IdentityAnchor[];
  };
}

/**
 * Trigger Intent Injection (M4 Remix)
 */
export async function triggerRemix(
  jobId: string,
  prompt: string,
  referenceImages?: string[]
): Promise<RemixResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/remix`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      prompt,
      reference_images: referenceImages || [],
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Remix failed" }));
    throw new Error(error.detail || "Remix failed");
  }

  return response.json();
}

/**
 * Get Remix status
 */
export async function getRemixStatus(jobId: string): Promise<RemixStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/remix/status`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch remix status" }));
    throw new Error(error.detail || "Failed to fetch remix status");
  }

  return response.json();
}

/**
 * Get Remix Diff (concrete vs remixed)
 */
export async function getRemixDiff(jobId: string): Promise<RemixDiffResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/remix/diff`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch remix diff" }));
    throw new Error(error.detail || "Failed to fetch remix diff");
  }

  return response.json();
}

/**
 * Get Remix Prompts (T2I/I2V)
 */
export async function getRemixPrompts(jobId: string): Promise<RemixPromptsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/remix/prompts`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch remix prompts" }));
    throw new Error(error.detail || "Failed to fetch remix prompts");
  }

  return response.json();
}

/**
 * Poll Remix status until completion
 */
export async function pollRemixStatus(
  jobId: string,
  onUpdate: (status: RemixStatusResponse) => void,
  intervalMs: number = 2000,
  maxAttempts: number = 60
): Promise<RemixStatusResponse> {
  let attempts = 0;

  while (attempts < maxAttempts) {
    const status = await getRemixStatus(jobId);
    onUpdate(status);

    if (status.status === "completed" || status.status === "failed") {
      return status;
    }

    await new Promise(resolve => setTimeout(resolve, intervalMs));
    attempts++;
  }

  throw new Error("Remix polling timeout");
}

/**
 * Use the original video analysis as-is (no remix modifications).
 * Synchronous — no polling needed.
 */
export async function useOriginal(jobId: string): Promise<{
  status: string;
  jobId: string;
  message: string;
  totalShots: number;
}> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/use-original`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to use original video" }));
    throw new Error(error.detail || "Failed to use original video");
  }

  return response.json();
}

// ============================================================
// M5: Asset Generation API
// ============================================================

export interface AssetGenerationResponse {
  status: string;
  jobId: string;
  message: string;
  assetsToGenerate?: {
    characters: number;
    characterViews: number;
    environments: number;
    total: number;
  };
}

export interface AssetGenerationStatusResponse {
  jobId: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  result?: {
    status: string;
    message: string;
    generated: number;
    failed: number;
    total: number;
    assets_dir: string;
  };
  error?: string;
}

export interface CharacterAsset {
  anchorId: string;
  name: string;
  status: string;
  threeViews: {
    front: string | null;
    side: string | null;
    back: string | null;
  };
}

export interface EnvironmentAsset {
  anchorId: string;
  name: string;
  status: string;
  referenceImage: string | null;
}

export interface GeneratedAssetsResponse {
  jobId: string;
  assets: {
    characters: CharacterAsset[];
    environments: EnvironmentAsset[];
  };
  assetsDir: string;
}

/**
 * Trigger asset generation (M5)
 */
export async function triggerAssetGeneration(jobId: string): Promise<AssetGenerationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/generate-assets`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Asset generation failed" }));
    throw new Error(error.detail || "Asset generation failed");
  }

  return response.json();
}

/**
 * Get asset generation status
 */
export async function getAssetGenerationStatus(jobId: string): Promise<AssetGenerationStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/assets/status`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch asset status" }));
    throw new Error(error.detail || "Failed to fetch asset status");
  }

  return response.json();
}

/**
 * Get generated assets
 */
export async function getGeneratedAssets(jobId: string): Promise<GeneratedAssetsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/assets`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch assets" }));
    throw new Error(error.detail || "Failed to fetch assets");
  }

  return response.json();
}

/**
 * Poll asset generation status until completion
 */
export async function pollAssetGeneration(
  jobId: string,
  onUpdate: (status: AssetGenerationStatusResponse) => void,
  intervalMs: number = 3000,
  maxAttempts: number = 150  // 150 × 3s = 7.5 minutes
): Promise<AssetGenerationStatusResponse> {
  let attempts = 0;

  while (attempts < maxAttempts) {
    const status = await getAssetGenerationStatus(jobId);
    onUpdate(status);

    if (status.status === "completed" || status.status === "failed" || status.status === "partial") {
      return status;
    }

    await new Promise(resolve => setTimeout(resolve, intervalMs));
    attempts++;
  }

  throw new Error("Asset generation polling timeout");
}

// ============================================================
// Character Ledger API
// ============================================================

export interface CharacterEntity {
  entityId: string;
  entityType: string;
  importance: "PRIMARY" | "SECONDARY" | "BACKGROUND";
  displayName: string;
  visualSignature: string;
  detailedDescription: string;
  appearsInShots: string[];
  shotCount: number;
  trackingConfidence?: string;
  visualCues?: string[];
  bindingStatus?: "BOUND" | "UNBOUND";
  boundAsset?: {
    assetId: string;
    name: string;
    imageUrl?: string;
  } | null;
}

export interface EnvironmentEntity {
  entityId: string;
  entityType: string;
  importance: "PRIMARY" | "SECONDARY";
  displayName: string;
  visualSignature: string;
  detailedDescription: string;
  appearsInShots: string[];
  shotCount: number;
  bindingStatus?: "BOUND" | "UNBOUND";
  boundAsset?: {
    assetId: string;
    name: string;
    imageUrl?: string;
  } | null;
}

export interface CharacterLedgerResponse {
  jobId: string;
  characterLedger: CharacterEntity[];
  environmentLedger: EnvironmentEntity[];
  summary: {
    totalCharacters: number;
    primaryCharacters: number;
    secondaryCharacters: number;
    totalEnvironments: number;
  };
}

/**
 * Get Character Ledger
 */
export async function getCharacterLedger(jobId: string): Promise<CharacterLedgerResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/character-ledger`);

  if (!response.ok) {
    if (response.status === 404) {
      return {
        jobId,
        characterLedger: [],
        environmentLedger: [],
        summary: {
          totalCharacters: 0,
          primaryCharacters: 0,
          secondaryCharacters: 0,
          totalEnvironments: 0,
        },
      };
    }
    const error = await response.json().catch(() => ({ detail: "Failed to fetch character ledger" }));
    throw new Error(error.detail || "Failed to fetch character ledger");
  }

  return response.json();
}

/**
 * Bind asset to entity
 */
export async function bindAssetToEntity(
  jobId: string,
  entityId: string,
  assetName: string,
  detailedDescription?: string,
  assetPath?: string
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/bind-asset`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      entityId,
      assetType: assetPath ? "uploaded" : "generated",
      assetPath: assetPath || null,
      anchorId: `anchor_${entityId}`,
      anchorName: assetName,
      detailedDescription: detailedDescription || assetName,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to bind asset" }));
    throw new Error(error.detail || "Failed to bind asset");
  }

  return response.json();
}

/**
 * Unbind asset
 */
export async function unbindAsset(
  jobId: string,
  entityId: string
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/bind-asset/${entityId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to unbind asset" }));
    throw new Error(error.detail || "Failed to unbind asset");
  }

  return response.json();
}

// ============================================================
// M5.1: Single Entity Asset Management API (Slot-level operations)
// ============================================================

export interface EntityThreeViewSlot {
  url: string | null;
  status: "empty" | "uploaded" | "generating";
}

export interface EntityState {
  jobId: string;
  anchorId: string;
  name: string;
  description: string;
  entityType: "character" | "environment";
  threeViews: {
    [key: string]: EntityThreeViewSlot;
  };
}

export interface GenerateViewsResponse {
  status: string;
  anchorId: string;
  entityType?: string;
  missingViews?: string[];
  existingViews?: string[];
  message?: string;
}

export interface GenerateViewsStatusResponse {
  anchorId: string;
  status: "not_started" | "running" | "completed" | "failed";
  started_at?: string;
  completed_at?: string;
  missing_views?: string[];
  results?: {
    [view: string]: {
      status: string;
      path: string | null;
    };
  };
  error?: string;
}

/**
 * Get single entity state (description + three slots)
 */
export async function getEntityState(jobId: string, anchorId: string): Promise<EntityState> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/entity/${anchorId}`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch entity state" }));
    throw new Error(error.detail || "Failed to fetch entity state");
  }

  return response.json();
}

/**
 * Update entity description
 */
export async function updateEntityDescription(
  jobId: string,
  anchorId: string,
  description: string
): Promise<{ status: string; anchorId: string; description: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/entity/${anchorId}/description`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ description }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to update description" }));
    throw new Error(error.detail || "Failed to update description");
  }

  return response.json();
}

/**
 * Upload image to specific slot
 */
export async function uploadEntityView(
  jobId: string,
  anchorId: string,
  view: string,
  file: File
): Promise<{ status: string; anchorId: string; view: string; filePath: string; url: string; updatedDescription?: string }> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/upload-view/${anchorId}/${view}`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to upload view" }));
    throw new Error(error.detail || "Failed to upload view");
  }

  return response.json();
}

/**
 * AI generate missing slots
 */
export async function generateEntityViews(
  jobId: string,
  anchorId: string,
  force: boolean = false
): Promise<GenerateViewsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/generate-views/${anchorId}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ force }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to generate views" }));
    throw new Error(error.detail || "Failed to generate views");
  }

  return response.json();
}

/**
 * Get generation status
 */
export async function getGenerateViewsStatus(
  jobId: string,
  anchorId: string
): Promise<GenerateViewsStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/generate-views/${anchorId}/status`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch generation status" }));
    throw new Error(error.detail || "Failed to fetch generation status");
  }

  return response.json();
}

/**
 * Poll generation status until completion
 */
export async function pollGenerateViewsStatus(
  jobId: string,
  anchorId: string,
  onUpdate: (status: GenerateViewsStatusResponse) => void,
  intervalMs: number = 3000,
  maxAttempts: number = 150  // 150 × 3s = 7.5 minutes, enough for 3 views
): Promise<GenerateViewsStatusResponse> {
  let attempts = 0;

  while (attempts < maxAttempts) {
    const status = await getGenerateViewsStatus(jobId, anchorId);
    onUpdate(status);

    if (status.status === "completed" || status.status === "failed") {
      return status;
    }

    await new Promise(resolve => setTimeout(resolve, intervalMs));
    attempts++;
  }

  throw new Error("Generation polling timeout");
}

// ============================================================
// Visual Style API (Visual style configuration)
// ============================================================

// Sound Design Types
export interface SoundDesignConfig {
  voiceStyle: string;
  voiceTone: string;
  backgroundMusic: string;
  soundEffects: string;
  enableAudioGeneration: boolean;
  confirmed: boolean;
}

export interface SoundDesignResponse {
  jobId: string;
  soundDesign: SoundDesignConfig;
}

/**
 * Get sound design configuration
 */
export async function getSoundDesign(jobId: string): Promise<SoundDesignResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/sound-design`);

  if (!response.ok) {
    if (response.status === 404) {
      return {
        jobId,
        soundDesign: {
          voiceStyle: "Natural",
          voiceTone: "Warm and friendly",
          backgroundMusic: "Upbeat, modern electronic",
          soundEffects: "Subtle, ambient",
          enableAudioGeneration: true,
          confirmed: false,
        },
      };
    }
    const error = await response.json().catch(() => ({ detail: "Failed to fetch sound design" }));
    throw new Error(error.detail || "Failed to fetch sound design");
  }

  // Backend returns config directly, wrap it in response format
  const config = await response.json();
  return {
    jobId,
    soundDesign: config,
  };
}

/**
 * Save sound design configuration
 */
export async function saveSoundDesign(
  jobId: string,
  config: Partial<SoundDesignConfig>
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/sound-design`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to save sound design" }));
    throw new Error(error.detail || "Failed to save sound design");
  }

  return response.json();
}

// Visual Style Types
export interface VisualStyleConfig {
  artStyle: string;
  colorPalette: string;
  lightingMood: string;
  cameraStyle: string;
  referenceImages: string[];
  confirmed: boolean;
}

export interface VisualStyleResponse {
  jobId: string;
  visualStyle: VisualStyleConfig;
}

/**
 * Get visual style configuration
 */
export async function getVisualStyle(jobId: string): Promise<VisualStyleResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/visual-style`);

  if (!response.ok) {
    if (response.status === 404) {
      // Return default empty config if not found
      return {
        jobId,
        visualStyle: {
          artStyle: "",
          colorPalette: "",
          lightingMood: "",
          cameraStyle: "",
          referenceImages: [],
          confirmed: false,
        },
      };
    }
    const error = await response.json().catch(() => ({ detail: "Failed to fetch visual style" }));
    throw new Error(error.detail || "Failed to fetch visual style");
  }

  return response.json();
}

/**
 * Save visual style configuration
 */
export async function saveVisualStyle(
  jobId: string,
  config: Partial<VisualStyleConfig>
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/visual-style`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to save visual style" }));
    throw new Error(error.detail || "Failed to save visual style");
  }

  return response.json();
}

/**
 * Upload visual reference image
 */
export async function uploadReferenceImage(
  jobId: string,
  file: File
): Promise<{ status: string; url: string; index: number }> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/visual-style/reference`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to upload reference image" }));
    throw new Error(error.detail || "Failed to upload reference image");
  }

  const result = await response.json();
  // Convert relative URL to full URL
  if (result.url && result.url.startsWith("/")) {
    result.url = `${API_BASE_URL}${result.url}`;
  }
  return result;
}

/**
 * Delete visual reference image
 */
export async function deleteReferenceImage(
  jobId: string,
  index: number
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/visual-style/reference/${index}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to delete reference image" }));
    throw new Error(error.detail || "Failed to delete reference image");
  }

  return response.json();
}

// ============================================================
// Product Three-Views API
// ============================================================

export interface ProductThreeViews {
  front: string | null;
  side: string | null;
  back: string | null;
}

export interface ProductAnchor {
  anchorId: string;
  name: string;
  description: string;
  threeViews: ProductThreeViews;
  status: "NOT_STARTED" | "GENERATING" | "SUCCESS" | "FAILED";
}

export interface ProductsResponse {
  jobId: string;
  products: ProductAnchor[];
}

export interface ProductStateResponse {
  jobId: string;
  anchorId: string;
  name: string;
  description: string;
  threeViews: {
    front: { url: string | null; status: string };
    side: { url: string | null; status: string };
    back: { url: string | null; status: string };
  };
  generationStatus: string;
}

export interface ProductGenerationStatusResponse {
  anchorId: string;
  status: "not_started" | "running" | "completed" | "failed";
  started_at?: string;
  completed_at?: string;
  results?: {
    [view: string]: {
      status: string;
      path: string | null;
    };
  };
  error?: string;
}

/**
 * Get all products list
 */
export async function getProducts(jobId: string): Promise<ProductsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/products`);

  if (!response.ok) {
    if (response.status === 404) {
      return { jobId, products: [] };
    }
    const error = await response.json().catch(() => ({ detail: "Failed to fetch products" }));
    throw new Error(error.detail || "Failed to fetch products");
  }

  return response.json();
}

/**
 * Create new product
 */
export async function createProduct(
  jobId: string,
  name: string,
  description: string
): Promise<{ status: string; product: ProductAnchor }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/products`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name, description }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to create product" }));
    throw new Error(error.detail || "Failed to create product");
  }

  return response.json();
}

/**
 * Update product information
 */
export async function updateProduct(
  jobId: string,
  anchorId: string,
  data: { name?: string; description?: string }
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/products/${anchorId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to update product" }));
    throw new Error(error.detail || "Failed to update product");
  }

  return response.json();
}

/**
 * Delete product
 */
export async function deleteProduct(
  jobId: string,
  anchorId: string
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/products/${anchorId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to delete product" }));
    throw new Error(error.detail || "Failed to delete product");
  }

  return response.json();
}

/**
 * Get product detailed state
 */
export async function getProductState(jobId: string, anchorId: string): Promise<ProductStateResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/products/${anchorId}`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch product state" }));
    throw new Error(error.detail || "Failed to fetch product state");
  }

  return response.json();
}

/**
 * Upload product view image
 */
export async function uploadProductView(
  jobId: string,
  anchorId: string,
  view: "front" | "side" | "back",
  file: File
): Promise<{ status: string; anchorId: string; view: string; filePath: string; url: string }> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/products/${anchorId}/upload/${view}`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to upload product view" }));
    throw new Error(error.detail || "Failed to upload product view");
  }

  const result = await response.json();
  // Convert relative URL to full URL
  if (result.url && result.url.startsWith("/")) {
    result.url = `${API_BASE_URL}${result.url}`;
  }
  return result;
}

/**
 * AI generate product three-views
 */
export async function generateProductViews(
  jobId: string,
  anchorId: string,
  force: boolean = false
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/products/${anchorId}/generate-views`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ force }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to generate product views" }));
    throw new Error(error.detail || "Failed to generate product views");
  }

  return response.json();
}

/**
 * Get product generation status (uses generic generation status endpoint)
 */
export async function getProductGenerationStatus(
  jobId: string,
  anchorId: string
): Promise<ProductGenerationStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/generate-views/${anchorId}/status`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch product generation status" }));
    throw new Error(error.detail || "Failed to fetch product generation status");
  }

  return response.json();
}

/**
 * Poll product generation status until completion
 */
export async function pollProductGenerationStatus(
  jobId: string,
  anchorId: string,
  onUpdate: (status: ProductGenerationStatusResponse) => void,
  intervalMs: number = 3000,
  maxAttempts: number = 150  // 150 × 3s = 7.5 minutes
): Promise<ProductGenerationStatusResponse> {
  let attempts = 0;

  while (attempts < maxAttempts) {
    const status = await getProductGenerationStatus(jobId, anchorId);
    onUpdate(status);

    if (status.status === "completed" || status.status === "failed") {
      return status;
    }

    await new Promise(resolve => setTimeout(resolve, intervalMs));
    attempts++;
  }

  throw new Error("Product generation polling timeout");
}

// ============================================================
// M6: Remix Storyboard API
// ============================================================

export interface RemixStoryboardShot {
  shotNumber: number;
  shotId: string;
  firstFrameImage: string;
  visualDescription: string;
  contentDescription: string;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  shotSize: string;
  cameraAngle: string;
  cameraMovement: string;
  focalLengthDepth: string;
  lighting: string;
  music: string;
  dialogueVoiceover: string;
  i2vPrompt: string;
  appliedAnchors: {
    characters: string[];
    environments: string[];
  };
}

export interface RemixStoryboardResponse {
  jobId: string;
  storyboard: RemixStoryboardShot[];
  totalDuration: number;
  remixContext: {
    identityAnchors: {
      characters: IdentityAnchor[];
      environments: IdentityAnchor[];
    };
    visualStyle: VisualStyleConfig;
    shotCount: number;
  };
}

export interface StoryboardChatResponse {
  updatedStoryboard: RemixStoryboardShot[];
  affectedShots: number[];
  response: string;
  action: "parameter_change" | "regenerate_prompt" | "info_query";
  totalDuration: number;
}

/**
 * Generate Remix Storyboard
 */
export async function generateRemixStoryboard(jobId: string): Promise<RemixStoryboardResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/generate-remix-storyboard`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to generate remix storyboard" }));
    throw new Error(error.detail || "Failed to generate remix storyboard");
  }

  return response.json();
}

/**
 * Storyboard AI Chat - modify storyboard with natural language
 */
export async function storyboardChat(
  jobId: string,
  message: string,
  currentStoryboard: RemixStoryboardShot[]
): Promise<StoryboardChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/storyboard/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      currentStoryboard,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Storyboard chat failed" }));
    throw new Error(error.detail || "Storyboard chat failed");
  }

  return response.json();
}

export interface RegenerateFramesResponse {
  jobId: string;
  regeneratedShots: RemixStoryboardShot[];
  count: number;
}

/**
 * Regenerate first frame image for specified shots
 */
export async function regenerateStoryboardFrames(
  jobId: string,
  shots: RemixStoryboardShot[]
): Promise<RegenerateFramesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/storyboard/regenerate-frames`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ shots }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Frame regeneration failed" }));
    throw new Error(error.detail || "Frame regeneration failed");
  }

  return response.json();
}


// ============================================================
// Storyboard Finalize API - Final confirmation before video generation
// ============================================================

// ============================================================
// Asset Library API — server-side persistence
// ============================================================

/**
 * Fetch all library assets, optionally filtered by type
 */
export async function fetchLibraryAssets(type?: string): Promise<any[]> {
  const url = type
    ? `${API_BASE_URL}/api/library/assets?type=${encodeURIComponent(type)}`
    : `${API_BASE_URL}/api/library/assets`;

  const response = await fetch(url);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch library assets" }));
    throw new Error(error.detail || "Failed to fetch library assets");
  }

  return response.json();
}

/**
 * Create a new library asset (id / timestamps auto-generated by backend)
 */
export async function createLibraryAsset(asset: Record<string, any>): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/api/library/assets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(asset),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to create library asset" }));
    throw new Error(error.detail || "Failed to create library asset");
  }

  return response.json();
}

/**
 * Fetch a single library asset by ID
 */
export async function fetchLibraryAsset(id: string): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/api/library/assets/${id}`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch library asset" }));
    throw new Error(error.detail || "Failed to fetch library asset");
  }

  return response.json();
}

/**
 * Update a library asset (merge fields)
 */
export async function updateLibraryAsset(id: string, updates: Record<string, any>): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/api/library/assets/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to update library asset" }));
    throw new Error(error.detail || "Failed to update library asset");
  }

  return response.json();
}

/**
 * Delete a library asset
 */
export async function deleteLibraryAsset(id: string): Promise<boolean> {
  const response = await fetch(`${API_BASE_URL}/api/library/assets/${id}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to delete library asset" }));
    throw new Error(error.detail || "Failed to delete library asset");
  }

  return true;
}

// ============================================================
// Storyboard Finalize API - Final confirmation before video generation
// ============================================================

export interface FinalizeStoryboardResponse {
  jobId: string;
  status: string;
  shotCount: number;
  framesStatus: Array<{
    shotId: string;
    frameExists: boolean;
    framePath: string | null;
  }>;
  missingFrames: string[];
  readyForVideo: boolean;
  message: string;
}

/**
 * 🎬 Final data sync before video generation
 *
 * Ensures Film IR contains all Storyboard Chat modifications
 * Must be called before starting video generation
 */
export async function finalizeStoryboard(
  jobId: string,
  storyboard: RemixStoryboardShot[]
): Promise<FinalizeStoryboardResponse> {
  const response = await fetch(`${API_BASE_URL}/api/job/${jobId}/storyboard/finalize`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ storyboard }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Storyboard finalization failed" }));
    throw new Error(error.detail || "Storyboard finalization failed");
  }

  return response.json();
}
