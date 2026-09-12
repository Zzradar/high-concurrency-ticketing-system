"""Isolated Stage0 environment setup; never touches historical containers."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(r'D:\Documents\vscode\high-concurrency-ticketing-system-phase18')
OUT=Path(__file__).resolve().parent
def run(*args,stdin=None):
    p=subprocess.run(args,input=stdin,capture_output=True,text=True,encoding='utf-8',timeout=120)
    if p.returncode: raise RuntimeError(p.stderr)
    return p.stdout.strip()
def sql(query):
    return run('docker','exec','-i','phase18-postgres','psql','-U','postgres','-d','ticketing','-qAt','-v','ON_ERROR_STOP=1',stdin=query)
def main():
    run('docker','network','create','--internal','phase18-stage0')
    for name,image,extra in [
        ('postgres','postgres:16-alpine',['-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=ticketing']),
        ('redis','redis:7.4-alpine',[])]:
        args=['docker','run','-d','--name','phase18-'+name,'--network','phase18-stage0','--network-alias',name,'--cpus','1','--memory','512m','--pids-limit','128','--ulimit','nofile=4096:4096',*extra,image]
        if name=='postgres': args+=['-c','shared_preload_libraries=pg_stat_statements','-c','pg_stat_statements.track=all']
        run(*args)
    for _ in range(50):
        try:sql('SELECT 1;');break
        except RuntimeError:time.sleep(.2)
    else:raise RuntimeError('PostgreSQL did not become ready')
    for path in sorted((ROOT/'backend/db/migrations').glob('*.sql')):sql(path.read_text(encoding='utf-8'))
    sql('CREATE EXTENSION pg_stat_statements;')
    sql((ROOT/'backend/db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
    config=json.loads((ROOT/'backend/config/config.performance.json').read_text(encoding='utf-8'))
    config['db_clients'][0].update(user='postgres',passwd='')
    config['custom_config']['authentication']['allowed_origins']+=['http://127.0.0.1:18181']
    (OUT/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    print('Isolated PostgreSQL/Redis ready; migrations 001-012 and demo seed applied.')
if __name__=='__main__':main()
