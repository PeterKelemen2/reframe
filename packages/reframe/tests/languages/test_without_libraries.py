"""``reframe.languages`` works where ``langcodes``, ``language_data`` and ``marisa-trie`` cannot
be imported: the product does not ship them."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

SCRIPT = textwrap.dedent(
    """
    import importlib.abc, json, sys

    BLOCKED = {"langcodes", "language_data", "marisa_trie"}

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ModuleNotFoundError(name)
            return None

    sys.meta_path.insert(0, Block())
    from reframe import languages as L

    result = {
        "codes": [L.normalize(v) for v in ("ger", "pt_br", "iw", "sgn-US", "zh-yue", "xx")],
        "names": [L.normalize(v) for v in ("német", "allemand", "achenés", "Cantonese")],
        "english": L.english_name("zh-Hant-HK"),
        "native": [L.native_name(v) for v in ("de-AT", "sr-Latn-ME", "ja-Latn", "pt-BR")],
        "codes_out": [L.to_matroska_legacy("yue"), L.to_mp4("pt-BR")],
        "search": [e.tag for e in L.search("allemand")][:1],
        "list": len(L.language_list()),
        "matches": L.matches("zh", "cmn-Hans"),
        "loaded": sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED),
    }
    print(json.dumps(result, ensure_ascii=False))
    """
)


def test_every_function_works_without_the_language_libraries() -> None:
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT], check=True, capture_output=True, text=True, timeout=120
    )
    result = json.loads(out.stdout)
    assert result == {
        "codes": ["de", "pt-BR", "he", "ase", "yue", None],
        "names": ["de", "de", "yif", "yue"],
        "english": "Chinese (Traditional, Hong Kong SAR China)",
        "native": [
            "Deutsch (Österreich)",
            "srpski (latinica, Crna Gora)",
            "日本語 (ラテン文字)",
            "português (Brasil)",
        ],
        "codes_out": ["chi", "por"],
        "search": ["de"],
        "list": 429,
        "matches": True,
        "loaded": [],
    }
