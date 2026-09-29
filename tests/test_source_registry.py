"""Setiap sumber RAW harus terdaftar di SEMUA tempat yang memakainya.

Insiden: `lua.py` dan `mgread.py` sudah dipakai (terdaftar di `project_scout`,
`qc.py`, `app.py`) tetapi filenya masih untracked -- hilang begitu repo
di-clone bersih atau `git clean`. Sebaliknya, `mist` sudah ditambahkan di
registry tetapi belum ikut didaftarkan di `project_scout.RAW_DOWNLOADERS`
dan dict di `qc.py`, sehingga muncul di sebagian layar saja.

Test ini menjaga dua invarian:
1. Setiap nama di `SOURCE_ORDER` bisa di-resolve `get_downloader`.
2. Sumber yang dipakai di `project_scout.RAW_DOWNLOADERS` dan dict `qc.py`
   semuanya resolvable (tidak menunjuk modul yang tidak ada).
3. Sumber yang wajib ada (lua, mgread, mist) benar-benar terdaftar di
   ketiga tempat itu.
"""
import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from raw_downloader import get_downloader  # noqa: E402
from raw_downloader.resolver import SOURCE_ORDER  # noqa: E402

import project_scout  # noqa: E402

# Sumber yang wajib terdaftar di semua tempat.
REQUIRED = ("lua", "mgread", "mist")


def _qc_downloader_keys() -> set[str]:
    """Ambil key dict downloader di qc.py lewat AST.

    qc.py punya banyak dict (payload, stats, ...). Dict downloader adalah
    satu-satunya yang seluruh nilainya berupa `Name` berakhiran `_downloader`.
    """
    tree = ast.parse((ROOT / "dashboard/backend/routers/qc.py").read_text())
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict) or not node.keys:
            continue
        values = [v for v in node.values if v is not None]
        if not values:
            continue
        if not all(
            isinstance(v, ast.Name) and v.id.endswith("_downloader")
            for v in values
        ):
            continue
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


class SourceOrderTest(unittest.TestCase):
    def test_semua_source_order_resolvable(self):
        for source in SOURCE_ORDER:
            with self.subTest(source=source):
                downloader = get_downloader(source)
                self.assertIsNotNone(downloader)
                # Downloader lama (asura, omega, ...) tidak mengekspos `.source`;
                # keluarga Dusk/Lua/MGRead/Mist harus cocok dengan namanya.
                declared = getattr(downloader, "source", None)
                if declared is not None:
                    self.assertEqual(declared, source)

    def test_tanpa_duplikat(self):
        self.assertEqual(len(SOURCE_ORDER), len(set(SOURCE_ORDER)))


class ProjectScoutRegistryTest(unittest.TestCase):
    def test_raw_downloaders_resolvable(self):
        for source, downloader in project_scout.RAW_DOWNLOADERS.items():
            with self.subTest(source=source):
                self.assertIs(downloader, get_downloader(source))

    def test_sumber_wajib_terdaftar(self):
        for source in REQUIRED:
            with self.subTest(source=source):
                self.assertIn(source, project_scout.RAW_DOWNLOADERS)


class QcRouterRegistryTest(unittest.TestCase):
    def test_sumber_wajib_ada_di_qc(self):
        keys = _qc_downloader_keys()
        for source in REQUIRED:
            with self.subTest(source=source):
                self.assertIn(source, keys)

    def test_qc_keys_semuanya_resolvable(self):
        for source in _qc_downloader_keys():
            with self.subTest(source=source):
                get_downloader(source)  # tidak boleh melempar ValueError


class RegisteredModulesExistTest(unittest.TestCase):
    """Sumber yang dipakai harus punya file yang benar-benar di-track git."""

    def test_file_downloader_wajib_ada(self):
        for name in ("lua.py", "mgread.py", "mist.py"):
            with self.subTest(file=name):
                self.assertTrue(
                    (ROOT / "raw_downloader" / name).exists(),
                    f"{name} hilang dari raw_downloader/",
                )


if __name__ == "__main__":
    unittest.main()
