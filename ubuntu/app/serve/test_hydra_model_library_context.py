"""The HYDRA library and the local picker explain the selected model's components."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'serve' / 'web'
HYDRA = (WEB / 'hydra-model-library.js').read_text(encoding='utf-8')
PICKER = (WEB / 'local-model-picker.js').read_text(encoding='utf-8')


class SelectionContextTests(unittest.TestCase):
    def test_the_selected_model_lists_its_paired_projectors(self):
        self.assertIn('function selectionNotes', HYDRA)
        self.assertIn('componentsForModel(row,rows)', HYDRA)
        self.assertIn('utilizzato quando Visione', HYDRA)
        self.assertIn('owner.paired_projectors', HYDRA)
        self.assertIn('rows.some(row=>row.path===projector)', PICKER)

    def test_the_control_vector_is_described_as_optional_not_as_speed(self):
        self.assertIn('Vettore di controllo sperimentale', HYDRA)
        self.assertIn('non è un’accelerazione', HYDRA)
        self.assertIn('Si abilita al setup', HYDRA)

    def test_blocked_and_auxiliary_rows_can_be_inspected(self):
        self.assertIn('option.disabled=false', HYDRA)
        self.assertIn('row.component||!row.available', HYDRA)
        self.assertIn('Non avviabile come modello', PICKER)
        self.assertIn('model-picker-warning', PICKER)

    def test_the_local_picker_keeps_auxiliary_roles(self):
        self.assertIn("row.file_role==='controlvector'", PICKER)
        self.assertIn("row.file_role==='projector'", PICKER)
        self.assertIn('componente ausiliario', PICKER)


if __name__ == '__main__':
    unittest.main()
