"""api/agent — Agentic conversation loop for FindMe v2.

The agent calls tools (search_products, etc.) inside a reasoning loop driven
by an LLM. Designed provider-agnostic via the OpenAI SDK shape — switching
between Gemini, Claude, GPT-4o, etc. is a base_url + model change, not a
code change.
"""
