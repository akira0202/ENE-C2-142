# ENE-C2-142 — Municipal Energy-Scenario Input Evidence Extractor

> **Category**: Cat 2 (multi-step domain workflow)
> **Industry**: ENE

## Overview

This agent turns approved energy-statistics extracts into a traceable register of the
inputs a local energy scenario will be built on. You give it the extracts, the documentation of which
dataset version they came from, and the scenario worksheet; it reports, for every figure, the
geography and period it covers, the energy type, the unit, the source version, the rule used to pick
that value, and anything missing or ambiguous. It is aimed at municipal energy-planning teams and
utility planning analysts who need inputs a reviewer can reproduce.

It is read-only and works only from the extracts you supply, drawing no inference beyond them. Every
assumption and every decision that follows stays with the person building the scenario.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## What it returns

Every run completes and says what happened.

| Result | When |
|---|---|
| The scenario-input register | the request meets the input contract and the register passes the output check. Gaps in the supplied data are flagged inside the register, not treated as failures |
| A notice instead of a register, with a code | the request is one you can correct (not the documented JSON, a missing input, no single municipality, or extract rows whose version / dataset disagrees with the manifest — the notice names what to send instead), or the assembled register would have carried an operational directive. No part of the register is returned, and the notice never repeats what you sent |
| An error, with no output | the request is refused by the input screen, the output carries credential-shaped content, or the run hits a defect in this agent. These are never reported as a completed request |

This agent extracts evidence for a human to read. It never tells anyone to act, and it never
substitutes a different dataset version. The input contract, the codes and the full classification
are in [`docs/02_design.md`](docs/02_design.md).

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specifications
```

See `docs/` for the design specification and the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.

