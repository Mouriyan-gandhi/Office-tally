"""Interactive Windows setup; a local config file is never committed to Git."""
import getpass
import json
import os
from pathlib import Path
import sys
from connector.worker import main, Cloud
from app.company import COMPANY
from connector.windows_secrets import protect, unprotect


def launch():
    if os.name != 'nt':
        raise SystemExit('Use this launcher on the Windows office laptop. The Mac runs the app, not Tally.')
    folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / ('OfficeTally-Test' if COMPANY.endswith(' TEST') else 'OfficeTally')
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'connector.json'
    if path.exists():
        config = json.loads(path.read_text())
    else:
        print('Upkar Agency — Windows connector setup')
        print('Keep Tally open with Upkar Agency loaded. Do not expose port 9000.')
        url = input('App HTTPS address: ').strip()
        token = getpass.getpass('Connector token (hidden): ').strip()
        Cloud(url, token)
        port = int(input('Local Tally port [9000]: ').strip() or '9000')
        if not 1 <= port <= 65535:
            raise SystemExit('Invalid port')
        config = {'url': url, 'token_protected': protect(token), 'port': port, 'allow_writes': False}
        path.write_text(json.dumps(config))
        print('Saved local configuration. Sync starts in read-only mode.')
        print('For reviewed posting activation, see docs/WINDOWS.md.')
    os.environ['OFFICE_APP_URL'] = config['url']
    os.environ['OFFICE_CONNECTOR_TOKEN'] = unprotect(config['token_protected'])
    os.environ['OFFICE_ALLOW_TALLY_WRITES'] = 'YES' if config.get('allow_writes') else 'NO'
    sys.argv = [sys.argv[0], '--port', str(config['port'])]
    main()

if __name__ == '__main__':
    launch()
