"""Production ASGI transport for the same validated application handlers."""
from contextlib import asynccontextmanager
from email.message import Message
from io import BytesIO
import os
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from app import cloud, store
from app.server import Handler, MAX_BODY


class ASGIHandler(Handler):
    def __init__(self,path,headers,body,client):
        self.path=path
        self.headers=Message()
        for key,value in headers:
            self.headers[key]=value
        self.headers.replace_header('Content-Length',str(len(body))) if 'Content-Length' in self.headers else self.headers.__setitem__('Content-Length',str(len(body)))
        self.rfile=BytesIO(body)
        self.wfile=BytesIO()
        self.client_address=(client,0)
        self.status=200
        self.response_headers=[]
    def send_response(self,status,message=None): self.status=status
    def send_header(self,key,value): self.response_headers.append((key,value))
    def end_headers(self): pass


def dispatch(method,path,headers,body,client):
    handler=ASGIHandler(path,headers,body,client)
    handler.do_GET() if method=='GET' else handler.do_POST()
    response=Response(handler.wfile.getvalue(),status_code=handler.status)
    response.raw_headers=[(key.lower().encode('latin-1'),value.encode('latin-1')) for key,value in handler.response_headers]
    return response


async def endpoint(request: Request):
    if request.url.path=='/healthz':
        if request.method!='GET': return Response(status_code=405)
        try:
            def check():
                with store.transaction() as db: db.execute('SELECT 1').fetchone()
            await run_in_threadpool(check)
            return JSONResponse({'status':'ok'},headers={'Cache-Control':'no-store'})
        except Exception:
            return JSONResponse({'status':'unavailable'},status_code=503)
    size=0
    parts=[]
    async for chunk in request.stream():
        size+=len(chunk)
        if size>MAX_BODY:
            return JSONResponse({'error':'Request too large'},status_code=413)
        parts.append(chunk)
    path=request.url.path
    if request.url.query: path+='?'+request.url.query
    return await run_in_threadpool(dispatch,request.method,path,list(request.headers.items()),b''.join(parts),request.client.host if request.client else 'unknown')


@asynccontextmanager
async def lifespan(_app):
    if not cloud.enabled():
        raise RuntimeError('Production transport requires OFFICE_BACKEND=supabase; use the isolated local preview otherwise')
    cloud.settings()
    public=os.environ.get('OFFICE_PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL','')
    parsed=urlparse(public)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise RuntimeError('Set OFFICE_PUBLIC_URL to the deployed HTTPS origin')
    if len(os.environ.get('OFFICE_CONNECTOR_TOKEN',''))<32:
        raise RuntimeError('Set a private random connector token with at least 32 characters')
    await run_in_threadpool(store.init)
    await run_in_threadpool(cloud.check_bucket)
    yield


public=os.environ.get('OFFICE_PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL','')
host=urlparse(public).hostname
app=Starlette(debug=False,routes=[Route('/{path:path}',endpoint,methods=['GET','POST'])],lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=[host] if host else ['localhost','127.0.0.1','testserver'])
