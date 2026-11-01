// Test data shaped as the real server sends it: `naming/preview` of a copy of multitrack.mkv
// at `Hacksaw.Ridge.2016.…-HenDerson/hacksawridge.2160p.remux-henderson.mkv`.
import type { NameResult, NamingOptions, ValidationIssue } from '@/api/types'
import type { NamingVariable } from '@/stores/system'

const FOLDER = 'Hacksaw.Ridge.2016.2160p.UHD.BluRay-HenDerson'

export function hacksawResult(overrides: Partial<NameResult> = {}): NameResult {
  return {
    source: 'folder',
    reason:
      'Folder name: 5 fields recognised, title with word separators (7 points); file name: 3 fields recognised (3 points)',
    season_pack: false,
    candidates: [
      {
        kind: 'file',
        text: 'hacksawridge.2160p.remux-henderson',
        path: `/media/${FOLDER}/hacksawridge.2160p.remux-henderson.mkv`,
        score: 3,
        recognised: ['title', 'resolution', 'release_group'],
        word_separators: false,
        fields: { kind: 'movie', name: 'hacksawridge', resolution: '2160p', separator: '.' },
        spans: [
          { field: 'name', start: 0, end: 12, text: 'hacksawridge' },
          { field: 'resolution', start: 13, end: 18, text: '2160p' },
          { field: 'other', start: 19, end: 24, text: 'remux' },
          { field: 'release_group', start: 25, end: 34, text: 'henderson' },
        ],
      },
      {
        kind: 'folder',
        text: FOLDER,
        path: `/media/${FOLDER}`,
        score: 7,
        recognised: ['title', 'year', 'resolution', 'source', 'release_group'],
        word_separators: true,
        fields: {
          kind: 'movie',
          main_title: 'Hacksaw.Ridge',
          name: 'Hacksaw.Ridge',
          year: 2016,
          source_type: 'UHD.BluRay',
          release_group: 'HenDerson',
          resolution: '2160p',
          separator: '.',
        },
        spans: [
          { field: 'name', start: 0, end: 13, text: 'Hacksaw.Ridge' },
          { field: 'year', start: 14, end: 18, text: '2016' },
          { field: 'resolution', start: 19, end: 24, text: '2160p' },
          { field: 'source_type', start: 25, end: 35, text: 'UHD.BluRay' },
          { field: 'release_group', start: 36, end: 45, text: 'HenDerson' },
        ],
      },
    ],
    skipped_folders: [],
    fields: {
      kind: 'movie',
      main_title: 'Hacksaw.Ridge',
      name: 'Hacksaw.Ridge',
      year: 2016,
      source_type: 'UHD.BluRay',
      release_group: 'HenDerson',
      resolution: '2160p',
      separator: '.',
    },
    template: '{main_title}',
    template_kind: 'movie',
    relative_path: 'Hacksaw.Ridge.mkv',
    path: '/output/Hacksaw.Ridge.mkv',
    extension: 'mkv',
    variables: { main_title: 'Hacksaw.Ridge', name: 'Hacksaw.Ridge', year: '2016', season: '' },
    notes: [],
    issues: [],
    ...overrides,
  }
}

/** What the server says about `{main_titel}`. */
export function unknownVariable(template = '{main_titel}'): ValidationIssue {
  return {
    severity: 'error',
    code: 'naming.unknown_variable',
    path: 'output.naming.template',
    message: 'Unknown variable {main_titel} (position 1). Did you mean {main_title}?',
    fixes: [
      {
        label: 'Use {main_title}',
        patch: [
          { op: 'add', path: '/output/naming/template', value: template.replace('titel', 'title') },
        ],
        target: 'job',
      },
    ],
  }
}

export function namingOptions(overrides: Partial<NamingOptions> = {}): NamingOptions {
  return {
    movie_template: '{main_title}',
    episode_template: '{main_title}',
    name_source: 'auto',
    word_separator: 'keep',
    title_case: false,
    replace_underscores: false,
    remove_punctuation: false,
    mp4_extension: 'mp4',
    output_folder_mode: 'fixed',
    output_folder: '/output',
    ...overrides,
  }
}

/** What jsdom lacks and PrimeVue's Select and overlays use. */
export function stubDom(): void {
  globalThis.ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  window.matchMedia ??= (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}

export const VARIABLES: NamingVariable[] = [
  { name: 'main_title', group: 'name', kind: 'text', description: 'The main title' },
  { name: 'name', group: 'name', kind: 'text', description: 'Title only' },
  { name: 'year', group: 'name', kind: 'number', description: 'Release year' },
  { name: 'season', group: 'name', kind: 'number', description: 'Season number' },
  { name: 'resolution', group: 'media', kind: 'text', description: '1080p' },
]
