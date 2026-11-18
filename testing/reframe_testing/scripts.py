"""Load a standalone script from ``scripts/`` into a test module, by its file name."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def load_script(file_name: str, module_name: str | None = None) -> ModuleType:
    """Import ``scripts/<file_name>`` as a module.

    The default module name is the file stem with ``-`` replaced by ``_``. A second load of the
    same file in one process needs its own ``module_name``, or it replaces the first in
    ``sys.modules``.
    """
    name = module_name or Path(file_name).stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / file_name)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module
