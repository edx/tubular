#! /usr/bin/env python3
# coding=utf-8

"""
Command-line script to drive the partner reporting part of the retirement process
"""

from collections import defaultdict, OrderedDict
from datetime import date, datetime, timedelta
from dateutil.parser import parse
from functools import partial
import logging
import os
from pytz import UTC
import sys
import unicodedata
import unicodecsv as csv

import click
from six import text_type

# Add top-level module path to sys.path before importing tubular code.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tubular.google_api import DriveApi  # pylint: disable=wrong-import-position
# pylint: disable=wrong-import-position
from tubular.scripts.helpers import (
    _config_with_drive_or_exit,
    _fail,
    _fail_exception,
    _log,
    _setup_lms_api_or_exit
)

# Return codes for various fail cases
ERR_SETUP_FAILED = -1
ERR_FETCHING_LEARNERS = -2
ERR_NO_CONFIG = -3
ERR_NO_SECRETS = -4
ERR_NO_OUTPUT_DIR = -5
ERR_BAD_CONFIG = -6
ERR_BAD_SECRETS = -7
ERR_UNKNOWN_ORG = -8
ERR_REPORTING = -9
ERR_DRIVE_UPLOAD = -10
ERR_CLEANUP = -11
ERR_DRIVE_LISTING = -12
ERR_MISSING_POC = -13

SCRIPT_SHORTNAME = 'Partner report'
LOG = partial(_log, SCRIPT_SHORTNAME)
FAIL = partial(_fail, SCRIPT_SHORTNAME)
FAIL_EXCEPTION = partial(_fail_exception, SCRIPT_SHORTNAME)
CONFIG_WITH_DRIVE_OR_EXIT = partial(_config_with_drive_or_exit, FAIL_EXCEPTION, ERR_BAD_CONFIG, ERR_BAD_SECRETS)
SETUP_LMS_OR_EXIT = partial(_setup_lms_api_or_exit, FAIL, ERR_SETUP_FAILED)

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# Prefix which starts all generated report filenames.
REPORTING_FILENAME_PREFIX = 'user_retirement'

# We'll store the access token here once retrieved
AUTH_HEADER = {}

# This text template will be the comment body for all new CSV uploads.  The
# following format variables need to be provided:
#   tags: space delimited list of google user tags, e.g. "+user1@gmail.com +user2@gmail.com"
NOTIFICATION_MESSAGE_TEMPLATE = """
Hello from edX. Dear {tags}, a new report listing the learners enrolled in your institution’s courses on edx.org that have requested deletion of their edX account and associated personal data within the last week has been published to Google Drive. Please access your folder to see the latest report.
""".strip()
# Used to verify deletion comments; must exist in DELETION_WARNING_MESSAGE_TEMPLATE
DELETION_WARNING_PHRASE = 'will be automatically deleted'
# Deletion warning template for files approaching expiration
# Format variables: tags, filename, days_until_deletion, deletion_date
DELETION_WARNING_MESSAGE_TEMPLATE = (
    'Hello from edX. Dear {tags}, this is an automated notice that the retirement report file '
    '"{filename}" in your Google Drive folder ' + DELETION_WARNING_PHRASE +
    ' in {days_until_deletion} days (on {deletion_date} UTC) as part of our data retention policy.'
)
LEARNER_CREATED_KEY = 'created'  # This key is currently required to exist in the learner
LEARNER_ORIGINAL_USERNAME_KEY = 'original_username'  # This key is currently required to exist in the learner
ORGS_KEY = 'orgs'
ORGS_CONFIG_KEY = 'orgs_config'
ORGS_CONFIG_ORG_KEY = 'org'
ORGS_CONFIG_FIELD_HEADINGS_KEY = 'field_headings'
ORGS_CONFIG_LEARNERS_KEY = 'learners'

# Default field headings for the CSV file
DEFAULT_FIELD_HEADINGS = ['user_id', 'original_username', 'original_email', 'original_name', 'deletion_completed']


