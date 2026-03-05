# coding=utf-8
"""
Test the retire_one_learner.py script
"""


import os

from click.testing import CliRunner
from mock import patch

from tubular.scripts.delete_expired_partner_gdpr_reports import (
    ERR_NO_CONFIG,
    ERR_BAD_CONFIG,
    ERR_NO_SECRETS,
    ERR_BAD_SECRETS,
    ERR_DELETING_REPORTS,
    ERR_BAD_AGE,
    delete_expired_reports
)
from tubular.scripts.retirement_partner_report import REPORTING_FILENAME_PREFIX
from tubular.tests.retirement_helpers import TEST_PLATFORM_NAME, fake_config_file, fake_google_secrets_file

TEST_CONFIG_FILENAME = 'test_config.yml'
TEST_GOOGLE_SECRETS_FILENAME = 'test_google_secrets.json'


def _call_script(age_in_days=1, expect_success=True):
    """
    Call the report deletion script with a generic, temporary config file.
    Returns the CliRunner.invoke results
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open(TEST_CONFIG_FILENAME, 'w') as config_f:
            fake_config_file(config_f)
        with open(TEST_GOOGLE_SECRETS_FILENAME, 'w') as secrets_f:
            fake_google_secrets_file(secrets_f)

        result = runner.invoke(
            delete_expired_reports,
            args=[
                '--config_file',
                TEST_CONFIG_FILENAME,
                '--google_secrets_file',
                TEST_GOOGLE_SECRETS_FILENAME,
                '--age_in_days',
                age_in_days
            ]
        )

        print(result)
        print(result.output)

        if expect_success:
            assert result.exit_code == 0

    return result


@patch('tubular.google_api.DriveApi.__init__')
@patch('tubular.google_api.DriveApi.walk_files')
@patch('tubular.google_api.DriveApi.list_permissions_for_files')
@patch('tubular.google_api.DriveApi.create_comments_for_files')
@patch('tubular.google_api.DriveApi.delete_files')
def test_successful_report_deletion(*args):
    mock_delete_files = args[0]
    mock_create_comments = args[1]
    mock_list_permissions = args[2]
    mock_walk_files = args[3]
    mock_driveapi = args[4]

    test_created_date = '2018-07-13T22:21:45.600275+00:00'
    file_prefix = '{}_{}'.format(REPORTING_FILENAME_PREFIX, TEST_PLATFORM_NAME)

    # Mock partner folders, files, and deletion
    mock_walk_files.side_effect = [
        # Partner folder discovery
        [{'id': 'partner1_folder_id', 'name': 'Partner1'}],
        # Notification file listing
        [],
        # Deletion walks files
        [
            {
                'id': 'folder1',
                'name': '{}.csv'.format(file_prefix),
                'createdTime': test_created_date,
            },
            {
                'id': 'folder2',
                'name': '{}_foo.csv'.format(file_prefix),
                'createdTime': test_created_date,
            },
            {
                'id': 'folder3',
                'name': '{}___bar.csv'.format(file_prefix),
                'createdTime': test_created_date,
            },
        ],
        # Non-CSV reporting
        [],
    ]
    
    mock_list_permissions.return_value = {'partner1_folder_id': [{'emailAddress': 'test@example.com'}]}
    mock_create_comments.return_value = None
    mock_delete_files.return_value = None
    mock_driveapi.return_value = None

    result = _call_script()

    # Make sure the files were listed (4 times: partner discovery, notifications, deletion, non-CSV reporting)
    assert mock_walk_files.call_count == 4

    # Make sure we tried to delete the files
    assert mock_delete_files.call_count == 1

    assert 'Partner report deletion complete' in result.output


@patch('tubular.google_api.DriveApi.__init__')
@patch('tubular.google_api.DriveApi.walk_files')
@patch('tubular.google_api.DriveApi.list_permissions_for_files')
@patch('tubular.google_api.DriveApi.create_comments_for_files')
@patch('tubular.google_api.DriveApi.delete_files')
def test_deletion_report_no_matching_files(*args):
    mock_delete_files = args[0]
    mock_create_comments = args[1]
    mock_list_permissions = args[2]
    mock_walk_files = args[3]
    mock_driveapi = args[4]

    test_created_date = '2018-07-13T22:21:45.600275+00:00'
    
    # Mock partner folders, files, and deletion
    mock_walk_files.side_effect = [
        # Partner folder discovery
        [{'id': 'partner1_folder_id', 'name': 'Partner1'}],
        # Notification file listing
        [],
        # Deletion walks files (no matching files)
        [
            {
                'id': 'folder1',
                'name': 'not_this.csv',
                'createdTime': test_created_date,
            },
            {
                'id': 'folder2',
                'name': 'or_this.csv',
                'createdTime': test_created_date,
            },
            {
                'id': 'folder3',
                'name': 'foo.csv',
                'createdTime': test_created_date,
            },
        ],
        # Non-CSV reporting
        [],
    ]
    
    mock_list_permissions.return_value = {'partner1_folder_id': [{'emailAddress': 'test@example.com'}]}
    mock_create_comments.return_value = None
    mock_delete_files.return_value = None
    mock_driveapi.return_value = None

    result = _call_script()

    # Make sure the files were listed (4 times: partner discovery, notifications, deletion, non-CSV reporting)
    assert mock_walk_files.call_count == 4

    # Make sure we did *not* try to delete the files - nothing to delete.
    assert mock_delete_files.call_count == 0

    assert 'Partner report deletion complete' in result.output


def test_no_config():
    runner = CliRunner()
    result = runner.invoke(delete_expired_reports)
    print(result.output)
    assert result.exit_code == ERR_NO_CONFIG
    assert 'No config file' in result.output


def test_no_secrets():
    runner = CliRunner()
    result = runner.invoke(delete_expired_reports, args=['--config_file', 'does_not_exist.yml'])
    print(result.output)
    assert result.exit_code == ERR_NO_SECRETS
    assert 'No secrets file' in result.output


def test_bad_config():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open(TEST_CONFIG_FILENAME, 'w') as config_f:
            config_f.write(']this is bad yaml')

        with open(TEST_GOOGLE_SECRETS_FILENAME, 'w') as config_f:
            config_f.write('{this is bad json but we should not get to parsing it')

        result = runner.invoke(
            delete_expired_reports,
            args=[
                '--config_file',
                TEST_CONFIG_FILENAME,
                '--google_secrets_file',
                TEST_GOOGLE_SECRETS_FILENAME,
                '--age_in_days', 1
            ]
        )
        print(result.output)
        assert result.exit_code == ERR_BAD_CONFIG
        assert 'Failed to read' in result.output


def test_bad_secrets():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open(TEST_CONFIG_FILENAME, 'w') as config_f:
            fake_config_file(config_f)

        with open(TEST_GOOGLE_SECRETS_FILENAME, 'w') as config_f:
            config_f.write('{this is bad json')

        tmp_output_dir = 'test_output_dir'
        os.mkdir(tmp_output_dir)

        result = runner.invoke(
            delete_expired_reports,
            args=[
                '--config_file',
                TEST_CONFIG_FILENAME,
                '--google_secrets_file',
                TEST_GOOGLE_SECRETS_FILENAME,
                '--age_in_days', 1
            ]
        )
        print(result.output)
        assert result.exit_code == ERR_BAD_SECRETS
        assert 'Failed to read' in result.output


def test_bad_age_in_days():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open(TEST_CONFIG_FILENAME, 'w') as config_f:
            fake_config_file(config_f)

        with open(TEST_GOOGLE_SECRETS_FILENAME, 'w') as config_f:
            fake_google_secrets_file(config_f)

        result = runner.invoke(
            delete_expired_reports,
            args=[
                '--config_file',
                TEST_CONFIG_FILENAME,
                '--google_secrets_file',
                TEST_GOOGLE_SECRETS_FILENAME,
                '--age_in_days', -1000
            ]
        )
        print(result.output)
        assert result.exit_code == ERR_BAD_AGE
        assert 'must be a positive integer' in result.output


@patch('tubular.google_api.DriveApi.__init__')
@patch('tubular.google_api.DriveApi.walk_files')
@patch('tubular.google_api.DriveApi.list_permissions_for_files')
@patch('tubular.google_api.DriveApi.create_comments_for_files')
@patch('tubular.google_api.DriveApi.delete_files_older_than')
def test_deletion_error(*args):
    mock_delete_old_reports = args[0]
    mock_create_comments = args[1]
    mock_list_permissions = args[2]
    mock_walk_files = args[3]
    mock_drive_init = args[4]
    
    # Mock successful partner folder discovery
    mock_walk_files.return_value = [{'id': 'partner1_folder_id', 'name': 'Partner1'}]
    mock_list_permissions.return_value = {'partner1_folder_id': [{'emailAddress': 'test@example.com'}]}
    mock_create_comments.return_value = None

    mock_delete_old_reports.side_effect = Exception()
    mock_drive_init.return_value = None

    result = _call_script(expect_success=False)

    assert result.exit_code == ERR_DELETING_REPORTS
    assert 'Unexpected error occurred' in result.output


@patch('tubular.google_api.DriveApi.__init__')
@patch('tubular.google_api.DriveApi.walk_files')
@patch('tubular.google_api.DriveApi.list_permissions_for_files')
@patch('tubular.google_api.DriveApi.create_comments_for_files')
@patch('tubular.google_api.DriveApi.delete_files_older_than')
def test_notifications_sent_for_old_files(*args):
    """
    Test that deletion notifications are sent for files older than the cutoff.
    """
    mock_delete_old_reports = args[0]
    mock_create_comments = args[1]
    mock_list_permissions = args[2]
    mock_walk_files = args[3]
    mock_driveapi = args[4]

    file_prefix = '{}_{}'.format(REPORTING_FILENAME_PREFIX, TEST_PLATFORM_NAME)
    old_date = '2018-01-01T00:00:00.000000+00:00'
    
    # Mock partner folders discovery
    mock_walk_files.side_effect = [
        # First call: discover partner folders
        [
            {'id': 'partner1_folder_id', 'name': 'Partner1'},
            {'id': 'partner2_folder_id', 'name': 'Partner2'},
        ],
        # Second call: list files in Partner1 folder
        [
            {'id': 'file1', 'name': '{}_2018_01_01.csv'.format(file_prefix), 'createdTime': old_date},
            {'id': 'file2', 'name': '{}_2018_01_02.csv'.format(file_prefix), 'createdTime': old_date},
        ],
        # Third call: list files in Partner2 folder
        [
            {'id': 'file3', 'name': '{}_2018_01_03.csv'.format(file_prefix), 'createdTime': old_date},
        ],
        # Fourth call: delete_files_older_than walks files
        [],
        # Fifth call: delete checks for non-CSV files
        [],
    ]
    
    # Mock permissions for partners
    mock_list_permissions.return_value = {
        'partner1_folder_id': [
            {'emailAddress': 'partner1@example.com'},
            {'emailAddress': 'user@edx.org'},  # Should be filtered out
        ],
        'partner2_folder_id': [
            {'emailAddress': 'partner2@example.com'},
        ],
    }
    
    mock_create_comments.return_value = None
    mock_delete_old_reports.return_value = None
    mock_driveapi.return_value = None

    result = _call_script(age_in_days=365)

    # Verify notifications were sent (one batch per partner)
    assert mock_create_comments.call_count == 2
    
    # Verify the batched notification calls
    first_call_args = mock_create_comments.call_args_list[0][0][0]
    second_call_args = mock_create_comments.call_args_list[1][0][0]
    
    # Partner1 should have 2 files notified
    assert len(first_call_args) == 2
    assert first_call_args[0][0] == 'file1'
    assert first_call_args[1][0] == 'file2'
    assert 'partner1@example.com' in first_call_args[0][1]
    
    # Partner2 should have 1 file notified
    assert len(second_call_args) == 1
    assert second_call_args[0][0] == 'file3'
    assert 'partner2@example.com' in second_call_args[0][1]
    
    assert 'Partner report deletion complete' in result.output


@patch('tubular.google_api.DriveApi.__init__')
@patch('tubular.google_api.DriveApi.walk_files')
@patch('tubular.google_api.DriveApi.list_permissions_for_files')
@patch('tubular.google_api.DriveApi.create_comments_for_files')
@patch('tubular.google_api.DriveApi.delete_files_older_than')
def test_notifications_not_sent_for_recent_files(*args):
    """
    Test that notifications are NOT sent for files newer than the cutoff.
    """
    mock_delete_old_reports = args[0]
    mock_create_comments = args[1]
    mock_list_permissions = args[2]
    mock_walk_files = args[3]
    mock_driveapi = args[4]

    file_prefix = '{}_{}'.format(REPORTING_FILENAME_PREFIX, TEST_PLATFORM_NAME)
    recent_date = '2026-03-04T00:00:00.000000+00:00'  # Yesterday (test date is March 5, 2026)
    
    # Mock partner folders discovery
    mock_walk_files.side_effect = [
        [{'id': 'partner1_folder_id', 'name': 'Partner1'}],
        # Files are too recent
        [
            {'id': 'file1', 'name': '{}_2026_03_04.csv'.format(file_prefix), 'createdTime': recent_date},
        ],
        [],  # delete_files_older_than
        [],  # non-CSV check
    ]
    
    mock_list_permissions.return_value = {
        'partner1_folder_id': [{'emailAddress': 'partner1@example.com'}],
    }
    
    mock_create_comments.return_value = None
    mock_delete_old_reports.return_value = None
    mock_driveapi.return_value = None

    result = _call_script(age_in_days=30)  # Files older than 30 days

    # Verify NO notifications were sent (files are too recent)
    assert mock_create_comments.call_count == 0
    
    assert 'Partner report deletion complete' in result.output


@patch('tubular.google_api.DriveApi.__init__')
@patch('tubular.google_api.DriveApi.walk_files')
@patch('tubular.google_api.DriveApi.list_permissions_for_files')
@patch('tubular.google_api.DriveApi.create_comments_for_files')
@patch('tubular.google_api.DriveApi.delete_files_older_than')
def test_notifications_respect_prefix_matching(*args):
    """
    Test that only files matching the expected prefix get notifications.
    """
    mock_delete_old_reports = args[0]
    mock_create_comments = args[1]
    mock_list_permissions = args[2]
    mock_walk_files = args[3]
    mock_driveapi = args[4]

    file_prefix = '{}_{}'.format(REPORTING_FILENAME_PREFIX, TEST_PLATFORM_NAME)
    old_date = '2018-01-01T00:00:00.000000+00:00'
    
    mock_walk_files.side_effect = [
        [{'id': 'partner1_folder_id', 'name': 'Partner1'}],
        [
            {'id': 'file1', 'name': '{}_2018_01_01.csv'.format(file_prefix), 'createdTime': old_date},
            {'id': 'file2', 'name': 'wrong_prefix_2018_01_02.csv', 'createdTime': old_date},
            {'id': 'file3', 'name': 'other_file.csv', 'createdTime': old_date},
        ],
        [],
        [],
    ]
    
    mock_list_permissions.return_value = {
        'partner1_folder_id': [{'emailAddress': 'partner1@example.com'}],
    }
    
    mock_create_comments.return_value = None
    mock_delete_old_reports.return_value = None
    mock_driveapi.return_value = None

    result = _call_script(age_in_days=365)

    # Should only notify for the one file matching the prefix
    assert mock_create_comments.call_count == 1
    call_args = mock_create_comments.call_args_list[0][0][0]
    assert len(call_args) == 1
    assert call_args[0][0] == 'file1'
    
    assert 'Partner report deletion complete' in result.output


@patch('tubular.google_api.DriveApi.__init__')
@patch('tubular.google_api.DriveApi.walk_files')
@patch('tubular.google_api.DriveApi.list_permissions_for_files')
@patch('tubular.google_api.DriveApi.create_comments_for_files')
@patch('tubular.google_api.DriveApi.delete_files_older_than')
def test_notifications_skip_partners_without_poc(*args):
    """
    Test that notifications are skipped for partners without external POC.
    """
    mock_delete_old_reports = args[0]
    mock_create_comments = args[1]
    mock_list_permissions = args[2]
    mock_walk_files = args[3]
    mock_driveapi = args[4]

    file_prefix = '{}_{}'.format(REPORTING_FILENAME_PREFIX, TEST_PLATFORM_NAME)
    old_date = '2018-01-01T00:00:00.000000+00:00'
    
    mock_walk_files.side_effect = [
        [
            {'id': 'partner1_folder_id', 'name': 'Partner1'},
            {'id': 'partner2_folder_id', 'name': 'Partner2'},
        ],
        [{'id': 'file1', 'name': '{}_2018_01_01.csv'.format(file_prefix), 'createdTime': old_date}],
        [{'id': 'file2', 'name': '{}_2018_01_02.csv'.format(file_prefix), 'createdTime': old_date}],
        [],
        [],
    ]
    
    # Partner1 has external POC, Partner2 only has denied domains
    mock_list_permissions.return_value = {
        'partner1_folder_id': [{'emailAddress': 'partner1@example.com'}],
        'partner2_folder_id': [{'emailAddress': 'user@edx.org'}],  # Denied domain
    }
    
    mock_create_comments.return_value = None
    mock_delete_old_reports.return_value = None
    mock_driveapi.return_value = None

    result = _call_script(age_in_days=365)

    # Only Partner1 should get notifications
    assert mock_create_comments.call_count == 1
    call_args = mock_create_comments.call_args_list[0][0][0]
    assert call_args[0][0] == 'file1'
    
    assert 'WARNING: Partner "Partner2" has no POC for deletion notifications' in result.output
    assert 'Partner report deletion complete' in result.output


@patch('tubular.google_api.DriveApi.__init__')
@patch('tubular.google_api.DriveApi.walk_files')
def test_notifications_fail_if_no_partner_folders(*args):
    """
    Test that script fails if no partner folders are found.
    """
    mock_walk_files = args[0]
    mock_driveapi = args[1]

    # Mock empty partner folders
    mock_walk_files.return_value = []
    mock_driveapi.return_value = None

    from tubular.scripts.delete_expired_partner_gdpr_reports import ERR_DRIVE_LISTING
    
    result = _call_script(expect_success=False)

    assert result.exit_code == ERR_DRIVE_LISTING
    assert 'Finding partner directories on Drive failed' in result.output

