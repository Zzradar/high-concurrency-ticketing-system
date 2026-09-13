"""Keep legacy defaults; permit explicitly isolated Phase19 fault transports."""
import os
import re


def topology():
    prefix = os.environ.get('PHASE18_FIXTURE_PREFIX', 'phase18-policy')
    if prefix != 'phase18-policy' and not re.fullmatch(r'phase18-phase19-[a-z0-9-]+', prefix):
        raise ValueError('Fault fixture prefix must identify Phase18 legacy or isolated Phase19 resources')
    data = os.environ.get('PHASE18_FIXTURE_DATA_NETWORK', 'phase18-policy-data')
    ingress = os.environ.get('PHASE18_FIXTURE_INGRESS_NETWORK', 'phase18-policy-ingress')
    if prefix != 'phase18-policy' and not all(re.fullmatch(r'phase19-[a-z0-9-]+', n) for n in (data, ingress)):
        raise ValueError('Phase19 fault fixtures must use exclusively Phase19 networks')
    return dict(api=prefix+'-api', no_secret_api=prefix+'-no-secret-api', data=data, ingress=ingress, prefix=prefix)
