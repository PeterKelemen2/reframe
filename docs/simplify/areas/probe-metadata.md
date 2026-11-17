# probe-metadata: simplification findings

Commit: 85d9dcb.
Verified: 2026-11-15, 4 confirmed, 11 adjusted, 0 rejected.

Scope: `packages/reframe/src/reframe/probe/`, `metadata/`, `chapters.py`, `languages.py`, `textfile.py` and their tests (`tests/probe/`, `tests/metadata/`, `tests/languages/`, `tests/test_chapters.py`, `tests/test_languages.py`). Source lines: 2,984 (probe) + 1,059 (metadata) + 329 (chapters) + 806 (languages) + 69 (textfile) = 5,247 code lines. Read in full: `probe/{__init__,ffprobe,prober,cache,parse,matroska,sampling,folder,bitrate}.py`, `metadata/{__init__,ebml,layout,versions,own_thread}.py`, `metadata/header.py`, `textfile.py`, `chapters.py` (first 430 lines = all), `languages.py` lines 1-280 and 800-1111. Only skimmed: `probe/{roles,names,hdr}.py`, `languages.py` lines 280-800 (the langcodes port: 0082 fixes it), the tests (read only the parts a finding touches).

## Summary

No leftovers of the MediaInfo or mkvpropedit paths remain in this scope (`rg -i "mediainfo|mkvpropedit"` over `reframe/` and `reframe_server/` finds one docstring that says "as mkvpropedit does"). The new C-18/C-19/C-20 code is mostly required by 0080, 0081 and 0082. The complexity that can go is around it. The Matroska reader, the sampler, the header writer and the tests each carry their own copy of the EBML basics (element IDs, a child walker, a read-N-bytes loop, test builders). Two caches sit in front of the probe cache's disk files (a memory LRU that costs more than it saves, and a hand-bumped `options` number that the source hash already covers). `start_probe_folder` is a second, unused copy of the service's folder task. `reframe.languages` has about 95 code lines (and 245 test lines) of `search` / `picker_label` / `entry` that no product code calls: the picker searches in TypeScript. Four findings are cross-area (batch, service, capabilities).

## Findings

