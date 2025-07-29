# Multi-Site Frontend Datadog Integration Enhancement

## Overview

This enhancement to the `frontend_multi_build.py` script addresses **COSMO2-75** by enabling proper Datadog Real User Monitoring (RUM) integration for multi-site micro-frontend applications like `frontend-app-learner-portal-programs`.

## Problem Statement

The original multi-site build process had several issues preventing proper Datadog integration:

1. **Private Package Installation**: The `@edx/frontend-logging` package wasn't being installed for each site build
2. **JavaScript Configuration**: The `env.config.js` file containing Datadog logging service configuration wasn't being copied to build directories
3. **Site-Specific Tracking**: No mechanism to differentiate between sites in Datadog monitoring
4. **Build Validation**: No validation that required packages and configurations were properly set up

## Solution

### Enhanced `frontend_multi_build.py`

The script now includes:

1. **Per-Site Private Package Installation**: Ensures `@edx/frontend-logging` is available for each site build
2. **JavaScript Config File Handling**: Copies `env.config.js` to each site's build directory
3. **Site-Specific Datadog Configuration**: Automatically creates site-specific Datadog service names
4. **Build Validation**: Validates that required packages and configurations are present
5. **Enhanced Logging**: Provides detailed logging for debugging and monitoring

### Enhanced `frontend_utils.py`

New methods added to the `FrontendBuilder` class:

- `ensure_datadog_config_for_site()`: Validates and enhances Datadog configuration per site
- `validate_js_config_and_logging()`: Validates that logging packages and config files are properly set up
- Enhanced `copy_js_config_file_to_app_root()`: Improved error handling and logging
- Enhanced `install_requirements_npm_private()`: Better logging for debugging

## Configuration Requirements

### YAML Configuration File

Your environment configuration (e.g., `prod_config.yml`) must include:

```yaml
APP_CONFIG:
  # Required Datadog RUM Configuration
  DATADOG_APPLICATION_ID: "your-datadog-application-id"
  DATADOG_CLIENT_TOKEN: "your-datadog-client-token"
  DATADOG_SITE: "datadoghq.com"
  DATADOG_SERVICE: "your-frontend-app-name"
  DATADOG_ENV: "prod"
  DATADOG_SESSION_SAMPLE_RATE: 20
  DATADOG_SESSION_REPLAY_SAMPLE_RATE: 0
  DATADOG_LOGS_SESSION_SAMPLE_RATE: 100
  
  # JavaScript configuration file
  JS_CONFIG_FILEPATH: "/path/to/your/env.config.js"

# Required private packages
NPM_PRIVATE:
  - "@edx/frontend-logging@^4.0.2"

# Multi-site configuration
MULTISITE:
  - HOSTNAME: "site1"
    APP_CONFIG:
      IDP_SLUG: "saml-site1"
  - HOSTNAME: "site2"
    APP_CONFIG:
      IDP_SLUG: "saml-site2"
```

### JavaScript Configuration File

Your `env.config.js` file should configure the Datadog logging service:

```javascript
import { DatadogLoggingService } from '@edx/frontend-logging';

const config = {
  loggingService: DatadogLoggingService,
};

export default config;
```

## Key Features

### 1. Site-Specific Datadog Service Names

The script automatically appends the hostname to the Datadog service name:
- Original service: `edx-frontend-app-learner-portal-programs`
- Site-specific services: 
  - `edx-frontend-app-learner-portal-programs-gatech`
  - `edx-frontend-app-learner-portal-programs-asu`
  - etc.

This allows for site-specific monitoring and alerting in Datadog.

### 2. Private Package Management

The script ensures that private packages like `@edx/frontend-logging` are:
- Installed before each site build
- Available in the correct scope for the build process
- Properly validated after installation

### 3. JavaScript Configuration Handling

The script:
- Copies the JavaScript config file to each site's build directory
- Validates that the file exists and is accessible
- Provides clear error messages if configuration is missing

