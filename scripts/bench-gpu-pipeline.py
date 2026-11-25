"""Time Reframe's encode command for a VAAPI preset against two GPU variants of the same command.

current: Reframe's command as it is (CPU decode, CPU filters, hwupload). hwdecode: the GPU
decodes, the CPU filters. gpu: the GPU decodes and filters (crop and scale_vaapi), so frames
never leave the GPU. Every variant keeps the rest of Reframe's command (maps, audio, muxing).
Each run reports frames per second, wall time, CPU time and the peak memory of FFmpeg. With no
source files, 4K test sources (H.264 and 10-bit HEVC at 40 Mb/s) are made in the work folder.
Linux only.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from reframe.tools import locate_tools

VARIANTS = ("current", "hwdecode", "gpu")
HWACCEL = ["-hwaccel", "vaapi", "-hwaccel_device", "va"]
# FFmpeg prints this and decodes on the CPU when the GPU cannot decode the source.
DECODE_FALLBACK = "Failed setup for format vaapi"
# Metadata-only filters: they work on VAAPI frames unchanged.
PASSTHROUGH = {"setsar", "setdar"}
SOURCES = {
    "h264": ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"],
    "hevc10": [
        "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le",
        "-x265-params", "log-level=error",
    ],
}  # fmt: skip


@dataclass
class Variant:
    name: str
    argv: list[str] | None
    skipped: str | None = None


@dataclass
class Run:
    variant: str
    batch: int
    ok: bool
    wall: float
    cpu: float
    peak_rss_mb: float
    frames: int
    output_mb: float
    decode_fallback: bool = False
    error: str | None = None


@dataclass
class Summary:
    """Medians over the batches. A batch is ``--parallel`` copies at once: its fps counts the
    frames of every copy, its CPU time and memory are their sums."""

    variant: str
    runs: int
    fps: float
    wall: float
    cpu: float
    peak_rss_mb: float
    output_mb: float
    notes: list[str] = field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not sys.platform.startswith("linux"):
        print("VAAPI is Linux only", file=sys.stderr)
        return 2
    work: Path = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    ffmpeg, env = find_ffmpeg(args.ffmpeg)
    sources: list[Path] = args.sources or [
        make_source(ffmpeg, env, work, kind, args.source_seconds) for kind in args.make_source
    ]
    report: list[dict[str, object]] = []
    failed = False
    for source in sources:
        print(f"\n{source.name}  (preset {args.preset}, parallel {args.parallel})", flush=True)
        try:
            base, output = plan_argv(source, args.preset, work)
        except PlanFailed as error:
            print(f"  {error}", file=sys.stderr)
            failed = True
            continue
        variants = [v for v in make_variants(base) if v.name in args.variants]
        for variant in variants:
            if variant.skipped:
                print(f"  {variant.name}: skipped, {variant.skipped}")
            elif args.show_commands and variant.argv is not None:
                print(f"  {variant.name}: {shlex.join([str(ffmpeg), *variant.argv])}")
        warm_page_cache(source)
        runs = run_all(ffmpeg, env, variants, output, work, args)
        summaries = summarise(variants, runs)
        print_table(summaries)
        failed = failed or any(not run.ok for run in runs)
        report.append(
            {
                "source": str(source),
                "preset": args.preset,
                "parallel": args.parallel,
                "variants": [asdict(v) for v in variants],
                "summaries": [asdict(s) for s in summaries],
                "runs": [asdict(r) for r in runs],
            }
        )
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))
        print(f"\nwrote {args.json}")
    return 1 if failed else 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bench-gpu-pipeline.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sources", nargs="*", type=Path, help="source files (default: made)")
    parser.add_argument("-p", "--preset", default="h265-vaapi-1080p", help="a VAAPI preset")
    parser.add_argument(
        "--variants",
        type=lambda text: text.split(","),
        default=list(VARIANTS),
        help=f"comma-separated, from {','.join(VARIANTS)} (default: all)",
    )
    parser.add_argument("-r", "--runs", type=int, default=3, help="runs per variant (median)")
    parser.add_argument(
        "-j", "--parallel", type=int, default=1, help="copies run at once (as parallel jobs)"
    )
    parser.add_argument("-t", "--seconds", type=float, help="encode only this much of each source")
    parser.add_argument(
        "--make-source",
        type=lambda text: text.split(","),
        default=list(SOURCES),
        help=f"test sources to make without source files: {','.join(SOURCES)}",
    )
    parser.add_argument("--source-seconds", type=int, default=20, help="length of made sources")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "reframe-bench",
        help="made sources and outputs (default: %(default)s)",
    )
    parser.add_argument("--ffmpeg", type=Path, help="default: Reframe's tool discovery")
    parser.add_argument("--keep", action="store_true", help="keep the encoded files")
    parser.add_argument("--show-commands", action="store_true", help="print each variant")
    parser.add_argument("--json", type=Path, help="also write every run to this JSON file")
    args = parser.parse_args(argv)
    unknown = set(args.variants) - set(VARIANTS) | set(args.make_source) - set(SOURCES)
    if unknown:
        parser.error(f"unknown: {', '.join(sorted(unknown))}")
    if args.runs < 1 or args.parallel < 1:
        parser.error("--runs and --parallel must be at least 1")
    return args


def find_ffmpeg(given: Path | None) -> tuple[Path, dict[str, str]]:
    """The ffmpeg Reframe would run, and the environment it runs it with. Settings → Tools
    paths are not read: pass ``--ffmpeg`` for those."""
    if given is not None:
        return given, dict(os.environ)
    location = locate_tools()["ffmpeg"]
    if location.path is None:
        raise SystemExit(f"no ffmpeg: {location.problem}")
    return location.path, {**os.environ, **location.env}


def make_source(ffmpeg: Path, env: dict[str, str], work: Path, kind: str, seconds: int) -> Path:
    # Per-frame noise keeps the bitrate near real 4K sources; without it they compress to little.
    path = work / f"source-{kind}-2160p24-40M-{seconds}s.mkv"
    if path.exists():
        return path
    print(f"making {path.name} …", flush=True)
    graph = "testsrc2=size=3840x2160:rate=24,noise=alls=4:allf=t"
    rate = ["-b:v", "40M", "-maxrate", "60M", "-bufsize", "80M"]
    partial = path.with_suffix(".part.mkv")
    argv = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", graph]
    argv += ["-t", str(seconds), *SOURCES[kind], *rate, str(partial)]
    subprocess.run(argv, env=env, check=True)
    partial.rename(path)
    return path


class PlanFailed(Exception):
    pass


def plan_argv(source: Path, preset: str, work: Path) -> tuple[list[str], str]:
    """Reframe's ffmpeg arguments for ``source`` with ``preset``, and their output path."""
    cli = Path(sys.executable).with_name("reframe")
    result = subprocess.run(
        [str(cli), "plan", "--json", "-p", preset, "-o", str(work / "plan"), str(source)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PlanFailed(
            f"reframe plan failed ({result.returncode}):\n{result.stdout}{result.stderr}"
        )
    plan = json.loads(result.stdout)["plan"]
    encodes = [step for step in plan["steps"] if step["kind"] == "encode"]
    if len(encodes) != 1:
        raise PlanFailed(f"{len(encodes)} encode steps: only one-pass encodes can be compared")
    argv: list[str] = encodes[0]["argv"]
    if argv[-1] != plan["output_tmp"]:
        raise PlanFailed("the encode command does not end with its output path")
    return argv, plan["output_tmp"]


def make_variants(base: list[str]) -> list[Variant]:
    variants = [Variant("current", base)]
    if not any(arg.startswith("vaapi=va:") for arg in base):
        reason = "the preset does not encode with VAAPI"
        return [*variants, Variant("hwdecode", None, reason), Variant("gpu", None, reason)]
    first_input = base.index("-i")
    variants.append(Variant("hwdecode", [*base[:first_input], *HWACCEL, *base[first_input:]]))
    if "-filter_complex" in base or "-filter:v:0" not in base:
        variants.append(Variant("gpu", None, "the video filters are not a simple chain"))
        return variants
    at = base.index("-filter:v:0") + 1
    chain, reason = vaapi_chain(base[at])
    if chain is None:
        variants.append(Variant("gpu", None, reason))
        return variants
    gpu = [*base[:first_input], *HWACCEL, "-hwaccel_output_format", "vaapi", *base[first_input:]]
    gpu[at + len(HWACCEL) + 2] = chain
    variants.append(Variant("gpu", gpu))
    return variants


def vaapi_chain(chain: str) -> tuple[str | None, str]:
    """``chain`` (CPU filters ending in ``format=…,hwupload``) as filters on VAAPI frames, or
    None and the reason it has no VAAPI form."""
    if "\\" in chain or "'" in chain or "[" in chain:
        return None, f"cannot split the filter chain {chain!r}"
    out: list[str] = []
    size: tuple[str, str] | None = None
    pix_fmt: str | None = None
    crop: tuple[str, str] | None = None
    for item in chain.split(","):
        name, _, options = item.partition("=")
        if name == "crop":
            if size is not None:
                return None, "crop after scale"
            crop = positional(options, ("w", "h"))
            out.append(item)
        elif name == "scale":
            size = positional(options, ("w", "h"))
            out.append("{scale}")
        elif name == "format":
            pix_fmt = options
        elif name == "hwupload":
            pass
        elif name in PASSTHROUGH:
            out.append(item)
        else:
            return None, f"no VAAPI form for {name}"
    if pix_fmt is None:
        return None, "the chain has no format= before hwupload"
    # On VAAPI frames crop only marks the rectangle: scale_vaapi without a size drops it.
    size = size or crop
    if crop is not None and (size is None or not all(part.isdigit() for part in size)):
        return None, "a crop needs a scale with a fixed size"
    scale = f"scale_vaapi=format={pix_fmt}"
    if size is not None:
        scale = f"scale_vaapi=w={size[0]}:h={size[1]}:format={pix_fmt}"
    if "{scale}" in out:
        out[out.index("{scale}")] = scale
    else:
        out.append(scale)
    return ",".join(out), ""


def positional(options: str, names: tuple[str, str]) -> tuple[str, str]:
    values: dict[str, str] = {}
    for index, part in enumerate(options.split(":")):
        key, sep, value = part.partition("=")
        if sep:
            values[key] = value
        elif index < len(names):
            values[names[index]] = part
    return values.get(names[0], "iw"), values.get(names[1], "ih")


def warm_page_cache(source: Path, limit: int = 4 << 30) -> None:
    """Read ``source`` once so the first run does not pay for the disk alone."""
    if source.stat().st_size > limit:
        return
    with source.open("rb") as file:
        while file.read(8 << 20):
            pass


def run_all(
    ffmpeg: Path,
    env: dict[str, str],
    variants: list[Variant],
    output: str,
    work: Path,
    args: argparse.Namespace,
) -> list[Run]:
    runs: list[Run] = []
    suffix = Path(output).suffix
    # Round-robin, so a slow start (clocks, caches) does not land on one variant.
    for number in range(args.runs):
        for variant in variants:
            if variant.argv is None:
                continue
            print(f"  run {number + 1}/{args.runs} {variant.name} …", end=" ", flush=True)
            batch = run_batch(ffmpeg, env, variant, suffix, work, number, args)
            runs += batch
            bad = [run for run in batch if not run.ok]
            fps = sum(r.frames for r in batch) / max(r.wall for r in batch)
            print(f"failed: {bad[0].error}" if bad else f"{fps:.1f} fps")
    return runs


def run_batch(
    ffmpeg: Path,
    env: dict[str, str],
    variant: Variant,
    suffix: str,
    work: Path,
    number: int,
    args: argparse.Namespace,
) -> list[Run]:
    """Run ``args.parallel`` copies of ``variant`` at once."""
    assert variant.argv is not None
    started = time.perf_counter()
    processes: list[tuple[subprocess.Popen[bytes], Path, Path, Path]] = []
    try:
        for copy in range(args.parallel):
            stem = work / f"run-{variant.name}-{number}-{copy}"
            out, progress, log = (
                stem.with_suffix(suffix),
                stem.with_suffix(".progress"),
                stem.with_suffix(".log"),
            )
            argv = [
                *variant.argv[:-1],
                *(["-t", str(args.seconds)] if args.seconds else []),
                str(out),
            ]
            with progress.open("wb") as stdout, log.open("wb") as stderr:
                process = subprocess.Popen(
                    [str(ffmpeg), *argv], stdout=stdout, stderr=stderr, env=env
                )
            processes.append((process, out, progress, log))
        by_pid = {entry[0].pid: entry for entry in processes}
        runs = []
        while by_pid:
            # wait4, not wait: it gives this child's own CPU time and peak memory.
            pid, status, usage = os.wait4(-1, 0)
            if pid not in by_pid:
                continue
            process, out, progress, log = by_pid.pop(pid)
            process.returncode = os.waitstatus_to_exitcode(status)
            wall = time.perf_counter() - started
            runs.append(
                collect(variant.name, number, process.returncode, wall, usage, out, progress, log)
            )
        return runs
    finally:
        for process, *files in processes:
            if process.returncode is None:
                process.kill()
                process.wait()
            if not args.keep:
                for path in files:
                    path.unlink(missing_ok=True)


def collect(
    variant: str,
    batch: int,
    code: int,
    wall: float,
    usage: resource.struct_rusage,
    out: Path,
    progress: Path,
    log: Path,
) -> Run:
    stderr = log.read_text(errors="replace")
    frames = 0
    for line in progress.read_text(errors="replace").splitlines():
        if line.startswith("frame="):
            frames = int(line.removeprefix("frame=") or 0)
    size = out.stat().st_size / 1e6 if out.exists() else 0.0
    error = None
    if code != 0:
        tail = [line for line in stderr.splitlines() if line.strip()][-3:]
        error = f"exit {code}: " + " | ".join(tail)
    return Run(
        variant=variant,
        batch=batch,
        ok=code == 0,
        wall=wall,
        cpu=usage.ru_utime + usage.ru_stime,
        peak_rss_mb=usage.ru_maxrss / 1024,
        frames=frames,
        output_mb=size,
        decode_fallback=DECODE_FALLBACK in stderr,
        error=error,
    )


def summarise(variants: list[Variant], runs: list[Run]) -> list[Summary]:
    summaries = []
    for variant in variants:
        mine = [run for run in runs if run.variant == variant.name]
        grouped = [[r for r in mine if r.batch == n] for n in sorted({r.batch for r in mine})]
        batches = [batch for batch in grouped if all(run.ok for run in batch)]
        if not batches:
            continue
        notes = []
        if any(run.decode_fallback for run in mine):
            notes.append("the GPU could not decode the source: FFmpeg decoded on the CPU")
        summaries.append(
            Summary(
                variant=variant.name,
                runs=len(batches),
                fps=statistics.median(
                    sum(r.frames for r in b) / max(r.wall for r in b) for b in batches
                ),
                wall=statistics.median(max(r.wall for r in b) for b in batches),
                cpu=statistics.median(sum(r.cpu for r in b) for b in batches),
                peak_rss_mb=max(sum(r.peak_rss_mb for r in b) for b in batches),
                output_mb=statistics.median(r.output_mb for r in mine if r.ok),
                notes=notes,
            )
        )
    return summaries


def print_table(summaries: list[Summary]) -> None:
    if not summaries:
        return
    base = next((s for s in summaries if s.variant == "current"), summaries[0])
    print(
        f"\n  {'variant':<9} {'fps':>7} {'rel fps':>7} {'wall s':>7} {'CPU s':>7} "
        f"{'rel CPU':>7} {'cores':>6} {'RSS MB':>7} {'out MB':>7}"
    )
    for s in summaries:
        print(
            f"  {s.variant:<9} {s.fps:>7.1f} {s.fps / base.fps:>7.2f} {s.wall:>7.2f} "
            f"{s.cpu:>7.1f} {s.cpu / base.cpu:>7.2f} {s.cpu / s.wall:>6.1f} "
            f"{s.peak_rss_mb:>7.0f} {s.output_mb:>7.1f}"
        )
        for note in s.notes:
            print(f"            {note}")


if __name__ == "__main__":
    raise SystemExit(main())
