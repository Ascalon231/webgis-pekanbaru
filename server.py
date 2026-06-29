import math
import io
import json
import os
import struct
import time
import urllib.request
import threading
from collections import OrderedDict

import flask
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from PIL import Image, ImageDraw
from flask import Flask, request, Response
from shapely.geometry import shape, box
from shapely.strtree import STRtree

class LRUCache:
    def __init__(self, maxsize=4096):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self.lock = threading.Lock()

    def __contains__(self, key):
        with self.lock:
            return key in self.cache

    def __getitem__(self, key):
        with self.lock:
            if key not in self.cache:
                raise KeyError(key)
            self.cache.move_to_end(key)
            return self.cache[key]

    def __setitem__(self, key, value):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.maxsize:
                self.cache.popitem(last=False)

app = Flask(__name__)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

DEM_FILE = os.path.join(DATA_DIR, 'DEMNAS_Pekanbaru.tif')

BATNAS_FILE = os.path.join(DATA_DIR, 'BATNAS_100E-105E_000-05N_MSL_v1.5.tif')
FACC_FILE = os.path.join(DATA_DIR, 'dem_facc_4326.tif')
SINKDIFF_FILE = os.path.join(DATA_DIR, 'dem_sinkdiff_4326.tif')

PEKANBARU_DEM_BOUNDS = (101.32298, 0.42042, 101.60531, 0.69097)
BATNAS_BOUNDS = (100.0, 0.0, 105.0, 5.0)

TILE_CACHE = LRUCache(maxsize=4096)
COLORMAP_CACHE = {}
CONTOUR_CACHE = {}
STREAMS_CACHE = None
WEATHER_CACHE = {'data': None, 'time': 0}


def load_contour_data(interval):
    key = f'contour_{interval}'
    if key in CONTOUR_CACHE:
        return CONTOUR_CACHE[key]

    fname = f'contours_{interval}_simple.geojson'
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.exists(fpath):
        return None

    with open(fpath) as f:
        raw = json.load(f)

    features = []
    for feat in raw['features']:
        elev = feat['properties'].get('elev', 0)
        geom = shape(feat['geometry'])
        features.append({'geom': geom, 'elev': elev})

    tree = STRtree([f['geom'] for f in features])

    CONTOUR_CACHE[key] = {'features': features, 'tree': tree}
    return CONTOUR_CACHE[key]


def render_contour_tile(interval, z, x, y):
    data = load_contour_data(interval)
    if data is None:
        return None

    lng_left, lat_bottom, lng_right, lat_top = tile_to_bounds(x, y, z)
    dx = (lng_right - lng_left) * 0.1
    dy = (lat_top - lat_bottom) * 0.1
    qbox = box(lng_left - dx, lat_bottom - dy, lng_right + dx, lat_top + dy)

    indices = data['tree'].query(qbox, predicate='intersects')

    img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    n = 2.0 ** z
    ts = 256.0

    def to_px(lng, lat):
        xt = (lng + 180.0) / 360.0
        yt = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0
        px = (xt * n - x) * ts
        py = (yt * n - y) * ts
        return (px, py)

    for idx in indices:
        feat = data['features'][idx]
        elev = feat['elev']
        geom = feat['geom']
        is_index = (elev % 25 == 0)
        color = (92, 58, 30, 230) if is_index else (166, 123, 91, 180)
        w = 3 if is_index else 1

        lines = []
        if geom.geom_type == 'LineString':
            lines.append(geom)
        elif geom.geom_type == 'MultiLineString':
            lines.extend(geom.geoms)

        for line in lines:
            pts = [to_px(lng, lat) for lng, lat in line.coords]
            if len(pts) > 1:
                draw.line(pts, fill=color, width=w)

    return img


RISK_BAND_COLORS = [
    (0.0, 0.25, (76, 175, 80, 160)),
    (0.25, 0.50, (255, 235, 59, 180)),
    (0.50, 0.75, (255, 152, 0, 200)),
    (0.75, 1.01, (244, 67, 54, 220)),
]

