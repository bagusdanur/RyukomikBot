import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dashboard.backend.raw_join import prepare_inputs


def test_width_changes_preserve_all_boundaries(tmp_path):
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    widths = [100, 80, 100]
    sources = []
    for index, (color, width) in enumerate(zip(colors, widths)):
        path = tmp_path / f'{index}.png'
        Image.new('RGB', (width, 8), color).save(path)
        sources.append(path)

    outputs = prepare_inputs(sources, tmp_path / 'joined', max_height=10, search_rows=4)

    assert [p.stem for p in outputs] == ['joined-001', 'joined-002', 'joined-003']
    for path, color, width in zip(outputs, colors, widths):
        image = np.asarray(Image.open(path).convert('RGB'))
        assert image.shape == (8, width, 3)
        assert np.array_equal(image[0, 0], np.asarray(color, dtype=np.uint8))
        assert np.array_equal(image[-1, -1], np.asarray(color, dtype=np.uint8))
