"""Platform proposals reject stale evidence and incompatible trusted workflows."""

import base64
import datetime
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('update_platform', Path(__file__).parents[1]/'scripts/update-platform.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class PlatformUpdateTests(unittest.TestCase):
    def test_freshness_is_inventory_bound_and_rejects_stale_future_or_naive_time(self):
        now = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
        selection = {'files': {'inventory.json': 'a'*64}}
        report = {'schema': 1, 'inventory_sha256': 'a'*64, 'assessed_at': now.isoformat()}
        update.fresh_assessment(report, selection, now)
        for change in ({'inventory_sha256': 'b'*64},
                       {'assessed_at': (now-datetime.timedelta(hours=24, seconds=1)).isoformat()},
                       {'assessed_at': (now+datetime.timedelta(seconds=1)).isoformat()},
                       {'assessed_at': now.replace(tzinfo=None).isoformat()}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                update.fresh_assessment({**report, **change}, selection, now)

    def test_existing_workflow_without_signing_profiles_is_refused(self):
        source = b'on:\n  workflow_call:\n    inputs:\n      publish:\n        type: boolean\n'
        response = {'encoding': 'base64', 'size': len(source),
                    'content': base64.b64encode(source).decode()}
        with patch.object(update, 'run', return_value=json.dumps(response)):
            with self.assertRaisesRegex(ValueError, 'private signing profiles'):
                update.check_workflow_support({'signer_commit': 'a'*40})

    def test_profile_support_must_come_from_the_exact_selected_workflow(self):
        source = b'on:\n  workflow_call:\n    inputs:\n      signing-profile:\n        type: string\n        default: protected\n'
        response = {'encoding': 'base64', 'size': len(source),
                    'content': base64.b64encode(source).decode()}
        with patch.object(update, 'run', return_value=json.dumps(response)) as run:
            update.check_workflow_support({'signer_commit': 'a'*40})
        self.assertTrue(run.call_args.args[-1].endswith('consumer.yml?ref='+'a'*40))
        for change in ({'size': 65537}, {'encoding': 'none'}, {'size': len(source)+1}):
            with self.subTest(change=change), \
                    patch.object(update, 'run', return_value=json.dumps({**response, **change})), \
                    self.assertRaises(ValueError):
                update.check_workflow_support({'signer_commit': 'a'*40})