def render_risk_tile(z, x, y):
    lng_left, lat_bottom, lng_right, lat_top = tile_to_bounds(x, y, z)

    elev = read_raster_window(DEM_FILE, lng_left, lat_bottom, lng_right, lat_top)
    if elev is None or np.all(np.isnan(elev)):
        return None

    facc = read_raster_window(FACC_FILE, lng_left, lat_bottom, lng_right, lat_top)
    sink = read_raster_window(SINKDIFF_FILE, lng_left, lat_bottom, lng_right, lat_top)

    if facc is None:
        facc = np.full_like(elev, np.nan)
    if sink is None:
        sink = np.full_like(elev, np.nan)

    va = elev[~np.isnan(elev)]
    e_min, e_max = va.min(), va.max()
    elev_norm = np.where(np.isnan(elev), np.nan,
                         1 - (elev - e_min) / (e_max - e_min + 0.01))

    vb = facc[~np.isnan(facc) & (facc > 0)]
    if len(vb) > 0:
        fl = np.log10(facc + 1)
        f_min, f_max = fl[~np.isnan(fl)].min(), fl[~np.isnan(fl)].max()
        facc_norm = np.where(np.isnan(facc) | (facc <= 0), 0,
                             (fl - f_min) / (f_max - f_min + 0.01))
    else:
        facc_norm = np.zeros_like(elev)

    vc = sink[~np.isnan(sink) & (sink > 0.01)]
    if len(vc) > 0:
        s_min, s_max = vc.min(), vc.max()
        sink_norm = np.where(np.isnan(sink) | (sink <= 0.01), 0,
                             (sink - s_min) / (s_max - s_min + 0.01))
    else:
        sink_norm = np.zeros_like(elev)

    risk = (0.3 * np.nan_to_num(elev_norm, nan=0)
            + 0.4 * facc_norm
            + 0.3 * sink_norm)

    h, w = risk.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for lo, hi, color in RISK_BAND_COLORS:
        mask = (risk >= lo) & (risk < hi)
        for c in range(4):
            rgba[:, :, c][mask] = color[c]
    rgba[:, :, 3][np.isnan(elev)] = 0

    return Image.fromarray(rgba, 'RGBA')


def load_streams_data():
    global STREAMS_CACHE
    if STREAMS_CACHE is not None:
        return STREAMS_CACHE
    fpath = os.path.join(DATA_DIR, 'streams.geojson')
    if not os.path.exists(fpath):
        return None
    with open(fpath) as f:
        raw = json.load(f)
    features = []
    for feat in raw['features']:
        geom = shape(feat['geometry'])
        features.append({'geom': geom})
    tree = STRtree([f['geom'] for f in features])
    STREAMS_CACHE = {'features': features, 'tree': tree}
    return STREAMS_CACHE


def render_streams_tile(z, x, y):
    data = load_streams_data()
    if data is None:
        return None
    lng_left, lat_bottom, lng_right, lat_top = tile_to_bounds(x, y, z)
    dx = (lng_right - lng_left) * 0.1
    dy = (lat_top - lat_bottom) * 0.1
    qbox = box(lng_left - dx, lat_bottom - dy, lng_right + dx, lat_top + dy)
    indices = data['tree'].query(qbox, predicate='intersects')
    img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    n = 2.0 ** z; ts = 256.0
    def to_px(lng, lat):
        xt = (lng + 180.0) / 360.0
        yt = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0
        return ((xt * n - x) * ts, (yt * n - y) * ts)
    for idx in indices:
        geom = data['features'][idx]['geom']
        polygons = []
        if geom.geom_type == 'Polygon':
            polygons.append(geom)
        elif geom.geom_type == 'LineString':
            pts = [to_px(lng, lat) for lng, lat in geom.coords]
            if len(pts) > 1:
                draw.line(pts, fill=(43, 131, 186, 200), width=1)
        elif geom.geom_type == 'MultiLineString':
            for line in geom.geoms:
                pts = [to_px(lng, lat) for lng, lat in line.coords]
                if len(pts) > 1:
                    draw.line(pts, fill=(43, 131, 186, 200), width=1)
        elif geom.geom_type == 'MultiPolygon':
            polygons.extend(geom.geoms)
        for poly in polygons:
            ext = [to_px(lng, lat) for lng, lat in poly.exterior.coords]
            if len(ext) > 2:
                draw.polygon(ext, fill=(43, 131, 186, 160), outline=(43, 131, 186, 220))
    return img


