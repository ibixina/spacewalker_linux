"""Render desktop-entry values without shell or sed interpretation of paths."""
from pathlib import Path
import sys


def string_value(value):
    return (value.replace('\\', '\\\\').replace('\n', '\\n')
            .replace('\r', '\\r').replace('\t', '\\t'))


def exec_value(value):
    # Exec quoting is interpreted after desktop-entry string unescaping.
    quoted = ''.join('\\'+c if c in '\\"`$' else c for c in value)
    return string_value('"'+quoted.replace('%', '%%')+'"')


def render(template, runner):
    return template.replace('@RUNNER@', exec_value(runner)).replace('@TRY_RUNNER@', string_value(runner))


if __name__ == '__main__':
    print(render(Path(sys.argv[1]).read_text(), sys.argv[2]), end='')
