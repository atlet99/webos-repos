#!/usr/bin/env python3
"""Build a static Homebrew Channel repository from IPK packages."""

import hashlib
import html
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get('BASE_URL', 'https://atlet99.github.io/webos-repos').rstrip('/')


class DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def add_description(entry, output, ipk_path=None):
    app_id = entry['id']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', app_id):
        raise ValueError('invalid application id: ' + app_id)
    markdown_path = ipk_path.with_suffix('.md') if ipk_path else None
    path = ROOT / 'descriptions' / (app_id + '.html')
    if markdown_path and markdown_path.is_file():
        import markdown
        content = markdown.markdown(markdown_path.read_text(encoding='utf-8'), extensions=['sane_lists', 'fenced_code', 'tables'])
        path = markdown_path
    elif path.exists():
        content = path.read_text(encoding='utf-8')
    else:
        content = None
    if content is not None:
        parser = DescriptionText()
        parser.feed(content)
        text = ' '.join(' '.join(parser.parts).split())
        if not text:
            raise ValueError('description file is empty: ' + str(path))
        target = output / 'descriptions'
        target.mkdir(exist_ok=True)
        name = app_id + '.html'
        (target / name).write_text(content, encoding='utf-8')
        entry['fullDescriptionUrl'] = BASE_URL + '/descriptions/' + quote(name)
        if not entry.get('shortDescription'):
            entry['shortDescription'] = html.escape(text[:200])
    elif not entry.get('fullDescriptionUrl') and not entry.get('shortDescription'):
        description = entry['manifest'].get('appDescription')
        if isinstance(description, str) and description.strip():
            entry['shortDescription'] = html.escape(description.strip())
        else:
            if ipk_path:
                raise ValueError('missing description for ' + ipk_path.name + '; create ' + str(ipk_path.with_suffix('.md')))
            raise ValueError('missing description for ' + app_id + '; create descriptions/' + app_id + '.html')


def absolute_url(base, value):
    if not isinstance(value, str) or not value:
        raise ValueError('missing URL in ' + base)
    url = urljoin(base, value)
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.netloc:
        raise ValueError('expected HTTPS URL: ' + url)
    return url


def fetch_json(url):
    request = Request(url, headers={'User-Agent': 'webos-repos/1.0', 'Accept': 'application/json'})
    with urlopen(request, timeout=30) as response:
        absolute_url(url, response.geturl())
        return json.load(response)


def external_packages(url):
    seen = set()
    while url:
        url = absolute_url(url, url)
        if url in seen:
            raise ValueError('repository pagination cycle: ' + url)
        seen.add(url)
        data = fetch_json(url)
        if not isinstance(data, dict) or not isinstance(data.get('packages'), list):
            raise ValueError('invalid repository catalog: ' + url)
        for raw in data['packages']:
            if not isinstance(raw, dict):
                raise ValueError('invalid package in ' + url)
            entry = dict(raw)
            manifest_url = absolute_url(url, entry['manifestUrl']) if entry.get('manifestUrl') else url
            manifest = entry.get('manifest')
            if manifest is None and entry.get('manifestUrl'):
                manifest = fetch_json(manifest_url)
            if not isinstance(manifest, dict):
                raise ValueError('missing manifest in ' + url)
            manifest = dict(manifest)
            if not isinstance(entry.get('id'), str) or not entry['id'] or manifest.get('id') != entry['id']:
                raise ValueError('missing or mismatched package ID in ' + url)
            if not isinstance(manifest.get('version'), str) or not manifest['version']:
                raise ValueError('missing package version for ' + entry['id'])
            if not isinstance(entry.get('title'), str) or not entry['title']:
                raise ValueError('missing package title for ' + entry['id'])
            digest = manifest.get('ipkHash')
            if not isinstance(digest, dict) or not isinstance(digest.get('sha256'), str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest['sha256']):
                raise ValueError('missing SHA-256 for ' + entry['id'])
            manifest['ipkUrl'] = absolute_url(manifest_url, manifest.get('ipkUrl'))
            for key in ('iconUri', 'sourceUrl'):
                if manifest.get(key):
                    manifest[key] = absolute_url(manifest_url, manifest[key])
            for key in ('iconUri', 'fullDescriptionUrl'):
                if entry.get(key):
                    entry[key] = absolute_url(url, entry[key])
            if not entry.get('iconUri') and manifest.get('iconUri'):
                entry['iconUri'] = manifest['iconUri']
            entry['manifestUrl'] = manifest_url
            entry['manifest'] = manifest
            yield entry
        paging = data.get('paging') or {}
        if not isinstance(paging, dict):
            raise ValueError('invalid pagination in ' + url)
        url = absolute_url(url, paging['nextUrl']) if paging.get('nextUrl') else None


def read_package(path):
    members = subprocess.check_output(['ar', '-t', str(path)], text=True).splitlines()
    data = [name for name in members if re.fullmatch(r'data\.tar(?:\.(?:gz|xz|bz2))?', name)]
    if len(data) != 1:
        raise ValueError('expected one supported data.tar archive')
    archive = subprocess.check_output(['ar', '-p', str(path), data[0]])
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:*') as tar:
        apps = [member for member in tar.getmembers()
                if member.isfile() and re.fullmatch(r'(?:\./)?usr/palm/applications/[^/]+/appinfo\.json', member.name)]
        if len(apps) != 1:
            raise ValueError('expected exactly one application appinfo.json')
        info = json.load(tar.extractfile(apps[0]))
        for key in ('id', 'version', 'title'):
            if not isinstance(info.get(key), str) or not info[key].strip():
                raise ValueError('missing or invalid appinfo field: ' + key)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', info['id']):
            raise ValueError('invalid application id')
        if apps[0].name.split('/')[-2] != info['id']:
            raise ValueError('application directory does not match appinfo id')
        icon = info.get('icon')
        icon_bytes = None
        if icon:
            if not isinstance(icon, str) or icon.startswith('/') or '..' in icon.split('/'):
                raise ValueError('invalid icon path')
            icon_path = apps[0].name.rsplit('/', 1)[0] + '/' + icon
            try:
                member = tar.getmember(icon_path)
                if not member.isfile():
                    raise ValueError('icon is not a regular file')
                icon_bytes = tar.extractfile(member).read()
            except KeyError:
                raise ValueError('icon not found in package: ' + icon)
        return info, icon_bytes