def webmercator_to_geographic(x, y):
    r = 6378137.0
    lng = math.degrees(x / r)
    lat = math.degrees(2 * math.atan(math.exp(y / r)) - math.pi / 2)
    return lng, lat


def tile_to_bounds(x, y, z):
    n = 2.0 ** z
    origin = 20037508.342789244
    min_x = (x / n) * 2 * origin - origin
    max_x = ((x + 1) / n) * 2 * origin - origin
    min_y = origin - ((y + 1) / n) * 2 * origin
    max_y = origin - (y / n) * 2 * origin
    lng_left, lat_bottom = webmercator_to_geographic(min_x, min_y)
    lng_right, lat_top = webmercator_to_geographic(max_x, max_y)
    return lng_left, lat_bottom, lng_right, lat_top


def make_colormap(cmap_name='terrain', steps=256, flip=False):
    key = (cmap_name, steps, flip)
    if key in COLORMAP_CACHE:
        return COLORMAP_CACHE[key]
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    cmap = plt.get_cmap(cmap_name, steps)
    if flip:
        cmap = cmap.reversed()
    colors = (cmap(np.arange(steps)) * 255).astype(np.uint8)[:, :3]
    COLORMAP_CACHE[key] = colors
    plt.close('all')
    return colors


def apply_colormap(data, cmap_name='terrain', vmin=None, vmax=None, flip=False):
    if vmin is None:
        vmin = np.nanmin(data)
    if vmax is None:
        vmax = np.nanmax(data)
    if vmax - vmin < 0.01:
        vmax = vmin + 1.0
    colors = make_colormap(cmap_name, flip=flip)
    normalized = np.clip((data - vmin) / (vmax - vmin), 0, 0.9999)
    indices = (normalized * (colors.shape[0] - 1)).astype(np.uint16)
    return colors[indices]


def hillshade(data, az=315, alt=45):
    dx = np.gradient(data, axis=1)
    dy = np.gradient(data, axis=0)
    az_rad = np.radians(360 - az)
    alt_rad = np.radians(alt)
    shaded = np.sin(alt_rad) * np.ones_like(data)
    shaded -= np.cos(alt_rad) * (np.sin(az_rad) * dx + np.cos(az_rad) * dy)
    shaded = np.clip(shaded, 0, 1)
    return (shaded * 255).astype(np.uint8)


def read_raster_window(filepath, left, bottom, right, top, out_shape=(256, 256)):
    with rasterio.open(filepath) as src:
        try:
            window = from_bounds(left, bottom, right, top, src.transform)
            nodata_val = src.nodata
            if nodata_val is None:
                if np.issubdtype(src.dtypes[0], np.floating):
                    nodata_val = np.nan
                else:
                    nodata_val = -9999
            
            data = src.read(
                1,
                window=window,
                out_shape=out_shape,
                resampling=rasterio.enums.Resampling.bilinear,
                boundless=True,
                fill_value=nodata_val
            )
            data = data.astype(np.float32)
            if np.isnan(nodata_val):
                pass
            else:
                data[data == nodata_val] = np.nan
        except Exception:
            return None
    return data


