/** Copies `from` to each `/`-separated path of `relatives` under `root`; resolves with the absolute paths. */
export function copyAs(from: string, root: string, relatives: string[]): Promise<string[]>
