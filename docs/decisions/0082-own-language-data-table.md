# 0082 — A generated language table replaces langcodes and language_data at run time

- Status: accepted
- Date: 2026-11-15
- Steps: C-20 (new); also C-6, Q-5

## Context

`reframe.languages` (C-6) is built on `langcodes` 3.5 and `language_data` 1.4 (which needs
`marisa-trie`, a compiled library). It uses them for:

- **Tags**: parsing and checking any BCP 47 tag against the IANA registry, and the canonical
  form (`iw` → `he`, `aa-AN` → `aa-CW`); ISO 639-1, 639-2/B, 639-2/T and 639-3 codes; the
  macrolanguage (`yue` → `zh`, for the Matroska `Language` element).
- **Names**: the English name (`display_name("en")`) and the native name (`autonym()`) of any
  tag. Both reach users: the picker, and the `{lang_name}` and `{lang_native}` variables of
  track-name templates (`batch/rules.py`, `batch/audio_rules.py`), for any track language,
  `de-AT` too.
- **Name search**: `Language.find` turns a name in any of 356 CLDR locales into a tag. The
  picker uses it when nothing in its list matches (`allemand`, `német`), and `normalize` uses it
  for names.

The installed size is about 27 MB: `language_data` 24 MB (of it 9.9 MB of name tries and
4.5 MB of names per locale), `langcodes` 1.3 MB, and `marisa-trie`. Every package ships it.

### The check (2026-11-15, `langcodes` 3.5.1, `language_data` 1.4.0)

A scratch script built the table that a dev-time script would generate from the two libraries,
and compared it with today's functions:

| What | Result |
|------|--------|
| Core table: every IANA language subtag (8213) with its canonical tag, English name, native name and ISO codes; English names of every script (209), region (304) and variant (108); the picker list | 774 KB JSON, 167 KB gzipped, built in 0.4 s |
| English names of 138,778 tags (every listed base language × every region, × 60 scripts, and the list) | **All equal** when composed as `Language (detail, detail)`, with two rules: a script that is the language's IANA `Suppress-Script` is left out (`ar-Arab` → "Arabic"; holds for all 131 such languages), and `und`, `mul`, `zxx`, `mis` with a detail compose as "Unknown language (…)" (331 tags) |
| `normalize` of 8248 one-subtag inputs (every registry language subtag, the listed tags, deprecated and ISO 639-2/B codes) | All equal but `hbs`, which `OVERRIDES` already handles in code |
| Native names of variants that are not in the list (`de-AT` → "Deutsch (Österreich)") | Need the region and script names in each locale: 2.06 MB, 632 KB gzipped for all 356 locales |
| Name search without the names in other locales | Of 60,535 names of the listed languages in all CLDR locales, today 60,313 resolve; with English and native names only, 10,471 do. **49,842 are lost**, for example `német`, `Ungarisch`, `allemand`, `アファル語` |
| Those names kept in the table | 2.02 MB, 618 KB gzipped (1.35 MB, 396 KB for the listed languages only) |
| English names of every registry language as search input | 18 of 8213 resolve differently: duplicate or ambiguous names (`Geji` is `gyz` and `gji`; `Serbian (Montenegro)` gives `sr` today, `sr-ME` from the table) |

Not checked by this run: the canonical form of tags with more than one subtag (extlang, a
grandfathered tag, region and variant aliases), and the exact rule of langcodes' fuzzy name
match (a prefix of at least 4 characters, which today turns `achenés` into `yif`).

## Decision

1. **A generated data file replaces `langcodes`, `language_data` and `marisa-trie` at run
   time.** `scripts/gen-language-data.py` builds it from the two libraries, which move to the
   dev dependency group. The file is committed in `reframe/definitions/data/` and read with
   the standard library.
2. **Everything stays as it is now. Nothing is dropped.** The file holds:
   - the IANA registry subtags with their type, `Deprecated`, `Preferred-Value`,
     `Suppress-Script` and `Macrolanguage` fields;
   - the alias tables that langcodes applies, and the canonical tag of each language subtag;
   - ISO 639-1, 639-2/B, 639-2/T and 639-3 codes;
   - English names of languages, scripts, regions and variants, and native names;
   - region and script names in each locale, for the native name of any variant;
   - language names in each locale, for the name search, with langcodes' name normalisation
     and its matching rules, so `német` still finds Hungarian's word for German.
3. **Split into a core part and lazy parts.** The core part (codes, canonical forms, English
   and native names) is read at the first use. The names per locale are read only when a
   native name of an unlisted variant or a name search needs them.
4. **`reframe.languages` keeps its public API and its results.** Its implementation reads the
   table. A deliberate change of a result (for example dropping the fuzzy prefix match) is a
   separate decision.
5. **Checks** (dev and CI, with the libraries installed):
   - `scripts/gen-language-data.py --check` fails when the committed file differs from a new
     build;
   - an equivalence test compares `normalize`, `english_name`, `native_name`,
     `to_matroska_legacy`, `to_mp4`, `search` and `matches` with the library-based results over
     a fixed corpus: every registry language subtag, every listed base language with every
     region and script, deprecated, extlang and grandfathered tags, and the names of every
     listed language in every locale.
6. **Licences**: the file holds CLDR and IANA registry data. The notices (Q-5) carry their
   terms instead of the entries of the three libraries.
7. **When**: in M10, before the release checklist (step C-20).

## Consequences

- About 27 MB and one compiled dependency leave every package. The file is about 4.8 MB
  (about 1.4 MB gzipped).
- An update of CLDR or the IANA registry is a run of the script and a commit, no longer a
  dependency update. Dependabot no longer sees it, so the release checklist gets a line to
  build the file again from the newest library versions.
- The 18 ambiguous English names show that "the same results" needs one rule per tie. The
  equivalence test fixes each one to today's result.
- To revisit: the native names of unlisted variants (632 KB gzipped) and the names in other
  locales (618 KB) are the large parts. If the size matters later, they can be cut down, but
  only with a decision, because users see both.

## Plan changes

- `05-core.md`: new section **C-20 Language data table**; the core's dependency list; C-6's
  `languages.py` line.
- `02-architecture.md`: the Languages row of the stack table.
- `07-desktop-app.md`: the PyInstaller hidden-imports note (langcodes data).
- `08-roadmap.md`: C-20 in M10.
- `09-quality-and-release.md`: the licensing table (CLDR and IANA data).
