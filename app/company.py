"""The only non-live target is an explicitly named, isolated local test company."""
import os

def company_name():
    test = os.environ.get('OFFICE_TEST_COMPANY','')
    if not test:
        return 'Upkar Agency'
    if test != 'Upkar Agency TEST':
        raise RuntimeError('Test company must be named Upkar Agency TEST')
    if os.environ.get('OFFICE_BACKEND','local') != 'local':
        raise RuntimeError('Test-company mode requires a separate local database, never the cloud workspace')
    return test

COMPANY = company_name()
