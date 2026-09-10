// Pure checks on an independent browser trace; no fabricated request timing.
export function validateColdStartup(trace){
  const rows=trace.requests,errors=[];
  const groups={auth:rows.filter(x=>x.path==='/auth/me'),notifications:rows.filter(x=>x.path==='/notifications'),
    session:rows.filter(x=>/^\/sessions\/[^/]+$/.test(x.path)),event:rows.filter(x=>x.path.startsWith('/events/')),
    layout:rows.filter(x=>x.path.endsWith('/seat-layout')),availability:rows.filter(x=>x.path.endsWith('/seat-availability')),
    checkouts:rows.filter(x=>x.path==='/checkout-sessions'),orders:rows.filter(x=>x.path==='/orders')};
  for(const [name,expected] of Object.entries({auth:2,notifications:2,session:1,event:1,layout:1,availability:1,checkouts:1,orders:1})){
    if(groups[name].length!==expected)errors.push('count '+name);
  }
  if(rows.length!==10||rows.some(x=>x.method!=='GET'||x.status!==200))errors.push('unexpected request/status');
  if(errors.length)return {passed:false,errors};
  if(groups.checkouts[0].query.recoverable!=='true'||groups.orders[0].query.limit!=='20'||groups.checkouts[0].query.sessionId!==groups.orders[0].query.sessionId)errors.push('list query mismatch');
  const overlap=items=>Math.max(...items.map(x=>x.startedAfterMs))<Math.min(...items.map(x=>x.finishedAfterMs));
  const parallel={auth:overlap(groups.auth),notifications:overlap(groups.notifications),page:overlap([...groups.event,...groups.layout,...groups.availability]),lists:overlap([...groups.checkouts,...groups.orders])};
  for(const [name,value] of Object.entries(parallel))if(!value)errors.push('parallel interval not observed '+name);
  const before=(a,b)=>a.sequence<b.sequence;
  if(!groups.auth.every(a=>before(a,groups.session[0]))||![...groups.event,...groups.layout,...groups.availability].every(x=>before(groups.session[0],x)&&before(x,groups.checkouts[0])&&before(x,groups.orders[0])))errors.push('dependency order');
  return {passed:!errors.length,errors,counts:Object.fromEntries(Object.entries(groups).map(([k,v])=>[k,v.length])),parallel,
    dependencySource:['frontend/src/router.ts','frontend/src/App.vue','frontend/src/auth/authState.ts','frontend/src/pages/SeatSelectionPage.vue']};
}
