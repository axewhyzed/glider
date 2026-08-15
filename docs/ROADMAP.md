# Glider product direction and roadmap

Status: proposed direction after v3.3.1.

This document describes the direction for Glider after the core engineering
and hardening phase. It is a product strategy and prioritization guide, not a
promise that every item will ship exactly as written.

## Product thesis

Glider should become:

> A developer-controlled, deterministic execution engine for declarative and
> AI-assisted scrapers.

Glider should help technical users maintain many small-to-medium recurring
scrapers without turning every scraper into a bespoke Python application.

The ideal workflow is:

```text
configuration
    ↓
validation
    ↓
preview
    ↓
contract test
    ↓
scrape
    ↓
checkpoint / resume
    ↓
structured export
```

The configuration remains the durable artifact. The execution engine remains
controlled, observable, resumable, and safe.

## Target users

The primary users are:

- freelancers and small scraping agencies maintaining multiple client jobs;
- developers who repeatedly need small-to-medium scrapers;
- internal data teams maintaining recurring competitor, catalog, jobs, news,
  or research extraction;
- AI/data engineers who need controlled ingestion jobs without writing a new
  crawler project for every source.

These users are technical enough to understand selectors, APIs, credentials,
and deployment, but do not want every new source to require custom crawler
infrastructure.

## Positioning

Glider should not try to be:

- a point-and-click no-code tool competing with visual scraping products;
- a fully programmable replacement for Scrapy;
- a massive distributed crawling platform competing with Crawlee or hosted
  scraping platforms;
- a marketplace of thousands of hosted scrapers;
- an LLM that executes arbitrary generated code.

The useful distinction is developer-oriented declarative scraping:

```text
less code than a custom spider
+
more control than a browser extension
+
more operational discipline than a one-off script
```

For ecosystem context, see the official [Scrapy documentation], [Crawlee
documentation], and [Apify Actors documentation]. These projects are strong
at programmable crawling, crawler infrastructure, and hosted structured
execution respectively; Glider should differentiate through its configuration
contract, controlled runtime, and local ownership model.

[Scrapy documentation]: https://docs.scrapy.org/en/latest/
[Crawlee documentation]: https://crawlee.dev/
[Apify Actors documentation]: https://docs.apify.com/actors

## Principles

### 1. Keep execution deterministic

The runtime should execute a validated specification predictably. It should
not silently invent selectors, change extraction semantics, or execute
arbitrary code.

### 2. Treat configuration as a public API

Configuration files are the product's portable artifacts. They should be
versioned, schema-documented, testable, reviewable, and migratable.

### 3. Make AI an authoring client, not a trusted runtime

An LLM may propose a configuration, explain a validation failure, or suggest a
repair. Glider must still validate the result, apply URL and credential policy,
show a preview, and require an explicit execution boundary.

### 4. Optimize for the fifth scraper

The important usability test is not whether a user can scrape one page once.
It is whether a developer can create and maintain the fifth recurring scraper
without multiplying operational complexity.

### 5. Prefer capability over defensive complexity

Security and reliability remain release requirements, but future effort should
prioritize high-value extraction, authentication, debugging, integrations, and
developer ergonomics over another broad hardening cycle.

## Core product bets

### Versioned scraper specifications

Add an explicit `spec_version` and publish the generated JSON Schema. Provide:

- stable field and policy semantics;
- machine-readable diagnostics with JSON paths and remediation hints;
- compatibility rules between specification versions;
- migration tooling for older configurations;
- configuration composition and environment-specific overlays.

### Scraper contracts

Let users pair a configuration with deterministic fixtures and expected output:

```text
fixture HTML or JSON
    ↓
validated configuration
    ↓
expected structured output
    ↓
extraction test
```

When a target changes, the user should see which field drifted, which selector
was involved, and what the old and new values were. This is more useful than
discovering a broken selector only after a scheduled run silently produces
empty data.

### AI-assisted configuration authoring

The intended flow is:

```text
user request
    ↓
AI-generated Glider configuration
    ↓
schema validation
    ↓
security and policy validation
    ↓
preview and contract test
    ↓
human approval
    ↓
execution
```

