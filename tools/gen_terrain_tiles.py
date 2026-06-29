"""Generate XYZ terrain-RGB tiles from terrain_rgb.tif."""
import math, os, sys
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from PIL import Image

SRC = 'static/terrain_rgb.tif'
OUT_DIR = 'static/terrain_tiles'

PEKANBARU = (101.32298, 0.42042, 101.60531, 0.69097)
LNG_MIN, LAT_MIN, LNG_MAX, LAT_MAX = PEKANBARU

def lonlat_to_tile(lon, lat, z):
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return int(math.floor(x)), int(math.floor(y))

def tile_bounds(x, y, z):
    n = 2.0 ** z
    lon_left = x / n * 360.0 - 180.0
    lon_right = (x + 1) / n * 360.0 - 180.0
    lat_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_left, lat_bottom, lon_right, lat_top

MIN_ZOOM, MAX_ZOOM = 8, 14

# Open dataset once and keep it open
with rasterio.open(SRC) as src:
    src_bounds = src.bounds
    src_transform = src.transform
    total_tiles = 0

    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        x_min, y_max = lonlat_to_tile(LNG_MIN, LAT_MIN, z)
        x_max, y_min = lonlat_to_tile(LNG_MAX, LAT_MAX, z)
        x_min, x_max = min(x_min, x_max), max(x_min, x_max)
        y_min, y_max = min(y_min, y_max), max(y_min, y_max)

        z_dir = os.path.join(OUT_DIR, str(z))
        os.makedirs(z_dir, exist_ok=True)

        count = 0
        for x in range(x_min, x_max + 1):
            x_dir = os.path.join(z_dir, str(x))
            os.makedirs(x_dir, exist_ok=True)

            for y in range(y_min, y_max + 1):
                out_path = os.path.join(x_dir, f'{y}.png')
                if os.path.exists(out_path):
                    continue

                left, bottom, right, top = tile_bounds(x, y, z)

                # Expand bounds slightly to avoid edge artifacts
                pad = 0.0005
                q_left = max(left - pad, src_bounds.left)
                q_bottom = max(bottom - pad, src_bounds.bottom)
                q_right = min(right + pad, src_bounds.right)
                q_top = min(top + pad, src_bounds.top)

                if q_left >= q_right or q_bottom >= q_top:
                    continue

                try:
                    window = from_bounds(q_left, q_bottom, q_right, q_top, src_transform)
                    data = src.read(window=window, out_shape=(3, 256, 256),
                                    resampling=Resampling.bilinear, boundless=True)

                    rgba = np.zeros((256, 256, 4), dtype=np.uint8)
                    rgba[:, :, :3] = np.transpose(data, (1, 2, 0))
                    nodata_mask = np.all(data == 0, axis=0)
                    rgba[:, :, 3] = np.where(nodata_mask, 0, 255)

                    Image.fromarray(rgba, 'RGBA').save(out_path, 'PNG')
                    count += 1
                except Exception as e:
                    print(f'Error z={z} x={x} y={y}: {e}', file=sys.stderr)

        total_tiles += count
        print(f'Zoom {z}: {x_min}-{x_max} x {y_min}-{y_max} = {count} tiles')

print(f'\nDone! {total_tiles} tiles generated in {OUT_DIR}')
