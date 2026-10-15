#!/usr/bin/env python3
"""Validate owner inputs without accessing private material or running build hooks."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--owner', type=Path, required=True)
parser.add_argument('--tools', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.tools.resolve()))
from lanrith import config, extensions, release, trust

owner = args.owner.resolve()
value = config.load(owner/'config.yaml')
selection = trust.lock(owner/'platform.lock')
for name in ('boot.crt', 'evidence.crt'):
    release.public_key(owner/'trust'/name)
release.require(release.public_key(owner/'trust/boot.crt') != release.public_key(owner/'trust/evidence.crt'),
                'Boot and evidence signing authorities must be separate.')
release.require(value['hostname'] != 'example-router' and
                not any('RXhhbXBsZU9ubHlOb3RB' in key for key in value['administration']['authorized_keys']),
                'Replace the synthetic template identity and administrator key.')
release.require(value['hardware'].get('machine_id') not in (None,
                '0123456789abcdef0123456789abcdef', 'fedcba9876543210fedcba9876543210'),
                'Run scripts/initialize.py once to select the permanent device identity.')
if value['extensions']:
    pins = json.loads(release.read(owner/'extensions.lock', 65536), object_pairs_hook=release.unique)
    release.require(set(pins) == set(value['extensions']), 'Extension lock differs from configuration.')
    for identity, digest in pins.items():
        release.require(extensions.admit(owner/'extensions'/identity, digest)['id'] == identity,
                        'Extension differs from its selected identity.')
for path in (owner/'.github/workflows').glob('*.yml'):
    for pin in re.findall(r'Lanrith/lanrith/\.github/workflows/consumer\.yml@([^\s]+)', path.read_text()):
        release.require(pin == selection['signer_commit'], 'Reusable workflow differs from the reviewed platform pin.')
print('Owner configuration, trust, integration inventory and workflow pins verified.')
