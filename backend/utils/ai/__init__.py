"""The AI module's provider plumbing (#98, ADR-0023).

A thin, testable seam over any OpenAI-compatible ``/chat/completions`` endpoint
(hosted or a local Ollama/vLLM). Nothing here is competition- or assistant-aware
— it's the transport the assistants build on in later phases. Kept out of the
import graph until an AI provider is actually configured, mirroring how the SAML
and LDAP transports lazily import their heavy dependencies.
"""
