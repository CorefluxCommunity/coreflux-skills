---
name: lot-agents
description: "How to write a DEFINE AGENT: the TYPE LLM connector it uses, required clauses, ADD TOOL grants scoped to topics or targets, delegation peers, CALL AGENT from actions, and how agents are added, updated and removed."
---

# LOT Agents — DEFINE AGENT

An agent is its own LoT entity, not a connector. It runs on a `TYPE LLM` connector that holds the
provider, model and key, and it can do nothing until `ADD TOOL` grants a tool. It is deployed
with `-addAgent`, never `-addRoute`. An in-broker agent deploys one only with a `create_lot`
grant for target `agent`, and every such deploy waits for a person to approve it; load
`create-agent` before designing one for a user.

## CRITICAL SYNTAX

- `DEFINE AGENT <Name>` — unquoted name: letters, digits, `_` and `-`.
- `USES LLM ROUTE <LlmRoute>` (or `USES LLM CONNECTOR <LlmRoute>`) is the **first** body line, unquoted. That connector must be `TYPE LLM`.
- `WITH DEFAULT_USER "<user>"` is **required**. It is the broker user a task runs as when no MQTT
  user started it (a `CALL AGENT` from an action). There is no implicit admin.
- Every other value is quoted: `WITH DESCRIPTION "…"`. `GET SECRET` / `GET ENV` work anywhere.
- 4-space indent; `ADD TOOL` settings are indented one more level.
- There is no `DEFINE ROUTE … WITH TYPE AGENT` and no `AGENT_CONFIG`; both were removed.

## Minimal agent

```
DEFINE ROUTE Gpt WITH TYPE LLM
    ADD LLM_CONFIG
        WITH PROVIDER "openai"
        WITH MODEL "gpt-5.5"
        WITH API_KEY GET SECRET "OPENAI_API_KEY"

DEFINE AGENT LineAssistant
    USES LLM ROUTE Gpt
    WITH DESCRIPTION "Answers questions about production line 1"
    WITH DEFAULT_USER "line1-agent"
    WITH SYSTEM_PROMPT "You watch line 1. Answer from live data and say when data is stale."
    WITH INTERACTION_TOPIC "agents/line1"
    ADD TOOL "read_mqtt"
        WITH TOPICS "lines/1/#"
    ADD TOOL "write_mqtt"
        WITH TOPICS "reports/line1/#"
        WITH LEVEL "write"
```

Deploy the LLM connector first, then the agent.

## Clauses

| Clause | Default | Meaning |
|---|---|---|
| `USES LLM ROUTE <name>` | required | The `TYPE LLM` connector the agent runs on |
| `WITH DEFAULT_USER` | required | Principal when no MQTT user started the task |
| `WITH DESCRIPTION` | `"Agent <name>."` | Card text; peers and the Hub read it |
| `WITH SYSTEM_PROMPT` | — | Persona and operating instructions |
| `WITH GUARDRAILS` | — | Text appended to the prompt. Prompt, not enforcement |
| `WITH AGENTS` | none | Comma-separated peers it may delegate to |
| `WITH MAX_ITERATIONS` | `10` | Tool calls per run |
| `WITH MAX_TOKENS` | `50000` | Token budget for the whole task tree |
| `WITH TASK_TIMEOUT` | `600` | Seconds before `deadline_exceeded` |
| `WITH MAX_IN_FLIGHT` | `4` | Concurrent tasks; more MQTT or delegated tasks answer `agent_busy` |
| `WITH QUEUE_SIZE` | `64` | `CALL AGENT` calls that wait for a slot when it is busy (0 = refuse at once) |
| `WITH QUEUE_TIMEOUT` | `60` | Seconds a queued `CALL AGENT` waits before `agent_busy` |
| `WITH MAX_CHAIN_DEPTH` | `4` | Delegation hops |
| `WITH MEMORY` | `"individual"` | One conversation per session; `"shared:<store>"` shares the session's conversation with every agent declaring that store; `"none"` keeps nothing |
| `WITH LONG_TERM_MEMORY` | — | `"individual"` or `"shared:<store>"`: memory across sessions, read and written with `memory__recall` / `memory__save` |
| `WITH SKILLS` | — | Comma-separated stored skills the agent attaches (built-ins are always available) |
| `WITH OUTPUT_MODEL` | — | A COLLAPSED model every final answer must be an instance of (returned as minified JSON) |
| `WITH AGENT_MODE` | `"agent"` | `"insight"` offers no writing tool at all |
| `WITH TOOL_EXECUTION_MODE` | `"auto"` | `"confirm"` makes every write wait for approval |
| `WITH AGENT_COLLAB_MODE` | `"delegate"` | `"orchestrate"` runs a turn's peer calls in parallel; `"handoff"` hands the conversation to a peer |
| `WITH MAX_HISTORY_TOKENS` | `12000` | Estimated tokens a session keeps between runs; oldest turns go first (0 = 40-message cap only) |
| `WITH INTERACTION_TOPIC` | — | Enables `{topic}/<session>/ask`, `/response`, `/cancel` |
| `WITH HUB_VISIBLE` | `"false"` | Show in the Hub chat picker |

