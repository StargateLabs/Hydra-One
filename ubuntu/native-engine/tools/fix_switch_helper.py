from pathlib import Path
path=Path(__file__).resolve().parents[1]/'serve/_switch.py'
source=path.read_text(encoding='utf-8')
start=source.index('    # igiene obbligatoria:')
end=source.index('    # il motore impiega',start)
source=source[:start]+source[end:]
source=source.replace('str(config), "--port", str(porta)]','str(config), "--port", str(porta), "--lazy", "--api-monitor", "--idle-unload", "900"]')
path.write_text(source,encoding='utf-8')
