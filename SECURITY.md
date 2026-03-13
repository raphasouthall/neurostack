# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Email: security@neurostack-project.dev

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

You should receive a response within 48 hours.

## Scope

NeuroStack runs locally and processes your private vault data. Security concerns include:
- Data leakage through cloud API calls (opt-in only)
- Prompt injection via vault content piped to LLMs
- Supply chain vulnerabilities in dependencies