### PRB-01: `languages.search`, `picker_label` and `entry` have no product caller
- Kind: decision-change
- Where: `packages/reframe/src/reframe/languages.py:880-887` (`picker_label`), `:930-934` (`entry`), `:963-1078` (`_RANK_*`, `_WORD_SPLIT`, `_Searchable`, `_searchable`, `_rank`, `search`, `_score`, `_ScoreKey`), and the `__all__` entries `"entry"`, `"picker_label"`, `"search"` (`:26-50`). Unused imports after the change: `Sequence`, `Container` (check with ruff).
- Now: The web picker gets the static list from `GET /api/languages` and searches in TypeScript (`frontend/src/components/language/catalog.ts`, `searchLanguages`, `writtenAs`). `rg` over `packages/*/src`, `scripts/`, `testing/`, `desktop/`: `languages.search` has 0 callers, `picker_label` 0, `entry` 0 (the CLI has no language search). The only users are tests. `language_list()` stays: its only product use is the server's `render()`, which writes the shipped `languages.json` (`routers/languages.py:55-58, 80`). The three functions are 93 code lines (counted with `ast`, docstrings and comments left out) of a Python picker that nothing runs. The plan names `search` (`docs/plan/05-core.md` C-6, line "`languages.py`: search (by name, native name, ISO 639-1/2/3, BCP 47) …"; `docs/status.md:63, 167`), and 0082 item 4 says "`reframe.languages` keeps its public API". So this is a plan and decision change, not a plain delete. What would have to be true: the owner accepts that the picker's ranking has one implementation (the TypeScript one, tested by `catalog.test.ts` and `LanguagePicker.test.ts`) and that Python has no search. Decision 0065 (item 1, "with the ranking of `reframe.languages.search`", and item 3, "as `reframe.languages.picker_label` does") names the Python functions as the reference that the TypeScript picker follows. Nothing runs the two against each other: the TS tests do not import Python results, so after the change the ranking is specified only by the TS tests.
- Change: Delete the three functions and their helpers. Keep `normalize`, `_find_name`, `_name_index`, `_search_tables` (used by `normalize` for names), `language_list`, `LanguageEntry`, `_make_entry`, `_sort_key`. Edit `05-core.md` C-6 (drop "search (by name, native name, ISO codes)" from the `languages.py` line, say the picker searches in the frontend), `docs/status.md:63, 167`, the module docstring of `languages.py` ("normalisation, search, ..."), and add one sentence each to 0082 and 0065 (a "Changed" note: `search`, `picker_label`, `entry` removed because the picker is client-side; the ranking in 0065 item 1 and the label in item 3 are now defined by `catalog.ts`). Then run `uv run ruff check` for the unused imports.
- Behaviour: unchanged for every user (no product path calls these). Python API `reframe.languages.search`, `picker_label`, `entry` disappear.
- Contracts touched: public core API (three names). No HTTP/OpenAPI change: `GET /api/languages` is built from `language_list`, which stays.
- Callers to update: none in `src`. Tests only.
- Tests: Delete in `tests/test_languages.py`: `test_picker_label` (265-271), `test_entry_outside_the_list` (317-328), `tags_of` helper (331-332; every use is in a search test), the `search` tests (335-399: `test_search_ranking`, `test_search_rank_order`, `test_search_code_beats_name`, `test_search_favourites_first`, `test_search_limit_and_no_match`, `test_search_finds_tags_and_names_outside_the_list`), `_search_keys` and `test_search_finds_every_entry_first` (478-500), and the `picker_label`, `entry`, `search` imports (28-31). In `tests/languages/test_equivalence.py`: `_search_differences` and the four `test_search_*` / `test_property_same_search_for_any_query` tests (247-277, 324, 356-357), and `"entry"` from the function tuples (166, 187). In `tests/languages/oracle.py`: `picker_label` (343-352), `entry` (393-398), `_Searchable`, `_searchable`, `_rank`, `search`, `_score` (439-543). In `tests/languages/test_without_libraries.py`: the `"search"` keys (32, 58). Keep `test_ties.py` (it imports only `normalize`, `english_name`, `native_name`). The tests that guard unchanged behaviour: `normalize`, `to_matroska_*`, `native_name`, `matches` tests.
- Decision records: 0082 (item 4, "keeps its public API and its results"; equivalence list in item 5 names `search`), and 0065 (items 1 and 3: the TS picker follows `search` and `picker_label`). The change keeps 0082's data and results for everything a product path uses.
- Size: M; estimated lines: -95 / -245
- Risk: low (no caller). The risk is in the plan edit: a later Python or CLI picker would need to bring `search` back.
- Depends on: none
- Confidence: medium (the plan, 0082 and 0065 ask for it; the evidence that nothing calls it is complete)
- Verdict: ADJUSTED (callers re-checked in `packages/`, `scripts/`, `testing/`, `desktop/`, `frontend/src`: still none, `gen-language-data.py` imports only tables; the finding missed that decision 0065 items 1 and 3 name `search` and `picker_label` as the TS picker's reference, so 0065 needs a note too; `picker_label` ends at 887; the `languages.py` module docstring also says "search")
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### PRB-02: `ProbeCache` memory layer costs more than it saves
- Kind: concurrency
- Where: `packages/reframe/src/reframe/probe/cache.py:45` (`MEMORY_ENTRIES`), `:107-111` (`_Entry`), `:114-132` (`__init__`: `_memory`, `_memory_entries`, `_lock`), `:136-152` (`get`), `:196-199` (`put`: `entry = _Entry(..., source.model_copy(deep=True))`, `_remember`), `:231-233` (the lock for `_puts`), `:270-280` (`_remember`, `forget_memory`), `:282-290` (`clear`), the `memory_entries` constructor argument, `OrderedDict` and `threading` imports; `__all__` entry `"MEMORY_ENTRIES"`.
- Now: A hit in the memory layer still returns `entry.source.model_copy(deep=True)`. I measured on the largest of the recorded probes in `testdata/probes/` (8,112 bytes of JSON, 300 runs each): `model_copy(deep=True)` 0.136 ms; `json.loads` + `MediaSource.model_validate` 0.095 ms, plus one small file read. So the memory layer saves nothing a user can notice, and `put` pays one more deep copy for it. A second LRU sits in front of it: `SourceService._known` (`service.py:278, 600-603`, `KNOWN_SOURCES`), which `SourceService.get()` reads first. The plan asks only for "key = absolute path + size + mtime. Stored as JSON in the cache dir" (`05-core.md` C-3). Nothing in the decisions requires the layer (0007 item 2 only says an over-deep entry is not kept "in the memory layer either").
- Change: Delete `_memory`, `_remember`, `forget_memory`, `MEMORY_ENTRIES`, `memory_entries`, and `_Entry`'s deep copy. `get(key, *, tool)` reads `_read(key)`, checks `tool`, and returns the freshly validated source (no copy needed). `put` stops copying. `clear()` keeps the file loop. Keep a lock only for `_puts`, or replace `_puts`/`due` with `itertools.count()` (`next(counter) % PRUNE_EVERY == 0`) and drop `threading`. `_Entry` becomes `(tool, source)` or a tuple. Do together with PRB-05 (same file).
- Behaviour: changes in one edge case: with a cache folder that cannot be written (read-only or full disk) `put` returns `False` and a later `probe` of the same file in the same run now runs ffprobe again; before, the memory layer answered. This includes `SourceService.store()` (`service.py:442-450` and `_store` below it, "so that `probe` and `get` return it"): a source stored with measured values (bit-rate scan, subtitle event counts) is returned by `get` through `_known`, but `probe` (which goes through `Prober._prepare` and the cache only) would no longer return it when the write fails. On a writable folder every hit costs one small file read (about 0.2 ms local). Say so in the commit.
- Contracts touched: none (the entry file layout is unchanged).
- Callers to update: none (`forget_memory` has 1 caller, `tests/probe/test_cache.py:64`; `memory_entries` 1, `test_cache.py:139`).
- Tests: delete `test_memory_layer_is_bounded` (`test_cache.py:138-144`) and `test_returned_sources_are_copies` (`:124-135`, always true when every `get` parses a file); remove `cache.forget_memory()` at `:64`; in `test_unwritable_directory_is_not_an_error` (`:147-156`) change the last assertion to `cache.get(...) is None`; in `test_cache_file_names.py:82` drop the "memory layer has it" assertion. Keep `test_hit_and_miss`, `test_invalidation`, the corrupt-entry, nesting and prune tests.
- Decision records: 0007 (item 2: nesting limit stays, `too_deep` is untouched).
- Size: S; estimated lines: -28 / -25
- Risk: low. `put`'s atomic `os.replace` already makes concurrent `get` safe.
- Depends on: none (do with PRB-05)
- Confidence: medium (measured on one probe; a very large source would shift both numbers the same way)
- Verdict: ADJUSTED (re-measured on the largest source that `parse_ffprobe` builds from `testdata/probes/`, `mkvmerge93-remux-pgs.json`, 11.7 KB of MediaSource JSON, 300 runs: `model_copy(deep=True)` 0.25 ms, file read + `json.loads` + `model_validate` 0.18 ms: the conclusion holds; the entry layout and `parser_fingerprint` are untouched, so no stale entry is possible; Behaviour bullet extended with the `SourceService.store()` contract in the unwritable-folder case; the `put` docstring and the module docstring line 1 also mention the memory layer)
- Orchestrator: Tier B, work package Q-6.13 (see ../plan.md).

### PRB-03: EBML basics exist four times (IDs, child walker, read loop, Seek entries)
- Kind: duplication
- Where:
  - Element IDs: `probe/sampling.py:55, 60, 61` (`_CLUSTER`, `_CRC32`, `_VOID`), `metadata/layout.py:31` (`_VOID`), `metadata/header.py:70-76` (`_VOID`, `_TRACK_TYPE`, `_NAME`, `_LANGUAGE`, `_LANGUAGE_IETF`, `_KINDS`), `metadata/ebml.py:31-32` (`VOID`, `CRC32`), against `probe/matroska.py:53-70, 84-97` (`_CLUSTER`, `_KINDS`, `_UINTS`, `_STRINGS`). `header.py:78-86` (`_FLAGS`) also repeats the six flag IDs and defaults that `matroska._UINTS` and `MatroskaTrack` already hold.
  - Child walker: `probe/sampling.py:133-171` (`_blocks`, twice: the cluster and the `BlockGroup`) does what `metadata/ebml.py:105-123` (`children`) does (known size, ends inside the parent, `budget.element()`), except that `children` stops at `MAX_CHILDREN` (4096).
  - Read-N-bytes loop (seek, read until `count` or EOF, join): `probe/matroska.py:348-363` (`_Reader.read`), `probe/sampling.py:92-110` (`_File.read`), `metadata/header.py:724-733` (`_read_at`). pylint reports the first two (`duplication.txt`, 12 lines).
  - Seek entry parse (`SeekID`, `SeekPosition` with the 4- and 8-byte limits): `probe/matroska.py:317-340` (`_seek_entries`) and `metadata/layout.py:129-148` (`_seek_head`).
- Now: Each module has its own copy, and `sampling.py`, `layout.py`, `header.py`, `ebml.py` reach into `matroska.py` for private names (`_header`, `_vint`, `_uint`, `_Budget`, `_Reader`, `_doc_type`, `_read`, nine ID constants in `header.py:36-45`). A fix in one copy (for example the `buffering=0` rule of 0081 "Built E", or a size limit) must be made again in the others.
- Change: Keep everything in `probe/matroska.py` (the tests patch `matroska._header` and `matroska._Reader.read`, so those names stay). Add there: `_VOID = 0xEC`, `_CRC32 = 0xBF`, and import `_CLUSTER`, `_KINDS` elsewhere instead of redefining; make `header._FLAG_IDS`, `_LANGUAGE`, `_NAME`, `_TRACK_TYPE` come from `matroska._UINTS` / `_STRINGS` (an inverse dict built once). Moving `Child` and `children` from `metadata/ebml.py` into `matroska.py` is not needed once `_blocks` stays (they have no second user; skip it). Leave `sampling._blocks` as it is (measured: `children` alone takes as long as the whole of `_blocks` today, see Behaviour). Add `def read_exactly(handle, pos, count) -> bytes` (seek, loop, join; keep the loop: `buffering=0` files return short reads) in `matroska.py`; `_Reader.read`, `_File.read` (after its window and budget checks) and `header._read_at` call it. Do not share `seek_entry` between `_seek_entries` and `_seek_head` unless it takes the already walked `(id, data)` pairs as its argument: the reader walks the `Seek` entry tolerantly (`_iter_children` through `islice(..., 8)`, an unknown size ends the walk, a short payload is cut) and the writer strictly (`children`: `MatroskaError` on an unknown size, an overrun or more than 4096 children), on purpose (see "Looked at and kept", the two walkers). Also delete `Layout.segment_pos` (`layout.py:76, 252`): 0 readers in `src`, `tests`, `testing` (`pos` stays: `size_pos=pos + id_len`).
- Behaviour: unchanged for the IDs, `read_exactly` and `segment_pos`. A `_blocks` on `children` would raise `MatroskaError` for the same inputs (unknown size or a child that ends past its parent; only the message text and which of two damages is named first change, because `children` walks the whole cluster before the checks on its children run), but it builds one `Child` per element on the sampler's hot path: re-measured with 60,000 `SimpleBlock`s of one cluster, `sampling._blocks` 69 ms, `ebml.children` alone 71 ms, so the rewrite would about double the CPU time of the cluster parse. A `seek_entry` that walks its children itself would make the reader strict or the writer tolerant.
- Contracts touched: none.
- Callers to update: `probe/sampling.py`, `metadata/{ebml,layout,header}.py` (IDs, `read_exactly`, `segment_pos`). No other file imports these names.
- Tests: no deletions. `tests/probe/test_sampling.py:235` (the overrunning child) and the header and layout suites are the guard. `tests/metadata/header/corpus.py:19`, `test_header_properties.py:23`, `test_header_layouts.py:15` import `_header`, `_Budget`, `_Reader` from `matroska`: unchanged. Add one test for `read_exactly` with a handle that returns short reads, if none exists.
- Decision records: 0080 ("H may import any name of `probe/matroska.py`"; "E keeps every existing name and signature there"), 0081 "Built E" (unbuffered reads). Both are kept: no name or signature of `matroska.py` goes.
- Size: S (without the `_blocks` rewrite and `seek_entry`); estimated lines: -30 / -0 (the new `read_exactly` adds about 10 lines; three loops of 8-10 lines go; the IDs save about 12 lines; `segment_pos` 2)
- Risk: low to medium. The header writer is the code that writes into user files (`header._read_at` is read by the torn-write recovery `_put_back`: its loop must stay equivalent, which `read_exactly` is). The changes are mechanical, and the oracle, property and fault-injection tests (`tests/metadata/header/`) run the same paths. Run `needs_mkvtoolnix` tests too.
- Depends on: none
- Confidence: high for the IDs, `read_exactly` and `segment_pos`; low for `_blocks` on `children` (CPU cost) and for `seek_entry` (tolerant against strict walkers): drop both
- Verdict: ADJUSTED (the `_blocks` rewrite doubles the cluster parse time, measured; `seek_entry` cannot be shared as proposed because the two Seek walkers differ on purpose; estimate -30 not -48; all anchors, the nine imported IDs, the 0 readers of `segment_pos`, the test patches of `matroska._header` (`test_matroska_limits_and_ietf.py:72`) and `matroska._Reader.read` (`:73`) are right; no existing test returns short reads, so the new `read_exactly` test is needed; `versions.py:10-11` also imports `children` and `_header`)
- Orchestrator: Tier B, work package Q-6.13 (see ../plan.md).

### PRB-04: `start_probe_folder` is an unused second copy of the service's folder task
- Kind: dead-code
- Where: `packages/reframe/src/reframe/probe/folder.py:192-220` (`start_probe_folder`), `:33` (`__all__`), `probe/__init__.py:22, 54`; imports `TaskInfo`, `TaskContext`, `TaskManager` in `folder.py:14-16, 18` if unused after.
- Now: `rg start_probe_folder` over the repository: 0 callers outside `folder.py`, `probe/__init__.py` and 3 tests (`tests/probe/test_folder.py:194, 231, 248`). The product runs `SourceService.probe_folder` (`service.py:353-405`), which does the same (`ctx.progress`, `probe_folder`, `to_json`, `TASK_KIND`) plus the NUL check, the tool-discovery wait and `_remember`. pylint flags the shared lines (`folder.py:208-217` against `service.py:389-396`). `TASK_KIND` stays (the service imports it).
- Change: Delete `start_probe_folder` and its re-exports. The service's `probe_folder` is the only task wrapper.
- Behaviour: unchanged (no caller).
- Contracts touched: public core API (one name, no product use).
- Callers to update: `tests/probe/test_folder.py` only.
- Tests: delete `test_folder_task_events` (`test_folder.py:182-214`): `tests/test_service.py:315` (`test_probe_folder_emits_task_events`) tests the same events through the service. Re-point `test_folder_task_with_fake_ffprobe` (`:220-240`) and `test_cancel_folder_task_kills_ffprobe` (`:242-260`) to `probe_folder(prober, folder, cancel=token)` without `TaskManager` (cancel through a `CancelToken`; the 4-at-a-time and kill-in-1.5-s assertions stay). `tests/test_service.py:157` also covers close killing a folder probe. Remove the unused `TaskManager`, `EventBus`, `TaskState` imports.
- Decision records: none apply (the plan says "Folder probe: a task with a concurrency limit (default 4) that reports progress", `05-core.md` C-3; the service meets it).
- Size: S; estimated lines: -22 / -45
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (0 callers in `packages/`, `testing/`, `scripts/`, `desktop/`, `docs/plan`, `docs/decisions`; the three test uses are at `test_folder.py:194, 231, 248`; the service's `probe_folder` meets the plan line. Note: `test_folder_task_events` asserts the exact event sequence, `test_probe_folder_emits_task_events` only a subset of the messages, so the deletion loses the exact-sequence check)
- Orchestrator: Tier A, work package Q-6.8 (see ../plan.md). SRV-01 (Q-6.14) later removes the rest of the folder probe; this entry is the safe first step.

### PRB-05: `MATROSKA_READER` and the cache `options` plumbing are covered by the source hash
- Kind: decision-change (0007 follow-up RB-7: "`MATROSKA_READER` stays in the cache options"; 0007 and 0034 record the number as the reader's cache version; 0081 "Built: E" records `cache_options()` as `{"matroska": 3}` and `{"matroska": 4}`). What would have to be true: the owner accepts that `parser_fingerprint()` plus `PARSER_VERSION` are the only cache levers, and that a note in 0007 and 0081 says `cache_options()` is gone.
- Where: `packages/reframe/src/reframe/probe/prober.py:65-69, 80-83` (`MATROSKA_READER`), `:163-165` (`Prober.cache_options`), `:178, 180, 193, 230, 246, 257, 323` (`options` threaded through `probe`, `_prepare`, `_probe_file`, `cache.get`, `cache.put`); `probe/cache.py:4, 107-111, 136-152, 172, 179, 181-203` (`options` argument, `_Entry.options`, the `"options"` key of the entry); `service.py:436, 516` (`options=prober.cache_options()`).
- Now: The cache option dict has one key, `{"matroska": 4}`, a number the developer bumps by hand when the reader or the sample changes. `parser_fingerprint()` already hashes `probe/matroska.py`, `probe/sampling.py` and `probe/prober.py` (`cache.py:57-71`); 0007 (follow-up RB-7) says "`MATROSKA_READER` stays in the cache options; a change to the reader no longer needs it raised". Since then it is a second, manual copy of what the hash does. In a frozen build (no source files) the fingerprint falls back to `reframe.__version__`, and the number is a constant 4 in every release, so it adds nothing there either. One test only pins the number (`test_matroska_limits_and_ietf.py::test_the_cache_options_name_the_new_reader`; Q-7.3 merged the `test_prober.py` one into it).
- Change: Remove `MATROSKA_READER`, `cache_options`, every `options` parameter and variable, `_Entry.options`, the `"options"` entry key and its check in `_read`. `ProbeCache.get(key, *, tool)` and `put(key, source, *, tool)`. Keep `PARSER_VERSION` (the manual lever for what the hash does not see: models, language tables). The edit changes `prober.py` and `cache.py`, which are in the hash, so every entry is a miss once (as for any parser change).
- Behaviour: unchanged for users; each cached probe runs once more. A new Reframe reading an old entry ignores its `options`; an old Reframe reading a new entry (no `options`) treats it as a miss (`cache.py:172`).
- Contracts touched: persisted probe-cache entry (the `options` key is dropped). CLAUDE.md asks for a `schema_version` bump, a migration and a down-level note for a removal in a persisted document. The entry is not a schema-versioned document, and no stale entry is possible in either direction: every entry carries `parser_fingerprint()`, which hashes `prober.py` and `cache.py` (both change here), so a new Reframe misses every old entry, and an old Reframe misses a new entry twice over (no `options` dict: `cache.py:172`; another fingerprint). The one-line `CACHE_FORMAT = 2` bump is free (`test_entry_layout` reads it by name) and follows the rule to the letter: prefer it. Edit 0007 and 0081 (a "Changed" note) in the same commit.
- Callers to update: `probe/prober.py`, `probe/cache.py`, `service.py:436, 516`.
- Tests: delete `test_the_cache_options_name_the_new_reader` (`test_matroska_limits_and_ietf.py`; it also holds what `test_cache_options_name_the_reader` in `test_prober.py` pinned), `test_deep_options_are_not_cached` (`test_cache_nesting.py:108-113`). Edit `test_cache.py:41-65, 114-120` (drop the `options` argument, the "other options" parametrize row at `:55`, and the `doc["options"]` assertion) and `test_cache_file_names.py:109`.
- Decision records: 0007 (RB-7 fingerprint, "stays in the cache options"; item 2 nesting: the depth check still covers the source), 0034 (item 5, the reader: "The probe cache's options get `"matroska": 1`"), 0081 "Built: E" (the fingerprint includes `sampling.py`; `cache_options()` values). The change keeps the fingerprint and `PARSER_VERSION` and drops the options number.
- Size: S; estimated lines: -24 / -22
- Risk: low
- Depends on: none (do with PRB-02)
- Confidence: medium (the code change is certain; it reverses a sentence of 0007 RB-7, so it needs the owner's yes)
- Verdict: ADJUSTED (kind is decision-change, not speculative-generality: 0007 RB-7 says the number stays, 0034 and 0081 record its values; the claim that the fingerprint covers what the number covers holds: `matroska.py`, `sampling.py`, `prober.py`, `parse.py`, `languages.py` and the tables are hashed, and in a frozen build both levers are constant per release; the "documents that cannot be rebuilt" wording is not in CLAUDE.md, so the persistence note is reworded and a `CACHE_FORMAT` bump is advised; anchors, callers (`service.py:436, 516`) and test lines checked)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### PRB-06: three constructors of `TrackMetadata` from a stream, and an unused `remux_job` parameter
- Kind: duplication
- Where: `packages/reframe/src/reframe/metadata/__init__.py:24-38` (`source_video_metadata`), `:41-61, 9, 46` (`remux_job(definitions=)`), against `packages/reframe/src/reframe/batch/resolve.py:59-74` (`video_metadata`) and `batch/metadata.py:30-59` (`effective_language`, `track_metadata`); also `batch/descriptors.py:~180-191` (`_flags`, same six flags). cross-area: batch.
- Now: All three build a `TrackMetadata` from `stream.language_ietf`/`language`, `title` and the six disposition flags. `video_metadata` differs only by `default=True`; `source_video_metadata` is `video_metadata` with `default=d.default`; `track_metadata` is the same for audio and subtitle streams. pylint flags `batch/descriptors.py:180-191` against `metadata/__init__.py:31-60`. `remux_job`'s `definitions` parameter is never read (`del definitions`; docstring: "the parameter is kept for the callers' contract"). Its one caller passes it (`jobs.py:673-675`); no test does.
- Change: Let `effective_language` and `track_metadata` take `AudioStream | SubtitleStream | VideoStream` (all three have `language_ietf`, `language`, `title`, `disposition`). `source_video_metadata(stream)` becomes `track_metadata(stream)`; `batch.video_metadata(stream)` stays as a public one-line name (`reframe.batch.__all__`, `reframe.jobs.__all__`, 3 uses in `tests/jobs/test_service.py`) and returns `track_metadata(stream).model_copy(update={"default": True})`. Delete `source_video_metadata` and call `track_metadata(source.video[0])` in `remux_job`. Delete the `definitions` parameter, `del definitions`, the `Definitions` import and the docstring sentence; drop `definitions=self.definitions` at `jobs.py:675`. Optionally let `descriptors._flags` reuse `track_metadata(stream)`'s flags (not needed).
- Behaviour: unchanged except one edge: for a video stream whose `language_ietf` is not a valid tag but whose `language` is, the language is now the valid one (as for audio and subtitle). The prober already sets an invalid `language_ietf` to `None` with a warning (`apply_matroska`), so a probed source cannot reach this.
- Contracts touched: public core API (`reframe.metadata.source_video_metadata` goes; `remux_job(definitions=)` goes; 0 other callers: `rg` finds `source_video_metadata` only in `metadata/__init__.py` and `tests/metadata/test_remux_job.py`).
- Callers to update: `reframe/jobs.py:673-675` (the `definitions=` argument; `jobs.py:20, 67` import and re-export `video_metadata`, which stays), `reframe/batch/resolve.py:59-74`, `reframe/batch/metadata.py:30-59`, `reframe/metadata/__init__.py`. `docs/core-breakdown.md:205` (a working document) lists the signature with `definitions=None`.
- Tests: `tests/metadata/test_remux_job.py:66, 87-96` use `source_video_metadata`: point them at `track_metadata`. `tests/jobs/test_service.py:22, 98, 292` use `video_metadata`: unchanged while it stays. Keep `test_remux_job.py` and `tests/command/test_metadata_edit.py` as the guard of the in-place edit's video flags.
- Decision records: 0034 / 0080 (an in-place edit changes only what the user changes: the video's `default` flag stays the source's). The change keeps that.
- Size: S; estimated lines: -24 / -8
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (the callers list missed that `video_metadata` is re-exported by `reframe.batch` and `reframe.jobs` (`__all__`) and used by `tests/jobs/test_service.py:22, 98, 292`: it stays as a thin wrapper, not deleted; `docs/core-breakdown.md:205` names the `definitions=None` signature; the VideoStream fields, the unused `definitions` parameter and the one caller `jobs.py:673-675` check out)
- Orchestrator: joined into X-08 (see ../cross-cutting.md); that entry decides the tier and the work package.

### PRB-07: EBML test builders written four times
- Kind: tests
- Where: `tests/probe/test_matroska.py:22-79` (`vint_size`, `element`, `uint`, `text`, `header`, `track`, `tracks`, `info`, `cluster`); `tests/metadata/header/corpus.py:85-95` (`encode_size`, `element`), `:23-33` (own copies of the element IDs); `tests/metadata/test_metadata_unusual_files.py:21-35` (`_element`, `_header`: a copy of `matroska._header`, which `corpus.py:19` imports from the product); `tests/probe/test_sampling.py:52-53` (`uint`, again). `tests/probe/test_sampling.py:42`, `test_sampling_media.py:28` and `test_matroska_limits_and_ietf.py:20` import the builders from another test module (`from .test_matroska import element, header, track, tracks`).
- Now: `element(id, payload)` exists three times with nearly the same job (ID bytes, size field, payload) but not the same bytes: `test_matroska.element` and `test_metadata_unusual_files._element` write a fixed 8-byte size field (and `test_matroska.element` also an unknown size with `unknown=True`), `corpus.element` the shortest size field or `width`; `uint` exists twice with another width rule (`test_matroska.uint` is one byte, `test_sampling.uint` the shortest). Three suites depend on `test_matroska.py` as a library. `testing/reframe_testing/blockscan.py` (the exact-block oracle) is independent of the product on purpose and stays.
- Change: Add `testing/reframe_testing/ebml.py` with `element`, `uint`, `text`, `vint_size`, and the Matroska test builders (`header`, `track`, `tracks`, `info`, `cluster`, `simple_block`). The four test modules import from it. Do not make the tests use `reframe.metadata.ebml.encode_*` (the writer's tests must not use the writer's encoder).
- Behaviour: unchanged (tests only).
- Contracts touched: none.
- Callers to update: the five test modules above and `tests/probe/test_matroska_limits_and_ietf.py`.
- Tests: all of them stay; they are the guard.
- Decision records: none.
- Size: M; estimated lines: -0 / -30 (the shared `element` needs a `width` and an `unknown` argument; `corpus.element` keeps its shortest-size default, so its callers pass the width they need; check the tests that compute byte offsets from the fixed 8-byte header before switching one)
- Risk: low
- Depends on: none
- Confidence: medium (the size of the saving depends on how much of `corpus.py` is reusable)
- Verdict: ADJUSTED (the builders are not identical: fixed 8-byte against shortest size fields and `uint` of one byte against the shortest; a shared module needs the arguments; estimate -30 not -50; the anchors and the three `from .test_matroska import` lines check out)
- Orchestrator: Tier A, work package Q-6.2 (see ../plan.md).

### PRB-08: `batch.descriptors.CODEC_LABELS` copies `probe/names.py`
- Kind: duplication
- Where: `packages/reframe/src/reframe/batch/descriptors.py:71-96` (`CODEC_LABELS`, 24 entries), `:37` (its `__all__` entry), `:127-133` (`codec_label`), `:195`; `batch/rules.py:24, 125, 132`; against `packages/reframe/src/reframe/probe/names.py:24-43, 105-130, 153-170` (`_VIDEO_BASE`, `_AUDIO_BASE`, `_SUBTITLE_NAMES`). cross-area: batch.
- Now: All 24 entries of `CODEC_LABELS` are also keys of `_VIDEO_BASE`, `_AUDIO_BASE` or `_SUBTITLE_NAMES` with the same text (checked with a script: 0 mismatches; the three `names` tables share no key, so a lookup in turn is unambiguous). `codec_label(stream)` already prefers `stream.display_codec` (made from `names`); `CODEC_LABELS` is only the fallback for a stream without one and the label of a rule's selector.
- Change: Add `def codec_name(codec: str) -> str` in `names.py` (the three base tables in turn, else the codec itself) and use it where `CODEC_LABELS.get(x, x)` is used (`descriptors.py:133`, `rules.py:125, 132`); `descriptors.py:195` keeps its "unknown codec" default with `names.codec_name(...) if codec else "unknown codec"`. Delete the dict.
- Behaviour: changes in a few labels: a codec that `names` knows but `CODEC_LABELS` does not (`vp8`, `mpeg1video`, `vc1`, `ac4`, `wmav2`, …) now shows its proper name in a batch row label instead of the raw codec name or "unknown codec". Nothing else.
- Contracts touched: none (label text of the batch matrix and rule explanations; HTTP responses carry the text, but no schema).
- Callers to update: `batch/descriptors.py`, `batch/rules.py`.
- Tests: none expected to change: a search of `tests/batch`, `reframe-server/tests` and `frontend/src` for the 34 codecs that `names` knows and `CODEC_LABELS` lacks finds no expected label text (the hits are `convert_to="srt"` and `codec_family` cases).
- Decision records: none found.
- Size: S; estimated lines: -20 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (re-run: 24 of 24 entries equal, no key shared between the three `names` tables; the `__all__` entry at `descriptors.py:37` was missing from "Where"; the tests bullet is now checked)
- Orchestrator: Tier B, work package Q-6.13 (see ../plan.md).
- Note (Tier B review, RB-1): the Behaviour line missed a second change. A codec that neither `names` nor the old `CODEC_LABELS` knows (`jacosub`, `pcm_s16le`, …) now shows its raw ffprobe codec name in `track_label`, not "unknown codec" (`eng jacosub`, was `eng unknown codec`). The code is kept; the change is announced in the Consequences of 0086 and pinned by `test_labels` in `tests/batch/test_descriptors.py`.

### PRB-09: file checks of a probe written twice (service and prober)
- Kind: duplication
- Where: `packages/reframe/src/reframe/probe/prober.py:226-249` (`Prober._prepare`: `os.stat`, `NOT_FOUND`, `UNREADABLE`, `NOT_A_FILE`) and `packages/reframe/src/reframe/service.py:651-671` (`_check_file`: the same three results, then NUL and a real `open`); call sites `service.py:316, 344`. cross-area: service.
- Now: `SourceService.probe` runs `_check_file` and then `prober.probe`, whose `_prepare` stats the file again with identical results and messages. pylint flags it (`prober.py:234-243` against `service.py:657-666`).
- Change: In `prober.py` add `def stat_regular(file: Path) -> os.stat_result | ProbeError` (the 8 shared lines); `_prepare` calls it. `service._check_file` becomes: NUL check, `stat_regular(file)` (returns the error if any), then the `open` check.
- Behaviour: unchanged.
- Contracts touched: none (a new function in the probe module).
- Callers to update: `probe/prober.py`, `service.py`.
- Tests: none change (`tests/probe/test_prober.py` and `tests/test_service*.py` guard the messages).
- Decision records: none.
- Size: S; estimated lines: -8 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (`_check_file` is called at `service.py:316` and `:344` only, the latter for `inspect_subtitle`; messages equal; `_absolute(path)` and `Path(os.path.abspath(path))` give the same file)
- Orchestrator: Tier A, work package Q-6.8 (see ../plan.md).

### PRB-10: the language-tag shape is checked in four places
- Kind: duplication
- Where: `packages/reframe/src/reframe/models/base.py:67-70` (`LanguageTag`), `probe/parse.py:68` (`_LANGUAGE_RE`, used at `:168, 177`), `probe/prober.py:86, 452-458` (`_LANGUAGE_TAG` as a `TypeAdapter`, `_is_language_tag`), `languages.py:120-122` (`_TAG_SHAPE`, `_MAX_TAG_LENGTH`).
- Now: One regex (`^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$`) and the 64-character limit appear in four modules, in three forms. `parse._bcp47` also re-checks the shape and length of a value that `languages.normalize` just returned (its result already passed `_TAG_SHAPE`, `languages.py:491`; whether it can be longer than 64 was not checked: keep the length check unless a test shows it cannot).
- Change: In `models/base.py` define `LANGUAGE_TAG_PATTERN`, `MAX_LANGUAGE_TAG`, and `def is_language_tag(value: str) -> bool`; `LanguageTag` uses the pattern; `parse.py`, `prober.py` and `languages.py` import them. Delete the `TypeAdapter` and `ValidationError` use in `prober._is_language_tag`.
- Behaviour: unchanged.
- Contracts touched: none (the pydantic pattern text stays the same, so the JSON Schema snapshot does not change).
- Callers to update: the four modules above.
- Tests: none change.
- Decision records: none.
- Size: S; estimated lines: -10 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (use `fullmatch` in the shared `is_language_tag`: `parse._LANGUAGE_RE.match` with `$` would accept a trailing newline, but both its inputs cannot carry one: `_language` strips first, `_bcp47` gets `normalize`'s output; `languages.py` also uses the bare pattern at `:465, 482, 491, 561`, so the module must export the compiled pattern, not only the function)
- Orchestrator: Tier A, work package Q-6.8 (see ../plan.md).

### PRB-11: `layout_hash` / `SourceFingerprint.probe_hash` is written and never read
- Kind: decision-change (the plan, `05-core.md:115`, names the field; CLAUDE.md: a plan change needs a decision record in the same commit). What would have to be true: the owner accepts that a source's fingerprint is size and mtime only.
- Where: `packages/reframe/src/reframe/probe/parse.py:591-606` (`layout_hash`), `:54, 683` (the call, `__all__`), `packages/reframe/src/reframe/models/media.py:69-70` (`SourceFingerprint.probe_hash`).
- Now: `rg probe_hash` over `packages/`, `frontend/src` (not the generated `schema.d.ts` or JSON fixtures), `desktop/`, `scripts/`: only the writer above, the model field, and three test assertions that it is set or differs (`tests/probe/test_prober.py:96`, `test_parse.py:280, 285`). Nothing compares it; `fingerprint` equality in the service uses `size` and `mtime` only (`service.py:640-642`). The plan names it (`05-core.md:115`: "path + fingerprint (size, mtime, probe hash)").
- Change: Delete `layout_hash` and the `model_copy(update=...)` line; delete the field. Edit `05-core.md:115`. Regenerate the OpenAPI types (`scripts/gen-api.sh`: `frontend/src/api/schema.d.ts:6437` loses the field), the schema snapshot (`tests/models/__snapshots__/test_schema.ambr`) and the probe snapshots (61 `probe_hash` lines in `tests/probe/__snapshots__/test_snapshots.ambr`); remove `probe_hash` from `frontend/src/components/matrix/testing/anime-s01.json` (26 lines). Cheaper option: keep the field in the model (optional, default `None`, no schema change) and only delete `layout_hash`, the call and the test assertions: then nothing a persisted document or the API says changes.
- Behaviour: unchanged for users (nobody reads it). Both options change the JSON a client sees (`fingerprint.probe_hash` is `null`, or the field is gone, in `reframe probe --json` and in the source responses of the API; no test and no frontend code reads it).
- Contracts touched: the cheap option also changes all 61 `probe_hash` values of `tests/probe/__snapshots__/test_snapshots.ambr` to `None` (the snapshot test passes a fingerprint, so `layout_hash` filled it): run `uv run pytest --snapshot-update` on that test. HTTP/OpenAPI (full removal: `SourceFingerprint` loses `probe_hash`; frontend types and one fixture change), persisted schema (a field removal in `SourceRef`, which is inside job settings and `MediaSource`; the persistence rules ask for a `schema_version` bump and a down-level note for removals; `DocumentModel` keeps the old value as an unknown field, an older version reads a missing optional field as `None`). Because of the bump, take the cheaper option unless a schema bump happens anyway.
- Callers to update: `probe/parse.py`, `models/media.py` (full removal), `frontend/src/api/schema.d.ts`, the fixture.
- Tests: delete `test_fingerprint_gets_the_layout_hash` (`test_parse.py:275-287`: the whole test is about the hash; keep its last line, `parse_ffprobe(data, FILE).ref.fingerprint is None`, in another test) and the assertion at `test_prober.py:96`; update the 61 snapshot values; the cheap option keeps the model tests as they are.
- Decision records: none found (0006/0007 do not mention it); the plan line `05-core.md:115` is the only mention in `docs/`.
- Size: S (cheap option) or M (full); estimated lines: -17 / -10
- Risk: low (cheap option); medium (full: snapshot churn and a migration)
- Depends on: none
- Confidence: medium (the plan names the field; the evidence of no reader is complete)
- Verdict: ADJUSTED (no reader found again in `packages/`, `frontend/src`, `desktop/`, `scripts/`, `testing/`, `docs/`; kind is decision-change because the plan names the field; the cheap option still changes the 61 probe snapshots; the test to delete is one whole function, not three assertions; the client-visible JSON changes in both options)
- Orchestrator: joined into X-09 (see ../cross-cutting.md); that entry decides the tier and the work package. The verifiers disagreed on the kind (MOD-07 called the `layout_hash` part plain dead code, this file a `decision-change`). Settled: the plan names the field only in a sketch comment, with no reason, and no code reads it, so rule 7 accepts it at Tier B. The cheap option (stop writing it, keep the field declared) is the one to make.

### PRB-12: small leftovers in the prober and sampler
- Kind: structure
- Where: `probe/prober.py:495-504` (`probe_file`), `:155, 160, 343, 370` (`Prober(frame_timeout=)`), `:403-449` (`_sample`, `_read_matroska`), `:461-462` (`_shown`); `probe/sampling.py:308-314` (`sample_clusters(samples=)`); `chapters.py:89-90` (`_shown`).
- Now: `probe_file` has 0 callers in `src` (3 test uses: `tests/probe/test_prober.py:286`, `tests/dimensions/test_ffmpeg.py:75`, and a child script in `test_sampling_media.py:293-295`); `Prober(frame_timeout=)` is never passed (0 callers, 0 tests), so `FRAME_TIMEOUT` can be used directly; `sample_clusters(samples=)` is never passed. `_sample` and `_read_matroska` have the same shape (run a blocking read in a thread, race it with cancel and a time limit, map `TimeoutError` and `OSError` to `_NOT_RUN`, a damaged-file error to `None`, log each). `_shown` is the same 3-line function in `prober.py` and `chapters.py`.
- Change: Delete `probe_file` (and its `__all__` entries in `prober.py` and `probe/__init__.py`; tests call `Prober(tool, ...).probe(path)`; also the `:func:`probe_file`` mentions in the docstrings of `probe/__init__.py:4`, `probe/prober.py:4` and `probe/bitrate.py:5`); delete the `frame_timeout` argument and attribute; delete the `samples` argument (use the constant `SAMPLES` at `sampling.py:333-342`); fold `_sample` and `_read_matroska` into one helper `_worker(file, call, timeout, cancel, damaged, what)` that returns `T | _Cancelled | _NotRun | None`. The two differ in the damaged-file exceptions (`_sample`: `ArithmeticError`, `ValueError`; `_read_matroska`: `matroska.MatroskaError`, which is not a `ValueError`), in the log text (`what`), and `_sample` sets its `stop` event in a `finally` (the sampler keeps it through the `call` closure, and `finally: stop.set()` must stay); one `_shown` kept in `reframe.models.text` (it already holds `replace_undecodable`) and imported by both.
- Behaviour: unchanged.
- Contracts touched: public core API (`probe_file`, `Prober.frame_timeout`, `sample_clusters(samples=)`: no product use).
- Callers to update: the three test uses of `probe_file`, and the docstrings that name it. Decision 0081 (the review table, line 326) names `probe_file` as history: leave it.
- Tests: re-point those three; the prober fault tests (`test_prober.py`, `test_sampling.py` timeout and OSError cases) guard the worker helper.
- Decision records: 0081 "Built E" item "limits" (the 30 s limit, cancel and OSError rules stay).
- Size: S; estimated lines: -25 / -6
- Risk: low
- Depends on: none
- Confidence: medium (the helper merge is a taste call; the deletions are certain)
- Verdict: ADJUSTED (`probe_file`, `frame_timeout` and `samples=` have the callers stated: re-checked over `packages/`, `testing/`, `scripts/`, `desktop/`; the missing details are the three docstring mentions of `probe_file`, and that `_sample` and `_read_matroska` differ in the damaged-file exception classes and the `finally: stop.set()`, so the helper takes the exception tuple)
- Orchestrator: Tier B, work package Q-6.13 (see ../plan.md).

### PRB-13: the fake-prober helper is written four times in the probe tests
- Kind: tests
- Where: `tests/probe/test_prober.py:57-73` (`streams_rule`, `stdout_file`, `make_prober`), `tests/probe/test_sampling.py:433-438` (`_fake_prober`), `tests/probe/test_folder.py:216-217` (`_fake_prober`), `tests/probe/test_sampling_media.py:267` (inline), and the rule `ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=[{"stdout_file": …}])` written out in `test_folder.py` (3×), `test_sampling.py`, `test_sampling_media.py`, `test_prober.py` (6 in the probe tests, 15 in `packages/` and `testing/`); `tests/test_service.py:65` has a second `stdout_file`.
- Now: 6 copies of the same rule in the probe tests (15 in the repository), 4 of `Prober(ProbeTool(str(fake.ffprobe), version="n-fake"))`.
- Change: Move `streams_rule`, `stdout_file` and `make_prober` to `tests/probe/conftest.py` (or `testing/reframe_testing/fake_tools.py` for `streams_rule` and `stdout_file`, which `test_cli.py`, `test_service*.py`, `test_facade.py` also need), and use them.
- Behaviour: unchanged (tests only).
- Contracts touched: none.
- Callers to update: the test modules above.
- Tests: all stay.
- Decision records: none (0004: shared test infrastructure lives in `testing/reframe_testing/`).
- Size: S; estimated lines: -0 / -20
- Risk: low
- Depends on: none (touches `test_folder.py` like PRB-04: do one after the other)
- Confidence: medium
- Verdict: CONFIRMED (counts checked: the rule is written out 15 times in `packages/` and `testing/`, 6 of them in `tests/probe/`; `tests/test_service.py:65-70` and `tests/jobs/conftest.py:186` have two more variants)
- Orchestrator: Tier A, work package Q-6.8 (see ../plan.md). Moved into Q-6.8 with PRB-04, because both edit `tests/probe/test_folder.py`.

### PRB-14: small duplicates in `textfile.py` and `chapters.py`
- Kind: duplication
- Where: `packages/reframe/src/reframe/textfile.py:25-33` (`_BOMS`), `:57-59` (`detect_charset`); `packages/reframe/src/reframe/chapters.py:94-104` (`_decode`: its own BOM list and the same "UTF-32LE first" comment), `:414` (`chapter_export` strips the suffix by hand).
- Now: The byte-order-mark table is in two modules (five marks each). `detect_charset` is `charset_of(...).name` and has no product caller: `analysis/subtitlefile.py:17, 20` imports it only to re-export it in `__all__` (the file calls `read_charset` at `:103`), and the 4 uses are in `tests/analysis/test_subtitlefile.py`; `charset_of` is called by `read_charset` (`textfile.py:103`) and `detect_charset`. `chapter_export` computes `name_of.name[: -len(name_of.suffix)]`, which is `PurePath.stem`.
- Change: Put the encoding name for Python in the `_BOMS` table of `textfile.py` as a third column (or one table of `(mark, label, codec)`) and let `chapters._decode` use `textfile`'s table; delete `detect_charset` (and its `__all__` entry at `textfile.py:18`; there is no caller to inline it into): remove the import and the `__all__` entry in `analysis/subtitlefile.py:17, 20`; use `name_of.stem`.
- Behaviour: unchanged (`PurePath.stem` equals `name[: -len(suffix)]`, also for a trailing dot).
- Contracts touched: `reframe.analysis.subtitlefile.detect_charset` and `reframe.textfile.detect_charset` (two public names, no product use).
- Callers to update: `analysis/subtitlefile.py` (import and `__all__` only), `chapters.py`.
- Tests: `tests/analysis/test_subtitlefile.py:8, 30, 35, 36` use `detect_charset` (imported from `reframe.analysis.subtitlefile`): point them at `charset_of(...).name` (the file already imports `charset_of` at `:9`).
- Decision records: none.
- Size: S; estimated lines: -12 / -0
- Risk: low
- Depends on: none
- Confidence: medium
- Verdict: ADJUSTED (`detect_charset` is not called in `subtitlefile.py`, only re-exported, so "inline into its caller" is wrong: delete it; `charset_of` has a product caller, `read_charset`; the 4 test places and the `PurePath.stem` equivalence check out)
- Orchestrator: Tier B, work package Q-6.13 (see ../plan.md).

### PRB-15: two folder-of-JSON caches with their own atomic write and prune
- Kind: duplication
- Where: `packages/reframe/src/reframe/probe/cache.py:181-236, 238-268` (`put`: `mkstemp`, `os.fdopen`, `os.replace`; `prune`), `packages/reframe/src/reframe/capabilities/cache.py:165-200` (`put`, `prune`: the same steps), against `packages/reframe/src/reframe/settings.py:106-117` (`replace_file`, with the Windows retry that the two caches lack). cross-area: capabilities, settings.
- Now: `probe/cache.py` and `capabilities/cache.py` both write an entry as a temp file in the cache folder and replace it, both remove left-over temp files and keep the newest N entries, both digest a key to a file name. `settings.replace_file` retries a Windows `PermissionError`; the probe cache returns `False` instead (documented: "the target is open elsewhere"), the capabilities cache logs a warning.
- Change: One helper in `reframe/settings.py` (or a new small module): `write_entry(directory, name, text) -> bool` (mkstemp, write, `replace_file`) and `prune_folder(directory, suffix, *, max_entries, max_age=None, now=None) -> int`; both caches call them. Only worth doing if the capabilities audit finds the same; decide there.
- Behaviour: unchanged except that the Windows retry applies to both caches (an entry is written more often instead of skipped). That is a Windows-only path: it needs a check on the Windows test VM (a mock test on Linux for `replace_file` already exists). The two caches also differ in what a helper must parameterise: temp-file name (`.<digest>-*.tmp` against `.tmp-*.json`), file encoding (ASCII `ensure_ascii` compact text against UTF-8 with `indent=1`), prune cadence (every 200th `put` against every `put`), prune rules (age plus count against count only) and the return value of a failed write (`False` against a logged warning).
- Contracts touched: none.
- Callers to update: `probe/cache.py`, `capabilities/cache.py`.
- Tests: `tests/probe/test_cache.py` (`test_replace_failure_is_not_an_error`, `test_prune_by_age_count_and_leftovers`) and `tests/capabilities/test_cache.py` guard it.
- Decision records: 0015 (settings and presets stores: atomic write and the Windows retry) for `replace_file`; 0007 item 2 (the nesting check stays in the probe cache).
- Size: M; estimated lines: -30 / -0
- Risk: low
- Depends on: PRB-02 (same file)
- Confidence: low (not measured end to end; the two prune rules differ: age plus count against count only)
- Verdict: ADJUSTED (anchors, the missing Windows retry and the two prune rules are right; added that the Windows-only path needs a check on the Windows test VM and the other differences a shared helper must parameterise: temp-file name, encoding, prune cadence, failure result)
- Orchestrator: joined into X-10 (see ../cross-cutting.md); that entry decides the tier and the work package.

## Looked at and kept

- `Prober` single flight (`_flights`, `_Flight`, `_land`, `prober.py:138-146, 184-218`): several callers can probe one file at once (the service's `probe`, `draft`, folder probes, the batch engine). It came from the M1 review and has a test (`test_concurrent_probes_of_one_file_share_one_ffprobe`). No evidence that no caller overlaps, so it stays.
- `matroska._read` against `layout.read_layout`: two walkers of the same front matter. They differ on purpose: the reader tolerates damage so a probe keeps `language_ietf` and the estimate; the writer refuses (`Refusal`) anything it cannot trust (0080 items 3-4). One walker would need a strict flag.
- `header.py` `_check`, `_Overlay`, `_read_state`, `_expected` (the runtime self-check that every planned state reads as old or new): a guard against layouts the planner gets wrong on real files. 0080 names that risk ("Reframe owns code that writes into the user's source file"). Removing it can damage a user's file.
- `header.py` `_leftovers`, `_after_failure`, `_put_back`, `HeaderBackup`, `_short_of_space`, the `Void` and `SeekHead` moves, `versions.py`, and `own_thread.py`: 0080 items 3-4 and its FW/FE review fixes (power-cut and cancel behaviour, `DocTypeVersion`).
- `probe/matroska.py` `_Budget` and the `MAX_*` limits, `sampling.py` limits (`MAX_SAMPLE_READ`, 30 s, windows, the whole-segment and in-a-row modes), unbuffered reads: 0034, 0081 items 3 and "Built E", and the CIFS finding in 0081.
- `probe/cache.py` nesting limits (`too_deep`), ASCII escapes for non-UTF-8 paths, `prune`, `parser_fingerprint` and its file list, `PARSER_VERSION`: 0007 item 2, M1 review, 0081 FE item 4, 0082 item 2. (`MATROSKA_READER` is the one cache number that can go, PRB-05, a decision-change; `PARSER_VERSION` stays as the manual lever for models and tables that the hash does not cover.)
- `bitrate.check_stats_tags(compressed=)` and the stats-tag rules in `parse.py` (`_vfr_decision`, `_Context`): 0081 item 2.
- `parse.py` lenient helpers (`_text`, `_float`, `_int`, `_nonneg`, `_tags`): real ffprobe output varies (recorded probes in `testdata/probes/`).
- `roles.py`, `names.py`, `hdr.py` keyword and name tables: 0006 and plan C-3.
- `languages.py` port of the langcodes algorithms (parser quirks, alias tables, `closest_match`, the lazy locale and search tables) and `tests/languages/oracle.py` plus `test_equivalence.py` (about 640 lines, 150 s in CI): 0082 items 2, 4 and 5. The oracle is the check for each CLDR update, so it stays. If the owner wants the repository smaller, the decision to change is 0082 item 5; not proposed.
- `chapters.py` (CSV, OGM and XML read and write, the own expat tree that refuses entities and reports line numbers) and `textfile.open_regular` (a FIFO named like a text file must not block): plan features and `testdata/README.md` formats.
- `ProbeTool.of` taking four kinds of argument: the service passes a `ToolInfo`; tests and `probe_file` users pass paths. Small, and the callers exist.
- `OwnThread`: two product callers (`queue/runner.py:551`, `preview/clip.py:280`), 0080.
