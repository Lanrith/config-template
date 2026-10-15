#!/usr/bin/env python3
"""Propose an authenticated qualified platform and matching workflow pin."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Lanrith/lanrith'


def run(*argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout


def main():
    all_releases = json.loads(run('gh', 'api', 'repos/'+REPOSITORY+'/releases?per_page=100'))
    candidates = all_releases
    candidates = [r for r in candidates if not r['draft'] and not r['prerelease'] and
                  re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', r['tag_name'])]
    if not candidates:
        raise ValueError('No production-qualified Lanrith release is available. Keep the existing accepted image.')
    chosen = max(candidates, key=lambda r: tuple(map(int, r['tag_name'][1:].split('.'))))
    with tempfile.TemporaryDirectory(prefix='lanrith-platform-proposal.') as temporary:
        work = Path(temporary)
        run('gh', 'release', 'download', chosen['tag_name'], '--repo', REPOSITORY, '--dir', str(work),
            '--pattern', 'selection.json', '--pattern', 'selection.json.intoto.jsonl',
            '--pattern', 'security.json', '--pattern', 'security.json.intoto.jsonl')
        value = json.loads((work/'selection.json').read_text())
        if value.get('repository') != REPOSITORY or value.get('version') != chosen['tag_name']:
            raise ValueError('Published platform selection has an unexpected identity.')
        for field in ('source_commit', 'signer_commit', 'security_workflow_commit'):
            if not re.fullmatch(r'[0-9a-f]{40}', value.get(field, '')):
                raise ValueError('Published platform selection has an invalid commit.')
        for name in ('selection.json', 'security.json'):
            run('gh', 'attestation', 'verify', str(work/name), '--bundle', str(work/(name+'.intoto.jsonl')),
                '--repo', REPOSITORY, '--signer-workflow', REPOSITORY+'/.github/workflows/build-base.yml',
                '--signer-digest', value['signer_commit'], '--source-digest', value['source_commit'],
                '--cert-oidc-issuer', 'https://token.actions.githubusercontent.com', '--deny-self-hosted-runners')
        security = json.loads((work/'security.json').read_text())
        if hashlib.sha256((work/'security.json').read_bytes()).hexdigest() != value['files']['security.json'] or \
                security.get('production_qualified') is not True or security.get('slsa_build_level') != 3 or \
                security.get('slsa_spec') != '1.2' or security.get('qualification', {}).get('result') != 'pass':
            raise ValueError('The selected release has incomplete production qualification.')
        # A workflow change is proposed for review, never executed by this updater.
        assessments = [r for r in all_releases if not r['draft'] and
                       re.fullmatch(r'assessment-[0-9]{8}T[0-9]{6}Z-'+value['files']['inventory.json'][:12], r['tag_name'])]
        if assessments:
            latest = max(assessments, key=lambda r: r['tag_name'])
            run('gh','release','download',latest['tag_name'],'--repo',REPOSITORY,'--dir',str(work),
                '--pattern','security-assessment.json','--pattern','security-assessment.json.intoto.jsonl')
            assessment = json.loads((work/'security-assessment.json').read_text())
            head = assessment.get('source_commit', '')
            if not re.fullmatch(r'[0-9a-f]{40}', head):
                raise ValueError('Invalid proposed security workflow identity.')
            run('gh','attestation','verify',str(work/'security-assessment.json'),'--bundle',
                str(work/'security-assessment.json.intoto.jsonl'),'--repo',REPOSITORY,'--signer-workflow',
                REPOSITORY+'/.github/workflows/security-audit.yml','--signer-digest',head,'--source-digest',head,
                '--cert-oidc-issuer','https://token.actions.githubusercontent.com','--deny-self-hosted-runners')
            if assessment.get('result') != 'pass' or assessment.get('inventory_sha256') != value['files']['inventory.json'] or \
                    set(value['files'].values()) & set(assessment.get('revoked_sha256', [])):
                raise ValueError('Latest retained assessment rejects the selected platform.')
            value['security_workflow_commit'] = head
        (ROOT/'platform.lock').write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            text = path.read_text()
            text = re.sub(r'(Lanrith/lanrith/\.github/workflows/consumer\.yml@)[0-9a-f]{40}',
                          r'\g<1>'+value['signer_commit'], text)
            text = re.sub(r'(ref: )[0-9a-f]{40}( # Lanrith compiler)',
                          r'\g<1>'+value['source_commit']+r'\g<2>', text)
            path.write_text(text)
    print('Qualified platform and workflow pins proposed. Review the diff before merging.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else 'Platform proposal failed closed.')
