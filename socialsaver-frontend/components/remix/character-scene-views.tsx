"use client"

import React from "react"

import { useState, useRef, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  User,
  MapPin,
  Upload,
  Check,
  X,
  ImageIcon,
  CheckCircle,
  Sparkles,
  Loader2,
  Music,
  Palette,
  Package,
  AlertTriangle,
  Pencil
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { CharacterView, SceneView, StoryThemeAnalysis } from "@/lib/types/remix"

// Sound Design State
interface SoundDesign {
  voiceStyle: string
  voiceTone: string
  backgroundMusic: string
  soundEffects: string
  voiceSampleUrl?: string
  musicSampleUrl?: string
}

// Visual Style State
interface VisualStyle {
  artStyle: string
  colorPalette: string
  lightingMood: string
  cameraStyle: string
  referenceImages: string[]
}

// Product View
interface ProductView {
  id: string
  name: string
  description: string
  frontView?: string
  sideView?: string
  backView?: string
  confirmed: boolean
}
import {
  uploadEntityView,
  updateEntityDescription,
  generateEntityViews,
  pollGenerateViewsStatus,
  getEntityState,
  type EntityState,
  // Sound Design APIs
  getSoundDesign,
  saveSoundDesign,
  type SoundDesignConfig,
  // Visual Style APIs
  getVisualStyle,
  saveVisualStyle,
  uploadReferenceImage,
  deleteReferenceImage,
  // Product APIs
  getProducts,
  createProduct,
  updateProduct,
  deleteProduct,
  uploadProductView,
  generateProductViews,
  pollProductGenerationStatus,
  getProductState,
  type VisualStyleConfig,
  type ProductAnchor,
  getAssetUrl,
} from "@/lib/api"

// Character/Environment Entity from Character Ledger (Video Analysis)
interface LedgerEntity {
  entityId: string;
  entityType: string;
  importance: "PRIMARY" | "SECONDARY" | "BACKGROUND";
  displayName: string;
  visualSignature: string;
  detailedDescription: string;
  appearsInShots: string[];
  shotCount: number;
}

// Identity Anchor from Remix (overrides)
interface IdentityAnchor {
  anchorId: string;
  anchorName?: string;
  name?: string;
  detailedDescription?: string;
  originalPlaceholder?: string;  // Maps to original entityId
  styleAdaptation?: string;
  atmosphericConditions?: string;
}

// Storyboard shot info for looking up original frames and scene extraction
interface StoryboardShotInfo {
  shotNumber: number
  shotId?: string
  firstFrameImage: string
  // Scene description fields (for fallback scene extraction)
  contentDescription?: string
  visualDescription?: string
  scene?: string  // Direct scene description from concrete shots
}

interface CharacterSceneViewsProps {
  jobId: string
  // Data from Video Analysis (Character Ledger) - provides complete list
  characterLedger: LedgerEntity[]
  environmentLedger: LedgerEntity[]
  // Data from Remix (Identity Anchors) - provides overrides
  characterAnchors: IdentityAnchor[]
  environmentAnchors: IdentityAnchor[]
  characters: CharacterView[]
  scenes: SceneView[]
  // Storyboard data for looking up original frames
  storyboard?: StoryboardShotInfo[]
  onCharactersChange: (characters: CharacterView[]) => void
  onScenesChange: (scenes: SceneView[]) => void
  onConfirm: () => void
  onBack: () => void
}

// Sound Design Section Component
function SoundDesignSection({
  soundDesign,
  onSoundDesignChange,
  onConfirm,
  onCancel,
  isConfirmed,
  onEdit,
}: {
  soundDesign: SoundDesign
  onSoundDesignChange: (updates: Partial<SoundDesign>) => void
  onConfirm: () => void
  onCancel: () => void
  isConfirmed: boolean
  onEdit: () => void
}) {
  const voiceSampleRef = useRef<HTMLInputElement>(null)
  const musicSampleRef = useRef<HTMLInputElement>(null)

  const handleVoiceSampleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      const url = URL.createObjectURL(file)
      onSoundDesignChange({ voiceSampleUrl: url })
    }
  }

  const handleMusicSampleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      const url = URL.createObjectURL(file)
      onSoundDesignChange({ musicSampleUrl: url })
    }
  }

  // Confirmed read-only view
  if (isConfirmed) {
    return (
      <div className="space-y-4">
        {/* Title outside card */}
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
            <Music className="w-5 h-5 text-accent" />
            Sound Design
            <CheckCircle className="w-4 h-4 text-accent" />
          </h3>
          <Button
            variant="ghost"
            size="icon"
            onClick={onEdit}
            className="h-8 w-8 text-muted-foreground hover:text-accent hover:bg-accent/10"
          >
            <Pencil className="w-4 h-4" />
          </Button>
        </div>
        <Card className="bg-card border-accent">
          <CardContent className="p-6">
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Voice Style</p>
                <p className="text-sm text-foreground">{soundDesign.voiceStyle || "-"}</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Voice Tone</p>
                <p className="text-sm text-foreground">{soundDesign.voiceTone || "-"}</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Background Music</p>
                <p className="text-sm text-foreground">{soundDesign.backgroundMusic || "-"}</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Sound Effects</p>
                <p className="text-sm text-foreground">{soundDesign.soundEffects || "-"}</p>
              </div>
            </div>
            {/* Placeholder to match Visual Style height */}
            <div className="h-12"></div>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Edit mode
  return (
    <div className="space-y-4">
      {/* Title outside card */}
      <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
        <Music className="w-5 h-5 text-accent" />
        Sound Design
      </h3>
      <Card className="bg-card border-border">
        <CardContent className="p-6">

        <div className="grid grid-cols-2 gap-4 mb-4">
          {/* Voice Style */}
          <div className="space-y-2">
            <Label htmlFor="voiceStyle" className="text-sm text-muted-foreground">Voice Style</Label>
            <Input
              id="voiceStyle"
              value={soundDesign.voiceStyle}
              onChange={(e) => onSoundDesignChange({ voiceStyle: e.target.value })}
              placeholder="Natural"
              className="bg-secondary border-border"
            />
          </div>

          {/* Voice Tone */}
          <div className="space-y-2">
            <Label htmlFor="voiceTone" className="text-sm text-muted-foreground">Voice Tone</Label>
            <Input
              id="voiceTone"
              value={soundDesign.voiceTone}
              onChange={(e) => onSoundDesignChange({ voiceTone: e.target.value })}
              placeholder="Warm and friendly"
              className="bg-secondary border-border"
            />
          </div>

          {/* Background Music */}
          <div className="space-y-2">
            <Label htmlFor="backgroundMusic" className="text-sm text-muted-foreground">Background Music</Label>
            <Input
              id="backgroundMusic"
              value={soundDesign.backgroundMusic}
              onChange={(e) => onSoundDesignChange({ backgroundMusic: e.target.value })}
              placeholder="Upbeat, modern electronic"
              className="bg-secondary border-border"
            />
          </div>

          {/* Sound Effects */}
          <div className="space-y-2">
            <Label htmlFor="soundEffects" className="text-sm text-muted-foreground">Sound Effects</Label>
            <Input
              id="soundEffects"
              value={soundDesign.soundEffects}
              onChange={(e) => onSoundDesignChange({ soundEffects: e.target.value })}
              placeholder="Subtle, ambient"
              className="bg-secondary border-border"
            />
          </div>
        </div>

        {/* Sample Uploads */}
        <div className="grid grid-cols-2 gap-4 mb-4">
          {/* Voice Sample */}
          <div className="space-y-2">
            <Label className="text-sm text-muted-foreground">Voice Sample (optional)</Label>
            <div
              onClick={() => voiceSampleRef.current?.click()}
              className={cn(
                "border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-all",
                soundDesign.voiceSampleUrl
                  ? "border-accent bg-accent/10"
                  : "border-border hover:border-accent hover:bg-secondary/50"
              )}
            >
              {soundDesign.voiceSampleUrl ? (
                <div className="flex items-center justify-center gap-2">
                  <CheckCircle className="w-4 h-4 text-accent" />
                  <span className="text-sm text-accent">Audio uploaded</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1">
                  <Upload className="w-5 h-5 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">Upload sample</span>
                </div>
              )}
              <input
                ref={voiceSampleRef}
                type="file"
                accept="audio/*"
                onChange={handleVoiceSampleUpload}
                className="hidden"
              />
            </div>
          </div>

          {/* Music Sample */}
          <div className="space-y-2">
            <Label className="text-sm text-muted-foreground">Music Sample (optional)</Label>
            <div
              onClick={() => musicSampleRef.current?.click()}
              className={cn(
                "border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-all",
                soundDesign.musicSampleUrl
                  ? "border-accent bg-accent/10"
                  : "border-border hover:border-accent hover:bg-secondary/50"
              )}
            >
              {soundDesign.musicSampleUrl ? (
                <div className="flex items-center justify-center gap-2">
                  <CheckCircle className="w-4 h-4 text-accent" />
                  <span className="text-sm text-accent">Audio uploaded</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1">
                  <Upload className="w-5 h-5 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">Upload sample</span>
                </div>
              )}
              <input
                ref={musicSampleRef}
                type="file"
                accept="audio/*"
                onChange={handleMusicSampleUpload}
                className="hidden"
              />
            </div>
          </div>
        </div>

        {/* Confirm / Cancel Buttons */}
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={onCancel}
            className="border-border text-foreground hover:bg-secondary bg-transparent"
          >
            <X className="w-4 h-4 mr-2" />
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={onConfirm}
            className="bg-accent text-accent-foreground hover:bg-accent/90"
          >
            <Check className="w-4 h-4 mr-1" />
            Confirm
          </Button>
        </div>
      </CardContent>
    </Card>
    </div>
  )
}

// Visual Style Section Component
function VisualStyleSection({
  jobId,
  visualStyle,
  onVisualStyleChange,
  onConfirm,
  onCancel,
  isConfirmed,
  onEdit,
}: {
  jobId: string
  visualStyle: VisualStyle
  onVisualStyleChange: (updates: Partial<VisualStyle>) => void
  onConfirm: () => void
  onCancel: () => void
  isConfirmed: boolean
  onEdit: () => void
}) {
  const referenceInputRef = useRef<HTMLInputElement>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  const handleReferenceUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      setIsUploading(true)
      try {
        const newUrls: string[] = []
        for (const file of Array.from(files)) {
          const result = await uploadReferenceImage(jobId, file)
          newUrls.push(result.url)
        }
        onVisualStyleChange({
          referenceImages: [...visualStyle.referenceImages, ...newUrls]
        })
      } catch (error) {
        console.error("Failed to upload reference images:", error)
      } finally {
        setIsUploading(false)
      }
    }
    if (referenceInputRef.current) {
      referenceInputRef.current.value = ""
    }
  }

  const removeReferenceImage = async (index: number) => {
    try {
      await deleteReferenceImage(jobId, index)
    } catch (error) {
      console.error("Failed to delete reference image:", error)
    }
    const newImages = visualStyle.referenceImages.filter((_, i) => i !== index)
    onVisualStyleChange({ referenceImages: newImages })
  }

  const handleConfirmClick = async () => {
    setIsSaving(true)
    try {
      await saveVisualStyle(jobId, {
        artStyle: visualStyle.artStyle,
        colorPalette: visualStyle.colorPalette,
        lightingMood: visualStyle.lightingMood,
        cameraStyle: visualStyle.cameraStyle,
        referenceImages: visualStyle.referenceImages,
        confirmed: true,
      })
      onConfirm()
    } catch (error) {
      console.error("Failed to save visual style:", error)
    } finally {
      setIsSaving(false)
    }
  }

  // Confirmed read-only view
  if (isConfirmed) {
    return (
      <div className="space-y-4">
        {/* Title outside card */}
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
            <Palette className="w-5 h-5 text-accent" />
            Visual Style
            <CheckCircle className="w-4 h-4 text-accent" />
          </h3>
          <Button
            variant="ghost"
            size="icon"
            onClick={onEdit}
            className="h-8 w-8 text-muted-foreground hover:text-accent hover:bg-accent/10"
          >
            <Pencil className="w-4 h-4" />
          </Button>
        </div>
        <Card className="bg-card border-accent">
          <CardContent className="p-6">
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Art Style</p>
                <p className="text-sm text-foreground">{visualStyle.artStyle || "-"}</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Color Palette</p>
                <p className="text-sm text-foreground">{visualStyle.colorPalette || "-"}</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Lighting Mood</p>
                <p className="text-sm text-foreground">{visualStyle.lightingMood || "-"}</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Camera Style</p>
                <p className="text-sm text-foreground">{visualStyle.cameraStyle || "-"}</p>
              </div>
            </div>
            {/* Show reference images in read-only */}
            {visualStyle.referenceImages.length > 0 ? (
              <div className="flex flex-wrap gap-2 h-12">
                {visualStyle.referenceImages.map((url, index) => (
                  <img
                    key={index}
                    src={url}
                    alt={`Reference ${index + 1}`}
                    className="w-12 h-12 object-cover rounded border border-border"
                  />
                ))}
              </div>
            ) : (
              <div className="h-12"></div>
            )}
          </CardContent>
        </Card>
      </div>
    )
  }

  // Edit mode
  return (
    <div className="space-y-4">
      {/* Title outside card */}
      <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
        <Palette className="w-5 h-5 text-accent" />
        Visual Style
      </h3>
      <Card className="bg-card border-border">
        <CardContent className="p-6">

        <div className="grid grid-cols-2 gap-4 mb-4">
          {/* Art Style */}
          <div className="space-y-2">
            <Label htmlFor="artStyle" className="text-sm text-muted-foreground">Art Style</Label>
            <Input
              id="artStyle"
              value={visualStyle.artStyle}
              onChange={(e) => onVisualStyleChange({ artStyle: e.target.value })}
              placeholder="Realistic"
              className="bg-secondary border-border"
            />
          </div>

          {/* Color Palette */}
          <div className="space-y-2">
            <Label htmlFor="colorPalette" className="text-sm text-muted-foreground">Color Palette</Label>
            <Input
              id="colorPalette"
              value={visualStyle.colorPalette}
              onChange={(e) => onVisualStyleChange({ colorPalette: e.target.value })}
              placeholder="Warm tones with high contrast"
              className="bg-secondary border-border"
            />
          </div>

          {/* Lighting Mood */}
          <div className="space-y-2">
            <Label htmlFor="lightingMood" className="text-sm text-muted-foreground">Lighting Mood</Label>
            <Input
              id="lightingMood"
              value={visualStyle.lightingMood}
              onChange={(e) => onVisualStyleChange({ lightingMood: e.target.value })}
              placeholder="Natural daylight"
              className="bg-secondary border-border"
            />
          </div>

          {/* Camera Style */}
          <div className="space-y-2">
            <Label htmlFor="cameraStyle" className="text-sm text-muted-foreground">Camera Style</Label>
            <Input
              id="cameraStyle"
              value={visualStyle.cameraStyle}
              onChange={(e) => onVisualStyleChange({ cameraStyle: e.target.value })}
              placeholder="Dynamic with smooth transitions"
              className="bg-secondary border-border"
            />
          </div>
        </div>

        {/* Reference Images */}
        <div className="space-y-2 mb-4">
          <Label className="text-sm text-muted-foreground">Reference Images (optional)</Label>
          <div className="flex flex-wrap gap-2">
            {visualStyle.referenceImages.map((url, index) => (
              <div key={index} className="relative group">
                <img
                  src={url}
                  alt={`Reference ${index + 1}`}
                  className="w-20 h-20 object-cover rounded-lg border border-border"
                />
                <button
                  type="button"
                  onClick={() => removeReferenceImage(index)}
                  className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
            {/* Add button */}
            <div
              onClick={() => referenceInputRef.current?.click()}
              className="w-20 h-20 border-2 border-dashed border-border rounded-lg flex flex-col items-center justify-center cursor-pointer hover:border-accent hover:bg-secondary/50 transition-all"
            >
              <span className="text-2xl text-muted-foreground">+</span>
              <span className="text-xs text-muted-foreground">Add</span>
            </div>
            <input
              ref={referenceInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={handleReferenceUpload}
              className="hidden"
            />
          </div>
        </div>

        {/* Confirm / Cancel Buttons */}
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={isSaving}
            className="border-border text-foreground hover:bg-secondary bg-transparent"
          >
            <X className="w-4 h-4 mr-2" />
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleConfirmClick}
            disabled={isSaving}
            className="bg-accent text-accent-foreground hover:bg-accent/90"
          >
            {isSaving ? (
              <>
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Check className="w-4 h-4 mr-1" />
                Confirm
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
    </div>
  )
}

// Product Card Component
function ProductCard({
  jobId,
  product,
  onUpdate,
  onDelete,
  onNameChange,
}: {
  jobId: string
  product: ProductView
  onUpdate: (updates: Partial<ProductView>) => void
  onDelete: () => void
  onNameChange: (name: string) => Promise<void>
}) {
  const [isGenerating, setIsGenerating] = useState(false)
  const [uploadingView, setUploadingView] = useState<string | null>(null)
  const [localDescription, setLocalDescription] = useState(product.description)
  const [localName, setLocalName] = useState(product.name)
  const [isSavingDescription, setIsSavingDescription] = useState(false)

  useEffect(() => {
    setLocalDescription(product.description)
  }, [product.description])

  useEffect(() => {
    setLocalName(product.name)
  }, [product.name])

  const handleImageUpload = async (view: 'front' | 'side' | 'back', file: File) => {
    setUploadingView(view)
    try {
      const result = await uploadProductView(jobId, product.id, view, file)
      const viewMap: Record<string, string> = {
        front: 'frontView',
        side: 'sideView',
        back: 'backView'
      }
      onUpdate({ [viewMap[view]]: result.url })
    } catch (error) {
      console.error("Upload failed:", error)
    } finally {
      setUploadingView(null)
    }
  }

  const handleDescriptionBlur = async () => {
    if (localDescription !== product.description) {
      setIsSavingDescription(true)
      try {
        await updateProduct(jobId, product.id, { description: localDescription })
        onUpdate({ description: localDescription })
      } catch (error) {
        console.error("Failed to save description:", error)
      } finally {
        setIsSavingDescription(false)
      }
    }
  }

  const handleNameBlur = async () => {
    if (localName !== product.name && localName.trim()) {
      try {
        await onNameChange(localName)
      } catch (error) {
        console.error("Failed to save name:", error)
        setLocalName(product.name) // Revert on error
      }
    }
  }

  const handleAIGenerate = async (forceRegenerate: boolean = false) => {
    setIsGenerating(true)
    try {
      // Save description first
      if (localDescription !== product.description) {
        await updateProduct(jobId, product.id, { description: localDescription })
        onUpdate({ description: localDescription })
      }

      // Trigger AI generation
      await generateProductViews(jobId, product.id, forceRegenerate)

      // Poll for completion
      await pollProductGenerationStatus(
        jobId,
        product.id,
        (status) => {
          console.log("Product generation status:", status.status)
        },
        3000,
        40
      )

      // Fetch updated state
      const updatedState = await getProductState(jobId, product.id)
      const cacheBuster = `?t=${Date.now()}`
      onUpdate({
        frontView: updatedState.threeViews.front?.url ? updatedState.threeViews.front.url + cacheBuster : undefined,
        sideView: updatedState.threeViews.side?.url ? updatedState.threeViews.side.url + cacheBuster : undefined,
        backView: updatedState.threeViews.back?.url ? updatedState.threeViews.back.url + cacheBuster : undefined,
        confirmed: true
      })
    } catch (error) {
      console.error("AI generation failed:", error)
    } finally {
      setIsGenerating(false)
    }
  }

  const handleConfirm = () => {
    onUpdate({ confirmed: true })
  }

  const allViewsFilled = product.frontView && product.sideView && product.backView

  return (
    <Card className={cn(
      "bg-card border-border transition-all",
      product.confirmed && "border-accent"
    )}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Package className="w-5 h-5 text-accent" />
            {product.confirmed ? (
              <span className="text-base font-semibold text-foreground">{localName}</span>
            ) : (
              <Input
                value={localName}
                onChange={(e) => setLocalName(e.target.value)}
                onBlur={handleNameBlur}
                placeholder="Product Name"
                className="bg-transparent border-none p-0 h-auto text-base font-semibold focus-visible:ring-0"
                disabled={isGenerating}
              />
            )}
            {product.confirmed && <CheckCircle className="w-4 h-4 text-accent" />}
          </div>
          <div className="flex items-center gap-1">
            {product.confirmed && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onUpdate({ confirmed: false })}
                className="h-8 w-8 text-muted-foreground hover:text-accent hover:bg-accent/10"
              >
                <Pencil className="w-4 h-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={onDelete}
              className="h-8 w-8 text-muted-foreground hover:text-red-500"
            >
              <X className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Three View Slots */}
        <div className="flex justify-between gap-3 px-2">
          <ViewUploadSlot
            label="Front"
            imageUrl={product.frontView}
            isLoading={uploadingView === 'front'}
            disabled={isGenerating || product.confirmed}
            onUpload={(file) => handleImageUpload('front', file)}
          />
          <ViewUploadSlot
            label="Side"
            imageUrl={product.sideView}
            isLoading={uploadingView === 'side'}
            disabled={isGenerating || product.confirmed}
            onUpload={(file) => handleImageUpload('side', file)}
          />
          <ViewUploadSlot
            label="Back"
            imageUrl={product.backView}
            isLoading={uploadingView === 'back'}
            disabled={isGenerating || product.confirmed}
            onUpload={(file) => handleImageUpload('back', file)}
          />
        </div>

        {/* Description */}
        {product.confirmed ? (
          <div className="text-sm text-muted-foreground">
            {localDescription || "No description available."}
          </div>
        ) : (
          <Textarea
            value={localDescription}
            onChange={(e) => setLocalDescription(e.target.value)}
            onBlur={handleDescriptionBlur}
            placeholder="Product description for AI generation..."
            className="bg-secondary border-border text-foreground min-h-[80px] text-sm"
            disabled={isGenerating}
          />
        )}

        {/* Action Buttons - only show when not confirmed */}
        {!product.confirmed && (
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleAIGenerate(!!allViewsFilled)}
              disabled={isGenerating || !localDescription.trim()}
              className="border-accent text-accent hover:bg-accent/10 bg-transparent"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4 mr-1" />
                  AI Generate
                </>
              )}
            </Button>
            <Button
              size="sm"
              onClick={handleConfirm}
              className="bg-accent text-accent-foreground hover:bg-accent/90"
            >
              <Check className="w-4 h-4 mr-1" />
              Confirm
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// Product Three-Views Section
function ProductThreeViewsSection({
  jobId,
  products,
  onProductsChange,
}: {
  jobId: string
  products: ProductView[]
  onProductsChange: (products: ProductView[]) => void
}) {
  const [isAdding, setIsAdding] = useState(false)

  const addProductHandler = async () => {
    setIsAdding(true)
    try {
      const result = await createProduct(jobId, "New Product", "")
      const newProduct: ProductView = {
        id: result.product.anchorId,
        name: result.product.name,
        description: result.product.description || "",
        confirmed: false,
      }
      onProductsChange([...products, newProduct])
    } catch (error) {
      console.error("Failed to create product:", error)
    } finally {
      setIsAdding(false)
    }
  }

  const updateProductLocal = (id: string, updates: Partial<ProductView>) => {
    onProductsChange(
      products.map((p) => (p.id === id ? { ...p, ...updates } : p))
    )
  }

  const updateProductName = async (id: string, name: string) => {
    await updateProduct(jobId, id, { name })
    updateProductLocal(id, { name })
  }

  const deleteProductHandler = async (id: string) => {
    try {
      await deleteProduct(jobId, id)
      onProductsChange(products.filter((p) => p.id !== id))
    } catch (error) {
      console.error("Failed to delete product:", error)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
          <Package className="w-5 h-5 text-accent" />
          Product Three-Views
          <span className="text-sm font-normal text-muted-foreground">
            ({products.filter(p => p.confirmed).length}/{products.length} confirmed)
          </span>
        </h3>
        <Button
          variant="outline"
          size="sm"
          onClick={addProductHandler}
          disabled={isAdding}
          className="border-accent text-accent hover:bg-accent/10 bg-transparent"
        >
          {isAdding ? (
            <>
              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              Adding...
            </>
          ) : (
            <>
              <Package className="w-4 h-4 mr-1" />
              Add Product
            </>
          )}
        </Button>
      </div>

      {products.length === 0 ? (
        <Card className="bg-card border-border border-dashed">
          <CardContent className="py-8 flex flex-col items-center justify-center text-center">
            <Package className="w-12 h-12 text-muted-foreground mb-3" />
            <p className="text-muted-foreground">No products added yet</p>
            <Button
              variant="outline"
              size="sm"
              onClick={addProductHandler}
              disabled={isAdding}
              className="mt-4 border-accent text-accent hover:bg-accent/10 bg-transparent"
            >
              {isAdding ? "Adding..." : "Add First Product"}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {products.map((product) => (
            <ProductCard
              key={product.id}
              jobId={jobId}
              product={product}
              onUpdate={(updates) => updateProductLocal(product.id, updates)}
              onDelete={() => deleteProductHandler(product.id)}
              onNameChange={(name) => updateProductName(product.id, name)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ViewUploadSlot({
  label,
  imageUrl,
  isLoading,
  onUpload,
  disabled,
  compact
}: {
  label: string
  imageUrl?: string | null
  isLoading?: boolean
  onUpload: (file: File) => void
  disabled?: boolean
  compact?: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleClick = () => {
    if (!disabled && !isLoading) {
      inputRef.current?.click()
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      onUpload(file)
    }
    if (inputRef.current) {
      inputRef.current.value = ""
    }
  }

  return (
    <div className={cn("flex flex-col items-center gap-1", compact ? "flex-1" : "flex-1")}>
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled || isLoading}
        className={cn(
          "rounded-lg border-2 border-dashed flex flex-col items-center justify-center transition-all",
          compact
            ? "w-full h-24 min-w-[70px]"
            : "w-full aspect-[3/4] min-w-[100px] max-w-[160px]",
          imageUrl
            ? "border-accent bg-accent/10 p-0"
            : "border-border hover:border-accent hover:bg-secondary/50",
          (disabled || isLoading) && "opacity-50 cursor-not-allowed"
        )}
      >
        {isLoading ? (
          <Loader2 className={cn("text-accent animate-spin", compact ? "w-5 h-5" : "w-8 h-8")} />
        ) : imageUrl ? (
          <img
            src={imageUrl}
            alt={label}
            className="w-full h-full object-cover rounded-lg"
          />
        ) : (
          <Upload className={cn("text-muted-foreground", compact ? "w-5 h-5" : "w-8 h-8")} />
        )}
      </button>
      <span className={cn("text-muted-foreground font-medium", compact ? "text-xs" : "text-sm")}>{label}</span>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        onChange={handleChange}
        className="hidden"
      />
    </div>
  )
}

function CharacterCard({
  jobId,
  anchorId,
  character,
  originalShotImage,
  onUpdate,
}: {
  jobId: string
  anchorId: string
  character: CharacterView
  originalShotImage?: string
  onUpdate: (updates: Partial<CharacterView>) => void
}) {
  const [isGenerating, setIsGenerating] = useState(false)
  const [uploadingView, setUploadingView] = useState<string | null>(null)
  const [isSavingDescription, setIsSavingDescription] = useState(false)
  const [localDescription, setLocalDescription] = useState(character.description)

  // Sync local description when character changes
  useEffect(() => {
    setLocalDescription(character.description)
  }, [character.description])

  const handleImageUpload = async (view: 'front' | 'side' | 'back', file: File) => {
    setUploadingView(view)
    try {
      const result = await uploadEntityView(jobId, anchorId, view, file)
      const viewMap: Record<string, string> = {
        front: 'frontView',
        side: 'sideView',
        back: 'backView'
      }
      const updates: Partial<CharacterView> = { [viewMap[view]]: result.url }
      // Auto-update description to match the uploaded image
      if (result.updatedDescription) {
        updates.description = result.updatedDescription
        setLocalDescription(result.updatedDescription)
      }
      onUpdate(updates)
    } catch (error) {
      console.error("Upload failed:", error)
    } finally {
      setUploadingView(null)
    }
  }

  const handleDescriptionBlur = async () => {
    if (localDescription !== character.description) {
      setIsSavingDescription(true)
      try {
        await updateEntityDescription(jobId, anchorId, localDescription)
        onUpdate({ description: localDescription })
      } catch (error) {
        console.error("Failed to save description:", error)
      } finally {
        setIsSavingDescription(false)
      }
    }
  }

  const handleAIGenerate = async (forceRegenerate: boolean = false) => {
    setIsGenerating(true)
    try {
      await updateEntityDescription(jobId, anchorId, localDescription)
      onUpdate({ description: localDescription })

      const result = await generateEntityViews(jobId, anchorId, forceRegenerate)

      if (result.status === "already_complete" && !forceRegenerate) {
        onUpdate({ confirmed: true })
        setIsGenerating(false)
        return
      }

      await pollGenerateViewsStatus(
        jobId,
        anchorId,
        (status) => {
          console.log("Generation status:", status.status)
        },
        3000,
        40
      )

      const updatedState = await getEntityState(jobId, anchorId)
      const cacheBuster = `?t=${Date.now()}`
      onUpdate({
        frontView: updatedState.threeViews.front?.url ? updatedState.threeViews.front.url + cacheBuster : undefined,
        sideView: updatedState.threeViews.side?.url ? updatedState.threeViews.side.url + cacheBuster : undefined,
        backView: updatedState.threeViews.back?.url ? updatedState.threeViews.back.url + cacheBuster : undefined,
        confirmed: true
      })
    } catch (error) {
      console.error("AI generation failed:", error)
    } finally {
      setIsGenerating(false)
    }
  }

  const handleConfirm = () => {
    onUpdate({ confirmed: true })
  }

  const allViewsFilled = character.frontView && character.sideView && character.backView

  return (
    <Card className={cn(
      "bg-card border-border transition-all",
      character.confirmed && "border-accent"
    )}>
      {/* Header: Icon + Name + CheckCircle (if confirmed) + Edit button (if confirmed) */}
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <User className="w-5 h-5 text-accent" />
            <CardTitle className="text-base text-foreground">{character.name}</CardTitle>
            {character.confirmed && <CheckCircle className="w-4 h-4 text-accent" />}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground font-mono">{anchorId}</span>
            {character.confirmed && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onUpdate({ confirmed: false })}
                className="h-8 w-8 text-muted-foreground hover:text-accent hover:bg-accent/10"
              >
                <Pencil className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Two-Column Layout: Original Shot + Three Views */}
        <div className="flex gap-4">
          {/* Left Column: ORIGINAL SHOT */}
          <div className="flex-shrink-0">
            <p className="text-xs text-muted-foreground mb-2 font-medium">ORIGINAL SHOT</p>
            <div className="relative w-40 bg-secondary rounded-lg overflow-hidden">
              {originalShotImage ? (
                <img
                  src={originalShotImage}
                  alt={`Original shot of ${character.name}`}
                  className="w-full h-auto object-contain"
                  onError={(e) => { (e.currentTarget.parentElement as HTMLElement).innerHTML = '<div class="w-full h-full flex items-center justify-center text-muted-foreground"><svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg></div>' }}
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                  <ImageIcon className="w-8 h-8" />
                </div>
              )}
            </div>
          </div>

          {/* Right Column: AI THREE-VIEWS */}
          <div className="flex-1">
            <p className="text-xs text-muted-foreground mb-2 font-medium">AI THREE-VIEWS</p>
            <div className="flex gap-2">
              <ViewUploadSlot
                label="Front"
                imageUrl={character.frontView}
                isLoading={uploadingView === 'front'}
                disabled={isGenerating || character.confirmed}
                onUpload={(file) => handleImageUpload('front', file)}
                compact
              />
              <ViewUploadSlot
                label="Side"
                imageUrl={character.sideView}
                isLoading={uploadingView === 'side'}
                disabled={isGenerating || character.confirmed}
                onUpload={(file) => handleImageUpload('side', file)}
                compact
              />
              <ViewUploadSlot
                label="Back"
                imageUrl={character.backView}
                isLoading={uploadingView === 'back'}
                disabled={isGenerating || character.confirmed}
                onUpload={(file) => handleImageUpload('back', file)}
                compact
              />
            </div>
          </div>
        </div>

        {/* Description */}
        {character.confirmed ? (
          <div className="text-sm text-muted-foreground">
            {localDescription || "No description available."}
          </div>
        ) : (
          <Textarea
            value={localDescription}
            onChange={(e) => setLocalDescription(e.target.value)}
            onBlur={handleDescriptionBlur}
            placeholder="Character description for AI generation..."
            className="bg-secondary border-border text-foreground min-h-[80px] text-sm"
            disabled={isGenerating}
          />
        )}

        {/* Action Buttons - only show when not confirmed */}
        {!character.confirmed && (
          <div className="flex justify-end gap-2 pt-2 border-t border-border">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleAIGenerate(!!allViewsFilled)}
              disabled={isGenerating || !localDescription.trim()}
              className="border-accent text-accent hover:bg-accent/10 bg-transparent"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4 mr-1" />
                  AI Generate
                </>
              )}
            </Button>
            <Button
              size="sm"
              onClick={handleConfirm}
              className="bg-accent text-accent-foreground hover:bg-accent/90"
            >
              <Check className="w-4 h-4 mr-1" />
              Confirm
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SceneCard({
  jobId,
  anchorId,
  scene,
  originalShotImage,
  onUpdate,
}: {
  jobId: string
  anchorId: string
  scene: SceneView
  originalShotImage?: string
  onUpdate: (updates: Partial<SceneView>) => void
}) {
  const [isGenerating, setIsGenerating] = useState(false)
  const [uploadingView, setUploadingView] = useState<string | null>(null)
  const [isSavingDescription, setIsSavingDescription] = useState(false)
  const [localDescription, setLocalDescription] = useState(scene.description)

  useEffect(() => {
    setLocalDescription(scene.description)
  }, [scene.description])

  const handleImageUpload = async (view: 'wide' | 'detail' | 'alt', file: File) => {
    setUploadingView(view)
    try {
      const result = await uploadEntityView(jobId, anchorId, view, file)
      const viewMap: Record<string, string> = {
        wide: 'establishingShot',
        detail: 'detailView',
        alt: 'alternateAngle'
      }
      const updates: Partial<SceneView> = { [viewMap[view]]: result.url }
      // Auto-update description to match the uploaded image
      if (result.updatedDescription) {
        updates.description = result.updatedDescription
        setLocalDescription(result.updatedDescription)
      }
      onUpdate(updates)
    } catch (error) {
      console.error("Upload failed:", error)
    } finally {
      setUploadingView(null)
    }
  }

  const handleDescriptionBlur = async () => {
    if (localDescription !== scene.description) {
      setIsSavingDescription(true)
      try {
        await updateEntityDescription(jobId, anchorId, localDescription)
        onUpdate({ description: localDescription })
      } catch (error) {
        console.error("Failed to save description:", error)
      } finally {
        setIsSavingDescription(false)
      }
    }
  }

  const handleAIGenerate = async (forceRegenerate: boolean = false) => {
    setIsGenerating(true)
    try {
      await updateEntityDescription(jobId, anchorId, localDescription)
      onUpdate({ description: localDescription })

      const result = await generateEntityViews(jobId, anchorId, forceRegenerate)

      if (result.status === "already_complete" && !forceRegenerate) {
        onUpdate({ confirmed: true })
        setIsGenerating(false)
        return
      }

      await pollGenerateViewsStatus(
        jobId,
        anchorId,
        (status) => {
          console.log("Generation status:", status.status)
        },
        3000,
        40
      )

      const updatedState = await getEntityState(jobId, anchorId)
      const cacheBuster = `?t=${Date.now()}`
      onUpdate({
        establishingShot: updatedState.threeViews.wide?.url ? updatedState.threeViews.wide.url + cacheBuster : undefined,
        detailView: updatedState.threeViews.detail?.url ? updatedState.threeViews.detail.url + cacheBuster : undefined,
        alternateAngle: updatedState.threeViews.alt?.url ? updatedState.threeViews.alt.url + cacheBuster : undefined,
        confirmed: true
      })
    } catch (error) {
      console.error("AI generation failed:", error)
    } finally {
      setIsGenerating(false)
    }
  }

  const handleConfirm = () => {
    onUpdate({ confirmed: true })
  }

  const allViewsFilled = scene.establishingShot && scene.detailView && scene.alternateAngle

  return (
    <Card className={cn(
      "bg-card border-border transition-all",
      scene.confirmed && "border-accent"
    )}>
      {/* Header: Icon + Name + CheckCircle (if confirmed) + Edit button (if confirmed) */}
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MapPin className="w-5 h-5 text-accent" />
            <CardTitle className="text-base text-foreground">{scene.name}</CardTitle>
            {scene.confirmed && <CheckCircle className="w-4 h-4 text-accent" />}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground font-mono">{anchorId}</span>
            {scene.confirmed && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onUpdate({ confirmed: false })}
                className="h-8 w-8 text-muted-foreground hover:text-accent hover:bg-accent/10"
              >
                <Pencil className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Two-Column Layout: Original Shot + Three Views */}
        <div className="flex gap-4">
          {/* Left Column: ORIGINAL SHOT */}
          <div className="flex-shrink-0">
            <p className="text-xs text-muted-foreground mb-2 font-medium">ORIGINAL SHOT</p>
            <div className="relative w-40 bg-secondary rounded-lg overflow-hidden">
              {originalShotImage ? (
                <img
                  src={originalShotImage}
                  alt={`Original shot of ${scene.name}`}
                  className="w-full h-auto object-contain"
                  onError={(e) => { (e.currentTarget.parentElement as HTMLElement).innerHTML = '<div class="w-full h-full flex items-center justify-center text-muted-foreground"><svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg></div>' }}
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                  <ImageIcon className="w-8 h-8" />
                </div>
              )}
            </div>
          </div>

          {/* Right Column: AI THREE-VIEWS */}
          <div className="flex-1">
            <p className="text-xs text-muted-foreground mb-2 font-medium">AI THREE-VIEWS</p>
            <div className="flex gap-2">
              <ViewUploadSlot
                label="Front"
                imageUrl={scene.establishingShot}
                isLoading={uploadingView === 'wide'}
                disabled={isGenerating || scene.confirmed}
                onUpload={(file) => handleImageUpload('wide', file)}
                compact
              />
              <ViewUploadSlot
                label="Side"
                imageUrl={scene.detailView}
                isLoading={uploadingView === 'detail'}
                disabled={isGenerating || scene.confirmed}
                onUpload={(file) => handleImageUpload('detail', file)}
                compact
              />
              <ViewUploadSlot
                label="Back"
                imageUrl={scene.alternateAngle}
                isLoading={uploadingView === 'alt'}
                disabled={isGenerating || scene.confirmed}
                onUpload={(file) => handleImageUpload('alt', file)}
                compact
              />
            </div>
          </div>
        </div>

        {/* Description */}
        {scene.confirmed ? (
          <div className="text-sm text-muted-foreground">
            {localDescription || "No description available."}
          </div>
        ) : (
          <Textarea
            value={localDescription}
            onChange={(e) => setLocalDescription(e.target.value)}
            onBlur={handleDescriptionBlur}
            placeholder="Scene description for AI generation..."
            className="bg-secondary border-border text-foreground min-h-[80px] text-sm"
            disabled={isGenerating}
          />
        )}

        {/* Action Buttons - only show when not confirmed */}
        {!scene.confirmed && (
          <div className="flex justify-end gap-2 pt-2 border-t border-border">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleAIGenerate(!!allViewsFilled)}
              disabled={isGenerating || !localDescription.trim()}
              className="border-accent text-accent hover:bg-accent/10 bg-transparent"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4 mr-1" />
                  AI Generate
                </>
              )}
            </Button>
            <Button
              size="sm"
              onClick={handleConfirm}
              className="bg-accent text-accent-foreground hover:bg-accent/90"
            >
              <Check className="w-4 h-4 mr-1" />
              Confirm
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function CharacterSceneViews({
  jobId,
  characterLedger,
  environmentLedger,
  characterAnchors,
  environmentAnchors,
  characters,
  scenes,
  storyboard,
  onCharactersChange,
  onScenesChange,
  onConfirm,
  onBack,
}: CharacterSceneViewsProps) {
  // Helper function to get original shot image for an entity
  const getOriginalShotImage = (entityId: string, entityType: 'character' | 'environment'): string | undefined => {
    // Find entity in ledger to get appearsInShots
    const ledger = entityType === 'character' ? characterLedger : environmentLedger

    // Try to find entity by exact ID match first
    let entity = ledger.find(e => e.entityId === entityId)

    // If not found, try to match by converting ID formats:
    // - "env_01" -> "orig_env_01" (remix anchors -> original ledger)
    // - "char_01" -> "orig_char_01"
    if (!entity) {
      const prefix = entityType === 'character' ? 'char' : 'env'
      const numMatch = entityId.match(/(\d+)$/)
      if (numMatch) {
        const origId = `orig_${prefix}_${numMatch[1].padStart(2, '0')}`
        entity = ledger.find(e => e.entityId === origId)
      }
    }

    // Also try matching by index if entity has format like "env_01" and ledger has "orig_env_01"
    if (!entity && entityId.match(/^(char|env)_\d+$/)) {
      const numMatch = entityId.match(/(\d+)$/)
      if (numMatch) {
        const num = parseInt(numMatch[1])
        // Find entity at the same index position (1-indexed)
        if (num > 0 && num <= ledger.length) {
          entity = ledger[num - 1]
        }
      }
    }

    if (!entity || !entity.appearsInShots || entity.appearsInShots.length === 0) {
      return undefined
    }

    // Get first shot ID where entity appears
    const firstShotId = entity.appearsInShots[0]

    // Find corresponding frame image from storyboard
    if (storyboard && storyboard.length > 0) {
      // Try to match by shotId first
      const matchByShot = storyboard.find(s =>
        s.shotId === firstShotId ||
        `shot_${String(s.shotNumber).padStart(2, '0')}` === firstShotId
      )
      if (matchByShot?.firstFrameImage) {
        return matchByShot.firstFrameImage
      }

      // Try to extract shot number and match
      const shotNumMatch = firstShotId.match(/(\d+)/)
      if (shotNumMatch) {
        const shotNum = parseInt(shotNumMatch[1])
        const matchByNum = storyboard.find(s => s.shotNumber === shotNum)
        if (matchByNum?.firstFrameImage) {
          return matchByNum.firstFrameImage
        }
      }
    }

    // Fallback: construct URL directly from shot ID (handles storyboard cache miss)
    return getAssetUrl(jobId, `frames/${firstShotId}.png`)
  }

  // Sound Design State
  const [soundDesign, setSoundDesign] = useState<SoundDesign>({
    voiceStyle: "Natural",
    voiceTone: "Warm and friendly",
    backgroundMusic: "Upbeat, modern electronic",
    soundEffects: "Subtle, ambient",
  })
  const [soundDesignConfirmed, setSoundDesignConfirmed] = useState(false)
  const [soundDesignEditing, setSoundDesignEditing] = useState(true)

  // Visual Style State
  const [visualStyle, setVisualStyle] = useState<VisualStyle>({
    artStyle: "Realistic",
    colorPalette: "Warm tones with high contrast",
    lightingMood: "Natural daylight",
    cameraStyle: "Dynamic with smooth transitions",
    referenceImages: [],
  })
  const [visualStyleConfirmed, setVisualStyleConfirmed] = useState(false)
  const [visualStyleEditing, setVisualStyleEditing] = useState(true)

  // Products State
  const [products, setProducts] = useState<ProductView[]>([])

  const handleSoundDesignChange = (updates: Partial<SoundDesign>) => {
    setSoundDesign((prev) => ({ ...prev, ...updates }))
    // Reset confirmation when changes are made
    setSoundDesignConfirmed(false)
  }

  const handleVisualStyleChange = (updates: Partial<VisualStyle>) => {
    setVisualStyle((prev) => ({ ...prev, ...updates }))
    // Reset confirmation when changes are made
    setVisualStyleConfirmed(false)
  }

  // Sound Design confirm/cancel/edit handlers
  const handleSoundDesignConfirm = async () => {
    // Save to backend
    try {
      await saveSoundDesign(jobId, {
        voiceStyle: soundDesign.voiceStyle,
        voiceTone: soundDesign.voiceTone,
        backgroundMusic: soundDesign.backgroundMusic,
        soundEffects: soundDesign.soundEffects,
        enableAudioGeneration: true,  // Enable audio generation by default
        confirmed: true,
      })
      setSoundDesignConfirmed(true)
      setSoundDesignEditing(false)
      console.log("Sound design saved:", soundDesign)
    } catch (error) {
      console.error("Failed to save sound design:", error)
    }
  }

  const handleSoundDesignCancel = () => {
    // Clear uploaded samples
    setSoundDesign((prev) => ({
      ...prev,
      voiceSampleUrl: undefined,
      musicSampleUrl: undefined,
    }))
  }

  const handleSoundDesignEdit = () => {
    setSoundDesignEditing(true)
    setSoundDesignConfirmed(false)
  }

  // Visual Style confirm/cancel/edit handlers
  const handleVisualStyleConfirm = () => {
    setVisualStyleConfirmed(true)
    setVisualStyleEditing(false)
    console.log("Visual style confirmed:", visualStyle)
  }

  const handleVisualStyleCancel = () => {
    // Clear uploaded reference images
    setVisualStyle((prev) => ({
      ...prev,
      referenceImages: [],
    }))
  }

  const handleVisualStyleEdit = () => {
    setVisualStyleEditing(true)
    setVisualStyleConfirmed(false)
  }

  // Load Sound Design from backend
  useEffect(() => {
    const loadSoundDesign = async () => {
      try {
        const response = await getSoundDesign(jobId)
        if (response.soundDesign) {
          setSoundDesign({
            voiceStyle: response.soundDesign.voiceStyle || "Natural",
            voiceTone: response.soundDesign.voiceTone || "Warm and friendly",
            backgroundMusic: response.soundDesign.backgroundMusic || "Upbeat, modern electronic",
            soundEffects: response.soundDesign.soundEffects || "Subtle, ambient",
          })
          setSoundDesignConfirmed(response.soundDesign.confirmed || false)
          if (response.soundDesign.confirmed) {
            setSoundDesignEditing(false)
          }
        }
      } catch (error) {
        console.error("Failed to load sound design:", error)
      }
    }
    if (jobId) {
      loadSoundDesign()
    }
  }, [jobId])

  // Load Visual Style from backend
  useEffect(() => {
    const loadVisualStyle = async () => {
      try {
        const response = await getVisualStyle(jobId)
        if (response.visualStyle) {
          setVisualStyle({
            artStyle: response.visualStyle.artStyle || "",
            colorPalette: response.visualStyle.colorPalette || "",
            lightingMood: response.visualStyle.lightingMood || "",
            cameraStyle: response.visualStyle.cameraStyle || "",
            referenceImages: response.visualStyle.referenceImages || [],
          })
          setVisualStyleConfirmed(response.visualStyle.confirmed || false)
        }
      } catch (error) {
        console.error("Failed to load visual style:", error)
      }
    }
    if (jobId) {
      loadVisualStyle()
    }
  }, [jobId])

  // Load Products from backend
  useEffect(() => {
    const loadProducts = async () => {
      try {
        const response = await getProducts(jobId)
        if (response.products && response.products.length > 0) {
          const loadedProducts: ProductView[] = response.products.map((p: ProductAnchor) => ({
            id: p.anchorId,
            name: p.name,
            description: p.description,
            frontView: p.threeViews.front || undefined,
            sideView: p.threeViews.side || undefined,
            backView: p.threeViews.back || undefined,
            confirmed: p.status === "SUCCESS",
          }))
          setProducts(loadedProducts)
        }
      } catch (error) {
        console.error("Failed to load products:", error)
      }
    }
    if (jobId) {
      loadProducts()
    }
  }, [jobId])

  // Initialize characters: Priority order:
  // 1. If characterAnchors exist (from remix), use them directly (they contain the remix-modified data)
  // 2. Otherwise, fall back to characterLedger (original video analysis data)
  useEffect(() => {
    // 🔍 DEBUG: Log all relevant state for troubleshooting
    console.log("🔍 [Character Init] State check:", {
      "characters.length": characters.length,
      "characterAnchors.length": characterAnchors.length,
      "characterLedger.length": characterLedger.length,
      "characterAnchors": characterAnchors.map(a => ({ id: a.anchorId, name: a.anchorName })),
      "characterLedger": characterLedger.map(e => ({ id: e.entityId, name: e.displayName, type: e.entityType }))
    })

    if (characters.length === 0) {
      let initialChars: CharacterView[] = []

      // Priority 1: Use characterAnchors if available (remix data with modifications)
      if (characterAnchors.length > 0) {
        console.log("📋 Initializing characters from remix anchors:", characterAnchors.length)
        initialChars = characterAnchors.map((anchor) => ({
          id: anchor.anchorId,
          name: anchor.anchorName || anchor.name || "Unknown Character",
          description: anchor.detailedDescription || "",
          frontView: undefined,
          sideView: undefined,
          backView: undefined,
          confirmed: false,
        }))
      }
      // Priority 2: Fall back to characterLedger if no anchors
      else if (characterLedger.length > 0) {
        console.log("📋 Initializing characters from ledger (no anchors):", characterLedger.length)
        // 🔍 Verify entityType to ensure we only get CHARACTER entities
        const validCharacters = characterLedger.filter(entity =>
          entity.entityType === "CHARACTER" || entity.entityId?.startsWith("orig_char_")
        )
        console.log("📋 Filtered valid characters:", validCharacters.length)

        initialChars = validCharacters.map((entity) => ({
          id: entity.entityId,
          name: entity.displayName,
          description: entity.detailedDescription || entity.visualSignature || "",
          frontView: undefined,
          sideView: undefined,
          backView: undefined,
          confirmed: false,
        }))
      }

      if (initialChars.length > 0) {
        console.log("📋 Setting characters:", initialChars.map(c => ({ id: c.id, name: c.name })))
        onCharactersChange(initialChars)
      } else {
        console.log("📋 No characters to initialize")
      }
    } else {
      console.log("📋 Characters already initialized, skipping:", characters.length)
    }
  }, [characterLedger, characterAnchors, characters.length, onCharactersChange])

  // Initialize scenes using a two-tier approach:
  // 1. Primary: Use environmentLedger from video analysis (already deduplicated)
  // 2. Fallback: Extract scenes from storyboard shots and deduplicate by similarity
  useEffect(() => {
    if (scenes.length === 0) {
      console.log("📋 Initializing scenes...")
      console.log("   - environmentLedger:", environmentLedger.length, "environments")
      console.log("   - environmentAnchors:", environmentAnchors.length, "anchors")
      console.log("   - storyboard:", storyboard?.length || 0, "shots")

      let initialScenes: SceneView[] = []

      // Create a lookup map for anchors by ID (try multiple ID formats)
      const anchorMap = new Map<string, IdentityAnchor>()
      environmentAnchors.forEach(anchor => {
        anchorMap.set(anchor.anchorId, anchor)
        // Also map by extracted number: "env_01" -> also accessible via "orig_env_01"
        const numMatch = anchor.anchorId.match(/(\d+)$/)
        if (numMatch) {
          anchorMap.set(`orig_env_${numMatch[1].padStart(2, '0')}`, anchor)
        }
      })

      // TIER 1: Use environmentLedger if available
      if (environmentLedger.length > 0) {
        console.log("📋 Using environmentLedger as primary source")
        initialScenes = environmentLedger.map((entity, index) => {
          // Try to find corresponding anchor
          const anchor = anchorMap.get(entity.entityId) || anchorMap.get(`env_${String(index + 1).padStart(2, '0')}`)

          if (anchor) {
            // Use anchor data (remix modified)
            let description = anchor.detailedDescription || entity.detailedDescription || entity.visualSignature || ""
            if (anchor.styleAdaptation) {
              description = description ? `${description}\n\nStyle: ${anchor.styleAdaptation}` : `Style: ${anchor.styleAdaptation}`
            }
            if (anchor.atmosphericConditions) {
              description = description ? `${description}\n\nAtmosphere: ${anchor.atmosphericConditions}` : `Atmosphere: ${anchor.atmosphericConditions}`
            }

            return {
              id: entity.entityId,
              name: anchor.anchorName || anchor.name || entity.displayName,
              description: description.trim(),
              establishingShot: undefined,
              detailView: undefined,
              alternateAngle: undefined,
              confirmed: false,
            }
          } else {
            return {
              id: entity.entityId,
              name: entity.displayName,
              description: entity.detailedDescription || entity.visualSignature || "",
              establishingShot: undefined,
              detailView: undefined,
              alternateAngle: undefined,
              confirmed: false,
            }
          }
        })
      }
      // TIER 2: Fallback - extract from storyboard and deduplicate
      else if (storyboard && storyboard.length > 0) {
        console.log("📋 Using storyboard as fallback source")

        // Extract scene info from each shot
        interface SceneInfo {
          shotNumber: number
          description: string
          image: string
        }

        const shotScenes: SceneInfo[] = storyboard.map(shot => ({
          shotNumber: shot.shotNumber,
          // Priority: scene > contentDescription > visualDescription > fallback
          description: shot.scene || shot.contentDescription || shot.visualDescription || `Scene from Shot ${shot.shotNumber}`,
          image: shot.firstFrameImage
        }))

        // Simple deduplication: group shots with very similar descriptions
        // For now, each shot is its own scene (user can merge later if needed)
        // A smarter approach would use AI to compare scene similarity
        const uniqueScenes = new Map<string, SceneInfo>()

        shotScenes.forEach((scene, index) => {
          // Simple heuristic: first 50 chars of description as key
          // This will group very similar scenes together
          const key = scene.description.slice(0, 50).toLowerCase().trim()

          // Keep the first occurrence of each unique scene
          if (!uniqueScenes.has(key)) {
            uniqueScenes.set(key, scene)
          }
        })

        initialScenes = Array.from(uniqueScenes.values()).map((scene, index) => {
          const sceneId = `scene_${String(index + 1).padStart(2, '0')}`
          const anchor = anchorMap.get(sceneId)

          return {
            id: sceneId,
            name: anchor?.anchorName || anchor?.name || `Scene ${index + 1}`,
            description: anchor?.detailedDescription || scene.description,
            establishingShot: undefined,
            detailView: undefined,
            alternateAngle: undefined,
            confirmed: false,
          }
        })
      }

      if (initialScenes.length > 0) {
        console.log("📋 Initialized", initialScenes.length, "scenes")
        onScenesChange(initialScenes)
      } else {
        console.log("📋 No scenes to initialize (no data available)")
      }
    }
  }, [environmentLedger, environmentAnchors, storyboard, scenes.length, onScenesChange])

  const updateCharacter = (id: string, updates: Partial<CharacterView>) => {
    onCharactersChange(
      characters.map((c) => (c.id === id ? { ...c, ...updates } : c))
    )
  }

  const updateScene = (id: string, updates: Partial<SceneView>) => {
    onScenesChange(
      scenes.map((s) => (s.id === id ? { ...s, ...updates } : s))
    )
  }

  const allConfirmed =
    characters.length > 0 &&
    characters.every((c) => c.confirmed) &&
    (scenes.length === 0 || scenes.every((s) => s.confirmed))

  const hasAnyContent = characters.length > 0 || scenes.length > 0

  // Confirmation Dialog State
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)

  // Calculate what has been modified (has three-views generated)
  const getModificationStatus = () => {
    const modifiedCharacters = characters.filter(c => c.frontView || c.sideView || c.backView)
    const unmodifiedCharacters = characters.filter(c => !c.frontView && !c.sideView && !c.backView)
    const modifiedScenes = scenes.filter(s => s.establishingShot || s.detailView || s.alternateAngle)
    const unmodifiedScenes = scenes.filter(s => !s.establishingShot && !s.detailView && !s.alternateAngle)
    const modifiedProducts = products.filter(p => p.frontView || p.sideView || p.backView)
    const unmodifiedProducts = products.filter(p => !p.frontView && !p.sideView && !p.backView)

    const totalModified = modifiedCharacters.length + modifiedScenes.length + modifiedProducts.length
    const totalUnmodified = unmodifiedCharacters.length + unmodifiedScenes.length + unmodifiedProducts.length

    return {
      modifiedCharacters,
      unmodifiedCharacters,
      modifiedScenes,
      unmodifiedScenes,
      modifiedProducts,
      unmodifiedProducts,
      totalModified,
      totalUnmodified,
      hasUnmodified: totalUnmodified > 0
    }
  }

  const handleGenerateStoryboard = () => {
    const status = getModificationStatus()
    if (status.hasUnmodified) {
      setShowConfirmDialog(true)
    } else {
      onConfirm()
    }
  }

  const handleConfirmAndGenerate = () => {
    setShowConfirmDialog(false)
    onConfirm()
  }

  return (
    <div className="space-y-8">
      {/* Introduction */}
      <Card className="bg-accent/10 border-accent">
        <CardContent className="py-4">
          <p className="text-sm text-foreground">
            Configure sound design, visual style, and three-view reference images for your remix.
            Customize audio settings, visual aesthetics, and upload or AI-generate character, scene, and product assets.
          </p>
        </CardContent>
      </Card>

      {/* Sound Design & Visual Style - Side by Side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {/* Sound Design Section */}
        <SoundDesignSection
          soundDesign={soundDesign}
          onSoundDesignChange={handleSoundDesignChange}
          onConfirm={handleSoundDesignConfirm}
          onCancel={handleSoundDesignCancel}
          isConfirmed={soundDesignConfirmed && !soundDesignEditing}
          onEdit={handleSoundDesignEdit}
        />

        {/* Visual Style Section */}
        <VisualStyleSection
          jobId={jobId}
          visualStyle={visualStyle}
          onVisualStyleChange={handleVisualStyleChange}
          onConfirm={handleVisualStyleConfirm}
          onCancel={handleVisualStyleCancel}
          isConfirmed={visualStyleConfirmed && !visualStyleEditing}
          onEdit={handleVisualStyleEdit}
        />
      </div>

      {/* Characters Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
            <User className="w-5 h-5 text-accent" />
            Character Three-Views
            <span className="text-sm font-normal text-muted-foreground">
              ({characters.filter(c => c.confirmed).length}/{characters.length} confirmed)
            </span>
          </h3>
        </div>

        {characters.length === 0 ? (
          <Card className="bg-card border-border border-dashed">
            <CardContent className="py-8 flex flex-col items-center justify-center text-center">
              <User className="w-12 h-12 text-muted-foreground mb-3" />
              <p className="text-muted-foreground">No characters from remix</p>
              <p className="text-xs text-muted-foreground mt-1">
                Characters will appear here after remix script generation
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {characters.map((character) => (
              <CharacterCard
                key={character.id}
                jobId={jobId}
                anchorId={character.id}
                character={character}
                originalShotImage={getOriginalShotImage(character.id, 'character')}
                onUpdate={(updates) => updateCharacter(character.id, updates)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Scenes Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
            <MapPin className="w-5 h-5 text-accent" />
            Scene Three-Views
            <span className="text-sm font-normal text-muted-foreground">
              ({scenes.filter(s => s.confirmed).length}/{scenes.length} confirmed)
            </span>
          </h3>
        </div>

        {scenes.length === 0 ? (
          <Card className="bg-card border-border border-dashed">
            <CardContent className="py-8 flex flex-col items-center justify-center text-center">
              <MapPin className="w-12 h-12 text-muted-foreground mb-3" />
              <p className="text-muted-foreground">No scenes from remix</p>
              <p className="text-xs text-muted-foreground mt-1">
                Scenes will appear here after remix script generation
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {scenes.map((scene) => (
              <SceneCard
                key={scene.id}
                jobId={jobId}
                anchorId={scene.id}
                scene={scene}
                originalShotImage={getOriginalShotImage(scene.id, 'environment')}
                onUpdate={(updates) => updateScene(scene.id, updates)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Product Three-Views Section */}
      <ProductThreeViewsSection
        jobId={jobId}
        products={products}
        onProductsChange={setProducts}
      />

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t border-border">
        <Button
          variant="outline"
          onClick={onBack}
          className="border-border text-foreground hover:bg-secondary bg-transparent"
        >
          Back to Script
        </Button>
        <div className="flex-1" />
        <Button
          onClick={handleGenerateStoryboard}
          className="bg-accent text-accent-foreground hover:bg-accent/90"
        >
          <Sparkles className="w-4 h-4 mr-2" />
          Generate Storyboard
        </Button>
      </div>

      {/* Confirmation Dialog for Unmodified Assets */}
      <Dialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-yellow-500" />
              Some Assets Not Modified
            </DialogTitle>
            <DialogDescription asChild>
              <div className="text-left pt-2 text-sm text-muted-foreground">
                {(() => {
                  const status = getModificationStatus()
                  const unmodifiedItems: string[] = []
                  if (status.unmodifiedCharacters.length > 0) {
                    unmodifiedItems.push(`${status.unmodifiedCharacters.length} character(s)`)
                  }
                  if (status.unmodifiedScenes.length > 0) {
                    unmodifiedItems.push(`${status.unmodifiedScenes.length} scene(s)`)
                  }
                  if (status.unmodifiedProducts.length > 0) {
                    unmodifiedItems.push(`${status.unmodifiedProducts.length} product(s)`)
                  }
                  return (
                    <>
                      <div className="mb-2">
                        The following assets have not been modified:
                      </div>
                      <ul className="list-disc list-inside mb-3 text-foreground">
                        {unmodifiedItems.map((item, idx) => (
                          <li key={idx}>{item}</li>
                        ))}
                      </ul>
                      <div className="text-yellow-600 dark:text-yellow-400 font-medium">
                        Unmodified assets will reference the original video content.
                      </div>
                    </>
                  )
                })()}
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col sm:flex-row gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setShowConfirmDialog(false)}
              className="border-border text-foreground hover:bg-secondary bg-transparent"
            >
              Cancel
            </Button>
            <Button
              onClick={handleConfirmAndGenerate}
              className="bg-accent text-accent-foreground hover:bg-accent/90"
            >
              <Check className="w-4 h-4 mr-2" />
              Confirm and Generate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
