import json
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner

import tubular.scripts.gocd_close_alert as close_alert


class TestGocdCloseAlert(TestCase):
    @patch.dict('os.environ', {
        'GO_PIPELINE_NAME': 'edxapp',
        'GO_STAGE_NAME': 'build',
        'GO_JOB_NAME': 'prod',
    })
    @patch('tubular.scripts.gocd_close_alert.opsgenie_api.OpsGenieAPI.close_opsgenie_alert_by_alias')
    def test_create_alert(self, mock_opsgenie_close):
        script_run = CliRunner().invoke(
            close_alert.gocd_close_alert,
            catch_exceptions=False,
            args=['--auth-token', 'XYZ'],
        )

        assert script_run.exit_code == 0
        mock_opsgenie_close.assert_called_once_with(
            'gocd-pipeline-edxapp-build-prod',
            source='tubular.scripts.gocd_close_alert',
        )
