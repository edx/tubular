#! /usr/bin/env python3
"""
Command-line script to delete GDPR partner reports on Google Drive that were created over N days ago.
"""


from datetime import datetime, timedelta
from dateutil.parser import parse
from functools import partial
from os import path
import io
import json
import logging
import sys

import click
import yaml
from pytz import UTC

# Add top-level module path to sys.path before importing tubular code.
sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from tubular.google_api import DriveApi  # pylint: disable=wrong-import-position
from tubular.scripts.helpers import _log, _fail, _fail_exception  # pylint: disable=wrong-import-position
from tubular.scripts.retirement_partner_report import REPORTING_FILENAME_PREFIX  # pylint: disable=wrong-import-position

SCRIPT_SHORTNAME = 'delete_expired_reports'
LOG = partial(_log, SCRIPT_SHORTNAME)
FAIL = partial(_fail, SCRIPT_SHORTNAME)
FAIL_EXCEPTION = partial(_fail_exception, SCRIPT_SHORTNAME)

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

# Deletion notification template for files about to be deleted
# Format variables: tags, filename
DELETION_NOTIFICATION_MESSAGE_TEMPLATE = """
Hello from edX. Dear {tags}, this is an automated notice that the retirement report file "{filename}" in your Google Drive folder is being deleted as part of our data retention policy.
""".strip()

# Return codes for various fail cases
ERR_NO_CONFIG = -1
ERR_BAD_CONFIG = -2
ERR_NO_SECRETS = -3
ERR_BAD_SECRETS = -4
ERR_DELETING_REPORTS = -5
ERR_BAD_AGE = -6


def _config_or_exit(config_file, google_secrets_file):
    """
    Returns the config values from the given file, allows overriding of passed in values.
    """
    try:
        with io.open(config_file, 'r') as config:
            config = yaml.safe_load(config)

        # Check required value
        if 'drive_partners_folder' not in config or not config['drive_partners_folder']:
            FAIL(ERR_BAD_CONFIG, 'No drive_partners_folder in config, or it is empty!')

    except Exception as exc:  # pylint: disable=broad-except
        FAIL_EXCEPTION(ERR_BAD_CONFIG, 'Failed to read config file {}'.format(config_file), exc)

    try:
        # Just load and parse the file to make sure it's legit JSON before doing
        # all of the work to delete old reports.
        with open(google_secrets_file, 'r') as secrets_f:
            json.load(secrets_f)

        config['google_secrets_file'] = google_secrets_file
        return config
    except Exception as exc:  # pylint: disable=broad-except
        FAIL_EXCEPTION(ERR_BAD_SECRETS, 'Failed to read secrets file {}'.format(google_secrets_file), exc)


def _get_external_emails_for_partners(drive, config):
    """
    Extract external email addresses from partner folder permissions.
    
    Args:
        drive (DriveApi): Initialized Drive API client.
        config (dict): Configuration dictionary containing partner_folder_mapping and denied_notification_domains.
    
    Returns:
        dict: Mapping of partner names to lists of external email addresses (denied domains filtered out).
    """
    partners = list(config.get('partner_folder_mapping', {}).keys())
    
    if not partners:
        LOG('No partner_folder_mapping found in config')
        return {}
    
    folder_ids = {config['partner_folder_mapping'][partner] for partner in partners}
    
    partner_folders_to_permissions = drive.list_permissions_for_files(
        folder_ids,
        fields='emailAddress',
    )
    
    permissions = {
        partner: partner_folders_to_permissions[config['partner_folder_mapping'][partner]]
        for partner in partners
    }
    
    denied_domains = config.get('denied_notification_domains', [])
    external_emails = {
        partner: [
            perm['emailAddress']
            for perm in permissions[partner]
            if not any(
                perm['emailAddress'].lower().endswith(denied_domain.lower())
                for denied_domain in denied_domains
            )
        ]
        for partner in permissions
    }
    
    return external_emails


