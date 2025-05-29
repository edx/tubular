# tubular

(Note: This is the 2U fork of <https://github.com/openedx/tubular>, which has been deprecated from Open edX.)

## Overview
Python scripts for integrating pipelines with various services/tools such as:
* Asgard
* Amazon Web Services EC2
* GitHub
* Jenkins
* Drupal

The scripts perform work to enable continuous delivery (CD) for https://edx.org. These scripts are called from various tasks/jobs/stages in GoCD pipelines - but could be called from any automation/CD framework.

## Retirement scripts in this repository versus edx-platform

### Repository Migration

On 26 February, 2024, having the following user retirement scripts in `tubular`
was [deprecated](https://github.com/openedx/axim-engineering/issues/881) and
migrated [to scripts/user_retirement](https://github.com/openedx/edx-platform/tree/master/scripts/user_retirement)
in the `edx-platform` repository.

The migration process was completed through [PR #34063](https://github.com/openedx/edx-platform/pull/34063).

- `tubular/scripts/get_learners_to_retire.py`
- `tubular/scripts/replace_usernames.py`
- `tubular/scripts/retire_one_learner.py`
- `tubular/scripts/retirement_archive_and_cleanup.py`
- `tubular/scripts/retirement_bulk_status_update.py`
- `tubular/scripts/retirement_partner_report.py`
- `tubular/scripts/structures.py`

### 2U Fork

After being deprecated for Open edX, this repo was forked into the `edx` GitHub org and is maintained by (and for) 2U. Initially, on 13 March, 2024 2U switched from `tubular` to `edx-platform` versions of the retirement scripts, but in May 2025, 2U  temporarily switched back to running user from this repository, in order to most efficiently solve the problem of divergent third-party retirement streams.

## Configuration
```
pip install -e .[dev]
```

## Testing
```
# Once, to install python versions:
cat .python-version | xargs -n1 pyenv install

# Run the tests
tox
```

## License

The code in this repository is licensed under the AGPL 3.0 unless
otherwise noted.

Please see ``LICENSE.txt`` for details.


## Reporting Security Issues

Please do not report security issues in public. Please email security@edx.org.

## Environment variables

|     Variable Name    | Default                         | Description                                                                                   |
|:--------------------:|---------------------------------|-----------------------------------------------------------------------------------------------|
| ASGARD_API_ENDPOINTS | http://dummy.url:8091/us-east-1 | Fully qualified URL for the Asgard instance against which to run the scripts.                 |
| ASGARD_API_TOKEN     | dummy-token                     | String - The Asgard token.                                                                    |
| ASGARD_WAIT_TIMEOUT  | 600                             | Integer - Time in seconds to wait for an action such as instances healthy in a load balancer. |
| REQUESTS_TIMEOUT     | 10                              | How long to wait for an HTTP connection/response from Asgard.                                 |
| RETRY_MAX_ATTEMPTS   | 5                               | Integer - Maximum number of attempts to be made when Asgard returns an error.                 |
| RETRY_SAILTHRU_MAX_ATTEMPTS | 5                        | Integer - Maximum number of attempts to be made when Sailthru returns an error.               |
| RETRY_DELAY_SECONDS  | 5                               | Time in seconds to wait between retries to Asgard.                                            |
| RETRY_MAX_TIME_SECONDS | None                          | Time in seconds to keep retrying Asgard before giving up.                                     |
| RETRY_FACTOR         | 1.5                             | Factor by which to multiply the base wait time per retry attempt for EC2 boto calls.          |
| ASGARD_ELB_HEALTH_TIMEOUT | 600                        | Time in seconds to wait for an EC2 instance to become healthy in an ELB.                      |
| SHA_LENGTH           | 10                              | Length of the commit SHA to use when querying for a PR by commit.                             |
| BATCH_SIZE           | 18                              | Number of commits to batch together when querying a PR by commit.                             |

## Guidelines

Some general guidelines for tubular scripts:

* Prefer --my-argument to --my_argument
* Install your scripts by adding them to the console_scripts list in setup.cfg
