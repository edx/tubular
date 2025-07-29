#! /usr/bin/env python3

"""
Command-line script to build a frontend application.
"""

import os
import shutil
import sys
from functools import partial

import click

# Add top-level module path to sys.path before importing tubular code.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tubular.scripts.helpers import _log, _fail  # pylint: disable=wrong-import-position
from tubular.scripts.frontend_utils import FrontendBuilder  # pylint: disable=wrong-import-position

SCRIPT_SHORTNAME = 'Build frontend'
LOG = partial(_log, SCRIPT_SHORTNAME)
FAIL = partial(_fail, SCRIPT_SHORTNAME)
MULTISITE_PATH = './multisite/dist'


@click.command("frontend_build")
@click.option(
    '--common-config-file',
    help='File from which common configuration variables are read.',
)
@click.option(
    '--env-config-file',
    help='File from which environment configuration variables are read.',
)
@click.option(
    '--app-name',
    help='Name of the frontend app.',
)
@click.option(
    '--version-file',
    help='File to which to write app version info to.',
)
def frontend_build(common_config_file, env_config_file, app_name, version_file):
    """
    Builds a frontend application with multi-site support.

    This script is specifically designed for multi-site micro-frontend applications
    like frontend-app-learner-portal-programs. It handles:
    
    1. Private NPM package installation (e.g., @edx/frontend-logging for Datadog)
    2. JavaScript-based configuration files (env.config.js)
    3. Site-specific environment variable configuration
    4. Datadog RUM integration with per-site tracking
    5. Multi-site build orchestration

    For Datadog RUM integration to work properly, ensure the following configuration
    is present in your environment config files:
    
    APP_CONFIG:
      DATADOG_APPLICATION_ID: "your-app-id"
      DATADOG_CLIENT_TOKEN: "your-client-token" 
      DATADOG_SITE: "datadoghq.com"
      DATADOG_SERVICE: "your-service-name"
      DATADOG_ENV: "prod|stg|dev"
      DATADOG_SESSION_SAMPLE_RATE: 20
      DATADOG_SESSION_REPLAY_SAMPLE_RATE: 0
      DATADOG_LOGS_SESSION_SAMPLE_RATE: 100
      JS_CONFIG_FILEPATH: "/path/to/env.config.js"
    
    NPM_PRIVATE:
      - "@edx/frontend-logging@^4.0.2"

    Uses the provided common and environment-specific configuration files to pass
    environment variables to the frontend build.

    Args:
        common_config_file (str): Path to a YAML file containing common configuration variables.
        env_config_file (str): Path to a YAML file containing environment configuration variables.
        app_name (str): Name of the frontend app.
        version_file (str): Path to a file to which application version info will be written.
    """
    if not app_name:
        FAIL(1, 'App name was not specified.')
    if not version_file:
        FAIL(1, 'Version file was not specified.')
    if not common_config_file:
        FAIL(1, 'Common config file was not specified.')
    if not env_config_file:
        FAIL(1, 'Environment config file was not specified.')

    builder = FrontendBuilder(common_config_file, env_config_file, app_name, version_file)
    builder.install_requirements()
    app_config = builder.get_app_config()

    # If the MULTISITE key is set, build the app once for each site (by setting
    # a HOSTNAME environment variable and store the each build output in
    # `dist/$HOSTNAME`.
    multisite_directory_path = os.path.join('.', app_name, MULTISITE_PATH)
    if os.path.exists(multisite_directory_path) and os.path.isdir(multisite_directory_path):
        shutil.rmtree(multisite_directory_path)
    multisite_sites = builder.env_cfg.get('MULTISITE', [])
    os.makedirs(MULTISITE_PATH)
    
    LOG(f'Building {len(multisite_sites)} sites for multi-site application {app_name}')
    
    for site_obj in multisite_sites:
        hostname = site_obj.get('HOSTNAME')
        if not hostname:
            FAIL(1, 'HOSTNAME is not set for a site in in app {}.'.format(app_name))

        LOG(f'Building site: {hostname} for app {app_name}')

        site_app_config = {}
        site_app_config.update(app_config)
        site_app_config.update(site_obj.get('APP_CONFIG', {}))
        site_app_config.update({'HOSTNAME': hostname})
        
        # Ensure Datadog configuration is properly set up for this site
        site_app_config = builder.ensure_datadog_config_for_site(site_app_config, hostname)
        
        # Copy JavaScript config file for this site if specified
        builder.copy_js_config_file_to_app_root(site_app_config, app_name)
        
        # Install private packages again to ensure they're available for this build
        # This ensures packages like @edx/frontend-logging are available for each site
        builder.install_requirements_npm_private()
        
        # Validate that logging and JS config are properly set up
        builder.validate_js_config_and_logging(app_name)
        
        env_vars = ['{}={}'.format(k, v) for k, v in site_app_config.items()]
        builder.build_app(
            env_vars,
            'Could not run `npm run build` for for site {} in app {}.'.format(hostname, app_name)
        )

        # Move built app from ./dist to a folder named after the site in the temporary
        # multisite directory. Since the build step uses app_name as a current working directory,
        # we need to move the files within that location.
        LOG(f'Moving build output for site {hostname}')
        os.renames(
            os.path.join('.', app_name, 'dist'),
            os.path.join('.', app_name, MULTISITE_PATH, hostname)
        )

    # Move the temporary directory down to `./dist` for deployment. The ./dist directory
    # will be non-existant since it was moved after each build. Since the build step uses app_name
    # as a current working directory, we need to move the files within that location.
    LOG(f'Finalizing multi-site build for {app_name}')
    os.renames(
        os.path.join('.', app_name, MULTISITE_PATH),
        os.path.join('.', app_name, 'dist')
    )

    builder.create_version_file()
    
    LOG(f'Successfully completed multi-site build for {app_name} with {len(multisite_sites)} sites')
    LOG(f'Sites built: {[site.get("HOSTNAME") for site in multisite_sites]}')


if __name__ == "__main__":
    frontend_build()  # pylint: disable=no-value-for-parameter
