// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { LoudnessMeasurement } from '@/api/types'
import { notBuilt } from '@/notBuilt'

export type ScanKind = 'bitrate' | 'subtitle' | 'loudness'

/** A scan task that has not ended. */
export interface ScanRun {
  sourceId: string
  kind: ScanKind
  /** The stream it measures; `null` for a subtitle scan of every subtitle track. */
  streamIndex: number | null
  taskId: string
  /** 0..1; `null` until the task reports one. */
  progress: number | null
}

/**
 * The **Measure** scans of a source's streams: each one a cancellable server task. When a
 * bitrate or subtitle scan ends, the source is read again (`sources.reload`), so its tables
 * show the measured values.
 */
export const useScansStore = defineStore('scans', () => {
  const runs = ref<ScanRun[]>([])
  /** The last loudness measurement per `sourceId:streamIndex` (the source does not keep it). */
  const loudness = ref<Record<string, LoudnessMeasurement>>({})

  /** The run of this scan, if one is going. A subtitle scan of every track has no stream. */
  function running(
    sourceId: string,
    kind: ScanKind,
    streamIndex: number | null = null,
  ): ScanRun | undefined {
    return notBuilt('scans.running', sourceId, kind, streamIndex)
  }

  async function measureBitrate(sourceId: string, streamIndex: number): Promise<void> {
    return notBuilt('scans.measureBitrate', sourceId, streamIndex)
  }

  /** Counts events and forced events; `streamIndexes` omitted: every subtitle track. */
  async function scanSubtitles(sourceId: string, streamIndexes?: number[]): Promise<void> {
    return notBuilt('scans.scanSubtitles', sourceId, streamIndexes)
  }

  /** `null` when the scan failed or was cancelled (the failure is a toast). */
  async function measureLoudness(
    sourceId: string,
    streamIndex: number,
  ): Promise<LoudnessMeasurement | null> {
    return notBuilt('scans.measureLoudness', sourceId, streamIndex)
  }

  async function cancel(run: ScanRun): Promise<void> {
    return notBuilt('scans.cancel', run)
  }

  return { runs, loudness, running, measureBitrate, scanSubtitles, measureLoudness, cancel }
})
