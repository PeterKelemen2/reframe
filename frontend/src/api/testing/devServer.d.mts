export interface DevServer {
  url: string
  token: string
  /** The address with `#token=…`. */
  open: string
  home: string
  media: string
  output: string
  /** The reframe-server process. */
  pid: number
  /** Stops it; rejects unless the processes are gone and the home is removed. */
  stop(): Promise<void>
}

/** Starts `scripts/dev-server.py --no-static`; `args` are its other options. */
export function startServer(options: { port: number; args?: string[] }): Promise<DevServer>
