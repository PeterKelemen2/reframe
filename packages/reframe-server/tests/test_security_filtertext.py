"""Free filter text from a web client: read as FFmpeg's filtergraph parser reads it, and only
allowed filters may appear in it."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.models import FilterConfig, JobDraft, JobSettings, SourceRef
from reframe_server import security
from reframe_server.config import ServerConfig, ServerMode
from reframe_server.errors import ProblemError
from reframe_server.filtertext import ALLOWED_FILTERS, GraphSyntaxError, parse_graph
from reframe_testing import media
from reframe_testing.server import Api

#: Graphs and the filters FFmpeg makes of them, in order (checked with the real ffmpeg below).
FFMPEG_READS = [
    ("hue=s='max(0,1)',hflip", ["hue", "hflip"]),
    ("hue=s=max(0\\,1),hflip", ["hue", "hflip"]),
    (" eq =brightness=0.1 , hflip , ", ["eq", "hflip"]),
    ("null@x,'hf'l\\ip", ["null", "hflip"]),
    ("[0:v]hflip [a];[a] vflip;", ["hflip", "vflip"]),
]

#: An option of one of these types can hold a file name, a URL or a plugin name.
_TEXT_OPTION = re.compile(r"^\s+(\S+)\s+<(?:string|dictionary|binary)>\s+\S+\s*(.*)$", re.M)
_NAMES_A_FILE = re.compile(
    r"file|path|url|uri\b|device|shader|plugin|model|librar|director|address|font|socket|"
    r"codec|filter_name",
    re.I,
)


def _names(graph: str) -> list[str]:
    return [found.name for chain in parse_graph(graph) for found in chain]


@pytest.mark.parametrize(("graph", "names"), FFMPEG_READS)
def test_the_parser_splits_a_graph_where_ffmpeg_does(graph: str, names: list[str]) -> None:
    assert _names(graph) == names


@pytest.mark.parametrize(
    ("graph", "reason"),
    [
        ("hue=s='1,hflip", "a quote is not closed"),
        ("hflip\\", "ends with a backslash"),
        (",hflip", "has no name"),
        ("hue=s=1]", "follows a filter"),
        ("[a", "not closed"),
    ],
)
def test_text_that_ffmpeg_refuses_or_reads_to_the_end_is_an_error(graph: str, reason: str) -> None:
    with pytest.raises(GraphSyntaxError, match=reason):
        parse_graph(graph)


def _ffmpeg_filters(ffmpeg: str, graph: str, folder: Path) -> list[str]:
    """The filters the real ffmpeg parses from ``graph`` (``-print_graphs_file``)."""
    out = folder / "graphs.json"
    run = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
         "nullsrc=s=64x64:d=0.04", "-filter_complex", graph, "-print_graphs_file", str(out),
         "-print_graphs_format", "json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    if "print_graphs" in run.stderr:
        pytest.skip("this ffmpeg cannot print its filter graphs")
    assert run.returncode == 0, run.stderr
    graphs = json.loads(out.read_text(encoding="utf-8"))["graphs"]
    return [
        found["filter_name"]
        for each in graphs
        for found in each["filters"]
        if found["filter_name"] not in ("buffer", "buffersink")
    ]


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(("graph", "names"), FFMPEG_READS)
def test_ffmpeg_splits_these_graphs_the_same_way(
    graph: str, names: list[str], tmp_path: Path
) -> None:
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    assert _ffmpeg_filters(ffmpeg, graph, tmp_path) == names


@pytest.mark.needs_ffmpeg
def test_ffmpeg_reads_an_open_quote_to_the_end(tmp_path: Path) -> None:
    """Why an open quote is refused: FFmpeg takes the rest of the text, filters and all, as
    one option value."""
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    graph = "metadata=mode=add:key=k:value='x,hflip"
    assert _ffmpeg_filters(ffmpeg, graph, tmp_path) == ["metadata"]


@pytest.mark.needs_ffmpeg
def test_no_allowed_filter_has_an_option_that_names_a_file() -> None:
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None

    def file_options(name: str) -> list[str] | None:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-h", f"filter={name}"],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout  # fmt: skip
        if not out.startswith("Filter "):
            return None  # not in this build: FFmpeg cannot run it either
        return [o for o, d in _TEXT_OPTION.findall(out) if _NAMES_A_FILE.search(f"{o} {d}")]

    for reads_files in ("movie", "drawtext", "libplacebo", "curves"):
        assert file_options(reads_files), f"the check does not see the file option of {reads_files}"
    found = {name: file_options(name) for name in sorted(ALLOWED_FILTERS)}
    assert {name: options for name, options in found.items() if options} == {}


def _config(tmp_path: Path, mode: ServerMode = "web") -> ServerConfig:
    return ServerConfig(
        mode=mode, auth="token", media_roots=[tmp_path], output_roots=[tmp_path / "out"]
    )


def _job(tmp_path: Path, filters: dict[str, FilterConfig]) -> JobSettings:
    job = JobSettings(source=SourceRef(path=tmp_path / "a.mkv"))
    job.output.path = tmp_path / "out" / "a.mkv"
    job.filters.root = filters
    return job


def _custom(text: str) -> dict[str, FilterConfig]:
    return {"custom": FilterConfig(custom=text)}


@pytest.mark.parametrize(
    ("filters", "detail"),
    [
        (_custom("movie=/etc/passwd,hflip"), "'movie' is not allowed"),
        (_custom("hue=s='1,hflip"), "a quote is not closed"),
        (_custom("hflip;vflip"), "second filter chain"),
        (_custom("[in]hflip"), "link labels"),
        (
            {"sharpen": FilterConfig(preset="custom", custom="5:5,hflip")},
            "',' outside quotes would start another filter",
        ),
        (
            {"detelecine": FilterConfig(preset="custom", custom="order=tff\\")},
            "ends with a backslash",
        ),
        ({"colorspace": FilterConfig(preset="custom", custom="range=tv")}, "'libplacebo'"),
    ],
)
def test_unsafe_free_filter_text_from_a_web_client_is_refused(
    tmp_path: Path, filters: dict[str, FilterConfig], detail: str
) -> None:
    with pytest.raises(ProblemError) as refused:
        security.jail_job(_config(tmp_path), _job(tmp_path, filters))
    problem = refused.value.problem
    assert (problem.status, problem.code) == (403, "filter.not_allowed")
    assert detail in (problem.detail or "")
    assert (problem.detail or "").startswith(f"filters.{next(iter(filters))}:")


@pytest.mark.parametrize(
    "filters",
    [
        _custom("scale=iw/2:ih/2,hue=s='max(0,1)'"),
        {"sharpen": FilterConfig(preset="custom", custom="lx=5:la='1,5':ca=0\\,5")},
        {"colorspace": FilterConfig(preset="custom", implementation="zscale", custom="r=tv")},
        {"denoise": FilterConfig(preset="light")},
        {"not_a_filter": FilterConfig(custom="movie=x")},
    ],
)
def test_safe_free_filter_text_passes(tmp_path: Path, filters: dict[str, FilterConfig]) -> None:
    security.jail_job(_config(tmp_path), _job(tmp_path, filters))


#: Free text (filter id, text) that makes the real ffmpeg read the file ``{file}`` names.
READS_A_FILE = [
    ("custom", "eq=/contrast={file}"),
    ("custom", "eq='/contrast'={file}"),
    ("custom", "eq=brightness=0\\: /contrast={file}"),
    ("sharpen", "5:5:/lx={file}"),
]


def _graph(filter_id: str, text: str) -> str:
    return {"custom": text, "sharpen": f"unsharp={text}"}[filter_id]


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(("filter_id", "text"), READS_A_FILE)
def test_ffmpeg_reads_an_option_value_from_a_file_for_these_texts(
    tmp_path: Path, filter_id: str, text: str
) -> None:
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET-FILE-CONTENT", encoding="utf-8")
    graph = _graph(filter_id, text.format(file=secret))
    run = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.04",
         "-vf", graph, "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert "SECRET-FILE-CONTENT" in run.stderr


@pytest.mark.parametrize(("filter_id", "text"), READS_A_FILE)
def test_free_filter_text_that_reads_a_file_is_refused(
    tmp_path: Path, filter_id: str, text: str
) -> None:
    preset = "default" if filter_id == "custom" else "custom"
    config = FilterConfig(preset=preset, custom=text.format(file="/etc/passwd"))
    with pytest.raises(ProblemError) as refused:
        security.jail_job(_config(tmp_path), _job(tmp_path, {filter_id: config}))
    problem = refused.value.problem
    assert (problem.status, problem.code) == (403, "filter.not_allowed")
    assert "starts with '/'" in (problem.detail or "")


def test_desktop_mode_keeps_free_filter_text(tmp_path: Path) -> None:
    job = _job(tmp_path, _custom("movie=/etc/passwd,hflip"))
    security.jail_job(_config(tmp_path, "desktop"), job)


async def _render(api: Api, job: dict[str, Any]) -> Any:
    return await api.client.post("/api/preview/render", json={"job": job, "timestamp": 1.0})


@pytest.mark.anyio
@pytest.mark.needs_ffmpeg
async def test_an_allowed_chain_still_runs_and_a_file_read_does_not(
    api: Api, fixture_media: Callable[[str], Path]
) -> None:
    file = api.add_fixture("multitrack", fixture_media)
    draft = await api.reframe.jobs.draft(file, output=api.output / "out.mkv")
    assert isinstance(draft, JobDraft)
    job = draft.job.model_dump(mode="json")
    job["filters"] = {"custom": {"custom": "eq=brightness=0.05,hue=s='max(0,1)'"}}
    rendered = await _render(api, job)
    assert rendered.status_code == 200, rendered.text
    assert [frame["kind"] for frame in rendered.json()["frames"]] == ["source", "output"]
    job["filters"] = {"custom": {"custom": f"movie={file},hflip"}}
    refused = await _render(api, job)
    assert (refused.status_code, refused.json()["code"]) == (403, "filter.not_allowed")
