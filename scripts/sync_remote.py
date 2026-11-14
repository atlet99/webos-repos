#!/usr/bin/env python3
"""Refresh third-party IPKs listed in remote-packages.json.

One request per package, one attempt, no retries: a sync is triggered by a daily
schedule and by upstream notifications, so hammering the source is never needed.
A failed or hung download must not stop the catalog, so failures are reported per
package and the command exits non-zero only after every package was tried.
"""

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'remote-packages.json'
PACKAGES = ROOT / 'packages'
TIMEOUT = 30

sys.path.insert(0, str(ROOT))
from packaging.version import InvalidVersion, Version  # noqa: E402

from scripts.build import read_package  # noqa: E402


def fetch(url):
    request = Request(url, headers={'User-Agent': 'webos-repos/1.0'})
    with urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def is_older(remote, local):
    try:
        return Version(remote) < Version(local)
    except InvalidVersion:
        return False


def staged_path(packages, filename):
    return packages / ('.' + filename + '.download')


def sync_one(app_id, config, packages=PACKAGES):
    """Download one IPK and replace packages/<filename> when the content changed."""
    url = config['url']
    filename = config['filename']
    print('Fetching ' + url, flush=True)
    data = fetch(url)
    if not data:
        raise ValueError('empty response for ' + url)
    with tempfile.TemporaryDirectory(dir=packages) as temp:
        temp_path = Path(temp) / filename
        temp_path.write_bytes(data)
        info, _ = read_package(temp_path)
    if info['id'] != app_id:
        raise ValueError('expected id ' + app_id + ', got ' + info['id'])
    target = packages / filename
    if target.is_file():
        if target.read_bytes() == data:
            print('  unchanged ' + filename, flush=True)
            return
        try:
            current = read_package(target)[0]['version']
        except (ValueError, OSError):
            current = None
        if current and is_older(info['version'], current):
            print('  skipped %s: remote version %s is older than %s' % (filename, info['version'], current), flush=True)
            return
    staged = staged_path(packages, filename)
    staged.write_bytes(data)
    os.replace(staged, target)
    print('  updated %s version=%s sha256=%s' % (filename, info['version'], hashlib.sha256(data).hexdigest()), flush=True)


def main(packages=PACKAGES):
    if not MANIFEST.is_file():
        raise SystemExit('missing ' + str(MANIFEST))
    if not packages.is_dir():
        raise SystemExit('missing ' + str(packages))
    configs = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if not isinstance(configs, dict):
        raise SystemExit('remote-packages.json must contain an object')
    for leftover in packages.glob('.*.download'):
        leftover.unlink()
    failures = []
    for app_id, config in configs.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', app_id):
            raise SystemExit('invalid app id: ' + app_id)
        if not isinstance(config, dict) or not isinstance(config.get('url'), str) or not isinstance(config.get('filename'), str):
            raise SystemExit('invalid config for ' + app_id)
        if Path(config['filename']).name != config['filename']:
            raise SystemExit('filename must be a plain name for ' + app_id)
        try:
            sync_one(app_id, config, packages)
        except (ValueError, OSError, KeyError) as error:
            failures.append(app_id)
            print('  FAILED %s: %s' % (app_id, error), file=sys.stderr, flush=True)
    if failures:
        raise SystemExit('sync failed for: ' + ', '.join(failures))
    print('Remote packages are up to date', flush=True)


if __name__ == '__main__':
    main()