Refused with a message naming the release that brings them: `EXTERNAL_ACCESS "true"`,
`WITH EXTERNAL_WRITES`, `ADD TOOL "run_lot_once"`. Legacy settings
(`MODEL`, `PROVIDER`, `TOOLS`, `BROKER_TOOLS`, `MCP_ROUTES`, `ACTIONS`, `ENABLED_COMMANDS`,
`INTERACTION_MODE`) are refused too: model settings belong on the LLM connector, tools on `ADD TOOL`.
Any other clause name is refused as unknown.

## ADD TOOL grants

Nothing is granted by default. Each grant names one tool and its scope:

| Tool | Scope | Level |
|---|---|---|
| `read_mqtt` | `WITH TOPICS "a/#, b/+"` (required) | read |
| `write_mqtt` | `WITH TOPICS` (required) | `WITH LEVEL "write"` |
| `read_lot` | `WITH TARGET "<kind or name>"` (optional) — kinds: action, model, route, rule, panel, agent, python, thing | read |
| `create_lot` | `WITH TARGET "action, rule"` — kinds: action, model, route, rule, panel, skill, agent | `write_confirm` (default) or `"write"` |
| `execute_connectors` (alias `execute_routes`) | `WITH TARGET "<connector>"` or `"<connector>.<event>"` (required) | `write_confirm` (default) or `"write"` |
| `execute_actions` | `WITH TARGET "<action>"` (required) | `write_confirm` (default) or `"write"` |
| `query_connector` | `WITH TARGET "<connector>"` (required); the connector needs `WITH AGENT_QUERIES "read"` | read |

- A writing grant defaults to `WITH LEVEL "write_confirm"`: each call waits until a person
  approves it (the task shows `input_required` meanwhile). `WITH LEVEL "write"` runs writes
  without asking.
- `+` and `#` must fill a whole topic level. `write_mqtt` can never publish under
  `$SYS/Coreflux/Agents/`.
- `create_lot` with target `agent` or `skill` is refused at `LEVEL "write"`: authoring those
  always waits for approval. Target `agent` is never implied by other targets.
- `query_connector` runs a query the agent writes against a SQL or CrateDB connector, inside a
  read-only transaction or as the connector's `AGENT_USERNAME`, and returns the rows. Its
  `operation` `"schema"` lists the tables and columns first.
- `TOPICS` is refused on the other tools, `TARGET` on the MQTT tools, `LEVEL` on read tools.
  Grants of one tool are merged.
- A grant is not a permission: every tool call is also checked against the ACL of the user the
  task runs as, and of the agent's `DEFAULT_USER`. A call outside the grant fails as
  `out_of_scope`; a call the user may not make fails as `unauthorized`.

## Calling an agent from an action

```
DEFINE ACTION TriageAlert
ON TOPIC "alerts/raw/+" DO
    CALL AGENT "AlertAnalyst.execute"
        WITH (task = PAYLOAD, session_id = TOPIC POSITION 3)
        RETURN AS {verdict}
    PUBLISH TOPIC "alerts/triaged" WITH {verdict}
```

The name is the dotted `"Agent.method"` string; methods are `execute` and `clear_history`.
There is no `METHOD` keyword. `execute` takes `task` (required), `session_id` and
`queue_timeout` (seconds to wait for a busy agent, overriding `QUEUE_TIMEOUT`; 0 = do not wait);
`clear_history` takes `session_id`. The task runs as the agent's `DEFAULT_USER`. A failure comes
back as JSON (`{ "success": false, "status", "code", "message" }`); read it with `GET JSON`.

## How work arrives

