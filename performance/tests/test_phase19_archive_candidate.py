import importlib.util
from pathlib import Path
import tempfile
import unittest
import json

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('phase19_archive_candidate',ROOT/'performance/scripts/phase19_archive_candidate.py')
archive=importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class CandidateArchiveTests(unittest.TestCase):
    def test_raw_fixture_excluded_and_original_hash_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source';source.mkdir()
            target=Path(directory)/'target'
            raw=b'{"valid":false}\r\n'
            (source/'result.json').write_bytes(raw)
            (source/'users.json').write_text('private-session-value')
            archive.archive(source,target,{'result.json'})
            self.assertFalse((target/'users.json').exists())
            manifest=json.loads((target/'archive-manifest.json').read_text())
            self.assertEqual(manifest['files']['result.json']['sourceSha256'],archive.digest(raw))
            (source/'result.json').write_text('{"valid":true}')
            with self.assertRaises(ValueError):archive.archive(source,target,{'result.json'})

    def test_local_devtools_endpoint_redacted(self):
        self.assertEqual(archive.redact('DevTools ws://127.0.0.1:54321/devtools/browser/abc-def'),'DevTools <DEVTOOLS_ENDPOINT>')


if __name__=='__main__':unittest.main()
