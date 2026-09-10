export const results = ['business_success','business_conflict','capacity_rejection','system_error','unexpected_contract'];
export const steps = ['health','auth','session','event','layout','availability','page','hold','adjust','abandon','confirm','recover','order','journey','reservation','login','login_identity','payment_start','payment_poll','payment_terminal'];

export function group(index, targets) {
    const bucket=(index+targets.seed)%20*5;
    return bucket<targets.behavior.browse?'browse':bucket<targets.behavior.browse+targets.behavior.hold?'hold':'order';
}
export function randomSeconds(index, sequence, range, seed) {
    let n=(Math.imul(index+1,1664525)+Math.imul(sequence+seed,1013904223))>>>0;
    n ^= n>>>16; n=Math.imul(n,2246822507)>>>0; n ^= n>>>13;
    return range[0]+(n>>>0)/4294967296*(range[1]-range[0]);
}
export function boundedIndex(index, slice) {
    if(!Number.isInteger(index)||index<0||slice[0]+index>=slice[1]) throw new Error('Phase14 data slice exhausted');
    return slice[0]+index;
}
export function seat(index, targets, count=null) {
    const d=targets.dataset; const sessions=count||d.events*d.sessionsPerEvent;
    if(!Number.isInteger(index)||index<0||index>=sessions*d.seatsPerSession)throw new Error('Phase14 seat pool exhausted');
    const ordinal=index%sessions;const n=Math.floor(index/sessions)+1;
    const e=String(Math.floor(ordinal/d.sessionsPerEvent)+1).padStart(3,'0');const s=String(ordinal%d.sessionsPerEvent+1).padStart(3,'0');
    return {sessionId:`perf-session-${e}-${s}`,sessionSeatId:`perf-ss-${e}-${s}-${String(n).padStart(6,'0')}`};
}
export function classify(status, body, expected, valid, conflictCodes=[]) {
    if(!status||!body)return 'system_error';
    if(status===409&&conflictCodes.includes(body.code))return 'business_conflict';
    if((status===503||status===429)&&['AUTH_BUSY','SEAT_MAP_BUSY'].includes(body.code))return 'capacity_rejection';
    if(status>=500)return 'system_error';
    if(status!==expected)return 'unexpected_contract';
    try {return valid(body)?'business_success':'unexpected_contract';} catch(_){return 'unexpected_contract';}
}
export function onceState() {
    let used=false;
    return {claim(){if(used)return false;used=true;return true;}};
}