def build(output):
    parsed = urlparse(BASE_URL)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('BASE_URL must be an HTTPS URL without query or fragment')
    overrides = json.loads((ROOT / 'packages.json').read_text(encoding='utf-8'))
    repositories = json.loads((ROOT / 'repositories.json').read_text(encoding='utf-8'))
    if not isinstance(repositories, list):
        raise ValueError('repositories.json must contain a list of URLs')
    packages = []
    checksums = []
    ids = set()
    (output / 'packages').mkdir(parents=True)
    (output / 'icons').mkdir()
    for path in sorted((ROOT / 'packages').glob('*.ipk')):
        info, icon = read_package(path)
        app_id = info['id']
        if app_id in ids:
            raise ValueError('multiple IPKs for ' + app_id + '; keep only the desired version')
        ids.add(app_id)
        metadata = overrides.get(app_id, {})
        sidecar = path.with_suffix('.json')
        if sidecar.exists():
            extra = json.loads(sidecar.read_text(encoding='utf-8'))
            if not isinstance(extra, dict):
                raise ValueError('expected JSON object in ' + str(sidecar))
            metadata = dict(metadata, **extra)
        if 'rootRequired' in metadata and not isinstance(metadata['rootRequired'], bool):
            raise ValueError('rootRequired must be true or false for ' + path.name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        filename = quote(path.name, safe='')
        manifest = {
            'id': app_id, 'version': info['version'], 'type': info.get('type', 'web'),
            'title': info['title'], 'rootRequired': metadata.get('rootRequired', False),
            'ipkUrl': BASE_URL + '/packages/' + filename,
            'ipkHash': {'sha256': digest}, 'ipkSha256sum': digest,
            'ipkSize': path.stat().st_size,
        }
        description = metadata.get('shortDescription', info.get('description', ''))
        if description:
            manifest['appDescription'] = description
        for key in ('sourceUrl',):
            if metadata.get(key):
                manifest[key] = metadata[key]
        if icon is not None:
            suffix = Path(info['icon']).suffix.lower()
            if suffix not in ('.png', '.jpg', '.jpeg', '.webp'):
                raise ValueError('unsupported icon format: ' + suffix)
            icon_name = app_id + suffix
            (output / 'icons' / icon_name).write_bytes(icon)
            manifest['iconUri'] = BASE_URL + '/icons/' + quote(icon_name)
        manifest_name = app_id + '.manifest.json'
        (output / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        entry = {'id': app_id, 'title': info['title'], 'manifestUrl': BASE_URL + '/' + manifest_name,
                 'manifest': manifest, 'pool': 'main', 'shortDescription': description}
        if icon is not None:
            entry['iconUri'] = manifest['iconUri']
        add_description(entry, output, path)
        packages.append(entry)
        shutil.copyfile(path, output / 'packages' / path.name)
        checksums.append(digest + '  packages/' + path.name)
    for repository in repositories:
        for entry in external_packages(repository):
            if entry['id'] in ids:
                raise ValueError('duplicate package ID ' + entry['id'] + ' in ' + repository)
            ids.add(entry['id'])
            add_description(entry, output)
            packages.append(entry)
    count = len(packages)
    catalog = {'packages': packages, 'paging': {'page': 1, 'count': count, 'maxPage': 1,
               'itemsTotal': count, 'prevUrl': None, 'nextUrl': None}}
    (output / 'apps.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'SHA256SUMS').write_text('\n'.join(checksums) + ('\n' if checksums else ''), encoding='utf-8')
    rows = []
    for item in packages:
        m = item['manifest']
        rows.append('<li><strong>' + html.escape(item['title']) + '</strong> · ' + html.escape(m['version']) +
                    ' · <a href="' + html.escape(m['ipkUrl'], quote=True) + '">Скачать IPK</a><br><code>' +
                    m['ipkHash']['sha256'] + '</code></li>')
    url = html.escape(BASE_URL + '/apps.json')
    page = '''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>webOS Homebrew Repository</title><style>body{font:16px/1.6 sans-serif;max-width:52rem;margin:3rem auto;padding:0 1rem;color:#202534}code{overflow-wrap:anywhere}li{margin:1em 0}a{color:#1456a0}</style></head>
<body><h1>webOS Homebrew Repository</h1><p>Добавьте адрес в Homebrew Channel: Settings → Add repository.</p>
<p><code>''' + url + '''</code></p><h2>Приложения</h2><ul>''' + ''.join(rows) + '''</ul>
<p><a href="apps.json">Каталог JSON</a> · <a href="SHA256SUMS">SHA-256</a></p></body></html>\n'''
    (output / 'index.html').write_text(page, encoding='utf-8')
    (output / '.nojekyll').touch()


def main():
    # Build separately so a malformed IPK never replaces the last successful output.
    with tempfile.TemporaryDirectory(dir=ROOT) as temp:
        output = Path(temp) / 'site'
        output.mkdir()
        build(output)
        destination = ROOT / '_site'
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(output), str(destination))
    print('Built _site/apps.json for ' + BASE_URL)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        sys.exit('Build failed: ' + str(error))
