from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'tools/build_language_data.py'
path.write_text('"""Compatibility entry point for the stable reviewed language catalogue."""\nfrom build_language_assets import main\n\nif __name__ == "__main__":main()\n',encoding='utf-8')
