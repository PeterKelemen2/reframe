"""Output naming (03 §Output naming; C-16).

- :func:`resolve_output_name`: the output name of one file. It picks the name source (file
  or folder name), parses the release name with guessit, renders the template and makes the
  name safe on Windows.
- :func:`check_template`: syntax errors, unknown variables (with "did you mean" fixes) and bad
  format specs of a template, as validation issues.
- :data:`VARIABLES`: the template variables, for the naming editor.
- :class:`NamingFs`: the file-system reads (folder listing, file times); tests replace it.

Modules: ``source`` (name source), ``parse`` (release-name parsing), ``template`` (template
syntax), ``context`` (variable values), ``clean`` (word separator, HandBrake clean-up),
``sanitize`` (safe file names), ``resolve`` (the whole step).
"""

from reframe.naming.fs import FileTimes, NamingFs, RealNamingFs
from reframe.naming.parse import parse_name
from reframe.naming.resolve import OVERRIDE_FIELDS, output_extension, resolve_output_name
from reframe.naming.template import check_template
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
    "resolve_output_name",
]
