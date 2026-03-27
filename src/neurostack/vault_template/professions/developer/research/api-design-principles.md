---
date: 2025-01-15
tags: [api-design, architecture, interfaces]
type: permanent
status: active
actionable: true
compositional: true
---

# API Design Principles

A well-designed API is easy to use correctly and hard to use incorrectly (Bloch, 2006). These principles apply to REST APIs, library interfaces, CLI tools, and internal module boundaries.

## Core Principles

### 1. Principle of Least Surprise

Names, parameters, and return types should behave as a caller would expect without reading documentation. If a function name is misleading, it will be misused — regardless of how clear the docs are.

### 2. Make Invalid States Unrepresentable

Use types to enforce constraints at compile time rather than runtime validation:

- Prefer enums over stringly-typed parameters
- Use newtypes to distinguish semantically different values (UserId vs. OrderId)
- Design signatures so callers cannot construct illegal input

### 3. Minimal Surface Area

Expose the smallest API that solves the problem. Every public symbol is a commitment:

- **YAGNI applies to APIs** — don't add endpoints "in case someone needs them"
- Internal helpers should stay internal
- Prefer composition over configuration flags

### 4. Consistent Naming and Conventions

| Concern | Convention |
|---------|-----------|
| Resource naming | Plural nouns: `/users`, `/orders` |
| Actions on resources | HTTP verbs (REST) or explicit verbs (RPC): `cancelOrder` |
| Filtering/sorting | Query parameters: `?status=active&sort=-created` |
| Pagination | Cursor-based over offset-based for large datasets |
| Error format | Consistent structure: `{error: {code, message, details}}` |

### 5. Versioning Strategy

- **URL path versioning** (`/v1/users`) — simple, explicit, easy to route
- **Header versioning** (`Accept: application/vnd.api+json;version=2`) — cleaner URLs, harder to test
- **Never break existing clients** — add fields, don't remove them. Deprecate with timelines.

## Error Handling

- Return appropriate HTTP status codes (don't 200-wrap errors)
- Include machine-readable error codes alongside human-readable messages
- Provide enough context to debug without exposing internals
- Distinguish client errors (4xx) from server errors (5xx) — they have different remediation paths

## Design Process

1. Write the **client code first** — what does the ideal caller experience look like?
2. Define the **contract** (OpenAPI, protobuf, GraphQL schema) before implementing
3. Review the API with consumers, not just implementers
4. Treat breaking changes as [[technical-debt-management|technical debt]] — they compound

## Related Notes

- [[twelve-factor-app]] — API-first as a modern extension of the twelve factors
- [[testing-pyramid]] — contract tests sit at the integration layer
- [[code-review-best-practices]] — API surface changes deserve extra scrutiny
- [[refactoring-patterns]] — the Strangler Fig pattern enables API evolution
