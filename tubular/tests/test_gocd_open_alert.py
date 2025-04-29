import json
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner

import tubular.scripts.gocd_open_alert as open_alert

SAMPLE_ENV = {
    'GO_PIPELINE_NAME': 'edxapp',
    'GO_PIPELINE_COUNTER': '123',
    'GO_STAGE_NAME': 'build',
    'GO_STAGE_COUNTER': '456',
    'GO_JOB_NAME': 'prod',
    'GO_TRIGGER_USER': 'Alice',
}

class TestGocdOpenAlert(TestCase):
    @patch.dict('os.environ', SAMPLE_ENV)
    @patch('tubular.scripts.gocd_open_alert.opsgenie_api.OpsGenieAPI.alert_opsgenie')
    def test_create_alert(self, mock_opsgenie_open):
        """Test basic alert creation, all options."""
        script_run = CliRunner().invoke(
            open_alert.gocd_open_alert,
            catch_exceptions=False,
            args=[
                '--auth-token', 'XYZ',
                '--responder', 'Some Team',
                '--runbook', 'https://example.com/wiki/runbook',
            ],
        )

        assert script_run.exit_code == 0
        mock_opsgenie_open.assert_called_once_with(
            "[GoCD] Pipeline failed: edxapp/build/prod",
            (
                "Pipeline edxapp failed.\n\n"
                "- Runbook: https://example.com/wiki/runbook\n"
                "- Build logs: https://gocd.tools.edx.org/go/tab/build/detail/edxapp/123/build/456/prod\n"
                "- Triggered by: Alice\n"
            ),
            'Some Team',
            alias='gocd-pipeline-edxapp-build-prod',
        )

    @patch.dict('os.environ', SAMPLE_ENV)
    @patch('tubular.scripts.gocd_open_alert.opsgenie_api.OpsGenieAPI.alert_opsgenie')
    def test_no_runbook(self, mock_opsgenie_open):
        """Test missing runbook URL"""
        script_run = CliRunner().invoke(
            open_alert.gocd_open_alert,
            catch_exceptions=False,
            args=[
                '--auth-token', 'XYZ',
                '--responder', 'Some Team',
            ],
        )

        assert script_run.exit_code == 0
        mock_opsgenie_open.assert_called_once_with(
            "[GoCD] Pipeline failed: edxapp/build/prod",
            (
                "Pipeline edxapp failed.\n\n"
                "- Runbook: <not provided>\n" # difference is here
                "- Build logs: https://gocd.tools.edx.org/go/tab/build/detail/edxapp/123/build/456/prod\n"
                "- Triggered by: Alice\n"
            ),
            'Some Team',
            alias='gocd-pipeline-edxapp-build-prod',
        )

    @patch('tubular.scripts.gocd_open_alert.log.error')
    def test_check_responder(self, mock_log_error):
        """Test that responder field can't be empty."""
        script_run = CliRunner().invoke(
            open_alert.gocd_open_alert,
            catch_exceptions=False,
            args=['--auth-token', 'XYZ', '--responder', ''],
        )

        assert script_run.exit_code == 1
        mock_log_error.assert_called_once_with("Responder field was empty -- refusing to create alert.")
