"""Supabase HTTP access. Keys stay on the backend; no redirect can forward them."""
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse, quote
import urllib.request
import urllib.error

MAX_FILE = 8 * 1024 * 1024

class CloudError(RuntimeError):
    pass

class CloudAuthError(PermissionError):
    pass


def enabled():
    return os.environ.get('OFFICE_BACKEND', 'local') == 'supabase'


def settings():
    url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise CloudError('Set SUPABASE_URL to the project HTTPS origin')
    publishable = os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')
    secret = os.environ.get('SUPABASE_SECRET_KEY', '')
    if not publishable.startswith('sb_publishable_') or not secret.startswith('sb_secret_'):
        raise CloudError('Use new Supabase publishable/secret keys in private host settings')
    owner = os.environ.get('OFFICE_OWNER_EMAIL', '').strip().casefold()
    if '@' not in owner:
        raise CloudError('Set OFFICE_OWNER_EMAIL to the sole approved admin email')
    return {'url':url,'publishable':publishable,'secret':secret,'owner':owner,
            'bucket':os.environ.get('SUPABASE_STORAGE_BUCKET','office-invoices')}


def request(method, path, payload=None, *, secret=False, token=None, raw=None, mime=None, limit=MAX_FILE):
    config = settings()
    headers = {'apikey': config['secret'] if secret else config['publishable']}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = raw
    if payload is not None:
        body = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    elif mime:
        headers['Content-Type'] = mime
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None
    req = urllib.request.Request(config['url'] + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
            data = response.read(limit+1)
            if len(data)>limit:
                raise CloudError('Supabase response exceeded the allowed size')
            return data
    except urllib.error.HTTPError as error:
        # Never echo provider responses, request headers or credentials into app errors.
        if path.startswith('/auth/') and error.code in (400,401,403,404,422):
            raise CloudAuthError('Sign-in failed or this account is not permitted') from None
        raise CloudError('Supabase request failed; check project configuration and access') from None
    except (OSError, urllib.error.URLError):
        raise CloudError('Supabase is temporarily unavailable') from None


def owner_allowed(user):
    config = settings()
    if not isinstance(user,dict) or user.get('email','').strip().casefold()!=config['owner']:
        return False
    if not user.get('email_confirmed_at') or not user.get('id') or user.get('deleted_at'):
        return False
    if user.get('banned_until'):
        try:
            banned = datetime.fromisoformat(user['banned_until'].replace('Z','+00:00'))
            if banned > datetime.now(timezone.utc):
                return False
        except (ValueError,TypeError):
            return False
    return True


def sign_in(email, password):
    if email.strip().casefold()!=settings()['owner']:
        raise CloudAuthError('Email or password is incorrect')
    value = json.loads(request('POST','/auth/v1/token?grant_type=password', {'email':email,'password':password}))
    token = value.get('access_token')
    if not token:
        raise CloudAuthError('Sign-in could not be verified')
    user = json.loads(request('GET','/auth/v1/user',token=token))
    if not owner_allowed(user):
        raise CloudAuthError('This account is not permitted')
    # Auth tokens are never stored in the browser, database, logs or app response.
    return {'id':user['id'],'email':user['email'].strip().casefold()}


def verify_admin(user_id):
    from uuid import UUID
    try:
        UUID(user_id)
    except (ValueError,TypeError):
        raise CloudAuthError('Invalid admin identity') from None
    value = json.loads(request('GET','/auth/v1/admin/users/'+quote(user_id,safe=''),secret=True))
    user = value.get('user',value)
    if user.get('id')!=user_id or not owner_allowed(user):
        raise CloudAuthError('This admin account is disabled or no longer authorized')


def put_file(object_key, body, mime):
    config = settings()
    key = quote(config['bucket'],safe='')+'/'+quote(object_key,safe='/')
    request('POST','/storage/v1/object/'+key,secret=True,raw=body,mime=mime)


def get_file(object_key):
    config = settings()
    key = quote(config['bucket'],safe='')+'/'+quote(object_key,safe='/')
    return request('GET','/storage/v1/object/'+key,secret=True)


def delete_file(object_key):
    config = settings()
    request('DELETE','/storage/v1/object/'+quote(config['bucket'],safe=''), {'prefixes':[object_key]},secret=True)


def check_bucket():
    config = settings()
    bucket = json.loads(request('GET','/storage/v1/bucket/'+quote(config['bucket'],safe=''),secret=True))
    if bucket.get('public') is not False:
        raise CloudError('The invoice bucket must be private')
