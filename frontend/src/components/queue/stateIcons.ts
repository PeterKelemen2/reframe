import {
  Ban,
  CircleAlert,
  CircleCheck,
  CirclePause,
  CirclePlay,
  CircleX,
  Clock,
  Info,
  LoaderCircle,
  TriangleAlert,
} from '@lucide/vue'
import type { Component } from 'vue'

import type { JobState } from '@/api/types'
import type { StatusTone } from '@/components/base/types'

/** A job state's icon; its colour is the state's tone (`STATE_TONE`). */
export const STATE_ICON: Record<JobState, Component> = {
  waiting: Clock,
  running: LoaderCircle,
  paused: CirclePause,
  done: CircleCheck,
  failed: CircleX,
  cancelled: Ban,
  interrupted: CircleAlert,
}

/** An activity line's icon by its tone: what happened, not what is under way. */
export const TONE_ICON: Record<StatusTone, Component> = {
  ok: CircleCheck,
  busy: CirclePlay,
  warn: TriangleAlert,
  error: CircleX,
  off: Info,
}