def _send_deletion_notifications(config, age_in_days, as_user_account, mimetype='text/csv'):
    """
    Send deletion notifications for files that are about to be deleted.
    
    Args:
        config (dict): Configuration dictionary
        age_in_days (int): Days before files are deleted (retention period)
        as_user_account (bool): Whether using OAuth2 user account authentication
        mimetype (str): Mimetype of files to check. Defaults to 'text/csv'.
    """
    LOG('Sending deletion notifications for files older than {} days'.format(age_in_days))
    
    try:
        drive = DriveApi(config['google_secrets_file'], as_user_account=as_user_account)
        now = datetime.now(UTC)
        delete_before_dt = now - timedelta(days=age_in_days)
        
        external_emails = _get_external_emails_for_partners(drive, config)
        
        platform_name = config.get('partner_report_platform_name', '')
        file_prefix = '{}_{}'.format(REPORTING_FILENAME_PREFIX, platform_name)
        
        for partner in config.get('partner_folder_mapping', {}).keys():
            folder_id = config['partner_folder_mapping'][partner]
            
            # Skip if no external POC (unless exempt)
            if not external_emails.get(partner, []):
                if partner not in config.get('exempted_partners', []):
                    LOG('WARNING: Partner "{}" has no POC for deletion notifications'.format(partner))
                continue
            
            try:
                files = drive.walk_files(
                    folder_id,
                    file_fields='id, name, createdTime',
                    mimetype=mimetype,
                    recurse=False
                )
                
                for file in files:
                    file_created = parse(file['createdTime'])
                    file_name = file.get('name', 'unknown')
                    
                    if not file_name.startswith(file_prefix):
                        continue
                    
                    if file_created < delete_before_dt:
                        file_id = file['id']
                        
                        tag_string = ' '.join('+' + email for email in external_emails[partner])
                        comment_content = DELETION_NOTIFICATION_MESSAGE_TEMPLATE.format(
                            tags=tag_string,
                            filename=file_name
                        )
                        
                        drive.create_comments_for_files([(file_id, comment_content)])
                        LOG('Sent deletion notification for file: {}'.format(file_name))
                        
            except Exception as exc:  # pylint: disable=broad-except
                LOG('WARNING: Error checking files for partner "{}": {}'.format(partner, exc))
                
    except Exception as exc:  # pylint: disable=broad-except
        LOG('WARNING: Error in deletion notification check: {}. Continuing with deletion process.'.format(exc))


@click.command("delete_expired_reports")
@click.option(
    '--config_file',
    help='YAML file that contains retirement-related configuration for this environment.'
)
@click.option(
    '--google_secrets_file',
    help='JSON file with Google service account credentials for deletion purposes.'
)
@click.option(
    '--age_in_days',
    type=int,
    help='Days ago from the current time - before which all GDPR partner reports will be deleted.'
)
@click.option(
    '--as_user_account',
    is_flag=True,
    help=(
        'Whether or not the given secrets file is an OAuth2 JSON token, '
        'which means that the authentication is done using a '
        'user account, and NOT a service account.'
    ),
    show_default=True,
)
def delete_expired_reports(
    config_file, google_secrets_file, age_in_days, as_user_account
):
    """
    Performs the partner report deletion as needed.
    Sends deletion notifications to users before files are deleted.
    """
    LOG('Starting partner report deletion using config file "{}", Google config "{}", and {} days back'.format(
        config_file, google_secrets_file, age_in_days
    ))

    if not config_file:
        FAIL(ERR_NO_CONFIG, 'No config file passed in.')

    if not google_secrets_file:
        FAIL(ERR_NO_SECRETS, 'No secrets file passed in.')

    if age_in_days <= 0:
        FAIL(ERR_BAD_AGE, 'age_in_days must be a positive integer.')

    config = _config_or_exit(config_file, google_secrets_file)

    try:
        LOG('Sending deletion notifications to users...')
        _send_deletion_notifications(config, age_in_days, as_user_account, mimetype='text/csv')
        
        delete_before_dt = datetime.now(UTC) - timedelta(days=age_in_days)
        drive = DriveApi(
            config['google_secrets_file'], as_user_account=as_user_account
        )
        LOG('DriveApi configured')
        drive.delete_files_older_than(
            config['drive_partners_folder'],
            delete_before_dt,
            mimetype='text/csv',
            prefix="{}_{}".format(REPORTING_FILENAME_PREFIX, config['partner_report_platform_name'])
        )
        LOG('Partner report deletion complete')
    except Exception as exc:  # pylint: disable=broad-except
        FAIL_EXCEPTION(ERR_DELETING_REPORTS, 'Unexpected error occurred!', exc)


if __name__ == '__main__':
    # pylint: disable=unexpected-keyword-arg, no-value-for-parameter
    delete_expired_reports(auto_envvar_prefix='RETIREMENT')
