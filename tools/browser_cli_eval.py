"""Pass CLI evaluation source as one argument on Windows, without shell quoting."""
import subprocess
import sys
from pathlib import Path
cli = Path.home()/'AppData/Local/npm-cache/_npx/31e32ef8478fbf80/node_modules/@playwright/cli/playwright-cli.js'
subprocess.run(['node',str(cli),'-s=strata','eval',Path(sys.argv[1]).read_text(encoding='utf-8')],check=True)
