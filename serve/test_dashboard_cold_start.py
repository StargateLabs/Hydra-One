"""The dashboard must never consume model resources merely by opening."""
import argparse
import ast
from pathlib import Path
import unittest


class ColdStartTests(unittest.TestCase):
    def test_real_cli_definitions_default_to_unloaded_with_explicit_preload(self):
        parser=argparse.ArgumentParser()
        source=Path(__file__).with_name('server.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument' and node.args and isinstance(node.args[0],ast.Constant) and node.args[0].value in ('--lazy','--preload'):
                eval(compile(ast.Expression(node),'<actual dashboard arguments>','eval'),{'ap':parser})
        self.assertTrue(parser.parse_args([]).lazy)
        self.assertTrue(parser.parse_args(['--lazy']).lazy)
        self.assertFalse(parser.parse_args(['--preload']).lazy)


if __name__=='__main__':unittest.main()
