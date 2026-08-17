"""
Tests for the Datadog sourcemap upload in frontend_utils.py. datadog-ci reads the
repository URL and commit SHA from its own working directory, so these tests pin
down the invocation rather than just its arguments.
"""

import os

from unittest import TestCase, mock

from git.exc import InvalidGitRepositoryError

from ..scripts.frontend_utils import FrontendDeployer, normalize_github_url

TEST_DATA_DIR = "tubular/tests/example-frontend-config"


def build_deployer(app_config=None):
    """ A deployer with config loading stubbed out, so tests stay focused on the upload. """
    with mock.patch.object(FrontendDeployer, '_get_configs', return_value=({}, {})):
        deployer = FrontendDeployer(
            f"{TEST_DATA_DIR}/common.yml",
            f"{TEST_DATA_DIR}/app.yml",
            'frontend-app-coolfrontend',
        )
    deployer.LOG = mock.Mock()
    deployer.FAIL = mock.Mock()
    deployer.get_app_config = mock.Mock(return_value=app_config or {})
    return deployer


class TestNormalizeGithubUrl(TestCase):
    """ Turning whatever git reports as ``origin`` into a URL Datadog can use. """

    def test_remote_forms(self):
        """ The organization is read from the remote, never assumed to be edx. """
        edx, path = 'https://github.com/edx/frontend-app-foo', 'edx/frontend-app-foo'
        for remote, expected in [
                (f'git@github.com:{path}.git', edx),
                (f'https://github.com/{path}.git', edx),
                (f'ssh://git@github.com/{path}.git', edx),
                (f'https://github.com/{path}', edx),
                (f'https://user:token@github.com/{path}.git', edx),
                ('git@github.com:openedx/frontend-app-foo.git', edx.replace('/edx/', '/openedx/')),
                # Unusable -- datadog-ci auto-detects rather than sending a wrong link.
                (None, None), ('', None), ('not-a-remote', None),
                ('https://github.com/onlyone', None), (f'git@ghe.example.com:{path}.git', None),
        ]:
            assert normalize_github_url(remote) == expected, remote


@mock.patch('tubular.scripts.frontend_utils.subprocess.Popen')
class TestUploadJsSourcemaps(TestCase):
    """ The datadog-ci invocation itself. """

    def _upload(self, mock_popen, *, configured_url=None, repo_exc=None,
                origin='git@github.com:edx/frontend-app-coolfrontend.git',
                returncode=0, output=''):
        """ Run the upload and return (deployer, command list, Popen kwargs). """
        mock_popen.return_value.communicate.return_value = (output, None)
        mock_popen.return_value.returncode = returncode
        deployer = build_deployer()
        repo = mock.Mock(**{'remotes.origin.url': origin})
        repo_patch = mock.patch('tubular.scripts.frontend_utils.Repo',
                                **({'side_effect': repo_exc} if repo_exc else {'return_value': repo}))
        with repo_patch, mock.patch.object(
                FrontendDeployer, '_upload_js_sourcemaps_config',
                return_value=('edx-frontend-app-coolfrontend', 'abc123', configured_url)):
            deployer._upload_js_sourcemaps('frontend-app-coolfrontend/dist')  # pylint: disable=protected-access
        args, kwargs = mock_popen.call_args
        return deployer, args[0], kwargs

    def test_invocation(self, mock_popen):
        """
        The whole fix depends on the cwd: datadog-ci reads git from it. The paths are
        relative to the deploy directory, so they must survive that change, and a list
        rather than a shell string keeps paths with spaces from breaking quoting.
        """
        _, command, kwargs = self._upload(mock_popen)
        assert kwargs['cwd'] == 'frontend-app-coolfrontend'
        assert isinstance(command, list) and not kwargs.get('shell', False)
        assert command[0].startswith('/') and command[0].endswith('/node_modules/.bin/datadog-ci')
        assert command[3].startswith('/') and command[3].endswith('frontend-app-coolfrontend/dist')

    def test_git_integration_is_enabled_at_the_repo_root(self, mock_popen):
        """ MFE sources live at the repo root, not under a directory named for the app. """
        _, command, _ = self._upload(mock_popen)
        assert '--disable-git' not in command
        assert '--project-path=./' in command
        assert '--service=edx-frontend-app-coolfrontend' in command
        assert '--release-version=abc123' in command
        assert '--repository-url=https://github.com/edx/frontend-app-coolfrontend' in command

    def test_explicit_repository_url_is_used_without_reading_git(self, mock_popen):
        _, command, _ = self._upload(
            mock_popen, configured_url='https://github.com/edx/elsewhere',
            repo_exc=InvalidGitRepositoryError('would fail if consulted'))
        assert '--repository-url=https://github.com/edx/elsewhere' in command

    def test_unreadable_remote_omits_repository_url(self, mock_popen):
        """ Upload without a link rather than failing, and say why in the log. """
        deployer, command, _ = self._upload(mock_popen, repo_exc=InvalidGitRepositoryError('nope'))
        assert not any(arg.startswith('--repository-url') for arg in command)
        assert any('Could not read the git remote' in str(c) for c in deployer.LOG.call_args_list)

    def test_nonzero_exit_is_logged_without_failing_the_deploy(self, mock_popen):
        deployer, _, _ = self._upload(mock_popen, returncode=1)
        assert any('Could not upload source maps' in str(c) for c in deployer.LOG.call_args_list)
        deployer.FAIL.assert_not_called()

    def test_git_warnings_on_zero_exit_are_surfaced(self, mock_popen):
        """ datadog-ci warns and exits zero, so the return code alone hides all of these. """
        for output, warned in [
                ('An error occured while invoking git: fatal: not a git repository', True),
                ('No tracked files found for sources contained in /dist/app.js.map', True),
                ('Could not attach git data for sourcemap /dist/app.js.map: boom', True),
                ('Uploaded 14 sourcemaps.', False),
        ]:
            deployer, _, _ = self._upload(mock_popen, output=output)
            logged = any('without git data' in str(c) for c in deployer.LOG.call_args_list)
            assert logged is warned, output

    def test_config_carries_the_repository_url_override(self, _mock_popen):
        """ Returned with service and version so get_app_config is read once, not twice. """
        deployer = build_deployer({'DATADOG_SERVICE': 'svc', 'APP_VERSION': 'sha',
                                   'DATADOG_REPOSITORY_URL': 'https://github.com/edx/x'})
        with mock.patch.dict(os.environ, {'DATADOG_API_KEY': 'key'}):
            assert deployer._upload_js_sourcemaps_config() == (  # pylint: disable=protected-access
                'svc', 'sha', 'https://github.com/edx/x')
        deployer.get_app_config.assert_called_once()

    def test_skips_upload_when_service_or_version_missing(self, mock_popen):
        deployer = build_deployer()
        with mock.patch.object(FrontendDeployer, '_upload_js_sourcemaps_config',
                               return_value=(None, None, None)):
            deployer._upload_js_sourcemaps('dist')  # pylint: disable=protected-access
        mock_popen.assert_not_called()
