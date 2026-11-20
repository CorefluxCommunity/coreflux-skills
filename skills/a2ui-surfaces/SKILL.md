---
name: a2ui-surfaces
description: "Show live broker data to the user as a small UI in the chat with the render_surface tool (A2UI 1.0 components bound to MQTT topics). Load before calling render_surface, or when the user asks to see, watch, compare or chart topic values."
---

# A2UI surfaces — live UI in the chat

`render_surface` turns a list of A2UI 1.0 components plus a map from data-model pointers to MQTT
topics into a surface the chat renders inline. The client keeps the values live: an A2UI renderer
(the Hub) subscribes to the bound topics itself; an MCP Apps host (for example Claude Desktop) shows
the broker's surface view, which polls the broker for fresh values (see "MCP Apps hosts" below).
Nothing is created on the broker.

## Surface or panel?

| Use a surface (`render_surface`) | Use a panel (`DEFINE PANEL`, skill `lot-panels`) |
|---|---|
| "Show me tank 1 and 2 next to the pump state" | A dashboard operators open every day |
| Throwaway, belongs to this conversation | Durable, deployed, permissioned, published to `$Visu` |
| One read-only tool call, no approval | A write the operator approves |

If the user wants to keep it, offer to write a panel instead.

## Binding syntax — the most common mistake

A component reads a bound value with **`{"@path": "/x"}` — the key is `@path`, with the `@`**.
`{"path": "/x"}` fails validation. Older A2UI drafts used `path`; this broker does not.

| Where | Write | Never |
|---|---|---|
| Any value (`value`, `text`, `label`, `rows`, action `context`, ...) | `{"@path": "/tank1"}` | `{"path": "/tank1"}` |
| Inside a List template | `{"@path": "value"}` (relative, still `@`) | `{"path": "value"}` |
| A List's `children` template (the only place) | `{"path": "/tanks", "componentId": "row"}` | `{"@path": "/tanks", ...}` |

Before calling `render_surface`, check every `{...path...}` object against this table.

## Other mistakes that fail validation

| Wrong | Right |
|---|---|
| `Text` with `"variant": "heading"` / `"h1"`…`"h5"` / `"title"` | `"variant"` is only `"body"` (default) or `"caption"`. There is no heading: the surface `title` is the heading; a Coreflux component's `label` captions it |
| `"title"` on a `Gauge`, `Value`, `Indicator`, `RealtimeChart` or `Table` | `"label"` |
| `RealtimeChart` with `values` / `datasets` / `lines` (several lines in one chart) | `"series": [{"label": "Main", "value": {"@path": "/main"}}, {"label": "HVAC", "value": {"@path": "/hvac"}}]`, one entry per line, and no `value` |
| `RealtimeChart` with both `value` and `series`, or neither | Exactly one: `value` for one line, `series` for several |
| `Text` with a Markdown heading (`"## Energy"`) | Plain text; Markdown is not rendered, the `#` shows literally |

## Input

```json
{
  "title": "Tank levels",
  "components": [ { "id": "root", "component": "Column", "children": ["..."] } ],
  "bindings": { "/tank1/level": { "topic": "plant/tank1/level", "json_path": "$.level" } },
  "data": { "note": "static values go here" }
}
```

- `components` is a **flat list**. Exactly one component has `"id": "root"`; containers name their
  children by id (`child`, `children`).
- `bindings` maps a JSON Pointer (`/a/b`) to `{ "topic", "json_path"? }`. A component reads the
  value with `{"@path": "/a/b"}`.
- `json_path` picks part of a JSON payload: `$.level`, `values[0].temp`, `status`. A payload that is
  not JSON is used as a string; `"23.5"` is the number 23.5.
- A topic with `+` or `#` writes an **array** of `{ "topic", "value" }` (sorted by topic) at its
  pointer. Show it with a `List` template or a `Table`.
- Only bind topics you can read. Find them with `explore_topics` first; a topic you may not read
  fails the call, and a topic with no value yet shows `null` until its first live message.

## Components

Basic catalog (the surface default, no `catalogId` needed): `Text`, `Row`, `Column`, `List`, `Card`,
`Tabs`, `Divider`, `Icon`, `Image`, `Button`, `TextField`, `CheckBox`, `ChoicePicker`, `Slider`,
`DateTimeInput`, `Modal`.

