#!/usr/bin/env python3
"""Configure private-repository protections and import independently managed keys."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def gh(*arguments, data=None):
    result = subprocess.run(['gh', *arguments], input=data, check=True, capture_output=True)
    return result.stdout


def api(repository, suffix, value=None):
    args = ['api', 'repos/'+repository+suffix]
    if value is not None:
        args += ['--method', 'PUT' if suffix.startswith('/environments/') else 'POST', '--input', '-']
    return json.loads(gh(*args, data=json.dumps(value).encode() if value is not None else None))


def key_matches(key, certificate):
    info = key.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid() and
            not info.st_mode & 0o077 and 0 < info.st_size <= 65536, 'Private key must be an owned mode-0600 regular file.')
    private = subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout'], check=True, capture_output=True).stdout
    public = subprocess.run(['openssl', 'x509', '-in', str(certificate), '-pubkey', '-noout'],
                            check=True, capture_output=True).stdout
    require(private == public, 'Private key does not match the reviewed public certificate.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository')
    parser.add_argument('--configure-protections', action='store_true')
    parser.add_argument('--import-keys', action='store_true')
    parser.add_argument('--boot-key', type=Path)
    parser.add_argument('--evidence-key', type=Path)
    args = parser.parse_args()
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository), 'Invalid repository.')
    repository = api(args.repository, '')
    require(repository['private'] and repository['default_branch'] == 'main',
            'Use a private configuration repository with main as its default branch.')
    if args.configure_protections:
        require(repository.get('permissions', {}).get('admin'), 'Repository administration is required for setup.')
        rules = api(args.repository, '/rulesets?per_page=100')
        require(not any(r['name'] == 'lanrith-reviewed-main' for r in rules),
                'Lanrith ruleset already exists; review its existing settings instead of replacing it.')
        api(args.repository, '/rulesets', {'name': 'lanrith-reviewed-main', 'target': 'branch', 'enforcement': 'active',
            'conditions': {'ref_name': {'include': ['refs/heads/main'], 'exclude': []}},
            'rules': [{'type': 'deletion'}, {'type': 'non_fast_forward'},
                {'type': 'pull_request', 'parameters': {'required_approving_review_count': 1,
                    'dismiss_stale_reviews_on_push': True, 'require_code_owner_review': False,
                    'require_last_push_approval': True, 'required_review_thread_resolution': True}},
                {'type': 'required_status_checks', 'parameters': {'strict_required_status_checks_policy': True,
                    'required_status_checks': [{'context': 'Configuration checks'}]}}]})
        for name in ('lanrith-signing', 'lanrith-evidence'):
            api(args.repository, '/environments/'+name,
                {'deployment_branch_policy': {'protected_branches': True, 'custom_branch_policies': False}})
    rules = api(args.repository, '/rules/branches/main?per_page=100')
    require(any(r['type'] == 'pull_request' and r.get('parameters', {}).get('required_approving_review_count', 0) >= 1
                for r in rules) and any(r['type'] == 'required_status_checks' for r in rules),
            'Protected main requires reviews and configuration checks.')
    for name in ('lanrith-signing', 'lanrith-evidence'):
        environment = api(args.repository, '/environments/'+name)
        require(environment.get('deployment_branch_policy', {}).get('protected_branches') is True,
                'Signing environments must restrict deployments to protected branches.')
    if args.import_keys:
        require(args.boot_key is not None and args.evidence_key is not None, 'Provide both existing key paths.')
        key_matches(args.boot_key, ROOT/'trust/boot.crt')
        key_matches(args.evidence_key, ROOT/'trust/evidence.crt')
        require((ROOT/'trust/boot.crt').read_bytes() != (ROOT/'trust/evidence.crt').read_bytes(),
                'Boot and evidence authorities must be separate.')
        for environment, values in (
            ('lanrith-signing', {'LANRITH_BOOT_KEY': args.boot_key, 'LANRITH_BOOT_CERTIFICATE': ROOT/'trust/boot.crt'}),
            ('lanrith-evidence', {'LANRITH_EVIDENCE_KEY': args.evidence_key, 'LANRITH_EVIDENCE_CERTIFICATE': ROOT/'trust/evidence.crt'})):
            for name, path in values.items():
                gh('secret', 'set', name, '--repo', args.repository, '--env', environment, data=path.read_bytes())
    print('Private repository protections and selected key imports verified. No image was built or deployed.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else
                         'Setup failed. Check repository permissions and private-environment support; use local signing if unavailable.')
