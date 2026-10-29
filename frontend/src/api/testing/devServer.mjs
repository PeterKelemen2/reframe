// A real reframe-server for the `*.server.test.ts` files, through scripts/dev-server.py. Plain
// JavaScript: the app's tsconfig has no Node types, and this file needs Node's.
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('../../../../', import.meta.url))
const READY_TIMEOUT = 60_000
const STOP_TIMEOUT = 20_000

function alive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

/** @param {{ port: number, args?: string[] }} options */
export function startServer({ port, args = [] }) {
  const child = spawn(
    'uv',
    [
      'run',
      'python',
      `${ROOT}scripts/dev-server.py`,
      '--port',
      String(port),
      '--no-static',
      ...args,
    ],
    { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] },
  )
  const errors = []
  child.stderr.setEncoding('utf8')
  child.stderr.on('data', (chunk) => {
    errors.push(chunk)
    if (errors.length > 50) errors.shift()
  })
  return new Promise((resolve, reject) => {
    let buffer = ''
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      reject(new Error(`dev-server did not get ready:\n${errors.join('')}`))
    }, READY_TIMEOUT)
    child.on('exit', (code) => {
      clearTimeout(timer)
      reject(new Error(`dev-server exited with ${code}:\n${errors.join('')}`))
    })
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk) => {
      buffer += chunk
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('{')) continue
        const ready = JSON.parse(line)
        if (ready.event !== 'ready') continue
        clearTimeout(timer)
        resolve({ ...ready, stop: () => stop(child, ready) })
      }
    })
  })
}

/** SIGTERM, then checks that the dev-server and the server are gone and the home removed. */
async function stop(child, ready) {
  if (child.exitCode === null) {
    const exited = new Promise((resolve) => child.once('exit', resolve))
    child.kill('SIGTERM')
    const timeout = new Promise((resolve) => setTimeout(resolve, STOP_TIMEOUT, 'timeout'))
    if ((await Promise.race([exited, timeout])) === 'timeout') {
      child.kill('SIGKILL')
      throw new Error('dev-server did not stop within the timeout')
    }
  }
  if (alive(ready.pid)) throw new Error(`reframe-server ${ready.pid} is still running`)
  if (existsSync(ready.home)) throw new Error(`the server home ${ready.home} is still there`)
}
