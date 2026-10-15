#!/usr/bin/env python3
"""Generate the template's permanent device identity once, before installation."""

import argparse
import os
from pathlib import Path
import re
import tempfile
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--configuration', type=Path, default=Path(__file__).resolve().parents[1]/'config.yaml')
args = parser.parse_args()
path = args.configuration
if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024*1024:
    raise SystemExit('Use an ordinary, bounded owner configuration file.')
before = path.read_bytes()
text = before.decode('utf-8')
pattern = r'(?m)^  machine_id: (0123456789abcdef0123456789abcdef|fedcba9876543210fedcba9876543210)(?: #[^\n]*)?$'
if len(re.findall(pattern, text)) != 1:
    raise SystemExit('A device identity already exists or the synthetic field is missing. Never rotate an installed identity.')
text = re.sub(pattern, '  machine_id: "'+uuid.uuid4().hex+'"', text)
descriptor, temporary = tempfile.mkstemp(prefix='.lanrith-identity-', dir=path.parent)
try:
    with os.fdopen(descriptor, 'wb') as output:
        output.write(text.encode())
        output.flush()
        os.fsync(output.fileno())
    if path.read_bytes() != before:
        raise SystemExit('Configuration changed during initialization.')
    os.replace(temporary, path)
finally:
    Path(temporary).unlink(missing_ok=True)
print('Permanent device identity created. Commit it and preserve it across upgrades, recovery and key rotation.')