def _check_all_learner_orgs_or_exit(config, learners):
    """
    Checks all learners and their orgs, ensuring that each org has a mapping to a partner Drive folder.
    If any orgs are missing a mapping, fails after printing the mismatched orgs.
    """
    # Loop through all learner orgs, checking for their mappings.
    mismatched_orgs = set()
    for learner in learners:
        # Check the orgs with standard fields
        if ORGS_KEY in learner:
            for org in learner[ORGS_KEY]:
                if org not in config['org_partner_mapping']:
                    mismatched_orgs.add(org)

        # Check the orgs with custom configurations (orgs with custom fields)
        if ORGS_CONFIG_KEY in learner:
            for org_config in learner[ORGS_CONFIG_KEY]:
                org_name = org_config[ORGS_CONFIG_ORG_KEY]
                if org_name not in config['org_partner_mapping']:
                    mismatched_orgs.add(org_name)
    if mismatched_orgs:
        FAIL(
            ERR_UNKNOWN_ORG,
            'Partners for organizations {} do not exist in configuration.'.format(text_type(mismatched_orgs))
        )


def _get_orgs_and_learners_or_exit(config):
    """
    Contacts LMS to get the list of learners to report on and the orgs they belong to.
    Reformats them into dicts with keys of the orgs and lists of learners as the value
    and returns a tuple of that dict plus a list of all of the learner usernames.
    """
    try:
        LOG('Retrieving all learners on which to report from the LMS.')
        learners = config['LMS'].retirement_partner_report()
        LOG('Retrieved {} learners from the LMS.'.format(len(learners)))

        _check_all_learner_orgs_or_exit(config, learners)

        orgs = defaultdict()
        usernames = []

        # Organize the learners, create separate dicts per partner, making sure each partner is in the mapping.
        # Learners can appear in more than one dict. It is assumed that each org has 1 and only 1 set of field headings.
        for learner in learners:
            usernames.append({'original_username': learner[LEARNER_ORIGINAL_USERNAME_KEY]})

            # Use the datetime upon which the record was 'created' in the partner reporting queue
            # as the approximate time upon which user retirement was completed ('deletion_completed')
            # for the record's user.
            learner['deletion_completed'] = learner[LEARNER_CREATED_KEY]

            # Create a list of orgs who should be notified about this user
            if ORGS_KEY in learner:
                for org_name in learner[ORGS_KEY]:
                    reporting_org_names = config['org_partner_mapping'][org_name]
                    _add_reporting_org(orgs, reporting_org_names, DEFAULT_FIELD_HEADINGS, learner)

            # Check for orgs with custom fields
            if ORGS_CONFIG_KEY in learner:
                for org_config in learner[ORGS_CONFIG_KEY]:
                    org_name = org_config[ORGS_CONFIG_ORG_KEY]
                    org_headings = org_config[ORGS_CONFIG_FIELD_HEADINGS_KEY]
                    reporting_org_names = config['org_partner_mapping'][org_name]
                    _add_reporting_org(orgs, reporting_org_names, org_headings, learner)

        return orgs, usernames
    except Exception as exc:  # pylint: disable=broad-except
        FAIL_EXCEPTION(ERR_FETCHING_LEARNERS, 'Unexpected exception occurred!', exc)


def _add_reporting_org(orgs, org_names, org_headings, learner):
    """
    Add the learner to the org
    """
    for org_name in org_names:
        # Create the org, if necessary
        orgs[org_name] = orgs.get(
            org_name,
            {
                ORGS_CONFIG_FIELD_HEADINGS_KEY: org_headings,
                ORGS_CONFIG_LEARNERS_KEY: []
            }
        )

        # Add the learner to the list of learners in the org
        orgs[org_name][ORGS_CONFIG_LEARNERS_KEY].append(learner)


def _generate_report_files_or_exit(config, report_data, output_dir):
    """
    Spins through the partners, creating a single CSV file for each
    """
    # We'll store all of the partner to file links here so we can be sure all files generated successfully
    # before trying to push to Google, minimizing the cases where we might have to overwrite files
    # already up there.
    partner_filenames = {}

    for partner_name in report_data:
        try:
            partner = report_data[partner_name]
            partner_headings = partner[ORGS_CONFIG_FIELD_HEADINGS_KEY]
            partner_learners = partner[ORGS_CONFIG_LEARNERS_KEY]
            outfile = _generate_report_file_or_exit(config, output_dir, partner_name, partner_headings,
                                                    partner_learners)
            partner_filenames[partner_name] = outfile
            LOG('Report complete for partner {}'.format(partner_name))
        except Exception as exc:  # pylint: disable=broad-except
            FAIL_EXCEPTION(ERR_REPORTING, 'Error reporting retirement for partner {}'.format(partner_name), exc)

    return partner_filenames


