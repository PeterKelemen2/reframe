import { describe, expect, it } from 'vitest'

import { stepLines, type Token, tokenize } from './commandLine'

// `EncodePlan.display` of the real server for multitrack.mkv with the H.265 MKV 1080p preset
// (paths shortened), POSIX quoting.
const DISPLAY =
  "/opt/ffmpeg/bin/ffmpeg -hide_banner -nostdin -y -progress pipe:1 -nostats -drc_scale:1 0 -i /data/media/multitrack.mkv -map 0:0 -filter:v:0 idet,bwdif=mode=send_frame:parity=auto:deint=interlaced,scale=320:180:flags=lanczos,setsar=1/1,format=yuv420p10le -filter:a:0 aresample=out_chlayout=stereo -c:v:0 libx265 -crf:v:0 22 -x265-params:v:0 strong-intra-smoothing=0:rect=0 -map_metadata:s -1 -metadata:s:a:2 'title=Director'\"'\"'s Commentary' -map_chapters -1 -f matroska /data/output/multitrack.part.mkv && mv -f -- /data/output/multitrack.part.mkv /data/output/multitrack.mkv"

function kindOf(tokens: Token[], text: string): string | undefined {
  return tokens.find((token) => token.text === text)?.kind
}

describe('tokenize', () => {
  const tokens = tokenize(DISPLAY)

  it('gives the command back exactly when the tokens are joined', () => {
    expect(tokens.map((token) => token.text).join('')).toBe(DISPLAY)
  })

  it('tells programs, options, values, paths, filter graphs and the step operator apart', () => {
    expect(kindOf(tokens, '/opt/ffmpeg/bin/ffmpeg')).toBe('program')
    expect(kindOf(tokens, '-hide_banner')).toBe('option')
    expect(kindOf(tokens, 'pipe:1')).toBe('value')
    expect(kindOf(tokens, '/data/media/multitrack.mkv')).toBe('path')
    expect(kindOf(tokens, 'aresample=out_chlayout=stereo')).toBe('filter')
    expect(kindOf(tokens, 'libx265')).toBe('value')
    expect(kindOf(tokens, '&&')).toBe('operator')
    expect(kindOf(tokens, 'mv')).toBe('program')
    expect(kindOf(tokens, '/data/output/multitrack.mkv')).toBe('path')
  })

  it('reads a negative number as a value, not an option', () => {
    const index = tokens.findIndex((token) => token.text === '-map_chapters')
    expect(tokens[index + 2]).toEqual({ text: '-1', kind: 'value' })
  })

  it('keeps a quoted argument with an escaped quote as one value', () => {
    expect(kindOf(tokens, "'title=Director'\"'\"'s Commentary'")).toBe('value')
  })

  it('reads Windows quoting', () => {
    const windows = tokenize('"C:\\Program Files\\ffmpeg.exe" -i "D:\\in put.mkv" -c:v:0 libx265')
    expect(windows.filter((token) => token.kind !== 'space')).toEqual([
      { text: '"C:\\Program Files\\ffmpeg.exe"', kind: 'program' },
      { text: '-i', kind: 'option' },
      { text: '"D:\\in put.mkv"', kind: 'path' },
      { text: '-c:v:0', kind: 'option' },
      { text: 'libx265', kind: 'value' },
    ])
  })
})

describe('stepLines', () => {
  it('puts each step on its own line, the operator at the end of the line before', () => {
    const lines = stepLines(tokenize('ffmpeg -i /a -f null - && ffmpeg -i /a /b && mv /b /c'))
    expect(lines.map((line) => line.map((token) => token.text).join(''))).toEqual([
      'ffmpeg -i /a -f null - &&',
      'ffmpeg -i /a /b &&',
      'mv /b /c',
    ])
  })
})
