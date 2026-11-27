"""Record Python API outputs for cross-runtime regression checks.

Run with the project's conda environment after intentionally changing API results.
The browser tests compare the complete response, including excerpts and ordering.
"""
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'playground'))
import server


def normalize(value):
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def fingerprint(value):
    raw = json.dumps(normalize(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


paths = ['/api/overview', '/api/network']
for kind, identifiers in [('researchers', [1, 401, 1000]), ('projects', [1, 750, 1500])]:
    paths.extend(f'/api/{kind}/{identifier}' for identifier in identifiers)
for identifier in [1, 401, 1000]:
    paths.append(f'/api/researchers/{identifier}/collaborators')
for kind in ['researchers', 'projects']:
    for query in ['', 'carbon', 'cellulose', 'cellulose OR biocomposites', 'carbon capture',
                  '"carbon dioxide"', '“carbon dioxide”', 'carbon AND capture OR hydrogen',
                  '%', '_', '\\', "' OR 1=1 --"]:
        paths.append(f'/api/{kind}?' + urlencode({'q': query}))
    for scope in ['research', 'expertise', 'needs', 'outcomes']:
        paths.append(f'/api/{kind}?' + urlencode({'q': 'water', 'scope': scope}))
    for parameters in [{'area': '2', 'q': 'cellulose OR carbon'}, {'role': 'PI', 'area': '1', 'q': 'carbon'},
                       {'offset': '15'}, {'q': 'carbon', 'offset': '100000'}]:
        paths.append(f'/api/{kind}?' + urlencode(parameters))

expected = {}
for path in paths:
    parsed = urlsplit(path)
    parts = parsed.path.strip('/').split('/')
    if parts[1] == 'overview':
        result = server.overview()
    elif parts[1] == 'network':
        result = server.network()
    elif len(parts) == 2:
        result = server.search(parts[1], parse_qs(parsed.query))
    elif len(parts) == 4:
        result = {'rows': server.collaborators(int(parts[2]))}
    else:
        result = server.detail(parts[1], int(parts[2]))
    expected[path] = fingerprint(result)

destination = ROOT / 'playground/browser_api_fixtures.json'
destination.write_text(json.dumps(expected, indent=2) + '\n')
print(f'Recorded {len(expected)} Python API response fingerprints.')
