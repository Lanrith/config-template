#!/usr/bin/env python3
"""Select private signing controls and import independently managed keys."""

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


def private_material(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid() and
                not info.st_mode & 0o077 and 0 < info.st_size <= 65536,
                'Private material must be an owned mode-0600 regular file.')
        data = stream.read(65537)
        after = os.fstat(stream.fileno())
        require(len(data) == info.st_size and info.st_size == after.st_size and
                info.st_mtime_ns == after.st_mtime_ns, 'Private material changed while reading.')
        return data


def key_matches(key, certificate):
    data = private_material(key)
    private = subprocess.run(['openssl', 'pkey', '-pubout'], input=data,
                             check=True, capture_output=True, timeout=15).stdout
    public = subprocess.run(['openssl', 'x509', '-in', str(certificate), '-pubkey', '-noout'],
                            check=True, capture_output=True).stdout
    require(private == public, 'Private key does not match the reviewed public certificate.')
    return data


def credential_scope(repository, profile, environment):
    return ['--repo', repository]+(['--env', environment] if profile == 'protected' else [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository')
    parser.add_argument('--signing-profile', choices=('protected', 'repository'), default='protected')
    parser.add_argument('--configure-protections', action='store_true')
    parser.add_argument('--import-keys', action='store_true')
    parser.add_argument('--boot-key', type=Path)
    parser.add_argument('--evidence-key', type=Path)
    parser.add_argument('--import-update-credentials', action='store_true')
    parser.add_argument('--update-app-id')
    parser.add_argument('--update-app-key', type=Path)
    parser.add_argument('--update-token', type=Path)
    args = parser.parse_args()
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository), 'Invalid repository.')
    repository = api(args.repository, '')
    require(repository['private'] and repository['default_branch'] == 'main',
            'Use a private configuration repository with main as its default branch.')
    require(not args.configure_protections or args.signing_profile == 'protected',
            'Use --configure-protections with the protected signing profile.')
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
        for name in ('lanrith-signing', 'lanrith-evidence', 'lanrith-updates'):
            api(args.repository, '/environments/'+name,
                {'deployment_branch_policy': {'protected_branches': True, 'custom_branch_policies': False}})
    if args.signing_profile == 'protected':
        rules = api(args.repository, '/rules/branches/main?per_page=100')
        require(any(r['type'] == 'pull_request' and r.get('parameters', {}).get('required_approving_review_count', 0) >= 1 and
                    r.get('parameters', {}).get('dismiss_stale_reviews_on_push') is True for r in rules) and
                any(r['type'] == 'required_status_checks' and
                    r.get('parameters', {}).get('required_status_checks') for r in rules),
                'Protected main requires reviews and configuration checks.')
        for name in ('lanrith-signing', 'lanrith-evidence', 'lanrith-updates'):
            environment = api(args.repository, '/environments/'+name)
            policy = environment.get('deployment_branch_policy') or {}
            require(policy.get('protected_branches') is True and not policy.get('custom_branch_policies'),
                    'Signing and update environments must restrict deployments to protected branches.')
    else:
        api(args.repository, '/actions/secrets')
    variables = api(args.repository, '/actions/variables?per_page=100')
    selected = [item['value'] for item in variables['variables'] if item['name'] == 'LANRITH_SIGNING_PROFILE']
    require(not selected or selected == [args.signing_profile],
            'The repository already selects a different signing profile. Review its credentials before changing modes.')
    if not selected:
        require(repository.get('permissions', {}).get('admin'), 'Repository administration is required to select signing controls.')
        gh('variable', 'set', 'LANRITH_SIGNING_PROFILE', '--repo', args.repository, '--body', args.signing_profile)
    if args.import_keys:
        require(args.boot_key is not None and args.evidence_key is not None, 'Provide both existing key paths.')
        boot_key = key_matches(args.boot_key, ROOT/'trust/boot.crt')
        evidence_key = key_matches(args.evidence_key, ROOT/'trust/evidence.crt')
        certificates = [subprocess.run(['openssl', 'x509', '-in', str(ROOT/'trust'/name), '-pubkey', '-noout'],
                                      check=True, capture_output=True, timeout=15).stdout
                        for name in ('boot.crt', 'evidence.crt')]
        require(certificates[0] != certificates[1],
                'Boot and evidence authorities must be separate.')
        for environment, values in (
            ('lanrith-signing', {'LANRITH_BOOT_KEY': boot_key, 'LANRITH_BOOT_CERTIFICATE': (ROOT/'trust/boot.crt').read_bytes()}),
            ('lanrith-evidence', {'LANRITH_EVIDENCE_KEY': evidence_key, 'LANRITH_EVIDENCE_CERTIFICATE': (ROOT/'trust/evidence.crt').read_bytes()})):
            for name, data in values.items():
                gh('secret', 'set', name, *credential_scope(args.repository, args.signing_profile, environment), data=data)
    if args.import_update_credentials:
        app = args.update_app_id is not None or args.update_app_key is not None
        require(app != (args.update_token is not None), 'Choose exactly one GitHub App or repository-scoped update token.')
        prefix = '/environments/lanrith-updates' if args.signing_profile == 'protected' else '/actions'
        scope = credential_scope(args.repository, args.signing_profile, 'lanrith-updates')
        configured = api(args.repository, prefix+'/secrets')
        names = {item['name'] for item in configured['secrets']}
        if app:
            require(args.update_app_id is not None and re.fullmatch(r'[1-9][0-9]*', args.update_app_id) and
                    args.update_app_key is not None and 'LANRITH_UPDATE_TOKEN' not in names,
                    'Supply both App inputs; remove any previous alternative update token first.')
            data = private_material(args.update_app_key)
            subprocess.run(['openssl', 'rsa', '-check', '-noout'], input=data,
                           check=True, capture_output=True, timeout=15)
            gh('variable', 'set', 'LANRITH_UPDATE_APP_ID', *scope, '--body', args.update_app_id)
            gh('secret', 'set', 'LANRITH_UPDATE_APP_PRIVATE_KEY', *scope, data=data)
        else:
            variables = api(args.repository, prefix+'/variables')
            require('LANRITH_UPDATE_APP_PRIVATE_KEY' not in names and
                    not any(item['name']=='LANRITH_UPDATE_APP_ID' for item in variables['variables']),
                    'Remove previous alternative App credentials before selecting an update token.')
            data = private_material(args.update_token).strip()
            require(data and all(33 <= byte <= 126 for byte in data), 'Update token has an invalid encoding.')
            gh('secret', 'set', 'LANRITH_UPDATE_TOKEN', *scope, data=data)
    print('Private signing profile '+args.signing_profile+' and selected credential imports verified. No image was built or deployed.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else
                         'Setup failed. Check repository permissions and private-environment support; use local signing if unavailable.')
