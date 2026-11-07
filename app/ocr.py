"""Local-only image/PDF OCR. Suggestions are never posting instructions."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def extract(path):
    binary = shutil.which('tesseract')
    if not binary:
        return {'available': False, 'message': 'Local OCR is not installed. Enter the bill manually, or install Tesseract on the app host.'}
    try:
        with tempfile.TemporaryDirectory(prefix='office-ocr-') as folder:
            images = [Path(path)]
            truncated = False
            if Path(path).suffix.lower() == '.pdf':
                renderer = shutil.which('pdftoppm')
                if not renderer:
                    return {'available': False, 'message': 'PDF attached. Install Poppler for local PDF OCR, or upload a JPG/PNG instead.'}
                prefix = str(Path(folder) / 'page')
                subprocess.run([renderer, '-f', '1', '-l', '3', '-scale-to', '2200', '-png', str(path), prefix],
                               capture_output=True, timeout=35, check=True)
                images = sorted(Path(folder).glob('page-*.png'))
                truncated = True
            chunks = []
            for image in images:
                result = subprocess.run([binary, str(image), 'stdout', '--psm', '6'], capture_output=True, text=True, timeout=45, check=True)
                chunks.append(result.stdout[:20000])
            content = '\n\n'.join(chunks)[:50000]
    except (subprocess.SubprocessError, OSError):
        return {'available': False, 'message': 'The bill could not be read. Use a clearer image, or enter the bill manually.'}
    reference = re.search(r'(?:invoice|bill)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9/\-]+)', content, re.I)
    gstins = re.findall(r'\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b', content.upper())
    total = re.search(r'(?:grand\s+total|net\s+(?:amount|total)|invoice\s+total)\s*[:₹Rs.\s]*([\d,]+\.\d{2})', content, re.I)
    return {'available': True, 'text': content, 'reference': reference.group(1) if reference else '', 'gstins': gstins,
            'suggested_total': total.group(1).replace(',', '') if total else '',
            'suggestions': suggestions(content),
            'message': ('Only the first 3 PDF pages were considered. ' if truncated else '') + 'Review the original and every field. Supplier, stock and tax mappings require your review.'}


def suggestions(content):
    """Conservative printed-text patterns; unknown layouts remain manual drafts."""
    from datetime import date
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    items = []
    for index, line in enumerate(lines):
        separate = re.search(r'Quantity\s*:\s*([\d.]+)\s*([A-Za-z]+)\s+Rate\s*:\s*([\d,.]+)', line, re.I)
        table = re.fullmatch(r'(.+?[A-Za-z].*?)\s+(\d+(?:\.\d+)?)\s+([A-Za-z]+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})', line)
        if separate and index:
            qty, unit, rate = separate.groups()
            items.append({'description':lines[index-1], 'qty':qty, 'unit':unit, 'rate':rate.replace(',','')})
        elif table:
            description, qty, unit, rate, _total = table.groups()
            items.append({'description':description, 'qty':qty, 'unit':unit, 'rate':rate.replace(',','')})
    day = re.search(r'\b(\d{4}-\d{2}-\d{2})\b',content)
    valid_date = ''
    if day:
        try:
            valid_date = date.fromisoformat(day.group(1)).isoformat()
        except ValueError:
            pass
    taxes = {}
    for label in ('CGST','SGST','IGST'):
        match = re.search(r'\b'+label+r'\s*([\d.]+)\s*%',content,re.I)
        if match:
            try:
                value = float(match.group(1))
                if 0 < value <= 100: taxes[label]=value
            except ValueError:
                pass
    return {'supplier_text':lines[0] if lines else '', 'date':valid_date, 'items':items[:100], 'tax_rates':taxes}
