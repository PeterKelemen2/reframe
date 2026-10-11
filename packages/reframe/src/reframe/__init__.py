"""Reframe core package.

The public API is the :class:`Reframe` facade (C-15, ``reframe.service``) and
``reframe.models``. Everything else is internal and can change.
"""

__version__ = "0.1.0.dev0"

from reframe.service import Reframe

__all__ = ["Reframe", "__version__"]
