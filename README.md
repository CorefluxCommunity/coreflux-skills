# Coreflux agent skills

[Agent Skills](https://agentskills.io) that teach coding agents — Claude Code, Cursor, Codex,
GitHub Copilot, Gemini CLI and others — to write **LoT (Language of Things)** and to work with the
[Coreflux MQTT broker](https://coreflux.org).

| Skill | Use it for |
|-------|------------|
| `broker-operations` | Operating a broker over MQTT: commands and replies, `$SYS` topics, triage, users and permissions, projects |
| `broker-tools` | The broker's MCP tools and the safe validate → deploy workflow |
| `lot-actions` | Actions: triggers, variables, topic operations, control flow, Python/LLM calls |
| `lot-agents` | `DEFINE AGENT`: LLM connectors, tool grants, delegation |
| `lot-models` | Models: data schemas, field types, topic bindings, storage, inheritance |
| `lot-panels` | LoTV panels: components, bindings, events |
| `lot-routes` | Connectors: databases, OT (Modbus, S7, OPC UA, …), REST, MQTT bridges, AI |
| `lot-rules` | Permission rules: ALLOW/DENY, topic patterns, priorities |
| `lot-themes` | LoTV themes: design tokens, light/dark modes, variants |
| `lot-things` | `DEFINE THING`: templates, parameters, references |
| `python-scripts` | Python scripts the broker runs, and `CALL PYTHON` |

`skills.json` lists them, with the broker version they were exported from (`brokerVersion`).

## Branches and tags

- `main` holds the skills of the latest GA (general availability) broker release, and every GA
  release has a tag with its version, e.g. `2.22.1`. Installing without a ref gets `main`.
- `dev` follows the broker between releases, including release candidates. It has no tags, and
  its `brokerVersion` is the release candidate or `<latest release>+<commit>`. Use it to try skills
  before they ship.

## Install

**Any agent (skills CLI):**

```bash
npx skills add CorefluxCommunity/coreflux-skills
```

**Claude Code plugin:**

```
/plugin marketplace add CorefluxCommunity/coreflux-skills
/plugin install coreflux@coreflux
```

**VS Code / Cursor:** the LoT Notebooks extension has a *Install Agent Skills* button in its
sidebar that lets you pick the skills and the folders to install them into.

**By hand:** copy `skills/<name>/` into your agent's skills folder — `.agents/skills/`,
`.claude/skills/` or `.cursor/skills/`, in your project or your home directory.

To match a specific broker release, use the tag with that version, e.g.
`npx skills add CorefluxCommunity/coreflux-skills#2.22.1`. For the upcoming release, use the `dev`
branch: `npx skills add CorefluxCommunity/coreflux-skills#dev`.

## Do not edit this repository by hand

These files are generated. The source of truth is the Coreflux broker, which ships the same skills
to its built-in agents. Each broker skill declares `audience: [broker, external]` in its
frontmatter, and only the `external` ones are exported here: to `dev` on every change to the
broker's main branch and every release candidate, and to `main` on every GA release. A pull request here is overwritten by the next sync, so
please report problems as an issue instead.

`python3 scripts/validate.py` checks the frontmatter of every skill; CI runs it on every push.

## License

MIT — see [LICENSE](LICENSE).
