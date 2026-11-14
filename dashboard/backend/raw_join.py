"""Bounded, lossless source joining. Never resize or discard source rows."""
from pathlib import Path
import json
import numpy as np
from PIL import Image

TITLE_SLUG = 'when-i-lied-on-a-dating-app'
VERSION = 3

def prepare_inputs(paths, directory, *, max_height=15000, search_rows=4000):
    """Join RAW pages up to `max_height` rows without exceeding memory.

    A single preallocated RGB buffer is filled row-by-row; the old version used
    np.concatenate() per source page, which allocated two or three full copies
    of the 15k-row canvas at once and pushed the dashboard process over its
    memory limit (PM2 restarted it -> nginx 502 during "gabung").
    """
    paths = [Path(p) for p in paths]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    signature = {'version': VERSION, 'height': max_height, 'search': search_rows,
                 'sources': [[p.name, p.stat().st_size, p.stat().st_mtime_ns] for p in paths]}
    manifest_path = directory / 'manifest.json'
    if manifest_path.exists():
        cached = json.loads(manifest_path.read_text())
        if cached['signature'] == signature and all((directory / p['name']).exists() for p in cached['pages']):
            return [directory / p['name'] for p in cached['pages']]

    pages, spans = [], []
    buffer = None
    filled = 0

    def ensure(width):
        nonlocal buffer
        if buffer is None or buffer.shape[1] != width:
            buffer = np.empty((max_height, width, 3), dtype=np.uint8)

    def flush(count, reason):
        nonlocal buffer, filled, spans
        count = int(count)
        name = f'joined-{len(pages)+1:03d}.webp'
        Image.fromarray(buffer[:count]).save(directory / name, 'WEBP', lossless=True, method=1)
        used, left = [], []
        for s in spans:
            y, n = s['output_y'], s['end_y'] - s['start_y']
            take = max(0, min(n, count - y))
            if take:
                used.append(dict(s, end_y=s['start_y'] + take))
            if take < n:
                left.append(dict(s, start_y=s['start_y'] + take, output_y=max(0, y - count)))
        pages.append({'name': name, 'width': buffer.shape[1], 'height': count,
                      'cut': reason, 'spans': used})
        # Shift only the unwritten tail currently present in the buffer.
        # The remainder is not the whole unfilled canvas: on a width-change
        # flush, the entire buffer was consumed, so no rows can survive.
        remainder = filled - count
        if remainder > 0:
            buffer[:remainder] = buffer[count:count + remainder]
        filled = remainder
        spans = left

    for path in paths:
        with Image.open(path) as source:
            arr = np.asarray(source.convert('RGB'))
        if filled and buffer is not None and buffer.shape[1] != arr.shape[1]:
            # Flush the old-width content before allocating a new canvas.
            # Doing this after ensure() would overwrite it with empty rows.
            flush(filled, 'WIDTH_CHANGE')
        ensure(arr.shape[1])
        offset = 0
        while offset < len(arr):
            take = min(max_height - filled, len(arr) - offset)
            buffer[filled:filled + take] = arr[offset:offset + take]
            spans.append({'source': path.name, 'start_y': offset, 'end_y': offset + take, 'output_y': filled})
            filled += take
            offset += take
            if filled == max_height:
                # Strict full-width blank bands avoid the thin sides of speech balloons.
                band = buffer[max(1, max_height - search_rows):max_height]
                blank = np.all(band >= 248, axis=(1, 2)) | np.all(band <= 7, axis=(1, 2))
                starts = np.flatnonzero(np.diff(np.r_[False, blank, False].astype(int)) == 1)
                ends = np.flatnonzero(np.diff(np.r_[False, blank, False].astype(int)) == -1)
                valid = [(a, b) for a, b in zip(starts, ends) if b - a >= 16]
                if valid:
                    a, b = valid[-1]
                    flush(max_height - len(band) + (a + b) // 2, 'FULL_WIDTH_GUTTER')
                else:
                    boundaries = [s['output_y'] for s in spans if s['output_y'] >= max_height - search_rows]
                    if boundaries:
                        flush(max(boundaries), 'NO_SAFE_GUTTER_SOURCE_BOUNDARY')
                    else:
                        flush(max_height, 'NO_SAFE_GUTTER')
    if filled:
        flush(filled, 'END_OF_SOURCE')
    manifest_path.write_text(json.dumps({'signature': signature, 'pages': pages}, indent=2))
    return [directory / p['name'] for p in pages]