def render_tile(layer, z, x, y):
    lng_left, lat_bottom, lng_right, lat_top = tile_to_bounds(x, y, z)

    if layer == 'dem':
        data = read_raster_window(DEM_FILE, lng_left, lat_bottom, lng_right, lat_top)
        if data is None or np.all(np.isnan(data)):
            return None
        colored = apply_colormap(data, 'terrain', vmin=-10, vmax=110)
        alpha = np.where(np.isnan(data), 0, 200).astype(np.uint8)
        rgba = np.concatenate([colored, alpha[:, :, np.newaxis]], axis=2)
        return Image.fromarray(rgba, 'RGBA')

    elif layer == 'batnas':
        data = read_raster_window(BATNAS_FILE, lng_left, lat_bottom, lng_right, lat_top)
        if data is None or np.all(np.isnan(data)):
            return None
        colored = apply_colormap(data, 'Blues', vmin=-2000, vmax=0, flip=True)
        alpha = np.where(np.isnan(data), 0, 180).astype(np.uint8)
        rgba = np.concatenate([colored, alpha[:, :, np.newaxis]], axis=2)
        return Image.fromarray(rgba, 'RGBA')

    elif layer == 'hillshade':
        data = read_raster_window(DEM_FILE, lng_left, lat_bottom, lng_right, lat_top, out_shape=(128, 128))
        if data is None or np.all(np.isnan(data)):
            return None
        filled = np.nan_to_num(data, nan=0)
        shaded = hillshade(filled)
        alpha = np.where(np.isnan(data), 0, 200).astype(np.uint8)
        rgba = np.concatenate([np.stack([shaded] * 3, axis=2), alpha[:, :, np.newaxis]], axis=2)
        return Image.fromarray(rgba, 'RGBA')

    elif layer == 'batnas_hillshade':
        data = read_raster_window(BATNAS_FILE, lng_left, lat_bottom, lng_right, lat_top, out_shape=(128, 128))
        if data is None or np.all(np.isnan(data)):
            return None
        filled = np.nan_to_num(data, nan=0)
        shaded = hillshade(filled)
        alpha = np.where(np.isnan(data), 0, 180).astype(np.uint8)
        rgba = np.concatenate([np.stack([shaded] * 3, axis=2), alpha[:, :, np.newaxis]], axis=2)
        return Image.fromarray(rgba, 'RGBA')

    elif layer == 'facc':
        if not os.path.exists(FACC_FILE):
            return None
        data = read_raster_window(FACC_FILE, lng_left, lat_bottom, lng_right, lat_top)
        if data is None or np.all(np.isnan(data)):
            return None
        data_log = np.log10(data + 1)
        colored = apply_colormap(data_log, 'Blues', vmin=0, vmax=6)
        alpha = np.where(np.isnan(data) | (data <= 0), 0, 180).astype(np.uint8)
        rgba = np.concatenate([colored, alpha[:, :, np.newaxis]], axis=2)
        return Image.fromarray(rgba, 'RGBA')

    elif layer == 'sinkdiff':
        if not os.path.exists(SINKDIFF_FILE):
            return None
        data = read_raster_window(SINKDIFF_FILE, lng_left, lat_bottom, lng_right, lat_top)
        if data is None or np.all(np.isnan(data)):
            return None
        colored = apply_colormap(data, 'Reds', vmin=0, vmax=np.nanmax(data) or 1)
        alpha = np.where(np.isnan(data) | (data <= 0.01), 0, 160).astype(np.uint8)
        rgba = np.concatenate([colored, alpha[:, :, np.newaxis]], axis=2)
        return Image.fromarray(rgba, 'RGBA')
    return None


@app.route('/tiles/terrainrgb/<int:z>/<int:x>/<int:y>.png')
def serve_terrain_rgb(z, x, y):
    cache_key = ('terrainrgb', z, x, y)
    if cache_key in TILE_CACHE:
        return Response(TILE_CACHE[cache_key], mimetype='image/png')

    lng_left, lat_bottom, lng_right, lat_top = tile_to_bounds(x, y, z)
    data = read_raster_window(DEM_FILE, lng_left, lat_bottom, lng_right, lat_top)
    if data is None or np.all(np.isnan(data)):
        return Response(status=204)

    data = np.nan_to_num(data, nan=0)
    encoded = ((data + 10000) / 0.1).astype(np.int32)
    R = np.floor(encoded / 65536).astype(np.uint8)
    G = np.floor((encoded % 65536) / 256).astype(np.uint8)
    B = np.floor(encoded % 256).astype(np.uint8)

    rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    rgba[:,:,0] = R
    rgba[:,:,1] = G
    rgba[:,:,2] = B
    rgba[:,:,3] = 255

    img = Image.fromarray(rgba, 'RGBA')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    png_data = buf.getvalue()
    TILE_CACHE[cache_key] = png_data
    return Response(png_data, mimetype='image/png')


