"""Private Supabase invoice storage; OCR only uses disposable temporary files."""
import base64
from pathlib import Path
import secrets
import tempfile
import time
from app import cloud, store
from app.domain import ValidationError
from app.ocr import extract


def upload(data, actor, mode):
    try:
        raw=base64.b64decode(data.get('content',''),validate=True)
    except Exception:
        raise ValidationError('Invalid image upload') from None
    if not raw or len(raw)>cloud.MAX_FILE:
        raise ValidationError('Upload a file smaller than 8 MB')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        mime,suffix='image/png','.png'
    elif raw.startswith(b'\xff\xd8\xff'):
        mime,suffix='image/jpeg','.jpg'
    elif raw.startswith(b'%PDF-'):
        mime,suffix='application/pdf','.pdf'
    else:
        raise ValidationError('Upload a JPG, PNG or PDF')
    identifier=secrets.token_hex(16)
    key=f'upkar-agency/{mode}/{identifier}{suffix}'
    name=str(data.get('name','bill'))[:200]
    cloud.put_file(key,raw,mime)
    try:
        with store.transaction() as db:
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',(identifier,mode,name,mime,key,time.time()))
            store.audit(db,actor,'bill_uploaded',identifier)
    except Exception:
        try:
            cloud.delete_file(key)
        except Exception:
            pass
        raise
    with tempfile.TemporaryDirectory(prefix='office-bill-') as directory:
        temporary=Path(directory)/('bill'+suffix)
        temporary.write_bytes(raw)
        ocr=extract(temporary)
    return {'id':identifier,'mime':mime,'name':name,'ocr':ocr}
