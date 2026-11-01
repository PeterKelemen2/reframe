import type { Language } from '@/api/types'

function language(
  tag: string,
  codes: [iso639_1: string | null, iso639_2b: string, iso639_2t: string],
  english_name: string,
  native_name: string,
): Language {
  const [iso639_1, iso639_2b, iso639_2t] = codes
  return {
    tag,
    iso639_1,
    iso639_2b,
    iso639_2t,
    iso639_3: iso639_2t,
    english_name,
    native_name,
    variant: tag.includes('-'),
  }
}

/** A part of `GET /api/languages` as the server sends it (ordered by English name). */
export function languages(): Language[] {
  return [
    language('egy', [null, 'egy', 'egy'], 'Ancient Egyptian', 'Ancient Egyptian'),
    language('zh', ['zh', 'chi', 'zho'], 'Chinese', '中文'),
    language('zh-Hans', ['zh', 'chi', 'zho'], 'Chinese (Simplified)', '中文（简体）'),
    language('en', ['en', 'eng', 'eng'], 'English', 'English'),
    language('fr', ['fr', 'fre', 'fra'], 'French', 'français'),
    language('de', ['de', 'ger', 'deu'], 'German', 'Deutsch'),
    language('hu', ['hu', 'hun', 'hun'], 'Hungarian', 'magyar'),
    language('pt', ['pt', 'por', 'por'], 'Portuguese', 'português'),
    language('pt-BR', ['pt', 'por', 'por'], 'Portuguese (Brazil)', 'português (Brasil)'),
    language('pt-PT', ['pt', 'por', 'por'], 'Portuguese (Portugal)', 'português (Portugal)'),
    language('sr', ['sr', 'srp', 'srp'], 'Serbian', 'српски'),
    language('sr-Latn', ['sr', 'srp', 'srp'], 'Serbian (Latin)', 'srpski (latinica)'),
    language('es', ['es', 'spa', 'spa'], 'Spanish', 'español'),
    language('es-419', ['es', 'spa', 'spa'], 'Spanish (Latin America)', 'español (Latinoamérica)'),
    language('und', [null, 'und', 'und'], 'Undetermined', 'Undetermined'),
  ]
}
