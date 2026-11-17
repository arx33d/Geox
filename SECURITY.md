# Security Policy

## Supported Versions

The following table lists the supported versions of Geox receiving security updates:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | Yes                |
| < 1.0   | No                 |

## Reporting a Vulnerability

The Geox team takes security and privacy seriously. If you discover a vulnerability or security flaw in Geox, please report it responsibly.

### How to Report

1. **Do not report security issues via public GitHub issues.**
2. Send an email with full details to `arx33dbu@gmail.com` (or submit a private security report through GitHub Security Advisories at https://github.com/arx33dbu/geox-BU/security/advisories/new).
3. Include the following information:
   - Type of issue (e.g. buffer overflow, credential exposure, privilege escalation)
   - Step-by-step instructions or proof-of-concept to reproduce the behavior
   - Operating system and version of Geox tested
   - Connected phone platform (iOS or Android) if device-specific
   - Any proposed fix or remediation

### Response Timeline

- **Initial Acknowledgment**: Within 48 hours of receipt.
- **Triage and Assessment**: Within 5 business days.
- **Fix and Release**: Critical vulnerabilities will be addressed in a patch release within 14 days of confirmation.
- **Public Disclosure**: Coordinated disclosure after a fix has been tested and released.

## Security Practices in Geox

- **Local-Only Service**: By default, the Geox API and Web UI bind to `127.0.0.1` unless explicitly requested otherwise.
- **No Remote Telemetry**: Geox does not collect, transmit, or store user location coordinates, GPX files, or telemetry to external servers.
- **Isolated Device Communication**: Device interaction uses standard Apple Mobile Device / Android Debug Bridge protocols over USB or encrypted tunnels without exposing host credentials.
- **Dependency Auditing**: Dependencies are monitored continuously using GitHub Dependabot and CodeQL static analysis.