def _generate_report_file_or_exit(config, output_dir, partner, field_headings, field_values):
    """
    Create a CSV file for the partner
    """
    LOG('Starting report for partner {}: {} learners to add. Field headings are {}'.format(
        partner,
        len(field_values),
        field_headings
    ))

    outfile = os.path.join(output_dir, '{}_{}_{}_{}.csv'.format(
        REPORTING_FILENAME_PREFIX, config['partner_report_platform_name'], partner, date.today().isoformat()
    ))

    # If there is already a file for this date, assume it is bad and replace it
    try:
        os.remove(outfile)
    except OSError:
        pass

    with open(outfile, 'wb') as f:
        writer = csv.DictWriter(f, field_headings, dialect=csv.excel, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(field_values)

    return outfile


def _config_drive_folder_map_or_exit(config):
    """
    Lists folders under our top level parent for this environment and returns
    a dict of {partner name: folder id}. Partner names should match the values
    in config['org_partner_mapping']
    """
    drive = DriveApi(config['google_secrets_file'])

    try:
        LOG('Attempting to find all partner sub-directories on Drive.')
        folders = drive.walk_files(
            config['drive_partners_folder'],
            mimetype='application/vnd.google-apps.folder',
            recurse=False
        )
    except Exception as exc:  # pylint: disable=broad-except
        FAIL_EXCEPTION(ERR_DRIVE_LISTING, 'Finding partner directories on Drive failed.', exc)

    if not folders:
        FAIL(ERR_DRIVE_LISTING, 'Finding partner directories on Drive failed. Check your permissions.')

    # As in _config_or_exit we force normalize the unicode here to make sure the keys
    # match. Otherwise the name we get back from Google won't match what's in the YAML config.
    config['partner_folder_mapping'] = OrderedDict()
    for folder in folders:
        folder['name'] = unicodedata.normalize('NFKC', text_type(folder['name']))
        config['partner_folder_mapping'][folder['name']] = folder['id']


def _push_files_to_google(config, partner_filenames):
    """
    Copy the file to Google drive for this partner

    Returns:
        List of file IDs for the uploaded csv files.
    """
    # First make sure we have Drive folders for all partners
    failed_partners = []
    for partner in partner_filenames:
        if partner not in config['partner_folder_mapping']:
            failed_partners.append(partner)

    if failed_partners:
        FAIL(ERR_BAD_CONFIG, 'These partners have retiring learners, but no Drive folder: {}'.format(failed_partners))

    file_ids = {}
    drive = DriveApi(config['google_secrets_file'])
    for partner in partner_filenames:
        # This is populated on the fly in _config_drive_folder_map_or_exit
        folder_id = config['partner_folder_mapping'][partner]
        file_id = None
        with open(partner_filenames[partner], 'rb') as f:
            try:
                drive_filename = os.path.basename(partner_filenames[partner])
                LOG('Attempting to upload {} to {} Drive folder.'.format(drive_filename, partner))
                file_id = drive.create_file_in_folder(folder_id, drive_filename, f, "text/csv")
            except Exception as exc:  # pylint: disable=broad-except
                FAIL_EXCEPTION(ERR_DRIVE_UPLOAD, 'Drive upload failed for: {}'.format(drive_filename), exc)
        file_ids[partner] = file_id
    return file_ids


def _get_partner_emails(drive, config, partners=None):
    """
    Extract external email addresses from partner folder permissions.
    
    This shared helper ensures consistent handling of permissions and denied domains
    across different notification paths (e.g. upload comments, deletion warnings, etc.).
    
    Args:
        drive (DriveApi): Initialized Drive API client.
        config (dict): Configuration dictionary containing partner_folder_mapping and denied_notification_domains.
        partners (list, optional): List of specific partner names to process. If None, processes all partners
                                   in partner_folder_mapping.
    
    Returns:
        dict: Mapping of partner names to lists of external email addresses (denied domains filtered out).
    """
    # Default to all partners if not specified
    if partners is None:
        partners = list(config['partner_folder_mapping'].keys())
    
    # Get unique folder IDs for the specified partners
    folder_ids = {config['partner_folder_mapping'][partner] for partner in partners}
    
    partner_folders_to_permissions = drive.list_permissions_for_files(
        folder_ids,
        fields='emailAddress',
    )
    # Create a mapping of partners to a list of permissions dicts
    permissions = {
        partner: partner_folders_to_permissions[config['partner_folder_mapping'][partner]]
        for partner in partners
    }
    # Filter out denied addresses and flatten to just email addresses
    external_emails = {
        partner: [
            perm['emailAddress']
            for perm in permissions[partner]
            if not any(
                perm['emailAddress'].lower().endswith(denied_domain.lower())
                for denied_domain in config['denied_notification_domains']
            )
        ]
        for partner in permissions
    }
    
    return external_emails


def _add_comments_to_files(config, partner_file_ids_dict):
    """
    Add comments to the uploaded csv files, triggering email notification.

    Args:
        partner_file_ids_dict (dict): Mapping of partner names to Drive file IDs corresponding to the newly uploaded csv files.
    """
    drive = DriveApi(config['google_secrets_file'])
    
    # Get external emails for partners with uploaded files
    external_emails = _get_partner_emails(drive, config, partners=list(partner_file_ids_dict.keys()))

    file_ids_and_comments = []
    missing_poc_partners = []

    for partner in partner_file_ids_dict:
        if not external_emails[partner]:
            # Check if this partner is exempt from POC requirements
            if partner in config.get('exempted_partners', []):
                LOG(
                    'INFO: Partner "{}" is configured to not require a POC - skipping notification.'
                    .format(partner)
                )
            else:
                # This is a compliance issue - missing POC prevents proper notification
                missing_poc_partners.append(partner)
                LOG(
                    'ERROR: Could not find a Point of Contact (POC) for partner: "{}". '
                    'Double check the partner folder permissions in Google Drive.'
                    .format(partner)
                )
        else:
            tag_string = ' '.join('+' + email for email in external_emails[partner])
            comment_content = NOTIFICATION_MESSAGE_TEMPLATE.format(tags=tag_string)
            file_ids_and_comments.append((partner_file_ids_dict[partner], comment_content))

    if file_ids_and_comments:
        try:
            LOG('Adding notification comments to uploaded csv files.')
            drive.create_comments_for_files(file_ids_and_comments)
        except Exception as exc:  # pylint: disable=broad-except
            # do not fail the script here, since comment errors are non-critical
            LOG('WARNING: there was an error adding Google Drive comments to the csv files: {}'.format(exc))

    # Fail if any partners are missing POC and not exempt.
    if missing_poc_partners:
        partner_word = 'partners' if len(missing_poc_partners) != 1 else 'partner'
        FAIL(ERR_MISSING_POC,
             'COMPLIANCE FAILURE: {} {} missing POC: {}. Project Coordinators must be informed.'
             .format(len(missing_poc_partners), partner_word, ', '.join('"{}"'.format(p) for p in missing_poc_partners)))


def _check_and_notify_about_expiring_files(config, enable_overdue_file_notification=False):
    """
    Check for existing files approaching their deletion date and send warning notifications.
    
    Uses configuration values:
    - deletion_warning_days: Days before deletion to send warning
        
    Args:
        config (dict): Configuration dictionary containing retention settings and Drive folder mappings.
    """
    # CLI parameter "--age_in_days" represents the retention period.
    retention_days = config.get('age_in_days', 60)
    warning_days = config.get('deletion_warning_days', 7)

    if retention_days <= 0 or warning_days <= 0:
        raise ValueError(
            'Misconfigured retention settings: age_in_days={}, deletion_warning_days={}. '
            'Both must be positive integers.'.format(retention_days, warning_days)
        )
    if warning_days >= retention_days:
        raise ValueError(
            'Misconfigured retention settings: deletion_warning_days ({}) must be less than '
            'age_in_days ({}).'.format(warning_days, retention_days)
        )
    
    LOG('Checking for files approaching deletion (retention: {} days, warning: {} days before)'.format(
        retention_days, warning_days
    ))
    
    try:
        drive = DriveApi(config['google_secrets_file'])
        now = datetime.now(UTC)
        warning_threshold = now - timedelta(days=(retention_days - warning_days))
        
        # Get external emails per partner using shared helper
        external_emails = _get_partner_emails(drive, config)
        
        for partner in config['partner_folder_mapping']:
            folder_id = config['partner_folder_mapping'][partner]
            
            # Skip if no external POC (unless exempt)
            if not external_emails[partner]:
                if partner not in config.get('exempted_partners', []):
                    LOG('WARNING: Partner "{}" has no POC for deletion warnings'.format(partner))
                continue
            
            try:
                files = drive.walk_files(
                    folder_id,
                    file_fields='id, name, createdTime',
                    recurse=False
                )

                pending_comments = []

                for file_info in files:
                    filename = file_info.get('name', '')

                    created_time_str = file_info.get('createdTime')
                    if not created_time_str:
                        LOG('WARNING: File {} has no creation time, skipping'.format(filename))
                        continue

                    file_created = parse(created_time_str)
                    if file_created.tzinfo is None:
                        file_created = file_created.replace(tzinfo=UTC)
                    else:
                        file_created = file_created.astimezone(UTC)

                    if file_created <= warning_threshold:
                        file_id = file_info.get('id')

                        # First check if the file already has the deletion warning to avoid
                        # duplicate comments on re-run.
                        existing_comments = drive.list_comments_for_file(file_id, fields='content')
                        has_warning = any(
                            DELETION_WARNING_PHRASE in comment.get('content', '')
                            for comment in existing_comments
                        )

                        if has_warning:
                            LOG('File {} already has deletion warning, skipping'.format(filename))
                            continue

                        deletion_datetime = file_created + timedelta(days=retention_days)
                        # Use total_seconds-based math to avoid .days flooring off-by-one
                        seconds_until_deletion = (deletion_datetime - now).total_seconds()
                        days_until_deletion = int(seconds_until_deletion / 86400)
                        # deletion_datetime is already UTC; format as a UTC date
                        deletion_date = deletion_datetime.strftime('%Y-%m-%d')

                        if days_until_deletion <= 0:
                            if enable_overdue_file_notification:
                                LOG('File {} is past its retention period, queuing overdue notification'.format(filename))
                                tag_string = ' '.join('+' + email for email in external_emails[partner])
                                comment_content = DELETION_WARNING_MESSAGE_TEMPLATE.format(
                                    tags=tag_string,
                                    filename=filename,
                                    days_until_deletion=days_until_deletion,
                                    deletion_date=deletion_date,
                                )
                                pending_comments.append((file_id, comment_content))
                                LOG('Queuing overdue file notification for: {}'.format(filename))
                            continue

                        if days_until_deletion > warning_days:
                            # File is older than warning_threshold but not yet in the warning window;
                            # this shouldn't normally happen but guard against clock skew or config changes.
                            LOG('File {} has {} days until deletion, outside warning window, skipping'.format(
                                filename, days_until_deletion
                            ))
                            continue

                        tag_string = ' '.join('+' + email for email in external_emails[partner])
                        comment_content = DELETION_WARNING_MESSAGE_TEMPLATE.format(
                            tags=tag_string,
                            filename=filename,
                            days_until_deletion=days_until_deletion,
                            deletion_date=deletion_date
                        )
                        pending_comments.append((file_id, comment_content))
                        LOG('Queuing deletion warning for file: {} ({} days until deletion)'.format(
                            filename, days_until_deletion
                        ))

                if pending_comments:
                    drive.create_comments_for_files(pending_comments)
                    LOG('Sent {} deletion warning(s) for partner "{}"'.format(len(pending_comments), partner))

            except Exception as exc:  # pylint: disable=broad-except
                LOG('WARNING: Error checking files for partner "{}": {}'.format(partner, exc))
                
    except Exception as exc:  # pylint: disable=broad-except
        LOG('WARNING: Error in deletion warning check: {}. Continuing with report generation.'.format(exc))


@click.command("generate_report")
@click.option(
    '--config_file',
    help='YAML file that contains retirement related configuration for this environment.'
)
@click.option(
    '--google_secrets_file',
    help='JSON file with Google service account credentials for uploading.'
)
@click.option(
    '--output_dir',
    help='The local directory that the script will write the reports to.'
)
@click.option(
    '--comments/--no_comments',
    default=True,
    help='Do or skip adding notification comments to the reports.'
)
@click.option(
    '--age_in_days',
    type=int,
    default=None,
    help='Number of days before files are deleted (matches cleanup job AGE_IN_DAYS).'
)
@click.option(
    '--deletion_warning_days',
    type=int,
    default=None,
    help='Number of days before deletion to send warning notification (overrides config file value).'
)
@click.option(
    '--enable_check_expiring_files',
    type=click.BOOL,
    default=False,
    help=(
        'Enable expiring file checks and deletion warning notifications for GDPR partner reports. '
        'If set to true, the script will identify files nearing deletion and notify partners. '
    ),
    show_default=True,
)
@click.option(
    '--enable_overdue_file_notification',
    type=click.BOOL,
    default=False,
    help=(
        'If enabled, send a notification comment to partners for files that are already past their '
        'retention period during the expiring files check.'
    ),
    show_default=True,
)
def generate_report(config_file, google_secrets_file, output_dir, comments, age_in_days, deletion_warning_days, enable_check_expiring_files, enable_overdue_file_notification):
    """
    Retrieves a JWT token as the retirement service learner, then performs the reporting process as that user.

    - Accepts the configuration file with all necessary credentials and URLs for a single environment
    - Gets the users in the LMS reporting queue and the partners they need to be reported to
    - Generates a single report per partner
    - Pushes the reports to Google Drive
    - Checks for old files and sends deletion warnings if configured
    - On success tells LMS to remove the users who succeeded from the reporting queue
    """
    LOG('Starting partner report using config file {} and Google config {}'.format(config_file, google_secrets_file))

    try:
        if not config_file:
            FAIL(ERR_NO_CONFIG, 'No config file passed in.')

        if not google_secrets_file:
            FAIL(ERR_NO_SECRETS, 'No secrets file passed in.')

        # The Jenkins DSL is supposed to create this path for us
        if not output_dir or not os.path.exists(output_dir):
            FAIL(ERR_NO_OUTPUT_DIR, 'No output_dir passed in or path does not exist.')

        config = CONFIG_WITH_DRIVE_OR_EXIT(config_file, google_secrets_file)
        
        # Override retention/warning days from CLI if provided
        if age_in_days is not None:
            config['age_in_days'] = age_in_days
        if deletion_warning_days is not None:
            config['deletion_warning_days'] = deletion_warning_days
        
        SETUP_LMS_OR_EXIT(config)
        _config_drive_folder_map_or_exit(config)
        
        # Check for expiring files and send warnings if enabled
        if enable_check_expiring_files:
            _check_and_notify_about_expiring_files(config, enable_overdue_file_notification=enable_overdue_file_notification)
        
        report_data, all_usernames = _get_orgs_and_learners_or_exit(config)
        # If no usernames were returned, then no reports need to be generated.
        if all_usernames:
            partner_filenames = _generate_report_files_or_exit(config, report_data, output_dir)

            # All files generated successfully, now push them to Google
            report_file_ids = _push_files_to_google(config, partner_filenames)

            if comments:
                # All files uploaded successfully, now add comments to them to trigger notifications
                _add_comments_to_files(config, report_file_ids)

            # Success, tell LMS to remove these users from the queue
            config['LMS'].retirement_partner_cleanup(all_usernames)
            LOG('All reports completed and uploaded to Google.')
    except Exception as exc:  # pylint: disable=broad-except
        FAIL_EXCEPTION(ERR_CLEANUP, 'Unexpected error occurred! Users may be stuck in the processing state!', exc)


if __name__ == '__main__':
    # pylint: disable=unexpected-keyword-arg, no-value-for-parameter
    generate_report(auto_envvar_prefix='RETIREMENT')
