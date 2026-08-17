"""
Utility file with helper classes for building and deploying frontends. Keeps
single and multi deployment scripts DRY.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys

from datetime import datetime
from functools import partial

import backoff
import CloudFlare
import yaml
from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError

# Add top-level module path to sys.path before importing tubular code.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tubular.git_repo import LocalGitAPI  # pylint: disable=wrong-import-position
from tubular.scripts.helpers import _log, _fail  # pylint: disable=wrong-import-position

MAX_TRIES = 3

# datadog-ci warns and exits zero when it cannot attach git data, so the return code
# never surfaces this. Without git data Datadog cannot link a stack frame to GitHub.
DATADOG_GIT_WARNINGS = (
    'error occured while invoking git',  # sic -- datadog-ci's own spelling
    'No tracked files found',
    'Could not attach git data',
)

# Owner and repo from a github.com remote, scp-style (git@github.com:edx/foo.git) or
# URL (https://github.com/edx/foo). Anything else is left to DATADOG_REPOSITORY_URL.
GITHUB_REMOTE = re.compile(r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$')


def normalize_github_url(remote_url):
    """ Convert a git remote into the https URL Datadog expects, or None if unusable. """
    match = GITHUB_REMOTE.search(remote_url or '')
    return 'https://github.com/{}/{}'.format(*match.groups()) if match else None


class FrontendUtils:
    """
    Base class for frontend utilities used for both building and
    deploying frontends, i.e. `FrontendBuilder` and `FrontendDeployer`.
    """

    def __init__(self, common_config_file, env_config_file, app_name):
        self.common_config_file = common_config_file
        self.env_config_file = env_config_file
        self.app_name = app_name
        self.common_cfg, self.env_cfg = self._get_configs()

    def FAIL(self):
        """ Placeholder for failure method """
        raise NotImplementedError

    def LOG(self):
        """ Placeholder for logging method """
        raise NotImplementedError

    def _get_configs(self):
        """ Loads configs from their paths """
        try:
            with io.open(self.common_config_file, 'r') as contents:
                common_vars = yaml.safe_load(contents)
        except IOError:
            self.FAIL(1, 'Common config file could not be opened.')

        try:
            with io.open(self.env_config_file, 'r') as contents:
                env_vars = yaml.safe_load(contents)
        except IOError:
            self.FAIL(1, 'Environment config file could not be opened.')

        return (common_vars, env_vars)

    def get_app_config(self):
        """ Combines the common and environment configs APP_CONFIG data """
        app_config = self.common_cfg.get('APP_CONFIG', {})
        app_config.update(self.env_cfg.get('APP_CONFIG', {}))
        app_config.update(self.env_cfg.get('FEATURE_FLAGS', {}))
        app_config['APP_VERSION'] = self.get_version_commit_sha()
        app_config['FEATURE_FLAGS'] = self.get_feature_flags()
        if not app_config:
            self.LOG('Config variables do not exist for app {}.'.format(self.app_name))
        return app_config

    def get_feature_flags(self):
        """ Accesses the feature flags from config and JSON encodes it to be placed in env variables """
        feature_flags = self.env_cfg.get('FEATURE_FLAGS', {})
        feature_flag_json = json.dumps(feature_flags)
        return feature_flag_json

    def get_version_commit_sha(self):
        """ Returns the commit SHA of the current HEAD """
        return LocalGitAPI(Repo(self.app_name)).get_head_sha()


class FrontendBuilder(FrontendUtils):
    """ Utility class for building frontends. """

    SCRIPT_SHORTNAME = 'Build frontend'
    LOG = partial(_log, SCRIPT_SHORTNAME)
    FAIL = partial(_fail, SCRIPT_SHORTNAME)

    def __init__(self, common_config_file, env_config_file, app_name, version_file):
        super().__init__(
            common_config_file=common_config_file,
            env_config_file=env_config_file,
            app_name=app_name,
        )
        self.version_file = version_file

    def install_requirements(self):
        """ Install requirements for app to build """
        proc = subprocess.Popen(['npm install'], cwd=self.app_name, shell=True)
        return_code = proc.wait()
        if return_code != 0:
            self.FAIL(1, 'Could not run `npm install` for app {}.'.format(self.app_name))

        self.install_requirements_npm_aliases()
        self.install_requirements_npm_private()

    def install_requirements_npm_aliases(self):
        """ Install NPM alias requirements for app to build """
        npm_aliases = self.get_npm_aliases_config()
        if npm_aliases:
            aliased_installs = ' '.join(['{}@{}'.format(k, v) for k, v in npm_aliases.items()])
            install_aliases_proc = subprocess.Popen(
                ['npm install {}'.format(aliased_installs)],
                cwd=self.app_name,
                shell=True
            )
            install_aliases_proc_return_code = install_aliases_proc.wait()
            if install_aliases_proc_return_code != 0:
                self.FAIL(1, 'Could not run `npm install` aliases {} for app {}.'.format(
                    aliased_installs, self.app_name
                ))

    def install_requirements_npm_private(self):
        """ Install NPM private requirements for app to build """
        npm_private = self.get_npm_private_config()
        if npm_private:
            install_list = ' '.join(npm_private)
            install_private_proc = subprocess.Popen(
                [f'npm install {install_list}'],
                cwd=self.app_name,
                shell=True
            )
            install_private_proc_return_code = install_private_proc.wait()
            if install_private_proc_return_code != 0:
                self.FAIL(1, 'Could not run `npm install {}` for app {}.'.format(
                    install_list, self.app_name
                ))

    def get_npm_aliases_config(self):
        """ Combines the common and environment configs NPM_ALIASES data """
        npm_aliases_config = self.common_cfg.get('NPM_ALIASES', {})
        npm_aliases_config.update(self.env_cfg.get('NPM_ALIASES', {}))
        if not npm_aliases_config:
            self.LOG('No NPM package aliases defined in config.')
        return npm_aliases_config

    def get_npm_private_config(self):
        """ Combines the common and environment configs NPM_PRIVATE packages """
        npm_private_config = self.common_cfg.get('NPM_PRIVATE', [])
        npm_private_config.extend(self.env_cfg.get('NPM_PRIVATE', []))
        if not npm_private_config:
            self.LOG('No NPM private packages defined in config.')
        return list(set(npm_private_config))

    def build_app(self, env_vars, fail_msg):
        """ Builds the app with environment variable. """
        proc = subprocess.Popen(
            ' '.join(env_vars + ['npm run build']),
            cwd=self.app_name,
            shell=True
        )
        build_return_code = proc.wait()
        if build_return_code != 0:
            self.FAIL(1, fail_msg)

    def create_version_file(self):
        """ Creates a version.json file to be deployed with frontend """
        # Add version.json file to build.
        version = {
            'repo': self.app_name,
            'commit': self.get_version_commit_sha(),
            'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        try:
            with io.open(self.version_file, 'w') as output_file:
                json.dump(version, output_file)
        except IOError:
            self.FAIL(1, 'Could not write to version file for app {}.'.format(self.app_name))

    def copy_js_config_file_to_app_root(self, app_config, app_name):
        """ Creates a copy of env.config.js(x) file to the app root """
        source = app_config.get('JS_CONFIG_FILEPATH')

        # Skip if JS_CONFIG_FILEPATH not defined
        if not source:
            return

        filename = app_config.get('LOCAL_JS_CONFIG_FILENAME', "env.config.js")
        destination = f"{app_name}/{filename}"
        try:
            shutil.copyfile(source, destination)
        except FileNotFoundError:
            self.FAIL(1, f"Could not find '{source}' for copying for app {app_name}.")
        except OSError:
            self.FAIL(1, f"Could not copy '{source}' to '{destination}', due to destination not writable.")


class FrontendDeployer(FrontendUtils):
    """ Utility class for deploying frontends. """

    SCRIPT_SHORTNAME = 'Deploy frontend'
    LOG = partial(_log, SCRIPT_SHORTNAME)
    FAIL = partial(_fail, SCRIPT_SHORTNAME)

    def _deploy_to_s3(self, bucket_name, app_dist):
        """ Deploy files to S3 bucket. """
        bucket_uri = 's3://{}'.format(bucket_name)
        proc = subprocess.Popen(
            ' '.join(['aws s3 sync', app_dist, bucket_uri, '--delete']),
            shell=True
        )
        return_code = proc.wait()
        if return_code != 0:
            self.FAIL(1, 'Could not sync app {} with S3 bucket {}.'.format(self.app_name, bucket_uri))

    def _get_npm_deploy_config(self):
        """ Combines the common and environment configs NPM_DEPLOY packages """
        npm_deploy_config = self.common_cfg.get('NPM_DEPLOY', [])
        npm_deploy_config.extend(self.env_cfg.get('NPM_DEPLOY', []))
        if not npm_deploy_config:
            self.LOG('No NPM packages defined for deployment in config.')
        return list(set(npm_deploy_config))

    def _install_requirements_npm_deploy(self):
        """ Install NPM requirements for app to deploy """
        npm_deploy = self._get_npm_deploy_config()
        if npm_deploy:
            install_list = ' '.join(npm_deploy)
            install_private_proc = subprocess.Popen(
                [f'npm install {install_list} --no-save'],
                shell=True
            )
            install_private_proc_return_code = install_private_proc.wait()
            if install_private_proc_return_code != 0:
                self.FAIL(1, 'Could not run `npm install {}` for app {}.'.format(
                    install_list, self.app_name
                ))

    def _upload_js_sourcemaps_config(self):
        """
        Retrieve config related to uploading JS sourcemaps. Returns the repository URL
        override too, so ``get_app_config`` -- which reads git HEAD -- is called once.
        """
        app_config = self.get_app_config()
        datadog_api_key = os.environ.get('DATADOG_API_KEY')
        if not datadog_api_key:
            # Can't upload source maps without ``DATADOG_API_KEY``, which must be set as an environment variable
            # before executing the Datadog CLI. The Datadog documentation suggests using a dedicated Datadog API key:
            # https://docs.datadoghq.com/real_user_monitoring/guide/upload-javascript-source-maps/
            self.LOG('Could not find DATADOG_API_KEY environment variable while uploading source maps.')
            return None, None, None

        service = app_config.get('DATADOG_SERVICE')
        if not service:
            self.LOG('Could not find DATADOG_SERVICE for app {} while uploading source maps.'.format(self.app_name))
            return None, None, None

        # Determine version for deployment, prioritizing app-specific version override, if any, before
        # default APP_VERSION commit SHA version.
        version = app_config.get('DATADOG_VERSION') or app_config.get('APP_VERSION')
        if not version:
            self.LOG('Could not find version for app {} while uploading source maps.'.format(self.app_name))
            return service, None, None

        # Successfully determined service and version for the app deployment
        return service, version, app_config.get('DATADOG_REPOSITORY_URL')

    def _get_datadog_repository_url(self, configured):
        """
        GitHub URL for linking stack frames to source, falling back to the checkout's
        remote. Not derivable from the app name: 'frontend-app-course-authoring' lives
        at edx/frontend-app-authoring.
        """
        if configured:
            return configured
        try:
            return normalize_github_url(Repo(self.app_name).remotes.origin.url)
        except (InvalidGitRepositoryError, NoSuchPathError, AttributeError, ValueError) as exc:
            self.LOG('Could not read the git remote for app {}: {}'.format(self.app_name, exc))
            return None

    def _upload_js_sourcemaps(self, app_dist):
        """ Upload JavaScript sourcemaps to Datadog. """
        service, version, configured_url = self._upload_js_sourcemaps_config()
        if not service or not version:
            # Could not determine appropriate service or version for app; skipping.
            return

        # Resolve before changing directory: both are relative to this script's working
        # directory, where npm install put node_modules and the build put dist.
        datadog_ci_bin = os.path.abspath('./node_modules/.bin/datadog-ci')
        abs_app_dist = os.path.abspath(app_dist)

        command = [
            datadog_ci_bin, 'sourcemaps', 'upload', abs_app_dist,
            '--service={}'.format(service),
            '--release-version={}'.format(version),
            '--minified-path-prefix=/',  # Sourcemaps are relative to the root when deployed
            '--project-path=./',  # MFE sources live at the root of the repo
        ]
        repository_url = self._get_datadog_repository_url(configured_url)
        if repository_url:
            command.append('--repository-url={}'.format(repository_url))

        self.LOG('Uploading source maps to Datadog for app {}.'.format(self.app_name))
        # datadog-ci reads the commit SHA (`git rev-parse HEAD`) and tracked file list
        # (`git ls-files`) from its working directory, so it must run in the app checkout.
        proc = subprocess.Popen(
            command,
            cwd=self.app_name,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        output, _ = proc.communicate()
        if output:
            self.LOG(output.strip())
        if proc.returncode != 0:
            # If failure occurs, log the error but don't fail the deployment.
            self.LOG('Could not upload source maps to Datadog for app {}.'.format(self.app_name))
        elif any(warning in output for warning in DATADOG_GIT_WARNINGS):
            self.LOG(
                'Source maps for app {} uploaded without git data; GitHub links will be '
                'missing. Check the datadog-ci warning above.'.format(self.app_name)
            )

    def deploy_site(self, bucket_name, app_dist):
        """ Deploy files to bucket. """
        self._deploy_to_s3(bucket_name, app_dist)
        self._install_requirements_npm_deploy()
        self._upload_js_sourcemaps(app_dist)
        self.LOG('Frontend application {} successfully deployed to {}.'.format(self.app_name, bucket_name))

    @backoff.on_exception(backoff.expo,
                          (CloudFlare.exceptions.CloudFlareAPIError),
                          max_tries=MAX_TRIES)
    def purge_cache(self, bucket_name):
        """
            Purge the Cloudflare cache for the frontend hostname.
            Frontend S3 buckets are named by hostname.
            Cloudflare zones are named by domain.
            Assumes the caller's shell has the following environment
            variables set to enable Cloudflare API auth:
            CF_API_EMAIL
            CF_API_KEY
        """
        zone_name = '.'.join(bucket_name.split('.')[-2:])  # Zone name is the TLD
        data = {'hosts': [bucket_name]}
        cloudflare_client = CloudFlare.CloudFlare()
        zone_id = cloudflare_client.zones.get(params={'name': zone_name})[0]['id']  # pylint: disable=no-member
        cloudflare_client.zones.purge_cache.post(zone_id, data=data)  # pylint: disable=no-member
        self.LOG('Successfully purged Cloudflare cache for hostname {}.'.format(bucket_name))
