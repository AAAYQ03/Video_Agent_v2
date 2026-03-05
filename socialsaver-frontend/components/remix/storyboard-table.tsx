"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card" // Card used for empty state
import { Button } from "@/components/ui/button"
import { FolderOpen, Trash2 } from "lucide-react"
import { SaveToLibraryDialog } from "@/components/save-to-library-dialog"
import { saveShotToLibrary } from "@/lib/asset-storage"
import type { StoryboardShot } from "@/lib/types/remix"

// API base URL for image loading
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface StoryboardTableProps {
  data: StoryboardShot[]
  title?: string
  showSaveButtons?: boolean
  onDeleteShot?: (shotNumber: number) => void
}

export function StoryboardTable({ data, title = "Storyboard Breakdown", showSaveButtons = true, onDeleteShot }: StoryboardTableProps) {
  // Format time to avoid floating point precision issues
  const formatTime = (seconds: number): string => {
    if (seconds === undefined || seconds === null) return "-"
    return `${Math.round(seconds * 10) / 10}s`
  }

  // Safe string accessor that handles N/A and empty values
  const safeStr = (val: any): string => {
    if (!val || val === "N/A" || val === "n/a" || val === "NA") return "-"
    return String(val)
  }

  // Clean description text: remove placeholders like [PROTAGONIST_A & B] and leading "Static. "
  const cleanDesc = (val: any): string => {
    const s = safeStr(val)
    if (s === "-") return s
    return s
      .replace(/\s*\[[^\]]*\]\s*/g, " ")   // Remove [PROTAGONIST_A & B] etc.
      .replace(/^Static\.\s*/i, "")          // Remove leading "Static. "
      .trim()
  }

  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [selectedShot, setSelectedShot] = useState<StoryboardShot | null>(null)

  const handleSaveShot = (shot: StoryboardShot) => {
    setSelectedShot(shot)
    setSaveDialogOpen(true)
  }

  const handleSaveToLibrary = async (name: string, tags: string[]) => {
    if (!selectedShot) return
    await saveShotToLibrary(name, tags, selectedShot)
  }

  // Handle undefined or empty data
  if (!data || data.length === 0) {
    return (
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-center py-8">No storyboard data available</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <div className="w-full">
        {/* Card Header - Title only */}
        <div className="bg-card border border-border border-b-0 rounded-t-xl px-6 py-4 flex items-center justify-between">
          <h3 className="text-foreground font-semibold leading-none">{title}</h3>
          <span className="text-xs text-muted-foreground">← Scroll horizontally →</span>
        </div>
        {/* Horizontal scroll container - Independent from Card Header to ensure scrollability */}
        <div
          className="border border-border rounded-b-xl bg-card pb-4 storyboard-scroll"
          style={{
            overflowX: 'scroll',
            overflowY: 'visible',
            WebkitOverflowScrolling: 'touch',
          }}
        >
          <table className="border-collapse text-sm w-max">
            <colgroup>
              <col style={{width: "40px"}} />
              <col style={{width: "160px"}} />
              <col style={{width: "280px"}} />
              <col style={{width: "280px"}} />
              <col style={{width: "130px"}} />
              <col style={{width: "100px"}} />
              <col style={{width: "100px"}} />
              <col style={{width: "100px"}} />
              <col style={{width: "150px"}} />
              <col style={{width: "200px"}} />
              <col style={{width: "220px"}} />
              <col style={{width: "220px"}} />
              {showSaveButtons && <col style={{width: "60px"}} />}
              {onDeleteShot && <col style={{width: "60px"}} />}
            </colgroup>
              <thead>
                <tr className="border-b border-border bg-secondary/30">
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">#</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">Frame</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">frame_description</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">content_analysis</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">Time</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">shot_type</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">camera_angle</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">camera_movement</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">focus_and_depth</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">lighting</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">music_and_sound</th>
                  <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">voiceover</th>
                  {showSaveButtons && (
                    <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">Save</th>
                  )}
                  {onDeleteShot && (
                    <th className="text-muted-foreground text-left p-3 font-medium whitespace-nowrap">Delete</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {data.map((shot) => (
                  <tr key={shot.shotNumber} className="border-b border-border hover:bg-secondary/20">
                    {/* shot_number */}
                    <td className="text-foreground font-medium p-3 align-top">{shot.shotNumber}</td>
                    {/* Frame Image - Larger preview */}
                    <td className="p-2 align-top">
                      <div className="w-36 bg-secondary rounded flex items-center justify-center text-xs text-muted-foreground overflow-hidden">
                        {shot.firstFrameImage ? (
                          <img
                            src={shot.firstFrameImage.startsWith("http") ? shot.firstFrameImage : `${API_BASE_URL}${shot.firstFrameImage}`}
                            alt={`Shot ${shot.shotNumber}`}
                            className="w-full h-auto object-contain rounded"
                            onError={(e) => {
                              (e.target as HTMLImageElement).style.display = 'none'
                            }}
                          />
                        ) : (
                          "-"
                        )}
                      </div>
                    </td>
                    {/* frame_description (Visual Description) */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "250px"}}>
                      <div className="break-words whitespace-normal text-xs">{cleanDesc(shot.visualDescription)}</div>
                    </td>
                    {/* content_analysis (Content Description) */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "250px"}}>
                      <div className="break-words whitespace-normal text-xs">{cleanDesc(shot.contentDescription)}</div>
                    </td>
                    {/* Time: start_time / end_time / duration_seconds */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "130px"}}>
                      <div className="text-xs">
                        <div>Start: {formatTime(shot.startSeconds)}</div>
                        <div>End: {formatTime(shot.endSeconds)}</div>
                        <div className="text-muted-foreground">Dur: {formatTime(shot.durationSeconds)}</div>
                      </div>
                    </td>
                    {/* shot_type */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "100px"}}>
                      <div className="break-words whitespace-normal text-xs">{safeStr(shot.shotType || shot.shotSize)}</div>
                    </td>
                    {/* camera_angle */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "100px"}}>
                      <div className="break-words whitespace-normal text-xs">{safeStr(shot.cameraAngle)}</div>
                    </td>
                    {/* camera_movement */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "100px"}}>
                      <div className="break-words whitespace-normal text-xs">{safeStr(shot.cameraMovement)}</div>
                    </td>
                    {/* focus_and_depth */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "140px"}}>
                      <div className="break-words whitespace-normal text-xs">{safeStr(shot.focusAndDepth || shot.focalLengthDepth)}</div>
                    </td>
                    {/* lighting */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "180px"}}>
                      <div className="break-words whitespace-normal text-xs">{safeStr(shot.lighting)}</div>
                    </td>
                    {/* music_and_sound */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "200px"}}>
                      <div className="break-words whitespace-normal text-xs">
                        {safeStr(shot.musicAndSound) !== "-" ? safeStr(shot.musicAndSound) : (
                          <>
                            {safeStr(shot.soundDesign) !== "-" && safeStr(shot.soundDesign)}
                            {safeStr(shot.soundDesign) !== "-" && safeStr(shot.music) !== "-" && " | "}
                            {safeStr(shot.music) !== "-" && safeStr(shot.music)}
                            {safeStr(shot.soundDesign) === "-" && safeStr(shot.music) === "-" && "-"}
                          </>
                        )}
                      </div>
                    </td>
                    {/* voiceover */}
                    <td className="text-foreground p-3 align-top" style={{minWidth: "200px"}}>
                      <div className="break-words whitespace-normal text-xs">
                        {safeStr(shot.voiceover) !== "-" ? safeStr(shot.voiceover) : safeStr(shot.dialogueVoiceover)}
                        {shot.dialogueText && shot.dialogueText !== "-" && (
                          <div className="text-muted-foreground italic mt-1">"{shot.dialogueText}"</div>
                        )}
                      </div>
                    </td>
                    {showSaveButtons && (
                      <td className="p-3 align-top">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleSaveShot(shot)}
                          className="h-8 px-2 text-accent hover:text-accent hover:bg-accent/10"
                        >
                          <FolderOpen className="w-4 h-4" />
                        </Button>
                      </td>
                    )}
                    {onDeleteShot && (
                      <td className="p-3 align-top">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onDeleteShot(shot.shotNumber)}
                          className="h-8 px-2 text-red-500 hover:text-red-600 hover:bg-red-500/10"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      {selectedShot && (
        <SaveToLibraryDialog
          open={saveDialogOpen}
          onOpenChange={setSaveDialogOpen}
          assetType="storyboard"
          defaultName={`Shot ${selectedShot.shotNumber} - ${selectedShot.visualDescription?.slice(0, 30) || "Untitled"}...`}
          onSave={handleSaveToLibrary}
        />
      )}
    </>
  )
}
