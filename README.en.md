# CertKeeper

CertKeeper is an open-source certificate lifecycle management tool focused on automating certificate issuance, renewal, deployment, and notification workflows for SSL/TLS operations.

This repository is currently in the "design completed, first implementation in progress" stage. The content below describes the intended product and phase-one scope, not a claim that every feature is already production-ready.

中文版: [README.md](./README.md)

## Goals

- Automate certificate issuance and renewal through ACME-compatible providers
- Manage multiple domains and SAN certificates in one place
- Deploy renewed certificates to nginx servers and cloud CDNs
- Send notifications for success, failure, and upcoming expiration events
- Support both CLI-driven execution and long-running daemon mode

## Phase One Scope

The first implementation phase is planned as a Python CLI application with:

- CLI entry points: `init`, `register`, `apply`, `renew`, `deploy`, `list`, `check`, `daemon`
- YAML-based configuration loading with environment variable expansion
- Local certificate and state storage
- ACME account registration and certificate request orchestration
- `http-01` and `dns-01` challenge abstractions
- Initial providers:
  - DNS: Alibaba Cloud DNS
  - Deployment: nginx over SSH, Tencent Cloud CDN, Alibaba Cloud CDN
  - Notification: SMTP email
- Daemon scheduling and basic logging

## Planned Architecture

The project follows a layered structure:

```text
CLI -> Core Engine -> Providers -> Storage
```

Key modules:

- `cli`: command entry points and exit code handling
- `config`: YAML loading, environment expansion, reference validation
- `core`: orchestration, scheduling, and state management
- `acme_client`: ACME account and certificate request wrappers
- `challenges`: `http-01` / `dns-01` challenge handlers
- `dns`, `deployers`, `notifications`: pluggable provider implementations

## Configuration Model

The planned configuration format is a single YAML file that defines ACME settings, scheduler options, notification channels, DNS providers, deploy targets, and certificate tasks. Example:

```yaml
acme:
  directory: https://acme-v02.api.letsencrypt.org/directory
  email: admin@example.com

scheduler:
  enabled: true
  interval: daily
  time: "03:00"

certificates:
  - domain: example.com
    san: [www.example.com]
    challenge: dns-01
    dns_provider: aliyun
    deploy_to: [nginx-web]
```

Sensitive values are expected to be read from environment variables using `${ENV_VAR}` syntax instead of being committed into the config file.

## Planned Commands

The initial command surface is designed as:

```bash
certkeeper init
certkeeper register
certkeeper apply
certkeeper apply --force
certkeeper renew <domain>
certkeeper deploy <domain>
certkeeper list
certkeeper check
certkeeper daemon
certkeeper start
certkeeper start --daemon
certkeeper start --status
certkeeper start --stop
```

These commands will become available incrementally as implementation progresses.

## Development Status

- Current status: documentation and design spec exist, implementation bootstrap is underway
- Primary language: Python 3.11+
- Current focus: CLI scaffold, configuration system, storage layer, orchestration flow

## Roadmap

- Phase one: CLI, daemon mode, ACME workflow, initial providers, SMTP notifications
- Phase two: Web UI, more DNS providers, more deployment targets, more notification channels
- Later: stronger observability, better configuration UX, and a broader plugin ecosystem

## Contributing

Issues, suggestions, and pull requests are welcome. Feedback is especially valuable around:

- certificate renewal and deployment workflows
- provider abstraction design
- service management on Windows and Linux
- documentation, tests, and example configurations

## Design Spec

For the detailed design document, see:

- `docs/superpowers/specs/2026-04-13-certkeeper-design.md`
