"""Dedicated independent Delta observer; all latency timestamps share perf_counter."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.parse import urlencode

from harness import Stack, request, save


class Observer:
    def __init__(self, stack, cancel=None):
        self.stack = stack
        self.session = stack.fixture['writerSession']
        self.zone = stack.fixture['zones'][4]
        self.user = stack.users[stack.fixture['observerUser']]
        self.state = {}
        self.generation = self.cursor = None
        self.interval = 2.0
        self.next_read = 0
        self.timeline = []
        self.changed = set()
        self.cancel = cancel

    def read(self):
        wait=max(0,self.next_read-time.perf_counter())
        if self.cancel:
            if self.cancel.wait(wait):raise RuntimeError('Propagation stopped by resource gate')
        else:time.sleep(wait)
        query = {'zone':self.zone}
        if self.cursor is not None:
            query.update(generation=self.generation, since=self.cursor)
        code, body, timing = request(self.stack.base, '/sessions/'+self.session+'/seat-availability?'+urlencode(query), self.user)
        ended = time.perf_counter()
        if code != 200 or body.get('degraded') or body.get('sessionId') != self.session or body.get('zone') != self.zone:
            raise RuntimeError('Propagation observer contract/status')
        if self.generation == body['generation'] and self.cursor and tuple(map(int,body['cursor'].split('-'))) < tuple(map(int,self.cursor.split('-'))):
            raise RuntimeError('Propagation cursor regression')
        if body['mode'] == 'snapshot':
            self.state = {s['id']:s['status'] for s in body['seats']}
            self.changed = set()
        else:
            self.state.update({s['id']:s['status'] for s in body['changes']})
            self.changed = {s['id'] for s in body['changes']}
        self.generation, self.cursor = body['generation'],body['cursor']
        self.interval = body['pollAfterMs']/1000
        if self.interval < 0 or self.interval > 30 or (not body['hasMore'] and self.interval < .5):
            raise RuntimeError('Propagation invalid server hint')
        self.next_read = ended+max(.001,self.interval)
        self.timeline.append({'utc':datetime.now(timezone.utc).isoformat(),'monotonic':ended,'mode':body['mode'],
            'cursor':body['cursor'],'reset':body['reset'],'hasMore':body['hasMore'],'pollAfterMs':body['pollAfterMs'],**timing})
        return ended

    def wait_for(self, seat, target, write_ended, category, operation, require_change=False):
        deadline = write_ended+30
        while time.perf_counter() < deadline:
            seen = self.read()
            if self.state.get(seat) == target and (not require_change or seat in self.changed):
                return {'category':category,'operation':operation,'target':target,'writeResponseMonotonic':write_ended,
                    'firstSeenMonotonic':seen,'milliseconds':(seen-write_ended)*1000,'matched':True}
        return {'category':category,'operation':operation,'target':target,'matched':False,'milliseconds':None}

    def dwell(self, seconds):
        until=time.perf_counter()+seconds
        opportunities=0
        while time.perf_counter()<until:
            self.read();opportunities+=1
        if opportunities<2:
            raise RuntimeError('Dwell did not cover two planned observer reads')

    def write(self,path,body=None,method='POST'):
        code,value,_=request(self.stack.base,path,self.user,method,body)
        ended=time.perf_counter()
        if code not in (200,201):
            raise RuntimeError('Propagation writer status '+str(code))
        return value,ended


def collect(stack, out, cycles, cancel=None):
    if out.exists():raise ValueError('Refuse overwriting propagation point')
    out.mkdir(parents=True)
    observer=Observer(stack,cancel)
    result={'clock':'single process time.perf_counter, seconds','startedUtc':datetime.now(timezone.utc).isoformat(),
        'dwellSeconds':10,'cyclesPlanned':cycles,'samples':[],'passed':False}
    active_checkout=None
    active_order=None
    try:
        observer.read()
        for cycle in range(cycles):
            seat=f'phase19-ss-001-002-{4501+cycle:06d}'
            for flow in ['abandon','confirm_cancel']:
                if cancel and cancel.is_set():raise RuntimeError('Propagation stopped by resource gate')
                checkout,ended=observer.write('/checkout-sessions',{'sessionId':observer.session,'seatIds':[seat]})
                active_checkout=checkout['id']
                result['samples'].append(observer.wait_for(seat,'HELD',ended,'temporary','hold'))
                # TTL=15s: dwell starts at successful write, not after a delayed observation.
                remaining=max(0,10-(time.perf_counter()-ended))
                observer.dwell(remaining)
                if flow=='abandon':
                    _,ended=observer.write('/checkout-sessions/'+active_checkout+'/abandon')
                    active_checkout=None
                    result['samples'].append(observer.wait_for(seat,'AVAILABLE',ended,'convergence','abandon'))
                else:
                    value,ended=observer.write('/checkout-sessions/'+active_checkout+'/confirm')
                    active_order=value['checkoutSession']['order']['id']
                    active_checkout=None
                    # Both temporary and formal reservation display HELD. Require
                    # a NEW Delta entry after the pre-confirm cursor was drained;
                    # merely seeing the cached HELD state cannot prove projection.
                    result['samples'].append(observer.wait_for(seat,'HELD',ended,'formal','confirm',require_change=True))
                    observer.dwell(10)
                    _,ended=observer.write('/orders/'+active_order+'/cancel')
                    active_order=None
                    result['samples'].append(observer.wait_for(seat,'AVAILABLE',ended,'formal','cancel'))
                    result['samples'].append({**result['samples'][-1],'category':'convergence','operation':'cancel_final'})
            save(out/'partial.json',result)
        result['passed']=all(s['matched'] for s in result['samples']) and len(result['samples'])==cycles*6
    except Exception as error:
        result['error']=str(error)
    finally:
        cleanup=[]
        for path in ([] if active_checkout is None else ['/checkout-sessions/'+active_checkout+'/abandon'])+([] if active_order is None else ['/orders/'+active_order+'/cancel']):
            try:
                observer.write(path);cleanup.append({'passed':True})
            except Exception as error:
                cleanup.append({'passed':False,'error':str(error)})
                result['passed']=False
        result['cleanup']=cleanup
        result['endedUtc']=datetime.now(timezone.utc).isoformat()
        save(out/'observer-timeline.json',observer.timeline)
        save(out/'result.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--private',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=3)
    args=parser.parse_args()
    result=collect(Stack(args.private),args.out,args.cycles)
    print({'passed':result['passed'],'samples':len(result['samples']),'error':result.get('error')})
    raise SystemExit(0 if result['passed'] else 1)