Coreflux catalog — every one of these needs
`"catalogId": "https://coreflux.org/a2ui/catalogs/coreflux/v1/catalog.json"`:

| Component | Key properties |
|---|---|
| `Gauge` | `value` (number), `label`, `unit`, `min`, `max`, `decimals`, `thresholds` |
| `Value` | `value` (any), `label`, `unit`, `decimals`, `thresholds` |
| `Indicator` | `value` (state), `label`, `colors` (`{"running": "green"}`) |
| `RealtimeChart` | `value` (number) **or** `series` (`[{"label", "value"}]`, up to 8 lines on one time axis), `label`, `unit`, `chartType` (`line`/`area`/`bar`), `maxPoints`, `min`, `max` |
| `Table` | `rows` (array of objects), `label`, `columns` (`[{"key", "label"?, "type"?}]`), `pageSize` |

Put related values that share a unit in one chart with `series` (main, HVAC and solar power in kW);
the chart draws a legend and a tooltip that lists every line at the hovered time. Values in
different units go in separate charts.

```json
{ "id": "energy", "component": "RealtimeChart",
  "catalogId": "https://coreflux.org/a2ui/catalogs/coreflux/v1/catalog.json",
  "label": "Building A energy", "unit": "kW",
  "series": [
    { "label": "Main",  "value": { "@path": "/main" } },
    { "label": "HVAC",  "value": { "@path": "/hvac" } },
    { "label": "Solar", "value": { "@path": "/solar" } }
  ] }
```

`thresholds` is `[{"at": 80, "color": "warning"}, {"at": 95, "color": "critical"}]`. The full schema
is the MCP resource `a2ui://coreflux/catalog`.

Rules that fail validation when broken:

- Bind with `{"@path": "/x"}` (with the `@`); see "Binding syntax" above. The one place without
  the `@` is a List's `children` template, `{"path": "/items", "componentId": "row"}`.
- `Text` needs `text`; `Button` needs `child` (a `Text` id) and `action`.
- No property outside the component's schema — no `style`, no `title` on a `Gauge` (use `label`).
- The components form a **tree**: each id appears in at most one `child`, `children`, template
  `componentId`, tab `child`, `trigger` or `content`, and only once there. `root` is never a child.
  A component referenced twice would render twice.

> **A button's label is its `child` only — never also a sibling in the Row.**
>
> Wrong (the label shows twice, and the call fails):
> `{ "id": "root", "component": "Row", "children": ["state", "restart_label", "restart"] }` with
> `{ "id": "restart", "component": "Button", "child": "restart_label", … }`
>
> Right: `{ "id": "root", "component": "Row", "children": ["state", "restart"] }` — the Button
> brings its label with it.

## Buttons

