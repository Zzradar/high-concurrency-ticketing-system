import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('phase19_archive',ROOT/'performance/scripts/phase19_archive_diagnostics.py')
archive=importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class ArchiveTests(unittest.TestCase):
    def test_prior_point_cannot_be_replaced_with_recomputed_result(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'result.json'
            archive.write_once(target,b'original')
            archive.write_once(target,b'original')
            with self.assertRaises(ValueError):
                archive.write_once(target,b'recomputed')
            self.assertEqual(target.read_bytes(),b'original')

    def test_private_path_redaction_handles_json_backslashes(self):
        raw=str(archive.PRIVATE).replace('\\','\\\\')+'/point'
        self.assertEqual(archive.redact(raw),'<PRIVATE_TEMP>/point')


if __name__=='__main__':unittest.main()
