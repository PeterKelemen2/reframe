"""Output naming: the output file name of one source, and the check of a naming template.
The file-system reads go through :class:`NamingFs`, which tests replace."""

from reframe.naming.fs import FileTimes, NamingFs, RealNamingFs
from reframe.naming.parse import parse_name
from reframe.naming.resolve import OVERRIDE_FIELDS, output_extension, resolve_output_name
from reframe.naming.template import check_template
from reframe.naming.value import render_value
from reframe.naming.variables import VARIABLES

__all__ = [
    "OVERRIDE_FIELDS",
    "VARIABLES",
    "FileTimes",
    "NamingFs",
    "RealNamingFs",
    "check_template",
    "output_extension",
    "parse_name",
    "render_value",
    "resolve_output_name",
]
