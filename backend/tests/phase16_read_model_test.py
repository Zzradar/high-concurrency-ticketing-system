"""Atomic script integration tests against a dedicated Redis; no production keys."""
from pathlib import Path
import json
import os
import re
import subprocess
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'src/availability'

class ReadModelTest(unittest.TestCase):
    def redis(self, *args, stdin=None):
        command = ['docker', 'exec', '-i', os.environ.get('PHASE16_REDIS_CONTAINER', 'phase16-redis'), 'redis-cli', '--json']
        if stdin is not None:
            command.append('-x')
        result = subprocess.run(command + [str(x) for x in args], input=stdin, text=True, encoding='utf-8', capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stdout.startswith('error:'), result.stdout)
        return json.loads(result.stdout)

    def script(self, name, *args, payload=None):
        source = (LUA/'common.lua').read_text() + '\n' + (LUA/(name+'.lua')).read_text()
        sha = self.redis('SCRIPT','LOAD',stdin=source)
        return self.redis('EVALSHA',sha,1,self.prefix,*args,stdin=payload)

    def setUp(self):
        self.session = 'p16-' + uuid.uuid4().hex
        self.prefix = 'ticketing:seat-availability:{' + self.session + '}'
        self.rows = [[str(i),'AVAILABLE','0','A' if i < 3 else 'B'] for i in range(6)]
        self.redis('SET',self.prefix+':init-lock','token','PX',15000)

    def raw(self, seat):
        return 'ticketing:seat-hold:{' + self.session + '}:' + str(seat)

    def init(self, token='token', generation='g1', rows=None):
        return self.script('init',token,generation,payload=json.dumps(rows or self.rows))

    def read(self, zone='A', generation='', cursor='', limit=1000):
        return self.script('read',zone,generation,cursor,limit)

    def apply(self, seat, status, version):
        return self.script('apply',seat,status,version,10)

    def hold(self, operation, seats, *args):
        source = (ROOT/'src/services/SeatHoldService.cpp').read_text()
        original = re.search(r'k' + operation + r'Script = R"lua\((.*?)\)lua";',source,re.S).group(1)
        script = ('local originalKeys = KEYS\nlocal KEYS = {string.gsub(string.match(KEYS[1], "^(.*}):"), "seat%-hold:", "seat-availability:", 1)}\n'
                  + (LUA/'common.lua').read_text()
                  + '\nlocal streamMaxlen=10\nlocal function originalOperation()\nlocal KEYS=originalKeys\n'
                  + original + '\nend\n' + (LUA/'hold.lua').read_text())
        sha = self.redis('SCRIPT','LOAD',stdin=script)
        return self.redis('EVALSHA',sha,len(seats),*(self.raw(s) for s in seats),*args)

    def test_cold_5000_and_latest_hold_at_publish(self):
        rows = [[str(i),'AVAILABLE',str(i),'Z'+str(i//1000)] for i in range(5000)]
        self.redis('SET',self.raw(0),'C1|2','PX',9000)
        self.assertEqual(self.init(rows=rows),['READY','g1'])
        self.assertEqual(self.redis('HLEN',self.prefix+':formal'),5000)
        self.assertEqual(self.redis('LRANGE',self.prefix+':zones',0,-1),['Z0','Z1','Z2','Z3','Z4'])
        self.assertEqual(self.redis('HGET',self.prefix+':formal','4999'),'AVAILABLE|4999')
        self.assertEqual(self.redis('HGET',self.prefix+':zone:Z0:summary','held'),'1')
        self.assertTrue(self.redis('HGET',self.prefix+':holds','0').startswith('C1|2|'))
        self.assertEqual(self.redis('SCARD',self.prefix+':zone:Z0:seats'),1000)
        self.assertNotEqual(self.read('Z0')[3],'0-0')

    def test_stale_initializer_cannot_publish(self):
        self.redis('SET',self.prefix+':init-lock','replacement','PX',15000)
        self.assertEqual(self.init(),['STALE_INIT'])
        self.assertEqual(self.redis('EXISTS',self.prefix+':meta'),0)
        self.assertEqual(self.init('replacement','g2'),['READY','g2'])

    def test_projection_versions_public_unchanged_still_delta(self):
        self.redis('SET',self.raw(0),'C1|1','PX',9000)
        self.init()
        cursor = self.read()[3]
        self.assertEqual(self.apply('0','HELD','1'),['APPLIED'])
        self.assertEqual(self.apply('0','SOLD','0'),['STALE_OR_DUPLICATE'])
        self.assertEqual(self.apply('0','HELD','1'),['STALE_OR_DUPLICATE'])
        response = self.read('A','g1',cursor)
        self.assertEqual(response[1],'delta')
        self.assertEqual(response[-3:],['0','HELD','C1'])
        self.assertEqual(self.redis('XLEN',self.prefix+':zone:A:changes'),2)
        self.assertEqual(self.redis('HGET',self.prefix+':zone:A:summary','held'),'1')

    def test_prepare_ensure_abort_finalize_release(self):
        self.init()
        self.assertEqual(self.hold('Prepare',[0,1],'C1',2,0,1,300),1)
        length = self.redis('XLEN',self.prefix+':zone:A:changes')
        self.assertEqual(self.hold('Prepare',[0,1],'C1',0,1,2,300),1)
        self.assertEqual(self.hold('Ensure',[0,1],'C1',2,300),1)
        self.assertEqual(self.redis('XLEN',self.prefix+':zone:A:changes'),length)
        self.assertEqual(self.hold('Ensure',[0],'C2',0,300),0)
        self.assertEqual(self.hold('Abort',[0],'C1',2),0)
        self.assertEqual(self.hold('Abort',[0],'C1',1),1)
        self.assertEqual(self.hold('Finalize',[1],'C1',2),1)
        self.assertEqual(self.hold('Ensure',[0],'C1',3,300),1)
        self.assertEqual(self.hold('Release',[0],'C1'),1)
        self.assertEqual(self.redis('HLEN',self.prefix+':holds'),0)
        self.assertEqual(self.redis('ZCARD',self.prefix+':hold-expiry'),0)
        self.assertEqual(self.redis('HGET',self.prefix+':zone:A:summary','available'),'3')

    def test_corrupt_model_does_not_partially_write_hold(self):
        self.init()
        self.redis('DEL',self.prefix+':zone:A:summary')
        self.redis('SET',self.prefix+':zone:A:summary','wrong type')
        self.assertEqual(self.hold('Ensure',[0,1],'C1',1,300),1)
        self.assertEqual(self.redis('GET',self.raw(0)),'C1|1')
        self.assertEqual(self.redis('GET',self.raw(1)),'C1|1')
        self.assertEqual(self.redis('EXISTS',self.prefix+':meta'),0)
        self.redis('SET',self.prefix+':init-lock','token','PX',15000)
        self.init()
        self.assertEqual(self.redis('HGET',self.prefix+':zone:A:summary','held'),'2')

    def test_expiry_and_extension_formal_precedence(self):
        self.init()
        self.hold('Ensure',[0,1],'C1',1,1)
        self.apply('1','SOLD','1')
        time.sleep(1.1)
        self.hold('Ensure',[0],'C1',2,300)
        self.assertEqual(self.script('expire',512,10)[0],'OK')
        self.assertEqual(self.redis('GET',self.raw(0)),'C1|2')
        self.assertEqual(self.redis('HGET',self.prefix+':formal','1'),'SOLD|1')
        self.assertEqual(self.redis('HGET',self.prefix+':zone:A:summary','sold'),'1')
        self.assertEqual(self.redis('HGET',self.prefix+':zone:A:summary','held'),'1')

    def test_defer_no_model_generation_and_zone(self):
        self.assertEqual(self.apply('0','SOLD','1'),['INITIALIZING'])
        self.redis('DEL',self.prefix+':init-lock')
        self.assertEqual(self.apply('0','SOLD','1'),['NO_MODEL'])
        self.redis('SET',self.prefix+':init-lock','token','PX',15000)
        self.init()
        response=self.read('A','old','1-0')
        self.assertEqual(response[1],'snapshot')
        self.assertEqual(response[4],'1')
        self.assertEqual(self.read('missing'),['ZONE_NOT_FOUND'])

    def test_dedupe_paging_no_change_and_trim(self):
        self.init()
        cursor=self.read()[3]
        for version in range(1,5):
            self.apply('0','SOLD' if version%2 else 'AVAILABLE',str(version))
        first=self.read('A','g1',cursor,2)
        self.assertEqual(first[5],'1')
        self.assertEqual(first[-3:],['0','AVAILABLE',''])
        second=self.read('A','g1',first[3],2)
        self.assertEqual(second[5],'0')
        nochange=self.read('A','g1',second[3])
        self.assertEqual(nochange[3],second[3])
        self.assertEqual(nochange[-1],'0')
        self.redis('XTRIM',self.prefix+':zone:A:changes','MAXLEN',1)
        reset=self.read('A','g1',cursor)
        self.assertEqual(reset[1],'snapshot')
        self.assertEqual(reset[6],'trim')

if __name__ == '__main__':
    unittest.main(verbosity=2)
