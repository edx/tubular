import json
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner
from ddt import data, ddt, unpack

import tubular.scripts.alert_opsgenie as ops


@ddt
class TestAlertOpsGenie(TestCase):
    @unpack
    @data(  # message, auth-token, description, responders, alias, should_fail
        ('Message', 'Auth', 'Description', None, None, False),
        ('Message', 'Auth', 'Description', 'Arch', 'Alias',  False),
        (None, 'Auth', 'Description', 'Arch', 'Alias', True),
        ('Message', None, 'Description', 'Arch', 'Alias', True),
        ('Message', 'Auth', None, 'Arch', 'Alias', True),
    )
    def test_create_alert(self, message, auth, description, responders, alias, should_fail):
        with patch.object(ops.opsgenie_api.Session, 'post') as mock_post:
            runner = CliRunner()
            # Omit an option entirely when its value is None so that click reports
            # the missing required option (exit code 2). click >= 8.2 stringifies a
            # literal None in the args list instead of treating it as absent.
            args = []
            for flag, value in (
                ('--message', message),
                ('--auth_token', auth),
                ('--description', description),
                ('--responders', responders),
                ('--alias', alias),
            ):
                if value is not None:
                    args.extend([flag, value])
            invoke_response = runner.invoke(
                ops.alert_opsgenie,
                catch_exceptions=False,
                args=args,
            )
            if should_fail:
                assert invoke_response.exit_code == 2
        if should_fail:
            mock_post.assert_not_called()
        if not should_fail:
            expected_params = {
                'message': message,
                'description': description,
                'responders': [{"name": responders, "type": "team"}] if responders else None,
                'alias': alias,
            }
            mock_post.assert_called_once_with(url="https://api.opsgenie.com/v2/alerts",
                                              data=json.dumps(expected_params))
