"""Private, test-only import evidence. The inspection command never calls Tally."""
import json
import os
from pathlib import Path
import re
import secrets
import xml.etree.ElementTree as ET


def folder():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'OfficeTally-Test'/'diagnostics'


def begin(xml):
    target=folder()/secrets.token_hex(16)
    target.mkdir(parents=True,exist_ok=False)
    (target/'request.xml').write_bytes(xml)
    (target/'result.json').write_text(json.dumps({'stage':'prepared','note':'Request prepared; no import outcome recorded yet'}))
    return target


def received(target,status,raw):
    (target/'response.xml').write_bytes(raw)
    (target/'result.json').write_text(json.dumps({'stage':'response_received','http_status':status,'bytes_saved':len(raw)}))


def inspect(target):
    from connector.read_company import parse_response
    result=json.loads((target/'result.json').read_text())
    response=target/'response.xml'
    if response.exists():
        try:
            root=parse_response(response.read_bytes(),allow_tally_errors=True)
            result['counts']={tag:root.findtext('.//'+tag) for tag in ('CREATED','ALTERED','DELETED','ERRORS','EXCEPTIONS','IGNORED')}
            result['details']=[{'field':n.tag,'message':n.text.strip()[:2000]} for n in root.iter()
                if n.tag.upper() in ('LINEERROR','ERROR','EXCEPTION','ERRORMSG','DESCRIPTION') and n.text and n.text.strip()][:30]
        except (ValueError,UnicodeError,ET.ParseError):
            result['note']='Response saved but could not be parsed safely; inspect the local file'
    return result


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Inspect the latest locally captured TEST import; never submits or retries a voucher')
    parser.parse_args()
    root=folder()
    files=sorted(root.glob('*/result.json'),key=lambda p:p.stat().st_mtime) if root.exists() else []
    if not files:
        print('No captured test import exists yet. Previous responses cannot be recovered retroactively.')
        return
    target=files[-1].parent
    print('LOCAL TEST evidence: '+str(target))
    print(json.dumps(inspect(target),indent=2))
    print('Files may contain business details. Share only relevant error text; do not upload the entire folder.')

if __name__=='__main__':main()
