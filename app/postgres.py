"""PostgreSQL adapter for the existing transactional repository operations."""
import os
import re
import sqlite3

class Row(dict):
    """Named access for app code, positional access for COUNT(*) compatibility."""
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)

class Cursor:
    def __init__(self,cursor): self.cursor=cursor
    def fetchone(self):
        value=self.cursor.fetchone()
        return Row(value) if value is not None else None
    def fetchall(self): return [Row(value) for value in self.cursor.fetchall()]
    def __iter__(self):
        for value in self.cursor: yield Row(value)


def translated(sql):
    # App SQL is source-controlled, never accepted from an HTTP request.
    if sql.strip().upper().startswith('INSERT OR REPLACE INTO SNAPSHOTS'):
        sql='INSERT INTO snapshots(mode,payload,updated) VALUES(?,?,?) ON CONFLICT(mode) DO UPDATE SET payload=EXCLUDED.payload,updated=EXCLUDED.updated'
    return sql.replace('?', '%s')

class Connection:
    def __init__(self,connection): self.connection=connection
    def execute(self,sql,params=()):
        import psycopg
        try:
            return Cursor(self.connection.execute(translated(sql),params))
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError('Database constraint rejected the change') from None
    def commit(self): self.connection.commit()
    def rollback(self): self.connection.rollback()
    def close(self): self.connection.close()


def connect():
    import psycopg
    from psycopg.rows import dict_row
    dsn=os.environ.get('DATABASE_URL','')
    if not dsn:
        raise RuntimeError('Set DATABASE_URL privately on the app host')
    # Disable prepared statements for compatibility with Supabase transaction poolers.
    options={'row_factory':dict_row,'prepare_threshold':None,'connect_timeout':15}
    local_test=os.environ.get('OFFICE_ALLOW_LOCAL_POSTGRES')=='YES'
    if local_test:
        from psycopg.conninfo import conninfo_to_dict
        info=conninfo_to_dict(dsn)
        if info.get('host') not in ('127.0.0.1','localhost'):
            raise RuntimeError('Local PostgreSQL override requires a loopback database')
    else:
        options['sslmode']='require'
    try:
        connection=psycopg.connect(dsn,**options)
        # One round trip for transaction setup, preserving role/RLS and locking.
        connection.execute("SET LOCAL ROLE office_backend; "
                           "SET LOCAL search_path TO office, pg_catalog; "
                           "SET LOCAL statement_timeout='25s'; "
                           "SET LOCAL lock_timeout='15s'; "
                           "SELECT pg_advisory_xact_lock(773121194701)")
        return Connection(connection)
    except Exception:
        if 'connection' in locals(): connection.close()
        raise RuntimeError('Cloud database unavailable or schema not installed; check private host configuration') from None
