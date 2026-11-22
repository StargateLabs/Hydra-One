"""The capability registry must describe wired workflows and cover every media task."""
import unittest
from types import SimpleNamespace


def worker(**state):
    return SimpleNamespace(status=lambda: state)


class CapabilityRegistryTests(unittest.TestCase):
    def service(self, **overrides):
        fields = dict(
            local_audio=worker(installed=True, status='idle', models=[{'name': 'tiny'}],
                               formats=['wav'], input_limit_bytes=200, duration_limit_s=300),
            local_speech=worker(installed=False, status='idle', models=[{'name': 'kokoro'}]),
            local_separation=worker(status='idle', models=[]),
            local_visual=worker(models=[{'kind': 'image', 'name': 'sd', 'test_fixture': False}]),
            local_generative_audio=worker(runtime_installed=True,
                                          models=[{'task': 'music', 'name': 'musicgen'}]),
        )
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def rows(self, **overrides):
        from serve.multimedia_capabilities import capabilities
        return {row['id']: row for row in capabilities(self.service(**overrides))['tasks']}

    def test_separation_is_declared_with_its_endpoints(self):
        rows = self.rows()
        self.assertIn('separation', rows)
        self.assertTrue(rows['separation']['implemented'])
        self.assertEqual(rows['separation']['endpoints'], ['/local-separation/run'])

    def test_visual_generation_follows_the_worker(self):
        rows = self.rows()
        for kind in ('image', 'video'):
            with self.subTest(kind=kind):
                self.assertTrue(rows[kind + '_generation']['implemented'])
                self.assertEqual(rows[kind + '_generation']['endpoints'], ['/local-visual/start'])
        self.assertTrue(rows['image_generation']['available'])
        self.assertFalse(rows['video_generation']['available'])

    def test_no_stale_not_implemented_row_survives_when_the_worker_is_present(self):
        rows = self.rows()
        self.assertNotIn('not_implemented', [row.get('verification_scope') for row in rows.values()])
        self.assertNotIn('No video generation runner is integrated.',
                         [row.get('reason') for row in rows.values()])

    def test_visual_generation_is_not_implemented_without_a_worker(self):
        from serve.multimedia_capabilities import capabilities
        service = self.service()
        del service.local_visual
        rows = {row['id']: row for row in capabilities(service)['tasks']}
        self.assertFalse(rows['image_generation']['implemented'])
        self.assertEqual(rows['image_generation']['endpoints'], [])

    def test_failed_separation_status_does_not_hide_other_workflows(self):
        service = self.service()
        service.local_separation.status = lambda: (_ for _ in ()).throw(ValueError('broken separation'))
        from serve.multimedia_capabilities import capabilities
        rows = {row['id']: row for row in capabilities(service)['tasks']}
        self.assertEqual(rows['separation']['error'], 'broken separation')
        self.assertIn('music', rows)


if __name__ == '__main__':
    unittest.main()
