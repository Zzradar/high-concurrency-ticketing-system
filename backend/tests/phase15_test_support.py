"""Only the dedicated Phase15 stack is addressed by these real integration gates."""
import os,json,subprocess,time,uuid
os.environ['TICKETING_BASE_URL']=os.environ.get('PHASE15_BASE_URL','http://127.0.0.1:18095')
from auth_test_support import AuthenticatedClient,anonymous_request,test_user_values,username_for_user
SESSION='ses-concert-1001';EVENT='evt-concert-2026'
def sql(statement,ok=True):
    r=subprocess.run(['docker','exec','-i',os.environ.get('PHASE15_POSTGRES_CONTAINER','phase15-api-postgres'),'psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],input=statement,capture_output=True,text=True,encoding='utf-8')
    if ok and r.returncode:raise AssertionError(r.stderr)
    if not ok and not r.returncode:raise AssertionError('SQL unexpectedly succeeded')
    return r.stdout.strip()
def redis(*args):
    r=subprocess.run(['docker','exec',os.environ.get('PHASE15_REDIS_CONTAINER','phase15-redis'),'redis-cli','--json',*map(str,args)],capture_output=True,text=True,encoding='utf-8')
    if r.returncode:raise AssertionError(r.stderr)
    return json.loads(r.stdout)
def until(predicate,seconds=10):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=predicate()
        if result:return result
        time.sleep(.05)
    raise AssertionError('Condition deadline exceeded')
def client():
    user='p15-'+uuid.uuid4().hex
    sql('INSERT INTO app_users(id,display_name,username,password_hash,status) VALUES '+test_user_values([user])+';')
    c=AuthenticatedClient(username_for_user(user));c.login();return user,c