A `Button` with `action.event` sends the event back to you as the user's next message: its `name`,
its resolved `context`, and `userMessage` if set. Then act with your normal tools (writes still need
the operator's approval). Bind context values to send what the surface shows:

```json
{ "id": "ack", "component": "Button", "child": "ack_label",
  "action": { "event": { "name": "restart_pump",
                         "context": { "pump": "pump1", "state": { "@path": "/pump/state" } } } } }
```

## Example 1 — a Card with a Button

A `Card` has exactly one `child` (never `children`); put several things in a `Column` and make that
the child. A `Button` needs `child` (its label) and `action`. Every component has an `id`.

```json
{
  "title": "Pump 1",
  "components": [
    { "id": "root", "component": "Card", "child": "body" },
    { "id": "body", "component": "Column", "children": ["status", "restart"] },
    { "id": "status", "component": "Text", "text": "Pump 1 is stopped" },
    { "id": "restart", "component": "Button", "child": "restart_label", "variant": "primary",
      "action": { "event": { "name": "restart_pump", "context": { "pump": "pump1" } } } },
    { "id": "restart_label", "component": "Text", "text": "Restart" }
  ]
}
```

## Example 2 — two gauges and a pump state

```json
{
  "title": "Tanks and pump",
  "components": [
    { "id": "root", "component": "Column", "children": ["gauges", "pump"] },
    { "id": "gauges", "component": "Row", "children": ["t1", "t2"] },
    { "id": "t1", "component": "Gauge", "catalogId": "https://coreflux.org/a2ui/catalogs/coreflux/v1/catalog.json",
      "label": "Tank 1", "unit": "%", "value": { "@path": "/tank1" },
      "thresholds": [{ "at": 80, "color": "warning" }, { "at": 95, "color": "critical" }] },
    { "id": "t2", "component": "Gauge", "catalogId": "https://coreflux.org/a2ui/catalogs/coreflux/v1/catalog.json",
      "label": "Tank 2", "unit": "%", "value": { "@path": "/tank2" } },
    { "id": "pump", "component": "Indicator", "catalogId": "https://coreflux.org/a2ui/catalogs/coreflux/v1/catalog.json",
      "label": "Pump 1", "value": { "@path": "/pump" } }
  ],
  "bindings": {
    "/tank1": { "topic": "plant/tank1/level", "json_path": "$.level" },
    "/tank2": { "topic": "plant/tank2/level", "json_path": "$.level" },
    "/pump": { "topic": "plant/pump1/state", "json_path": "$.state" }
  }
}
```

## Example 3 — every tank, from a wildcard

```json
{
  "title": "All tank levels",
  "components": [
    { "id": "root", "component": "Card", "child": "list" },
    { "id": "list", "component": "List", "children": { "path": "/tanks", "componentId": "item" } },
    { "id": "item", "component": "Row", "children": ["name", "level"] },
    { "id": "name", "component": "Text", "text": { "@path": "topic" } },
    { "id": "level", "component": "Value", "catalogId": "https://coreflux.org/a2ui/catalogs/coreflux/v1/catalog.json",
      "label": "Level", "unit": "%", "value": { "@path": "value" } }
  ],
  "bindings": { "/tanks": { "topic": "plant/+/level", "json_path": "$.level" } }
}
```

The same array also fits a table:
`{ "id": "root", "component": "Table", "catalogId": "…coreflux…", "rows": { "@path": "/tanks" }, "columns": [{"key": "topic"}, {"key": "value", "type": "number"}] }`.

## When the call fails

The error is A2UI's: `{"version": "1.0", "error": {"code": "VALIDATION_FAILED", "path": "/createSurface/components/2/value", "message": "…"}}`.
The message names the component (type and id), the property, and what it takes or which
properties the component has. Fix exactly that and call again. `PERMISSION_DENIED` names a binding whose topic you may
not read: drop it. Limits: 200 components, 50 bindings, 10 wildcard bindings, 500 wildcard matches
in total (over all wildcard bindings), 64 KB of data (your `data` plus every bound value).

## Inputs and bindings

An input (`TextField`, `Slider`, `CheckBox`, `ChoicePicker`, `DateTimeInput`) may not write where a
binding keeps a live value: its `value` `@path` must not equal a binding pointer, sit under one, or
contain one. Inside a `List` template a relative path is resolved against the template's `path`
for every item, so a `TextField` with `{"@path": "v"}` in a List over a bound `/tank` writes
`/tank/*/v` and is refused. Give inputs their own part of the data model (`/form/...`, or a template
over an unbound list).

## MCP Apps hosts

A client that is an MCP Apps host gets `render_surface` with a broker-served view
(`ui://coreflux/surface-<hash>.html`). On that path:

- Components follow the `mcp-app` profile: Coreflux, display and input components. `Image`,
  `Video`, `AudioPlayer` and the `openUrl` function are refused; show a link as `Text`.
- The `regex` check runs in the view with a linear-time regex engine, so patterns with lookaround
  (`(?=`, `(?!`, `(?<=`, `(?<!`), backreferences (`\1`, `\k<name>`) or inline flags (`(?i)`) are not
  supported there. The broker does not reject them, but the check will not behave as written: use
  plain classes, groups, alternation and quantifiers.
- The view polls `get_surface_values` about every 3 s for at most 10 minutes, then shows a Refresh
  button the user presses to resume. The limits above apply to every poll.
- Polling is rate limited to 600 calls a minute per token, 300 per session.
- A payload the broker cannot use as JSON (for example one with duplicate keys) shows as `null`.

After a successful call the user already sees the values: answer in a sentence or two, do not
repeat them as a table.
