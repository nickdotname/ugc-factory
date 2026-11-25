"""CC0 low-poly kits for the low-poly story page (studio/lowpoly_video.py), from OpenGameArt.

    python studio/lowpoly/fetch.py      (GitHub Actions: download the kits, keep their models, upload them)

Each kit's OpenGameArt page is read for its zip; the page must say CC0. Only model files (glTF/GLB with their
textures, FBX) are kept, one zip per kit, uploaded to the GitHub release "lowpoly-kit" and recorded with their
page and licence in studio/lowpoly/kits.json. Rendering only reads that release.
"""
import io, json, os, re, subprocess, sys, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'lowpoly-kit'
UA = {'User-Agent': 'CloseQuartersKit/1.0 (https://closequarters.vip) python-urllib/3'}
PAGES = {
    'blocky': 'https://opengameart.org/content/blocky-characters',
    'suburban': 'https://opengameart.org/content/city-kit-suburban',
    'commercial': 'https://opengameart.org/content/city-kit-commercial',
    'roads': 'https://opengameart.org/content/city-kit-roads',
    'furniture': 'https://opengameart.org/content/furniture-kit',
    'cars': 'https://opengameart.org/content/car-kit',
    'animated1': 'https://opengameart.org/content/animated-characters-1',
    'animated2': 'https://opengameart.org/content/animated-characters-2',
    'human': 'https://opengameart.org/content/animated-human-low-poly',
}
KEEP = re.compile(r'\.(glb|gltf|bin|png|jpg|fbx)$', re.I)


def get(url, raw=True):
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r: return r.read()
        except Exception as exc:
            if k == 3: raise
            print('  retry', url, exc); time.sleep(5 * (k + 1))


def main():
    out = os.path.join(HERE, 'new'); os.makedirs(out, exist_ok=True); kits = {}
    for name, page in PAGES.items():
        try: html = get(page).decode('utf-8', 'replace')
        except Exception as exc: print('skip', name, exc); continue
        if 'CC0' not in html: print('skip', name, 'not CC0'); continue
        zips = sorted(set(re.findall(r'https?://opengameart\.org/sites/default/files/[^"\'<>\s]+\.zip', html)))
        if not zips: print('skip', name, 'no zip'); continue
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zo:
            n = 0
            for z in zips:
                try: data = get(z)
                except Exception as exc: print('  ', z, exc); continue
                with zipfile.ZipFile(io.BytesIO(data)) as zi:
                    for info in zi.infolist():
                        if KEEP.search(info.filename) and not info.filename.startswith('__MACOSX'):
                            zo.writestr(info.filename, zi.read(info)); n += 1
        if not n: print('skip', name, 'no models'); continue
        path = os.path.join(out, 'kit_%s.zip' % name); open(path, 'wb').write(buf.getvalue())
        kits[name] = dict(asset='kit_%s.zip' % name, page=page, licence='CC0 1.0 (OpenGameArt page)', files=n, zips=zips)
        print('+', name, n, 'files', round(len(buf.getvalue()) / 1e6, 1), 'MB')
    if kits:
        if subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode:
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Low-poly kit (CC0)', '--notes',
                            'CC0 low-poly models from OpenGameArt for the low-poly story page. Sources: studio/lowpoly/kits.json'], check=True)
        subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + [os.path.join(out, k['asset']) for k in kits.values()], check=True)
    old = {}
    try: old = json.load(open(os.path.join(HERE, 'kits.json')))
    except (OSError, ValueError): pass
    old.update(kits); json.dump(old, open(os.path.join(HERE, 'kits.json'), 'w'), indent=1); print(len(old), 'kits')



def pull():
    """Unzip the kits from the release into studio/lowpoly/cache (once per runner). Without them the scenes use box houses."""
    cache = os.path.join(HERE, 'cache'); os.makedirs(cache, exist_ok=True)
    try: kits = json.load(open(os.path.join(HERE, 'kits.json')))
    except (OSError, ValueError): return 0
    n = 0
    for name, k in kits.items():
        dest = os.path.join(cache, name)
        if os.path.isdir(dest): n += 1; continue
        try:
            rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
            aid = {a['name']: a['id'] for a in rel.get('assets', [])}[k['asset']]
            data = subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream', 'repos/%s/releases/assets/%d' % (REPO, aid)], capture_output=True, check=True).stdout
            zipfile.ZipFile(io.BytesIO(data)).extractall(dest); n += 1
        except Exception as exc: print('kit %s not pulled: %s' % (name, exc))
    return n


if __name__ == '__main__':
    pull() if sys.argv[1:] == ['pull'] else main()