@app.route('/tiles/<layer>/<int:z>/<int:x>/<int:y>.png')
def serve_tile(layer, z, x, y):
    allowed = ('dem', 'batnas', 'hillshade', 'batnas_hillshade', 'facc', 'sinkdiff')
    if layer not in allowed:
        return 'Invalid layer', 404
    cache_key = (layer, z, x, y)
    if cache_key in TILE_CACHE:
        data = TILE_CACHE[cache_key]
        return Response(data, mimetype='image/png')

    img = render_tile(layer, z, x, y)
    if img is None:
        return Response(status=204)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    png_data = buf.getvalue()
    TILE_CACHE[cache_key] = png_data
    return Response(png_data, mimetype='image/png')


@app.route('/tiles/contour/<interval>/<int:z>/<int:x>/<int:y>.png')
def serve_contour_tile(interval, z, x, y):
    if interval not in ('1m', '5m', '10m'):
        return 'Invalid interval', 404
    cache_key = ('contour', interval, z, x, y)
    if cache_key in TILE_CACHE:
        data = TILE_CACHE[cache_key]
        return Response(data, mimetype='image/png')

    img = render_contour_tile(interval, z, x, y)
    if img is None:
        return Response(status=204)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    png_data = buf.getvalue()
    TILE_CACHE[cache_key] = png_data
    return Response(png_data, mimetype='image/png')


@app.route('/tiles/risk/<int:z>/<int:x>/<int:y>.png')
def serve_risk_tile(z, x, y):
    cache_key = ('risk', z, x, y)
    if cache_key in TILE_CACHE:
        return Response(TILE_CACHE[cache_key], mimetype='image/png')
    img = render_risk_tile(z, x, y)
    if img is None:
        return Response(status=204)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    png_data = buf.getvalue()
    TILE_CACHE[cache_key] = png_data
    return Response(png_data, mimetype='image/png')


@app.route('/tiles/streams/<int:z>/<int:x>/<int:y>.png')
def serve_streams_tile(z, x, y):
    cache_key = ('streams', z, x, y)
    if cache_key in TILE_CACHE:
        return Response(TILE_CACHE[cache_key], mimetype='image/png')
    img = render_streams_tile(z, x, y)
    if img is None:
        return Response(status=204)
    buf = io.BytesIO(); img.save(buf, format='PNG')
    png_data = buf.getvalue()
    TILE_CACHE[cache_key] = png_data
    return Response(png_data, mimetype='image/png')


