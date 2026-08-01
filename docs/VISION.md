# Project Vision Document

# Flagpost — Modern Open Source CTF Competition Platform

> **This is the founding document — intent, not status.** It's kept close to as
> written so the original reasoning stays legible, and it is deliberately *not*
> updated as features ship. For what Flagpost does today read
> [`../README.md`](../README.md); for how it's built,
> [`ARCHITECTURE.md`](ARCHITECTURE.md); for what's next,
> [`ROADMAP.md`](ROADMAP.md). Where this document and `ARCHITECTURE.md`
> disagree, `ARCHITECTURE.md` wins — it's the binding one, and §11.3 explicitly
> reconciles the two on the plugin/core split.

## Overview

This project aims to build a modern, open-source competition management platform focused initially on Capture The Flag (CTF) competitions.

The goal is not to simply recreate existing CTF platforms, but to build a next-generation competition operations platform that addresses the pain points experienced by organisers, judges, competitors, and educators.

The platform should provide a complete ecosystem for designing, running, managing, analysing, and improving technical competitions.

---

# Core Principles

## 1. Open Source First

The project will be developed as an open-source platform.

Goals:

* Community-driven development
* Transparent roadmap
* Public documentation
* Community contributions
* Extensible architecture
* Self-hosting as the primary deployment model

Commercial offerings may be considered in the future, but the initial focus is building an excellent open-source product.

---

## 2. Event-Driven Architecture

Everything within the platform should be modelled around events.

Events are the foundation of the system.

Examples:

* User registered
* Team created
* Challenge created
* Challenge solved
* Hint requested
* Support ticket created
* Competition started
* Competition ended
* Feedback submitted
* Announcement published

These events should power:

* Automations
* Notifications
* Analytics
* Integrations
* AI functionality
* Audit history

The platform should not just store data; it should understand what is happening.

---

## 3. Extensible by Design

The platform should support modular functionality.

Features should be implemented through:

* Core modules
* Plugins
* External integrations
* APIs

The goal is to create an ecosystem rather than a closed application.

---

## 4. Excellent User Experience

The platform should prioritise usability.

For competitors:

* Fast interface
* Clear challenge navigation
* Real-time updates
* Team collaboration
* Easy access to support

For organisers:

* Simple competition management
* Powerful administration tools
* Useful analytics
* Reduced reliance on external tools

---

# Initial Scope

The initial release focuses exclusively on CTF competitions.

Out of scope initially:

* Challenge hosting infrastructure
* Container management
* Remote service provisioning

The platform manages competitions, not challenge infrastructure.

---

# Core Features

## Competition Management

* Create competitions
* Manage users
* Manage teams
* Challenge management
* Scoring
* Hints
* Files
* Categories
* Scheduling
* Announcements

---

# Organiser Features

## Support System

Replace external tools such as Discord channels or ticket systems.

Features:

* Competitor support tickets
* Judge responses
* Internal notes
* Ticket assignment
* Challenge linking
* Support analytics

Metrics:

* Response times
* Common issues
* Problematic challenges

---

## Feedback System

Built-in post-competition feedback.

Features:

* Custom surveys
* Multiple question types
* Anonymous feedback
* Challenge ratings
* Exportable results

---

## Judge Dashboard

A central operational view.

Includes:

* Competition status
* Active competitors
* Recent solves
* Support queue
* Challenge health
* System notifications

---

## Challenge Lifecycle Management

A challenge should exist beyond just a title, description, and flag.

Challenge information:

* Author
* Difficulty
* Category
* Intended solve path
* Internal notes
* Review status
* Version history
* Writeup
* Testing information

Workflow:

Draft → Review → Testing → Approved → Published

---

## Challenge Analytics

Provide insights after competitions.

Examples:

* Completion rate
* Average solve time
* Hint usage
* Support requests
* Difficulty rating
* Student feedback

---

# Automation System

A major differentiator.

The platform should include a flexible automation engine.

Model:

Trigger → Conditions → Actions

Example:

```
Trigger:
Challenge solved

Conditions:
First solve

Actions:
- Announce first blood
- Award achievement
- Notify judges
```

Potential triggers:

* Competition events
* Challenge events
* User events
* Team events
* Support events
* Feedback events

Potential actions:

* Send notification
* Release hint
* Unlock challenge
* Create task
* Update score
* Call webhook
* Send email

---

# AI Integration

AI should provide practical value.

## Administrator AI Assistant

Potential uses:

* Query competition statistics
* Analyse support tickets
* Summarise feedback
* Answer platform documentation questions
* Identify problematic challenges

Examples:

"What challenges caused the most problems?"

"Which teams are struggling?"

"Summarise competitor feedback."

---

## Competitor AI Assistant

Potentially provide:

* Platform help
* Rules clarification
* General cybersecurity explanations

Challenge assistance should be controlled by competition organisers.

The system should avoid becoming a challenge solver. Strict guardrails should be in place.

---

# Plugin Ecosystem

Inspired by platforms such as Obsidian.

## Core Plugins

Functionality shipped with the platform but optionally enabled.

Examples:

* Authentication providers
* SSO
* Notifications
* Integrations
* Collaboration tools

---

## Community Plugins

Potential extensions:

* Analytics
* Integrations
* Automation actions
* External services

---

## Plugin Marketplace

Future capability:

* Plugin discovery
* Version management
* Ratings
* Publisher verification
* Documentation

Security approach:

* Automated scanning
* Dependency checks
* Verified publishers
* Transparent reputation

---

# Future Expansion

The architecture should allow future support for:

* Programming competitions
* Secure coding competitions
* AI competitions
* Other technical competitions

The initial implementation remains focused on CTFs.

---

# Suggested Technology Stack

## Frontend

* Next.js 14
* React 18
* TypeScript
* Tailwind CSS

Collaboration:

* Tiptap
* Y.js

---

## Backend

* Python
* FastAPI
* SQLAlchemy 2.0
* Alembic

---

## Data

* PostgreSQL
* Redis
* MinIO (S3 compatible storage)

---

## Deployment

Primary:

* Docker
* Docker Compose

Future:

* Kubernetes
* Helm

The default deployment experience should remain simple.

---

# Website

The project website should include:

* Landing page
* Detailed Documentation
* API reference
* Development guides
* Live demo
* Plugin marketplace
* Blog
* Showcase of deployments

---

# Development Documentation

Required documents:

```
/docs

VISION.md
ARCHITECTURE.md
ROADMAP.md
PLUGIN_SYSTEM.md
API_DESIGN.md
SECURITY.md

/docs/adr
    Architecture Decision Records
```

*What actually happened:* `PLUGIN_SYSTEM.md` and `API_DESIGN.md` were never
written as separate files — the module system became `ARCHITECTURE.md` §11 and
the API conventions §6/§7/§8, on the grounds that splitting them out would mean
two places to keep in sync for no reader benefit. `SECURITY.md` lives at the
repository root (where GitHub looks for it), and `PRIVACY.md` joined it.

These documents provide context for:

* Human contributors
* AI development assistants
* Future maintainers

---

# Long-Term Goal

Create the operating system for technical competitions.

Move beyond:

"A website where competitors submit flags"

towards:

"A complete platform for creating, operating, analysing, and improving technical competitions."