The first AI integration should be provider-neutral. Glider should expose
schemas, examples, diagnostics, and a predictable validation loop rather than
requiring one hosted model or embedding an untrusted model call in the engine.

## Roadmap

### v4.0 — Declarative scraper platform

Focus: make the existing engine easy to author, test, and maintain.

- Add `spec_version` to the configuration contract.
- Generate and publish JSON Schema for configuration tooling.
- Add `glider init` for creating a project and starter configuration.
- Improve `validate --strict` with field-level diagnostics and suggestions.
- Add fixture-backed scraper contract tests.
- Add extraction preview and selector inspection workflows.
- Add configuration diff and normalized-output comparison.
- Expand examples around HTML, APIs, browser interactions, pagination, and
  authentication.
- Document a complete multi-scraper project layout.

### v4.1 — AI-assisted authoring

Focus: make Glider a safe target for AI-generated scraper specifications.

- Publish machine-readable schemas and capability metadata.
- Define a provider-neutral config-generation and repair protocol.
- Add a preview-before-execute workflow for generated configurations.
- Return structured validation errors suitable for an AI repair loop.
- Add explicit human approval gates before network execution.
- Add evaluation fixtures for generated configurations.
- Never permit generated configuration to bypass URL, credential, browser, or
  output policies.

### v4.2 — Production workflows

Focus: reduce the cost of operating many recurring scrapers.

- Add reusable authentication and session profiles.
- Support more pagination patterns: cursor APIs, page numbers, load-more
  controls, and bounded infinite scroll.
- Improve browser workflows for login, multi-step interaction, downloads, and
  session reuse.
- Add practical sinks such as S3-compatible storage, Postgres, and webhooks.
- Add run comparison, extraction-drift reports, and schema-change alerts.
- Add scheduling and notification adapters without requiring a hosted Glider
  control plane.

### Later, only after adoption evidence

Consider the following only after real users demonstrate the need:

- hosted execution and team management;
- distributed crawling;
- a public configuration/template marketplace;
- managed proxy infrastructure;
- billing and usage metering.

These are substantial products in their own right and should not distract from
proving the developer-oriented declarative wedge.

## Capability priorities

When choosing between feature requests, prioritize work that improves several
recurring scraper workflows:

1. authentication and session reuse;
2. flexible pagination and browser interactions;
3. extraction primitives for tables, attributes, embedded JSON, and repeated
   records;
4. selector inspection and response debugging;
5. fixture-backed contracts and drift detection;
6. durable output integrations;
7. scheduling and notifications.

Avoid adding a feature solely because it makes a single demo more impressive.
Prefer features that reduce configuration authoring time, repair time, or
failed-run recovery time across multiple sites.

## Validation strategy

Before calling a roadmap phase successful, validate it with real workflows and
deterministic fixtures.

### User validation

Work with a small set of freelancers, agencies, or internal data teams that
maintain multiple recurring scrapers. Measure:

- time from a blank project to a validated first run;
- time to create a second and fifth scraper;
- time to diagnose and repair selector drift;
- percentage of interrupted runs successfully resumed;
- number of recurring jobs kept on Glider after the trial.

### Engineering validation

Every new capability should include:

- deterministic local fixtures;
- configuration validation coverage;
- browser coverage where applicable;
- failure and cancellation behavior;
- documentation and a copyable example;
- a code review focused on compatibility and security boundaries.

### Product success signal

The strongest early signal is repeated use, not raw scrape volume:

> Can a technical user operate five recurring scrapers with less custom code
> and less maintenance than their previous approach?

## Current foundation

As of v3.3.1, Glider already provides the foundation for this direction:

- configuration-driven HTTP and browser execution;
- URL, credential, proxy, and browser security controls;
- checkpointing, cancellation-safe streaming, and resumable runs;
- deterministic local integration fixtures and benchmark scenarios;
- examples, validation, preview, scrape, and release documentation.

The next phase should build product leverage on top of that foundation rather
than replacing the execution core.
