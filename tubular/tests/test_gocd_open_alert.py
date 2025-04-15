import json
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner

import tubular.scripts.gocd_open_alert as open_alert


class TestGocdOpenAlert(TestCase):
    @patch.dict('os.environ', {
        'GO_PIPELINE_NAME': 'edxapp',
        'GO_PIPELINE_COUNTER': '123',
        'GO_STAGE_NAME': 'build',
        'GO_STAGE_COUNTER': '456',
        'GO_JOB_NAME': 'prod',
        'GO_TRIGGER_USER': 'Alice',
    })
    @patch('tubular.scripts.gocd_open_alert.opsgenie_api.OpsGenieAPI.alert_opsgenie')
    def test_create_alert(self, mock_opsgenie_open):
        script_run = CliRunner().invoke(
            open_alert.gocd_open_alert,
            catch_exceptions=False,
            args=['--auth-token', 'XYZ', '--responder', 'Some Team'],
        )

        assert script_run.exit_code == 0
        mock_opsgenie_open.assert_called_once_with(
            "[GoCD] Build Failed on edxapp",
            (
                "Pipeline edxapp failed. Please see the build logs: "
                "https://gocd.tools.edx.org/go/tab/build/detail/edxapp/123/build/456/prod "
                "(triggered by Alice)"
            ),
            'Some Team',
            alias='gocd-pipeline-edxapp-build-prod',
        )
