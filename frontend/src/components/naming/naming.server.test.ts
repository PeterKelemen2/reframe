// What the naming editors rely on in the real server's `naming/preview`, with release names.
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import type { JobSettings, NameResult, NamingOptions } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { copyAs } from './testing/releases.mjs'

const PORT = 8782

const HACKSAW =
  'Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC.HUN-HenDerson/hacksawridge.2160p.remux-henderson.mkv'
const SOPRANOS =
  'The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm/The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm.mkv'

let server: DevServer
const ids: Record<string, string> = {}

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'multitrack', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
  const paths = await copyAs(`${server.media}/multitrack.mkv`, server.media, [HACKSAW, SOPRANOS])
  const probe = await http<{ task_id: string }>(server, 'POST', '/api/sources', { paths })
  const task = await endedTask(server, probe.task_id)
  const sources = (task.result as { sources: { id: string; path: string }[] }).sources
  for (const source of sources)
    ids[source.path.includes('Sopranos') ? 'sopranos' : 'hacksaw'] = source.id
}, 120_000)

afterAll(async () => {
  await server.stop()
})

async function preview(body: object): Promise<NameResult[]> {
  return http<NameResult[]>(server, 'POST', '/api/naming/preview', body)
}

describe('naming/preview on the real server', () => {
  it('takes the folder name for a movie whose folder has the better name, and colours its parts', async () => {
    const [result] = await preview({ source_ids: [ids.hacksaw] })
    expect(result?.source).toBe('folder')
    expect(result?.reason).toMatch(/^Folder name: \d+ fields recognised/)
    expect(result?.relative_path).toBe('Hacksaw.Ridge.mkv')
    expect(result?.path).toBe(`${server.output}/Hacksaw.Ridge.mkv`)
    const folder = result?.candidates?.find((candidate) => candidate.kind === 'folder')
    expect(folder?.spans?.slice(0, 2)).toEqual([
      { field: 'name', start: 0, end: 13, text: 'Hacksaw.Ridge' },
      { field: 'year', start: 14, end: 18, text: '2016' },
    ])
  })

  it('takes the file name for an episode in a season folder', async () => {
    const [result] = await preview({ source_ids: [ids.sopranos] })
    expect(result).toMatchObject({
      source: 'file',
      template_kind: 'episode',
      relative_path: 'The.Sopranos.S03E02.Proshai.Livushka.mkv',
    })
    expect(result?.reason).toContain('Only the file name has an episode number (S03E02)')
  })

  it('checks only the template a source uses', async () => {
    const naming: NamingOptions = {
      movie_template: '{main_title}',
      episode_template: '{main_titel}',
      name_source: 'auto',
      word_separator: 'keep',
      title_case: false,
      replace_underscores: false,
      remove_punctuation: false,
      mp4_extension: 'mp4',
      output_folder_mode: 'fixed',
      output_folder: server.output,
    }
    const [movie, episode] = await preview({
      naming,
      source_ids: [ids.hacksaw, ids.sopranos],
      container: 'mkv',
    })
    expect(movie?.issues).toEqual([])
    expect(episode?.issues?.map((issue) => [issue.code, issue.path])).toEqual([
      ['naming.unknown_variable', 'output.naming.template'],
    ])
  })

  it("names a job with its own template and field overrides; a bad template's fix carries the whole template", async () => {
    const { job } = await http<{ job: JobSettings }>(server, 'POST', '/api/jobs/draft', {
      source_id: ids.hacksaw,
    })
    const withNaming = (naming: object): JobSettings => ({
      ...job,
      output: { ...job.output!, naming: { ...job.output!.naming!, ...naming } },
    })

    const [overridden] = await preview({
      source_ids: [ids.hacksaw],
      job: withNaming({ template: '{name} ({year})', field_overrides: { name: 'My Movie' } }),
    })
    expect(overridden?.relative_path).toBe('My Movie (2016).mkv')

    const [broken] = await preview({
      source_ids: [ids.hacksaw],
      job: withNaming({ template: '{main_titel}.x' }),
    })
    const issue = broken?.issues?.find((found) => found.code === 'naming.unknown_variable')
    expect(issue?.path).toBe('output.naming.template')
    expect(issue?.fixes?.[0]?.patch).toEqual([
      { op: 'add', path: '/output/naming/template', value: '{main_title}.x' },
    ])
    // A template with errors names the file after the source file.
    expect(broken?.relative_path).toBe('hacksawridge.2160p.remux-henderson.mkv')
  })
})
