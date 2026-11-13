// What the Python core makes of the recorded probes' frame rates and frame ranges, for a test
// that pins `range.ts` to it. Plain JavaScript: the app's tsconfig has no Node types.
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('../../../../', import.meta.url))

const SCRIPT = String.raw`
import json, sys
from pathlib import Path
from types import SimpleNamespace

from reframe.command.video import source_rate
from reframe.models import FrameRange, SourceFingerprint
from reframe.probe import parse_ffprobe
from reframe.validation import JobContext
from reframe.validation.range import frame_count, range_duration

RANGES = json.loads(sys.argv[1])
probes = Path("testdata/probes")
out = []
for path in sorted([*probes.glob("*.json"), *(probes / "fixtures").glob("*.json")]):
    if path.name in ("index.json", "confirmed_strings.json") or path.name.endswith(".frames.json"):
        continue
    frames_path = path.with_name(path.name.removesuffix(".json") + ".frames.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = json.loads(frames_path.read_text(encoding="utf-8")) if frames_path.exists() else None
    source = parse_ffprobe(
        data,
        Path("/media") / path.name,
        frames=frames,
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
    )

    def context(selected):
        # The range arithmetic reads the job's range and the source only.
        return JobContext(SimpleNamespace(range=selected), source, *[None] * 6)

    video = source.video[0] if source.video else None
    rate = source_rate(video) if video is not None else None
    out.append({
        "name": str(path.relative_to(probes)),
        "source": source.model_dump(mode="json"),
        "rate": float(rate) if rate is not None else None,
        "frames": frame_count(context(None)),
        "seconds": [range_duration(context(FrameRange(start=s, end=e))) for s, e in RANGES],
    })
print(json.dumps(out))
`

/**
 * Each recorded probe in `testdata/probes` (and `fixtures/`) as the server gives it, with the
 * builder's frame rate, the frame count and the `range_duration` of each `[start, end]` in frames.
 */
export function pythonRanges(ranges) {
  const output = execFileSync('uv', ['run', 'python', '-c', SCRIPT, JSON.stringify(ranges)], {
    cwd: ROOT,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  return JSON.parse(output)
}
