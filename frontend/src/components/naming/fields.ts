/** The parsed-name fields a job can override (`JobNaming.field_overrides`), in panel order. */
export const OVERRIDE_FIELDS = [
  'name',
  'main_title',
  'season',
  'episode',
  'episode_code',
  'sub_title',
  'year',
  'edition',
  'source_type',
  'release_group',
] as const

export type OverrideField = (typeof OVERRIDE_FIELDS)[number]

/** The validation path of a naming template that the server checked (job or options alike). */
export const TEMPLATE_PATH = 'output.naming.template'
