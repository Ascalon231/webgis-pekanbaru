import json, os, urllib.request, urllib.parse, time, sys
from shapely.geometry import shape, Polygon

DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOUNDARY_FILE = os.path.join(DATA_DIR, 'pekanbaru_boundary.geojson')
OUTPUT = os.path.join(DATA_DIR, 'pekanbaru_buildings.geojson')

with open(BOUNDARY_FILE) as f:
    raw = json.load(f)
boundary = shape(raw['geometry'])
bounds = boundary.bounds

clat = (bounds[1] + bounds[3]) / 2
clon = (bounds[0] + bounds[2]) / 2
quadrants = [
    (bounds[1], bounds[0], clat, clon),
    (bounds[1], clon, clat, bounds[2]),
    (clat, bounds[0], bounds[3], clon),
    (clat, clon, bounds[3], bounds[2]),
]

def fetch_overpass(q, label, max_retries=5):
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                'https://overpass-api.de/api/interpreter',
                data=urllib.parse.urlencode({'data': q}).encode(),
                headers={'User-Agent': 'WebGIS-Pekanbaru/1.0'},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                chunk = json.loads(resp.read())
            return chunk.get('elements', [])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 15 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 504:
                wait = 10 * (attempt + 1)
                print(f"  Timeout, retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Error {e.code}, retrying...")
                time.sleep(10)
        except Exception as e:
            print(f"  Error: {e}, retrying...")
            time.sleep(10)
    return []

all_elements = []
for i, (s, w, n, e) in enumerate(quadrants):
    q = f"[out:json][timeout:180];way[\"building\"]({s:.4f},{w:.4f},{n:.4f},{e:.4f});(._;>;);out body;"
    print(f"Quadrant {i+1}/4: {s:.4f},{w:.4f} to {n:.4f},{e:.4f}")
    els = fetch_overpass(q, i+1)
    all_elements.extend(els)
    print(f"  Got {len(els)} elements")
    time.sleep(5)

nodes = {}
ways_data = []
for el in all_elements:
    if el['type'] == 'node':
        nodes[el['id']] = (el['lon'], el['lat'])
    elif el['type'] == 'way':
        ways_data.append(el)

print(f"Reconstructing {len(ways_data)} buildings from {len(nodes)} nodes...")

features = []
skipped = 0
for way in ways_data:
    coords = []
    for nid in way.get('nodes', []):
        if nid in nodes:
            coords.append(nodes[nid])
    if len(coords) < 3:
        skipped += 1
        continue
    try:
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.area < 1e-8:
            skipped += 1
            continue
        if not poly.intersects(boundary):
            skipped += 1
            continue
        poly = poly.intersection(boundary)
        if poly.is_empty or poly.area < 1e-8:
            skipped += 1
            continue
    except Exception:
        skipped += 1
        continue

    props = {'building': way.get('tags', {}).get('building', 'yes')}
    h = way.get('tags', {}).get('height', '')
    levels = way.get('tags', {}).get('building:levels', '')
    if h:
        try:
            props['height'] = float(h.replace(' m', '').replace('m', ''))
        except:
            pass
    if levels:
        try:
            props['levels'] = int(float(levels))
        except:
            pass
    if 'height' not in props:
        props['height'] = props.get('levels', 1) * 3.0

    features.append({'type': 'Feature', 'properties': props, 'geometry': shape(poly).__geo_interface__})

result = {'type': 'FeatureCollection', 'features': features}
with open(OUTPUT, 'w') as f:
    json.dump(result, f)

print(f"Done: {len(features)} buildings saved, {skipped} skipped")
print(f"Output: {OUTPUT}")
