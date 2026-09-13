import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from phase19_archive_formal import package, digest


class FormalArchiveTests(unittest.TestCase):
    def test_lossless_timeline_private_exclusion_and_failed_result(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source'; source.mkdir()
            target = Path(folder) / 'archive'
            raw = b'{"metric":1}\n'
            (source / 'k6-points.jsonl').write_bytes(raw)
            result = {'valid': False, 'endedUtc': '2026-09-13T00:00:00Z', 'rawPointsSha256': digest(raw), 'rawPointsBytes': len(raw)}
            (source / 'result.json').write_text(json.dumps(result))
            timeline = json.dumps({'samples': ['sample'] * 130000}).encode()
            (source / 'system-observations.json').write_bytes(timeline)
            (source / 'users.json').write_text('session-secret')
            manifest = package(source, target)
            self.assertFalse((target / 'users.json').exists())
            self.assertFalse((target / 'k6-points.jsonl').exists())
            self.assertFalse(json.loads((target / 'result.json').read_text())['valid'])
            self.assertEqual(gzip.decompress((target / 'system-observations.json.gz').read_bytes()), timeline)
            self.assertEqual(manifest['privateRawPoints']['sha256'], digest(raw))
            with self.assertRaises(ValueError): package(source, target)

    def test_tampered_raw_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source'; source.mkdir()
            target = Path(folder) / 'archive'
            (source / 'result.json').write_text('{"endedUtc":"2026-09-13T00:00:00Z","rawPointsSha256":"wrong","rawPointsBytes":1}')
            (source / 'k6-points.jsonl').write_bytes(b'x')
            with self.assertRaises(ValueError): package(source, target)
            self.assertFalse(target.exists())

    def test_native_gzip_raw_hash_is_retained_without_committing_the_private_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';source.mkdir()
            target=Path(folder)/'archive'
            raw=gzip.compress(b'{"metric":1}\n',mtime=0)
            (source/'k6-points.jsonl.gz').write_bytes(raw)
            (source/'result.json').write_text(json.dumps({'endedUtc':'2026-09-13T00:00:00Z',
                'rawPointsSha256':digest(raw),'rawPointsBytes':len(raw)}))
            result=package(source,target)
            self.assertTrue(result['privateRawPoints']['path'].endswith('.jsonl.gz'))
            self.assertEqual(result['privateRawPoints']['sha256'],digest(raw))
            self.assertFalse((target/'k6-points.jsonl.gz').exists())

    def test_incomplete_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError): package(Path(folder), Path(folder) / 'archive')
            (Path(folder) / 'browser.json').write_text('{"passed":false,"requests":[]}')
            with self.assertRaises(ValueError): package(Path(folder), Path(folder) / 'archive')


if __name__ == '__main__': unittest.main()
