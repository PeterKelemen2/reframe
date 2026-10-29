import { expect, vi } from 'vitest'

import type { JobSettings, TaskInfo } from '../types'

/** A request to the server with its token, beside the app's own client. */
export async function http<T>(
  server: { url: string; token: string },
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${server.url}${path}`, {
    method,
    headers: { Authorization: `Bearer ${server.token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok)
    throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`)
  return (response.status === 204 ? undefined : await response.json()) as T
}

export async function endedTask(
  server: { url: string; token: string },
  taskId: string,
): Promise<TaskInfo> {
  let task: TaskInfo | undefined
  await vi.waitFor(
    async () => {
      task = await http<TaskInfo>(server, 'GET', `/api/tasks/${taskId}`)
      expect(['done', 'failed', 'cancelled']).toContain(task.state)
    },
    { timeout: 30_000, interval: 100 },
  )
  return task as TaskInfo
}

/** A job of the media root's `multitrack.mkv` with the default preset. */
export async function draftJob(server: {
  url: string
  token: string
  media: string
}): Promise<JobSettings> {
  const { task_id } = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/multitrack.mkv`],
  })
  const task = await endedTask(server, task_id)
  const { sources } = task.result as { sources: { id: string }[] }
  const draft = await http<{ job: JobSettings }>(server, 'POST', '/api/jobs/draft', {
    source_id: sources[0]?.id,
  })
  return draft.job
}

let added = 0

/** Adds the job without the app's client, under an output name of its own; resolves with its id. */
export async function addJob(
  server: { url: string; token: string },
  job: JobSettings,
): Promise<string> {
  added += 1
  const path = String(job.output?.path).replace(/[^/]*$/, `job-${Date.now()}-${added}.mkv`)
  const settings = { ...job, output: { ...job.output, path } }
  const [queued] = await http<{ id: string }[]>(server, 'POST', '/api/queue', { jobs: [settings] })
  return queued?.id ?? ''
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
