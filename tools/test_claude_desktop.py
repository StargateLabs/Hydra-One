"""Desktop integration checks without opening UI or starting inference."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from serve import claude_desktop


class DesktopTests(unittest.TestCase):
    def test_gateway_stable_alias_has_explicit_transport_tier(self):
        rows=[{'id':'local/qwen','object':'model'},{'id':'strata','object':'model','alias_of':'local/qwen'}]
        result=claude_desktop.gateway_models(rows)
        self.assertNotIn('anthropic_family_tier',result[0])
        self.assertEqual(result[1]['anthropic_family_tier'],'sonnet')
        self.assertTrue(result[1]['is_family_default'])
        self.assertIn('local/qwen',result[1]['display_name'])
        self.assertNotIn('anthropic_family_tier',rows[1])

    def test_discovery_preserves_dynamic_models(self):
        with patch.object(claude_desktop, 'executable', return_value=Path('Claude.exe')), patch.object(claude_desktop, '_policy', return_value={'inferenceProvider':'gateway','inferenceGatewayBaseUrl':claude_desktop.GATEWAY}):
            result = claude_desktop.status()
            self.assertTrue(result['configured'])
            self.assertTrue(result['model_discovery'])
            self.assertFalse(result['inference_verified'])

    def test_launch_only_original_desktop(self):
        path = Path('C:/official/AnthropicClaude/claude.exe')
        with patch.object(claude_desktop, 'executable', return_value=path), patch.object(claude_desktop, '_policy', return_value={}), patch.object(claude_desktop.subprocess, 'Popen') as process:
            result = claude_desktop.launch()
            self.assertTrue(result['launched'])
            self.assertEqual(process.call_args.args[0], [str(path)])
            self.assertFalse(result['desktop']['configured'])

    def test_missing_app_fails_clearly(self):
        with patch.object(claude_desktop, 'executable', return_value=None), self.assertRaises(RuntimeError):
            claude_desktop.launch()


if __name__ == '__main__':
    unittest.main()
