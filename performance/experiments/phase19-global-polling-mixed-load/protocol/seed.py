"""Extend the existing dataset generator, with an exact Phase19 namespace and fresh-db guard."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location('phase19_existing_generator', ROOT / 'performance/data/generate_dataset.py')
generator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = generator
spec.loader.exec_module(generator)


def namespace(text):
    return text.replace('perf-', 'phase19-')


def prepare():
    profile = json.loads((HERE / 'profile.json').read_text())
    shape = generator.validate_profile(profile)
    credentials = generator.generate_session_credentials(shape.active_auth_sessions)
    statement = namespace(generator.build_generation_sql(profile, shape, credentials, 86400, 604800))
    users = [{k: namespace(v) if k in ('userId', 'username', 'authSessionId') else v for k, v in u.items()}
             for u in generator.public_sessions(credentials)]
    return statement, users, shape


def seed(sql, private_output):
    if sql("SELECT count(*) FROM app_users WHERE id LIKE 'phase19-%'").strip() != '0':
        raise RuntimeError('Refuse reusing a Phase19 dataset; create a fresh owned volume')
    statement, users, shape = prepare()
    sql(statement)
    # The shared generator predates publishing snapshots; extend those fixture tables only.
    sql("""INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price)
SELECT s.id,z.id,z.venue_id,10000 FROM sessions s JOIN venue_zones z ON z.venue_id=s.venue_id
WHERE s.id LIKE 'phase19-session-%';
UPDATE events SET published_at=clock_timestamp(),published_by='U-ADMIN-DEMO' WHERE id LIKE 'phase19-event-%';""")
    private_output.mkdir(parents=True, exist_ok=True)
    (private_output/'users.json').write_text(json.dumps(users), encoding='utf-8')
    config = {'zones': [f'Zone-{i}' for i in range(5)], 'readerSession': 'phase19-session-001-001',
        'writerSession': 'phase19-session-001-002', 'hotspotSession': 'phase19-session-001-003',
        'sentinelSession': 'phase19-session-001-004', 'journeySession': 'phase19-session-001-005',
        'writerSeats': [f'phase19-ss-001-002-{i:06d}' for i in range(1, 801)], 'holdTtlSeconds': 5,
        'observerSeatRange': [4501, 5000], 'readerUserRange': [0, 2999], 'writerUserRange': [3000, 3399],
        'observerUser': 3500, 'sentinelUser': 3501, 'hotspotUserRange': [4000, 4999]}
    (private_output/'config.json').write_text(json.dumps(config), encoding='utf-8')
    raw = sql("SELECT id,session_id,seat_id,status,price,formal_version FROM session_seats WHERE id LIKE 'phase19-ss-%' ORDER BY id")
    return {'registeredUsers': shape.registered_users, 'activeAuthSessions': shape.active_auth_sessions,
            'sessions': shape.sessions, 'seatsPerSession': shape.seats, 'totalSessionSeats': shape.session_seats,
            'inventorySha256': hashlib.sha256(raw.encode()).hexdigest(),
            'profileSha256': hashlib.sha256((HERE/'profile.json').read_bytes()).hexdigest(),
            'credentialExport': 'private output only; raw credentials must not be committed'}
