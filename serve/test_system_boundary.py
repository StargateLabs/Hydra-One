import tempfile
import unittest
from pathlib import Path
from serve.frontend import ChatTemplate
from serve.safetensors_runtime import normalize_messages

class SystemBoundaryTests(unittest.TestCase):
    def test_direct_template_has_no_late_system_or_developer(self):
        source=[{'role':'system','content':'start'},{'role':'user','content':'hello'},{'role':'developer','content':'later'}]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'template.jinja'
            path.write_text("{% for m in messages %}{% if m.role == 'system' and not loop.first %}{{ raise_exception('System message must be at the beginning.') }}{% endif %}{{ m.role }}:{{ m.content }};{% endfor %}")
            self.assertEqual(ChatTemplate(path).render(source),'system:start;user:hello;user:later;')
        self.assertEqual(source[2]['role'],'developer')

    def test_safetensors_combines_instruction_messages_first(self):
        source=[{'role':'user','content':'hello'},{'role':'developer','content':'one'},{'role':'system','content':'two'}]
        self.assertEqual(normalize_messages(source),[{'role':'system','content':'one\n\ntwo'},source[0]])
        self.assertEqual(source[1]['role'],'developer')