- **Task topic:** publish to `$SYS/Coreflux/Agents/<agent>/task/<id>/request`; the answer is on
  `…/task/<id>/response`, progress on `…/status` and `…/stream`, and `…/cancel` stops it.
  Publishing under `$SYS` needs a `PublishSys` rule, for `root` too, or it is dropped silently.
- **Interaction topic:** with `INTERACTION_TOPIC "plant/line1"`, publish to
  `plant/line1/<session>/ask`; the answer comes on `…/<session>/response`.
- **`CALL AGENT`** from an action (above).
- **Delegation:** each peer in `WITH AGENTS` is offered as the tool `agent__<peer>__ask`
  (`handoff__<peer>` in handoff mode).
- **MCP:** an MCP client sees each agent it may reach as the tool `agent__<agent>__ask`.

## Approvals

A `write_confirm` call suspends the task (`input_required`) and retains the request on
`$SYS/Coreflux/Agents/<agent>/task/<id>/approval`. An approver publishes
`{ "approvalId", "approved": true|false, "reason" }` to `…/approval/decision`. The decision counts
only when the approver has a `PublishSys` rule on that topic and may make the same call
themselves; anything else is ignored. With no decision by the task deadline, the task fails
`deadline_exceeded`.

A body is plain text or JSON `{ "text", "session_id", "mode": "insight", "image", "pdf" }`;
`"insight"` makes the task read-only. A task asked over MQTT runs as the publishing client's
user, never as `DEFAULT_USER`; a delegated task runs as whoever started the chain.

## Agents on a dashboard

A panel can chat with an agent, answer its approvals and show its tasks, health and memory with
five component types: `agent-chat`, `agent-approvals`, `agent-activity`, `agent-status` and
`agent-memory`. Load `lot-panels` (section "Agent widgets") before writing one. What each needs
from the agent definition:

- `agent-chat` → `WITH INTERACTION_TOPIC`; without it nobody can chat from a panel.
- `agent-approvals` → writes that wait for approval (`LEVEL "write_confirm"`, the default).
- `agent-memory` → `WITH LONG_TERM_MEMORY` (`individual` or `shared:<store>`).
- `agent-activity`, `agent-status` → nothing extra.

```
ADD COMPONENT "Ask" WITH TYPE "agent-chat"
    SET AGENT "GateOpsAgent"
    SET SUGGESTIONS "Which gates have faults?, Summarise the last shift"
```

Viewers see them according to their own agent flags (`AllowedAgentRead`, `AllowedAgentApproval`,
`AllowedAgentManagement`), so say which flag the people using the dashboard need.

## Managing agents

- `-addAgent <DEFINE AGENT …>` adds an agent, or **updates it in place** if it exists. The new
  block is checked first; the agent keeps its conversations.
- `-removeAgent <name>` cancels its tasks, removes it and forgets its conversations.
- `-listAgents` lists name, LLM connector, status (`online` / `offline` / `error`) and description.
- Agents and connectors share one name space: an agent cannot take a connector's name.
- An LLM connector an agent uses cannot be removed until the agent is removed or updated.
- Agents need a Growth or Enterprise license, like `TYPE LLM`, but take no connector slot.
- Validate before deploying: `-validateLot` checks agent clauses and grants.
- Inside a `DEFINE THING` an agent is a `WITH AGENT` clause, owned by the Thing and named
  `<root>_…_<clause>`; load `lot-things` before touching one.

## Common Mistakes

- **WRONG:** `DEFINE ROUTE Assistant WITH TYPE AGENT` **RIGHT:** `DEFINE AGENT Assistant` + `USES LLM ROUTE <llm>`
- **WRONG:** `WITH MODEL "gpt-5.5"` on the agent **RIGHT:** model, provider and key on the `TYPE LLM` connector
- **WRONG:** `ADD TOOL "write_mqtt"` with no `LEVEL` and expecting it to run unattended **RIGHT:** no `LEVEL` means each write waits for approval; add `WITH LEVEL "write"` only for unattended writes
- **WRONG:** `ADD TOOL "read_mqtt"` with no `TOPICS` **RIGHT:** `WITH TOPICS "lines/1/#"`
- **WRONG:** `CALL AGENT "Planner" METHOD "execute"` **RIGHT:** `CALL AGENT "Planner.execute"` with an indented `WITH (task = …)`
- **WRONG:** deploying an agent with `-addRoute` **RIGHT:** `-addAgent`
