import type { ScriptText } from './scriptText'

/**
 * Findings of `findScriptText` in the code base that are not fixed yet, one entry per finding
 * (the line is left out: it moves). The check fails on a finding that is not here and on an
 * entry that no longer happens, so the list only shrinks.
 */
export const ALLOWED_SCRIPT_TEXT: Omit<ScriptText, 'line'>[] = [
  // Shell and pages.
  {
    file: '/src/components/queue/QueueTable.vue',
    where: 'number',
    text: 'data.live.percent.toFixed(1)',
  },
  { file: '/src/components/queue/format.ts', where: 'number', text: 'progress.fps.toFixed(1)' },
  { file: '/src/components/queue/format.ts', where: 'number', text: 'progress.speed.toFixed(2)' },
  // Picture and video.
  {
    file: '/src/components/summary/SourceCard.vue',
    where: 'joined',
    text: "[ t('summary.source.audioTracks', media.audio?.length ?? 0), t('summary.source.subtitleTracks', media.subtitles?.length ?? 0), ].join(' · ')",
  },
  {
    file: '/src/components/summary/format.ts',
    where: 'number',
    text: '(bytes / KIB ** 2).toFixed(1)',
  },
  {
    file: '/src/components/summary/format.ts',
    where: 'number',
    text: '(bytes / KIB ** 3).toFixed(2)',
  },
  {
    file: '/src/components/summary/format.ts',
    where: 'number',
    text: '(bitsPerSecond / 1_000_000).toFixed(1)',
  },
  { file: '/src/components/media/streams.ts', where: 'number', text: '(size / 1000).toFixed(3)' },
  // Tracks and batch.
  {
    file: '/src/components/tracks/AudioTrackRow.vue',
    where: 'number',
    text: 'track.drc.toFixed(1)',
  },
]
