"""Isolated local acceptance setup. Never connects to the hosted workspace."""
import getpass
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from http.server import ThreadingHTTPServer


def main():
    if os.name != 'nt':
        raise SystemExit('Run this acceptance setup on the Windows Tally laptop')
    # Set before importing configuration. Reject inherited cloud settings.
    os.environ['OFFICE_TEST_COMPANY']='Upkar Agency TEST'
    os.environ['OFFICE_BACKEND']='local'
    os.environ['OFFICE_ENABLE_POSTING']='YES'
    folder=Path(os.environ['LOCALAPPDATA'])/'OfficeTally-Test'
    folder.mkdir(parents=True,exist_ok=True)
    os.environ['OFFICE_DATA_DIR']=str(folder/'database')
    os.environ.pop('OFFICE_SECURE_COOKIE',None)
    from app import server,store
    from connector.worker import snapshot,process,COMPANY
    if COMPANY!='Upkar Agency TEST':raise SystemExit('Test company configuration was not applied')
    print('TEST ONLY: restore a separate company copy named Upkar Agency TEST.')
    print('This setup never uses the hosted app or its posting queue.')
    if input('Type Upkar Agency TEST to continue: ').strip()!=COMPANY:
        raise SystemExit('Cancelled')
    # Verify company before enabling the local worker.
    snapshot(9000)
    store.init()
    with store.transaction() as db:has_user=bool(db.execute('SELECT id FROM users LIMIT 1').fetchone())
    if not has_user:
        email=input('Local test admin email: ').strip()
        password=getpass.getpass('Choose a LOCAL TEST password (12+ characters): ')
        if password!=getpass.getpass('Repeat password: '):raise SystemExit('Passwords do not match')
        server.init_user(email,password)
    token=secrets.token_urlsafe(48)
    server.DEVICE_TOKEN=token;server.LIVE_WRITES=True;server.PREVIEW=False
    from connector.worker import Cloud
    cloud=Cloud('http://127.0.0.1:8767',token)
    stop=threading.Event()
    def worker():
        journal=sqlite3.connect(folder/'import-journal.db')
        journal.execute('CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,status TEXT NOT NULL,message TEXT NOT NULL)')
        try:
            while not stop.is_set():
                try:
                    masters=snapshot(9000);cloud.send('snapshot',{'snapshot':masters})
                    job=cloud.send('poll',{}).get('job')
                    if job:
                        status,message=process(job,masters,journal,9000,True)
                        cloud.send('result',{'id':job['id'],'lease':job['lease'],'status':status,'message':message})
                        print('TEST voucher: '+status+' — '+message,flush=True)
                    from connector.invoice_pdf import serve
                    serve(cloud,9000,COMPANY)
                except Exception as error:
                    print('Test connector unavailable ('+type(error).__name__+'). Check test company and port 9000.',flush=True)
                stop.wait(5)
        finally:journal.close()
    http=ThreadingHTTPServer(('127.0.0.1',8767),server.Handler)
    thread=threading.Thread(target=worker,daemon=True);thread.start()
    print('Open http://127.0.0.1:8767 on THIS Windows laptop; sign in and select Tally workspace.')
    print('Confirm the TEST COMPANY banner before approving any test entry. Ctrl+C stops this setup.')
    try:http.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        stop.set();http.server_close();thread.join(timeout=50)

if __name__=='__main__':main()
