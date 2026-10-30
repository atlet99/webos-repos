#!/usr/bin/env python3
"""Pin only the packages explicitly listed in requirements.txt."""

import os
import re
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parent.parent / 'requirements.txt'
NAME = r'[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*'
LINE = re.compile(r'^\s*(' + NAME + r')(?:==[^\s#]+)?\s*(?:#.*)?$')


def freeze(path, additions=()):
    original = path.read_text(encoding='utf-8')
    lines = []
    names = set()
    for line in original.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            lines.append(line)
            continue
        match = LINE.fullmatch(line)
        if not match:
            raise ValueError('unsupported requirement: ' + line)
        name = match.group(1)
        normalized = re.sub(r'[-_.]+', '-', name).lower()
        if normalized in names:
            raise ValueError('duplicate requirement: ' + name)
        names.add(normalized)
        try:
            installed = version(name)
        except PackageNotFoundError:
            raise ValueError('package not installed in .venv: ' + name) from None
        comment = '  #' + line.split('#', 1)[1] if '#' in line else ''
        lines.append(name + '==' + installed + comment)
    for name in additions:
        if not re.fullmatch(NAME, name):
            raise ValueError('invalid package name: ' + name)
        normalized = re.sub(r'[-_.]+', '-', name).lower()
        if normalized in names:
            continue
        try:
            installed = version(name)
        except PackageNotFoundError:
            raise ValueError('package not installed in .venv: ' + name) from None
        names.add(normalized)
        lines.append(name + '==' + installed)
    updated = '\n'.join(lines) + ('\n' if lines else '')
    if updated == original:
        return
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as temp:
        try:
            temp.write(updated)
            temp.flush()
            os.chmod(temp.name, path.stat().st_mode & 0o777)
            os.replace(temp.name, path)
        finally:
            if os.path.exists(temp.name):
                os.unlink(temp.name)


if __name__ == '__main__':
    try:
        freeze(REQUIREMENTS, sys.argv[1:])
    except (ValueError, OSError) as error:
        sys.exit('Freeze failed: ' + str(error))
    print('Updated direct dependencies in requirements.txt')