@app.route('/api/weather')
def weather_proxy():
    now = time.time()
    if WEATHER_CACHE['data'] and now - WEATHER_CACHE['time'] < 120:
        return flask.jsonify(WEATHER_CACHE['data'])
    try:
        req = urllib.request.Request(
            'https://api.rainviewer.com/public/weather-maps.json',
            headers={'User-Agent': 'WebGIS-Pekanbaru/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        host = data['host']
        frames = []
        for f in data.get('radar', {}).get('past', []):
            frames.append({'time': f['time'], 'path': f['path'],
                           'tile_url': host + f['path']})
        for f in data.get('radar', {}).get('nowcast', []):
            frames.append({'time': f['time'], 'path': f['path'],
                           'tile_url': host + f['path']})
        result = {'frames': frames, 'count': len(frames)}
        WEATHER_CACHE['data'] = result
        WEATHER_CACHE['time'] = now
        return flask.jsonify(result)
    except Exception as e:
        return {'error': str(e)}, 502


@app.route('/api/risk-score')
def risk_score():
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if lat is None or lng is None:
        return {'error': 'lat and lng required'}, 400

    elev = None
    with rasterio.open(DEM_FILE) as src:
        if src.bounds.left <= lng <= src.bounds.right and src.bounds.bottom <= lat <= src.bounds.top:
            try:
                row, col = src.index(lng, lat)
                v = float(src.read(1)[row, col])
                nd = src.nodata
                if not np.isnan(v) and (nd is None or v != nd):
                    elev = v
            except Exception:
                pass

    facc_val = 0
    if os.path.exists(FACC_FILE):
        with rasterio.open(FACC_FILE) as src:
            if src.bounds.left <= lng <= src.bounds.right and src.bounds.bottom <= lat <= src.bounds.top:
                try:
                    row, col = src.index(lng, lat)
                    v = float(src.read(1)[row, col])
                    if v > 0 and not np.isnan(v):
                        facc_val = v
                except Exception:
                    pass

    sink_val = 0
    if os.path.exists(SINKDIFF_FILE):
        with rasterio.open(SINKDIFF_FILE) as src:
            if src.bounds.left <= lng <= src.bounds.right and src.bounds.bottom <= lat <= src.bounds.top:
                try:
                    row, col = src.index(lng, lat)
                    v = float(src.read(1)[row, col])
                    if v > 0.01 and not np.isnan(v):
                        sink_val = v
                except Exception:
                    pass

    adj_facc = np.log10(facc_val + 1) / 6.0 if facc_val > 0 else 0
    adj_sink = min(sink_val / 19.0, 1.0) if sink_val > 0 else 0
    adj_elev = 1 - min(elev / 100.0, 1.0) if elev is not None else 0.5

    score = 0.3 * adj_elev + 0.4 * adj_facc + 0.3 * adj_sink

    if score < 0.25:
        zona = 'Aman'
        warna = '#4caf50'
        rekom = 'Cocok untuk pembangunan. Tidak rawan banjir.'
    elif score < 0.50:
        zona = 'Waspada'
        warna = '#ffeb3b'
        rekom = 'Hati-hati saat hujan deras >50mm/jam. Cocok untuk ruang terbuka hijau.'
    elif score < 0.75:
        zona = 'Siaga'
        warna = '#ff9800'
        rekom = 'Sering genangan. Hindari pembangunan rumah padat. Gunakan untuk resapan.'
    else:
        zona = 'Bahaya'
        warna = '#f44336'
        rekom = 'Titik kritis banjir. Prioritas drainase dan evakuasi.'

    return flask.jsonify({
        'lat': lat, 'lng': lng,
        'elevation': elev,
        'flow_accumulation': facc_val,
        'sink_depth': sink_val,
        'risk_score': round(score, 3),
        'risk_zone': zona,
        'risk_color': warna,
        'recommendation': rekom,
    })


@app.route('/api/elevation')
def query_elevation():
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if lat is None or lng is None:
        return {'error': 'lat and lng required'}, 400

    best_elev = None
    with rasterio.open(DEM_FILE) as src:
        if src.bounds.left <= lng <= src.bounds.right and src.bounds.bottom <= lat <= src.bounds.top:
            try:
                row, col = src.index(lng, lat)
                data = src.read(1)
                val = float(data[row, col])
                nd = src.nodata
                if not np.isnan(val) and (nd is None or val != nd):
                    best_elev = val
            except Exception:
                pass

    batnas_elev = None
    with rasterio.open(BATNAS_FILE) as src:
        b_left, b_bottom, b_right, b_top = src.bounds
        if b_left <= lng <= b_right and b_bottom <= lat <= b_top:
            try:
                row, col = src.index(lng, lat)
                data = src.read(1)
                val = float(data[row, col])
                if not np.isnan(val):
                    batnas_elev = val
            except Exception:
                pass

    facc_val = None
    if os.path.exists(FACC_FILE):
        with rasterio.open(FACC_FILE) as src:
            f_left, f_bottom, f_right, f_top = src.bounds
            if f_left <= lng <= f_right and f_bottom <= lat <= f_top:
                try:
                    row, col = src.index(lng, lat)
                    data = src.read(1)
                    val = float(data[row, col])
                    if val > 0 and not np.isnan(val):
                        facc_val = val
                except Exception:
                    pass

    return {
        'lat': lat,
        'lng': lng,
        'dem_elevation': best_elev,
        'batnas_elevation': batnas_elev,
        'flow_accumulation': facc_val,
    }


@app.route('/api/contours')
def generate_contours():
    bounds = request.args.get('bounds')
    interval = request.args.get('interval', 10, type=float)
    if not bounds:
        return {'error': 'bounds required (west,south,east,north)'}, 400
    parts = bounds.split(',')
    if len(parts) != 4:
        return {'error': 'bounds must be west,south,east,north'}, 400
    west, south, east, north = map(float, parts)

    import subprocess, tempfile
    tmp_dir = tempfile.mkdtemp()
    try:
        crop_path = os.path.join(tmp_dir, 'crop.tif')
        shp_path = os.path.join(tmp_dir, 'contours.shp')

        ret = subprocess.run([
            'gdal_translate', '-projwin_srs', 'EPSG:4326',
            '-projwin', str(west), str(north), str(east), str(south),
            DEM_FILE, crop_path
        ], capture_output=True, text=True, timeout=60)
        if ret.returncode != 0:
            return {'error': 'failed to crop DEM'}, 500

        ret = subprocess.run([
            'gdal_contour', '-i', str(interval), '-a', 'elev',
            crop_path, shp_path
        ], capture_output=True, text=True, timeout=120)
        if ret.returncode != 0:
            return {'error': 'failed to generate contours'}, 500

        result = subprocess.run(
            ['ogr2ogr', '-f', 'GeoJSON', '/vsistdout/', shp_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {'error': 'failed to convert contours'}, 500

        geojson = json.loads(result.stdout)
        return flask.jsonify(geojson)

    except Exception as e:
        return {'error': str(e)}, 500
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route('/api/siak')
def siak_analysis():
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if not os.path.exists(BATNAS_FILE):
        return {'error': 'BATNAS data not available'}, 500

    with rasterio.open(BATNAS_FILE) as src:
        b_left, b_bottom, b_right, b_top = src.bounds
        row, col = src.index(lng or 102.1, lat or 1.1)
        data = src.read(1)

        east_west = []
        for offset in range(-80, 81, 2):
            c = col + offset
            if 0 <= c < src.width:
                d = float(data[row, c])
                if not np.isnan(d):
                    lon = src.transform * (c, row)
                    east_west.append({'lon': round(lon[0], 4), 'depth': round(d, 1)})

        north_south = []
        for offset in range(-80, 81, 2):
            r = row + offset
            if 0 <= r < src.height:
                d = float(data[r, col])
                if not np.isnan(d):
                    lat_coord = src.transform * (col, r)
                    north_south.append({'lat': round(lat_coord[1], 4), 'depth': round(d, 1)})

        window = data[max(0, row-50):min(src.height, row+50),
                      max(0, col-50):min(src.width, col+50)]
        valid = window[~np.isnan(window)]

        return flask.jsonify({
            'location': {'lat': lat or 1.1, 'lng': lng or 102.1},
            'cross_section_ew': east_west,
            'cross_section_ns': north_south,
            'stats': {
                'min_depth': round(float(valid.min()), 1) if len(valid) > 0 else None,
                'max_depth': round(float(valid.max()), 1) if len(valid) > 0 else None,
                'mean_depth': round(float(valid.mean()), 1) if len(valid) > 0 else None,
                'sample_count': int(len(valid)),
            }
        })


@app.route('/api/info')
def layer_info():
    info = {
        'dem': {
            'bounds': list(PEKANBARU_DEM_BOUNDS),
            'elevation_range': {'min': -10, 'max': 110},
            'description': 'DEMNAS Pekanbaru - Digital Elevation Model'
        },
        'batnas': {
            'bounds': list(BATNAS_BOUNDS),
            'description': 'BATNAS - Bathymetry Nasional'
        },
        'center': [0.44, 101.5],
    }
    if os.path.exists(FACC_FILE):
        with rasterio.open(FACC_FILE) as src:
            info['flow_accumulation'] = {
                'bounds': [src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top],
                'description': 'Flow Accumulation from DEMNAS'
            }
    if os.path.exists(os.path.join(DATA_DIR, 'contours_1m_simple.geojson')):
        info['contours'] = {
            'available_intervals': [1, 5, 10],
            'files': {
                '1m': 'contours_1m_simple.geojson',
                '5m': 'contours_5m_simple.geojson',
                '10m': 'contours_10m_simple.geojson',
            }
        }
    return flask.jsonify(info)


@app.route('/data/<path:filename>')
def serve_data(filename):
    if not filename.endswith('.geojson'):
        return 'Not allowed', 403
    safe = os.path.normpath(os.path.join(DATA_DIR, filename))
    if not safe.startswith(DATA_DIR):
        return 'Not allowed', 403
    if not os.path.exists(safe):
        return 'Not found', 404
    return flask.send_file(safe, mimetype='application/geo+json')


@app.route('/')
def index():
    return flask.render_template('index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