### 4. Build Validation

The script validates:
- Required Datadog environment variables are present
- Private packages are properly installed
- JavaScript configuration files are accessible
- Build artifacts are properly organized

## Logging and Debugging

The enhanced script provides comprehensive logging:

```
Building 9 sites for multi-site application frontend-app-learner-portal-programs
Building site: gatech for app frontend-app-learner-portal-programs
Datadog RUM configuration validated for site 'gatech'
Updated Datadog service name to 'edx-frontend-app-learner-portal-programs-gatech' for site 'gatech'
Successfully copied JS config file from '/path/to/env.config.js' to 'frontend-app-learner-portal-programs/env.config.js'
Installing private NPM packages: @edx/frontend-logging@^4.0.2
Successfully installed private NPM packages for app frontend-app-learner-portal-programs
JavaScript config file found at frontend-app-learner-portal-programs/env.config.js
@edx/frontend-logging package is properly installed
Moving build output for site gatech
...
Successfully completed multi-site build for frontend-app-learner-portal-programs with 9 sites
Sites built: ['gatech', 'asu', 'purdue', 'utexas', 'iu', 'uq', 'uwm', 'e2d7', 'list']
```

## Migration from Existing Setup

### For frontend-app-learner-portal-programs

The existing configuration in `prod_config.yml` and `stage_config.yml` already includes all necessary Datadog configuration. The enhanced script will automatically:

1. Use the existing Datadog configuration
2. Create site-specific service names
3. Install the required `@edx/frontend-logging` package for each site
4. Copy the existing `env.config.js` file to each build

### For Other Multi-Site Applications

1. Add Datadog configuration to your environment config files
2. Add `@edx/frontend-logging` to your `NPM_PRIVATE` packages
3. Create an `env.config.js` file with Datadog logging service configuration
4. Update your application code to use the logging service

## Addressing COSMO2-75 Issues

### CORS Errors
- **Solution**: The enhanced script ensures proper package installation and configuration, reducing CORS-related issues
- **Validation**: The script validates that all required packages are present

### Session Sampling Inconsistencies  
- **Solution**: Site-specific Datadog configuration allows for consistent sampling per site
- **Configuration**: `DATADOG_SESSION_SAMPLE_RATE` can be configured per site if needed

### Noisy Monitors
- **Solution**: Site-specific service names enable targeted monitoring and alerting
- **Benefit**: Separate Datadog dashboards and alerts per site reduce noise

### Private Package Management
- **Solution**: Enhanced private package installation ensures `@edx/frontend-logging` is available for each build
- **Validation**: Build validation confirms packages are properly installed

## Testing and Validation

To test the enhanced functionality:

1. **Local Testing**: Run the build script with verbose logging enabled
2. **Staging Validation**: Deploy to staging and verify Datadog metrics are being received
3. **Site-Specific Validation**: Check that each site appears as a separate service in Datadog
4. **Error Handling**: Verify proper error messages when configuration is missing

## Backwards Compatibility

The enhancements are fully backwards compatible:
- Existing configurations continue to work without changes
- New functionality is only enabled when proper configuration is present
- Legacy builds without Datadog configuration continue to work normally

## Future Considerations

1. **Performance Monitoring**: Consider adding performance monitoring configuration
2. **Error Tracking**: Expand error tracking capabilities for better debugging
3. **A/B Testing Integration**: Support for experiment tracking in Datadog
4. **Security**: Ensure sensitive Datadog tokens are properly managed in CI/CD

## Files Modified

- `frontend_multi_build.py`: Enhanced multi-site build orchestration
- `frontend_utils.py`: Added Datadog configuration and validation methods
- `multisite_datadog_config_example.yml`: Example configuration file

## Support

For issues related to this enhancement:
1. Check the build logs for validation messages
2. Verify Datadog configuration is complete
3. Ensure private packages are accessible in your environment
4. Review the example configuration for proper setup
