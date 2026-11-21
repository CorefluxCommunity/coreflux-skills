---
name: lot-actions
description: "How to write LOT actions: triggers, variables, topic operations, control flow, callable actions, and integrations (Python, MCP, LLM)."
---

# LOT Actions — Complete Reference

## Failures and the action time limit

**TRY decides how failures behave.** There is no setting for this. Code inside a `TRY` body, and the body of an action that has `ON ERROR`, is a *raising scope*:

| Case | Outside a raising scope (as in broker 2.22) | Inside `TRY`, or an action with `ON ERROR` |
|---|---|---|
| `AS INT` / `AS DOUBLE` on NULL, blank or non-numeric text | `0` / `0.0` | raises (`Cannot convert 'abc' to INT`) |
| `AS INT` out of 32-bit range | `0` | raises |
| `AS BOOL` | `true`, `yes`, `on` (any case) and any non-zero number are TRUE; everything else FALSE | only `true` / `false` / `1` / `0`; anything else raises |
| Failed `CALL PYTHON` | logged; the `RETURN` variable is NULL | raises (`CALL PYTHON mod.fn failed: …`) |
| Typed `GET ENV` / `GET SECRET` unset or unconvertible | `0` / `0.0` / `false` / `""` | raises (`AS STRING` of an unset name is still `""`) |

A `CATCH` body and the `ON ERROR` handler itself are not raising scopes. A `CALL ACTION` callee follows its own `TRY` / `ON ERROR`, not the caller's (its errors still reach the caller's `TRY`). A fraction always truncates toward zero (`"3.9" AS INT` and `3.9 AS INT` are `3`; `-3.9` is `-3`). `LOOP` / `REPEAT`, `FOR` and `WHILE` always raise at their iteration cap, a top-level Python `bytes` return is plain base64, and every action run has a 30-second wall clock by default (`LotRuntime.ActionTimeoutSeconds`).

## CRITICAL SYNTAX — Read Before Writing Anything

### Action names are NEVER quoted in DEFINE
```
WRONG:  DEFINE ACTION "Heartbeat"
RIGHT:  DEFINE ACTION Heartbeat
```

### PUBLISH TOPIC uses WITH, never MESSAGE
```
WRONG:  PUBLISH TOPIC "t" MESSAGE "hello"
RIGHT:  PUBLISH TOPIC "t" WITH "hello"

WRONG:  KEEP TOPIC "t" MESSAGE "value"
RIGHT:  KEEP TOPIC "t" WITH "value"
```

The separator between topic and payload is always WITH (or TO or AS — all equivalent).
MESSAGE is a different keyword used elsewhere. Never use it with PUBLISH/KEEP TOPIC.

### SET uses quoted variable names and WITH
```
AVOID:  SET performance TO ({a} / {b}) * 100
RIGHT:  SET "performance" WITH ({a} / {b}) * 100

AVOID:  SET machineId TO TOPIC POSITION 3
RIGHT:  SET "machineId" WITH TOPIC POSITION 3
```

Always write variable names in SET double-quoted, with WITH between the name and value.
The parser also accepts an unquoted name and TO (WITH, TO, AS and IN are the same token),
but the quoted WITH form is the canonical one — use it everywhere.

### One DEFINE ACTION per broker.add_action call

broker.add_action accepts exactly ONE DEFINE ACTION block per call. To deploy
multiple actions, make multiple calls - one per action - and check each call's
result before the next (a parse or compile failure comes back as success=false
with the errors) so a syntax failure in action 2 does not hide a problem in
action 1. Errors raised while an action runs are reported by broker.diagnose
(its action_errors field). To deploy several actions atomically, use
broker.deploy_lot instead.

WRONG - three DEFINE ACTION blocks bundled into a single call:
```
broker.add_action(argument="
DEFINE ACTION PublishTopicAEvery5Seconds
ON EVERY 5 SECONDS DO
    PUBLISH TOPIC \"topica\" WITH \"tick\"

DEFINE ACTION ForwardTopicAToTopicB
ON TOPIC \"topica\" DO
    PUBLISH TOPIC \"topicb\" WITH PAYLOAD

DEFINE ACTION CountTopicBEvents
ON TOPIC \"topicb\" DO
    SET \"currentCount\" WITH GET TOPIC \"state/topicb/count\" AS INT
    KEEP TOPIC \"state/topicb/count\" WITH {currentCount} + 1
    PUBLISH TOPIC \"state/topicb/count/updated\" WITH {currentCount} + 1
")
```

RIGHT - one broker.add_action call per action, each result checked before the next:
```
broker.add_action(argument="DEFINE ACTION PublishTopicAEvery5Seconds\nON EVERY 5 SECONDS DO\n    PUBLISH TOPIC \"topica\" WITH \"tick\"")
# check the result: success=false carries the parse/compile errors

broker.add_action(argument="DEFINE ACTION ForwardTopicAToTopicB\nON TOPIC \"topica\" DO\n    PUBLISH TOPIC \"topicb\" WITH PAYLOAD")
# check the result: success=false carries the parse/compile errors

broker.add_action(argument="DEFINE ACTION CountTopicBEvents\nON TOPIC \"topicb\" DO\n    SET \"currentCount\" WITH GET TOPIC \"state/topicb/count\" AS INT\n    KEEP TOPIC \"state/topicb/count\" WITH {currentCount} + 1\n    PUBLISH TOPIC \"state/topicb/count/updated\" WITH {currentCount} + 1")
# check the result: success=false carries the parse/compile errors
```

If the user asks for N related actions, that is N separate broker.add_action
calls - never one combined call, regardless of how tightly coupled the actions
are.

---

## Basic Structure

```
DEFINE ACTION <name>
<trigger> DO
    <statements>
```

Action names are plain identifiers — no quotes, no spaces.
**The trigger line sits at column 0 (same as `DEFINE`). The body is indented 4 spaces under the trigger.**
Do NOT indent the trigger line under `DEFINE ACTION` — that produces an unexpected INDENT token before the trigger and the parser rejects it.

## Trigger Types

### ON EVERY — Interval Timer

Runs the action body repeatedly at a fixed interval.

```
DEFINE ACTION Heartbeat
ON EVERY 10 SECONDS DO
    PUBLISH TOPIC "system/heartbeat" WITH TIMESTAMP "ISO"
```

All valid time units:
```
ON EVERY 500 MILLISECONDS DO    -- sub-second polling
ON EVERY 5 SECONDS DO           -- fast cyclic (sensors, watchdog)
ON EVERY 1 MINUTES DO           -- moderate polling
ON EVERY 2 HOURS DO             -- periodic aggregation
ON EVERY 1 DAYS DO              -- daily tasks
ON EVERY 1 WEEKS DO             -- weekly tasks
ON EVERY 1 MONTHS DO            -- also YEARS; singular forms (SECOND, MINUTE…) and MS work too
```
The unit is not checked when the action is deployed: a misspelled unit (`5 SECS`) deploys
cleanly and fails only when scheduled ("Unsupported time unit" in the broker log).

### ON EVERY \<DAY> AT — Scheduled (Day-of-Week + Time)

Runs once at a specific time on the specified day(s). Time is in 24-hour format "HH:mm:ss".

```
-- Specific weekdays:
DEFINE ACTION MondayMeeting
ON EVERY MONDAY AT "09:00:00" DO
    PUBLISH TOPIC "calendar/reminder" WITH "Weekly meeting in 30 minutes"

-- All weekdays (Monday–Friday):
DEFINE ACTION DailyShiftStart
ON EVERY WEEKDAY AT "06:00:00" DO
    PUBLISH TOPIC "shift/status" WITH "active"
    KEEP TOPIC "state/shift" WITH "day"

-- Weekend only (Saturday + Sunday):
DEFINE ACTION WeekendMode
ON EVERY WEEKEND AT "08:00:00" DO
    KEEP TOPIC "state/mode" WITH "weekend"

-- Every day of the week independently:
DEFINE ACTION SaturdayBackup
ON EVERY SATURDAY AT "02:00:00" DO
    PUBLISH TOPIC "backup/trigger" WITH "start"
```

Valid day keywords: MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY, WEEKDAY, WEEKEND

Full day-of-week example set:
```
ON EVERY MONDAY AT "07:00:00" DO
ON EVERY TUESDAY AT "07:00:00" DO
ON EVERY WEDNESDAY AT "07:00:00" DO
ON EVERY THURSDAY AT "07:00:00" DO
ON EVERY FRIDAY AT "07:00:00" DO
ON EVERY SATURDAY AT "10:00:00" DO
ON EVERY SUNDAY AT "10:00:00" DO
ON EVERY WEEKDAY AT "07:00:00" DO   -- Mon-Fri only
ON EVERY WEEKEND AT "10:00:00" DO   -- Sat-Sun only
```

### ON TOPIC (MQTT-triggered)
```
DEFINE ACTION ProcessSensor
ON TOPIC "sensors/+/data" DO
    SET "deviceId" WITH TOPIC POSITION 2
    SET "temp" WITH PAYLOAD AS DOUBLE
    IF {temp} > 30 THEN
        PUBLISH TOPIC "alerts/" + {deviceId} WITH "High temperature: " + {temp}
```
Use `+` for a single-level and `#` for a multi-level wildcard in ON TOPIC, ON CHANGE, RISING /
FALLING and TIMER ON patterns (`ON TOPIC "plant/#"`). Edge and TIMER ON state is kept per
matched topic: `plant/a` and `plant/b/c` rise, fall and time out independently.
`ON TOPIC "…" RISING` fires when the payload goes from false to true, `FALLING` from true to false
(the keyword alone — `RISING EDGE` is refused). The payload is read as a BOOL: `true` / `1` or
`false` / `0`, any case, surrounding spaces ignored. Edge state is kept per action and topic and starts
empty when the action is deployed, so the **first** value only records it and never fires — a
retained `true` delivered at deploy or start included. A payload that is not one of those four
(`on`, `yes`, `2`, JSON) neither fires nor changes the state. Topics are
case-sensitive, so `ON TOPIC "Plant/A"` and `ON TOPIC "plant/a"` on one action are two triggers.
`ON TOPIC "…" TIMER ON <n> <UNIT>` fires once after the payload stays TRUE for the duration. In a
cluster it fires on the action's owner only (the same gate as ON EVERY / ON CRON); every node tracks
the TRUE window, so a new owner after failover keeps the pending deadline.
PAYLOAD gives the message content. TOPIC POSITION N extracts segment N (1-based).
PAYLOAD exists only in ON TOPIC and ON CHANGE actions. In ON EVERY, ON START, session triggers and
callable actions there is no message: a bare PAYLOAD fails to compile, and a typed `PAYLOAD AS DOUBLE`
compiles but never holds data. Read the last value with `GET TOPIC "…"` instead.

### ON CHANGE (MQTT-triggered only when payload bytes change)
```
DEFINE ACTION ProcessSensorOnChange
ON CHANGE "sensors/+/data" DO
    SET "temp" WITH PAYLOAD AS DOUBLE
    PUBLISH TOPIC "sensors/processed" WITH {temp}
```
Same topic patterns as ON TOPIC. Fires on first publish per topic, then only when the payload differs from the last cached value. Use ON TOPIC for every message; use ON CHANGE to skip unchanged repeats. (Not the same as Visu slider ON CHANGE DO PUBLISH — that is client UI only.)

### ON START (runs once at broker startup)
```
DEFINE ACTION Init
ON START DO
    PUBLISH TOPIC "system/status" WITH "online"
```
In a cluster, ON START runs once per cluster start, on one node, at most once. A node that restarts, or a definition deployed later, does not run it again.

### ON CONNECT / ON DISCONNECT / ON SUBSCRIBE (client session events)
```
DEFINE ACTION AuditConnect
ON CONNECT DO
    PUBLISH TOPIC "audit/connect/" + CLIENTID WITH USER + "@" + ENDPOINT
    KEEP TOPIC "sessions/" + CLIENTID + "/clean" WITH CLEANSESSION

DEFINE ACTION AuditDisconnect
ON DISCONNECT DO
    PUBLISH TOPIC "audit/disconnect/" + CLIENTID WITH DISCONNECTREASON

DEFINE ACTION AuditSensorSubscriptions
ON SUBSCRIBE "sensors/#" DO
    PUBLISH TOPIC "audit/subscriptions" WITH CLIENTID + " -> " + SUBSCRIBETOPIC + " qos=" + SUBSCRIBEQOS
```
ON CONNECT runs after the broker accepts a client's CONNECT; ON DISCONNECT when the client goes away
(clean, unclean or session takeover); ON SUBSCRIBE after the subscribe permission check allows a
subscription. `ON SUBSCRIBE "pattern"` fires when the subscribed topic filter matches the pattern
(`+`/`#` allowed); bare `ON SUBSCRIBE DO` fires for every allowed subscription.

Session keywords (no braces — they are keywords, not variables):

| Keyword | Value |
|---------|-------|
| CLIENTID | The client that connected, disconnected or subscribed |
| USER | That client's username (`USER IN GROUP "g"` / `USER IS "name"` work too) |
| ENDPOINT | Client address (`ip:port`) |
| CLEANSESSION | `"true"` / `"false"` from the CONNECT packet |
| DISCONNECTREASON | ON DISCONNECT only, e.g. `Clean (NormalDisconnection)`, `NotClean`, `Takeover` |
| SUBSCRIBETOPIC | ON SUBSCRIBE only: the topic filter the client subscribed to |
| SUBSCRIBEQOS | ON SUBSCRIBE only: the granted QoS (0, 1, 2); -1 elsewhere |

These actions have no triggering message: PAYLOAD fails to compile in them and TOPIC POSITION is
empty. The broker
only runs the session hooks while at least one action uses them, so there is no cost when unused.

### ON CRON — 5-field schedule

`ON CRON "min hour day-of-month month day-of-week"` (optional `WITH TIMEZONE "<IANA>"`). When both
day fields are restricted and neither starts with `*`, they combine with **OR**. If either starts
with `*` (`*` or `*/N`), the day test is DOM mask AND DOW mask (Vixie). Examples: `"0 0 13 * 5"`
every 13th and every Friday; `"0 0 */2 * 5"` Fridays with an odd day-of-month; `"0 0 13 * */2"` the
13th only on Sun/Tue/Thu/Sat; `"0 0 * * 5"` every Friday.

### Callable actions (INPUT / RETURN / OUTPUT)

Callable actions have no MQTT trigger. Use INPUT lines (at least one — an action with neither a trigger nor an INPUT is not callable, and `CALL ACTION` reports it as not found), DO body, then RETURN with one OUTPUT per line (one variable each). Comma-separated RETURN OUTPUT and single-line RETURN OUTPUT result are rejected.

```
DEFINE ACTION CalcAverage
INPUT value1 AS DOUBLE
INPUT value2 AS DOUBLE
DO
    SET "avg" WITH ({value1} + {value2}) / 2
RETURN
    OUTPUT avg
```

Multiple outputs (one OUTPUT per line):
```
DEFINE ACTION AnalyzeReading
INPUT value AS DOUBLE
INPUT threshold AS DOUBLE
DO
    SET "is_above" WITH ({value} > {threshold})
    SET "difference" WITH ({value} - {threshold})
    SET "percentage" WITH ({value} / {threshold} * 100)
RETURN
    OUTPUT is_above
    OUTPUT difference
    OUTPUT percentage
```

The number of RETURN variables at the CALL site must match the number of OUTPUTs declared
by the called action — otherwise the upload fails with a clear validation error.

## Variable Operations

### SET — assign a value
```
SET "myVar" WITH "hello"
SET "temp" WITH GET TOPIC "sensor/temp" AS DOUBLE
SET "data" WITH PAYLOAD.readings.temperature AS DOUBLE
SET "host" WITH GET ENV "DB_HOST"
SET "pass" WITH GET SECRET "DB_PASSWORD"
```

### GET TOPIC — read an MQTT topic's current value
```
SET "value" WITH GET TOPIC "sensors/temperature" AS DOUBLE
```
Type casting with AS: INT, DOUBLE (or FLOAT), BOOL, STRING, TIMESTAMP, OBJECT, ARRAY.
`GET TOPIC … AS ARRAY` in a SET currently fails to compile; read it AS STRING and parse it.

Lookup order (same in actions and rules):
1. In-flight KEEP/PUBLISH this action has not flushed yet
2. The payload that triggered this action (when reading that topic)
3. Live cache — latest KEEP or PUBLISH. PUBLISH replaces KEEP
4. MQTT retain — fallback after restart, before the cache is warm again

Use KEEP for state another action (or a rule) will GET TOPIC without notifying subscribers. Use TOPIC EXISTS in rules when the grant must be an MQTT retained message.

In a cluster, a KEEP is copied to every node and saved to disk, so GET TOPIC on any node returns it. The last write by timestamp wins, so a counter updated from two nodes can lose an update: keep one writer per topic.

### SUM / AVG / MIN / MAX / COUNT OF TOPIC — aggregate many topics
```
DEFINE ACTION LineEnergy
ON EVERY 10 SECONDS DO
    SET "total" WITH SUM OF TOPIC "plant/+/kw"
    SET "meters" WITH COUNT OF TOPIC "plant/+/kw" LIMIT 1000
    IF {total} EQUALS NULL THEN
        PUBLISH TOPIC "plant/kw/status" WITH "no readings"
    ELSE
        PUBLISH TOPIC "plant/kw/total" WITH {total}
```
Reads the current value of every topic that matches the MQTT filter (the value GET TOPIC would read,
including retained values from before the deploy or a restart). Matching is exact MQTT and
case-sensitive; `$` topics never match and a filter starting with `$` is refused. Non-numeric values
are skipped. COUNT is the number of numeric values (0 when none); SUM / AVG / MIN / MAX are DOUBLE, or
NULL when none. The filter is one operand: `SUM OF TOPIC "a/+" + 1` adds 1 to the sum, and a computed
filter goes in parentheses: `SUM OF TOPIC ("plant/" + {line} + "/+")`. `LIMIT` is a positive integer
literal (default 500); more matching topics than LIMIT raises a catchable error.

### GET JSON — extract from JSON (soft-deprecated; prefer member access)
```
SET "temp" WITH GET JSON "data.temperature" IN PAYLOAD AS DOUBLE
SET "name" WITH GET JSON "device.name" IN {myJson}
SET "ok" WITH (GET JSON "success" IN {result} AS BOOL)
```
Source must be a JSON string (PAYLOAD, a variable, or CALL PYTHON RETURN AS). Missing keys
and JSON null read as LoT NULL. AS BOOL / AS INT / AS DOUBLE on them are 0 / false, except inside
`TRY` or an action with `ON ERROR`, where they raise (or test `EQUALS EMPTY` first). AS STRING yields `""`.


### Members — structured JSON (`PAYLOAD.temp`, `report.unit`)
```
SET "id" WITH PAYLOAD.devices[0].id AS STRING
SET "temp" WITH PAYLOAD.temperature AS DOUBLE
SET report AS OBJECT = {}
SET report.device.location = "line-A"
SET report.temp WITH 23.5
SET report.unit = "celsius"
SET "h" WITH report.HAS("device")
SET "n" WITH report.KEYS.LENGTH
DELETE report.unit
SET "name" WITH PAYLOAD.name.UPPER
SET "m" WITH PAYLOAD."MAX" AS INT
SET "t1" WITH PAYLOAD."temp-1" AS INT
```
Read and write JSON members with a dot. `PAYLOAD.temperature` is the preferred short form, and the same shape works for `report.unit`,
`{report}.unit`, `(expr).k`. Prefer this over soft-deprecated `GET JSON`.
The short form works on `PAYLOAD`, `{x}`, a parenthesised expression, or a bare name the action has
already bound (a SET target, an INPUT, a RETURN name of CALL ACTION / CALL PYTHON / MCP / LLM / AGENT,
or a FOR variable). A dotted name whose head is not bound keeps its old meaning (a model field path
such as `performance_metrics.target_cycle_time`).
After a dot, an ALL-CAPS LoT method or keyword (`UPPER`, `ROUND`, `ABS`, `KEYS`, `HAS`, `LENGTH`,
`DELETE`, `JSON`, `TO`, …) is a method, never a member. Everything else (lowercase names, `ID`, `PV`, …)
is a member. So `PAYLOAD.name.UPPER` applies UPPER to the member, and `PAYLOAD.ID` reads the key `ID`.
A key spelled like a method, or with characters a name cannot have, is quoted (`PAYLOAD."MAX"`,
`PAYLOAD."temp-1"`) or uses the explicit form `PAYLOAD.JSON.MAX`.
`DELETE report.unit` removes a key (explicit form: `report.JSON.unit.DELETE`).
`report.LENGTH` is the key count of an object, the entry count of an array, or the character count
of a string.

**Explicit `.JSON.` form.** Every member read and write also works with a `.JSON.` step
(`PAYLOAD.JSON.temperature`, `SET report.JSON.unit = "C"`). It behaves exactly like the short form.
Prefer the short form. Use `.JSON.`, or a quoted key, when the key is spelled like a method
(`report.JSON.MAX`, `PAYLOAD."MAX"`). Under `.JSON.` every bare `.IDENTIFIER` is a key, even `.ABS`.

Paths use bracket indices (`devices[0].id`);
`GET JSON` still uses dot-number paths (`devices.0.id`) — the two are not identical.
Sources: bare variable, `{variable}`, `PAYLOAD`, `RESULT`, or a parenthesised expression.
Upserts accept `=`, `TO`, and `WITH`. `HAS` takes a string literal only. Reserved keys
(`DELETE`, `HAS`, `JSON`, `LENGTH`, `OBJECT`, `KEYS`) must be quoted
(with `\"` / `\\` unescaped). `.KEYS` returns the object's own keys as an
`ARRAY OF STRING` (insertion order); `.KEYS.LENGTH` is the count — quote
`."KEYS"` for a literal key named `KEYS`. `PAYLOAD` / `RESULT` are read-only (`SET PAYLOAD.k = 1` is refused).
Index-final upsert replaces an element and index-final `.DELETE` removes it; an index out of range
raises (`JsonDeleteMember: array index 5 out of range.`), and so does a delete through a value that
is not an object / array or from a source that is not JSON. Deleting a missing key (or under a
missing intermediate key) does nothing. Missing key and JSON `null` both read
as LoT `NULL` (not the text `"null"` — that sentinel remains only on legacy `GET JSON`).
Invalid JSON string sources read as `NULL`; writes are a runtime error and leave the value
unchanged. Create-on-write stops with a runtime error (value unchanged) when an intermediate
exists but is not an object — including when it is JSON `null`.
Quoted keys stay literal: `."a.b"` is one key, `."0"` is the key `"0"` (not an index).
Under `.JSON.` a math method needs parentheses, as in `(PAYLOAD.JSON.t).ABS`; the short form
`PAYLOAD.t.ABS` needs none.
`OBJECT` values behave as values (clone-on-write): assignment aliases until the first member write, which deep-clones the root so mutating `b` after `SET b WITH {a}` does not change `a`.
LoT `STRING` values always write as JSON strings (JSON-looking text is not re-parsed).
Writing LoT `NULL` through a member upsert stores JSON `null`; reading that key (or a missing key) yields LoT `NULL`. `AS INT` / `AS DOUBLE` / `AS BOOL` on LoT `NULL` are 0 / false, except inside `TRY` or an action with `ON ERROR`, where they raise (`NULL cannot be converted AS INT (PAYLOAD.missing)`). `AS STRING` yields `""`.
`NULL AS INT` (or any explicit type on a NULL literal) is refused at parse time — write untyped `SET "x" WITH NULL`. The parser's own message still says `SET x TO NULL`; that form parses, and it is not the one to write.
Clearing a variable that previously held `INT` / `DOUBLE` / `BOOL` with `SET "x" WITH NULL` is valid LoT: the hoist widens to `object`, reads after the clear yield LoT `NULL`, and `{x} == NULL` / `{x} != NULL` compile as null checks (never `ConvertToInt`/`ConvertToDouble`/`ConvertToBool` on null). Arithmetic on `x` before the clear still goes through the existing object/`Convert*` helpers.

```
SET "x" WITH NULL
SET report AS OBJECT = {}
SET report.k = NULL
KEEP TOPIC "cache/cleared" WITH NULL
PUBLISH TOPIC "events/cleared" WITH NULL
```

`KEEP` / `PUBLISH … WITH NULL` stringifies to an empty MQTT payload (`""`): KEEP writes `""` into the topic cache and does **not** clear an MQTT retained message on the wire.

### GET MODEL — fetch model data from a database route
```
SET "data" WITH GET MODEL "SensorData" FROM "MyDB" WHERE id EQUALS "sensor1"
PUBLISH TOPIC "sensors/result" WITH GET MODEL "SensorData" FROM "MyDB"
```
The query runs synchronously inside the action; with no matching row the result is an empty object.


## Connector status fields

Read curated RouteStatus for a connector registered on **this** node (in-memory; not via `$SYS`):

```lot
DEFINE ACTION WatchPlc
ON TOPIC "tick" DO
    IF plc_route.CONNECTED THEN
        PUBLISH TOPIC "plc/state" WITH plc_route.CONNECTION
    ELSE
        PUBLISH TOPIC "plc/state" WITH "down"
```

Fields (postfix-only; `SET CONNECTED WITH TRUE` is still a normal variable):
`CONNECTED` (BOOL), `CONNECTION`, `HEALTH`, `TYPE`, `ERRORS_TOTAL`, `ERRORS_CONSECUTIVE`, `ERRORS_RATE`,
`MESSAGES_TOTAL`, `MESSAGES_SUCCEEDED`, `MESSAGES_FAILED`, `LAST_ACTIVITY`, `LAST_SUCCESS_AT`,
`LAST_ERROR_AT`, `LAST_ERROR` / `LAST_ERROR_MESSAGE`, `UPTIME`, `CONNECTED_SINCE`, `WARNING`, `TIMESTAMP`.

- `CONNECTION` / `HEALTH` values are PascalCase (`Connected`, `Green`, …) and compared case-sensitively.
- Unknown / unregistered / remote-pinned connectors throw at runtime (catch with `TRY` / `ON ERROR`); a
  disabled connector throws `Connector 'X' is disabled`.
- `SET plc_route.CONNECTED …` is a parse error — status fields are read-only.
- `{name}` is always the variable; a `SET` binding does not shadow `plc_route.CONNECTED`.

## Topic Operations

### PUBLISH vs KEEP — When to Use Which

Use **PUBLISH** when the message should flow to external consumers:
- Sending data to database routes (route events listen on MQTT and fire on arrival)
- Sending alerts, events, or updates to dashboards and UIs
- Triggering other systems or services
- One-time notifications

Use **KEEP** when the value is shared internal state between actions:
- Storing a counter, mode flag, or last-known value that another action needs to read
- Values that actions read back with GET TOPIC without broadcasting to subscribers

KEEP stores the value in the broker cache without MQTT delivery. A later PUBLISH of the same topic replaces it and notifies subscribers.
PUBLISH delivers to current subscribers. It is not MQTT retain (TOPIC EXISTS does not see KEEP).

```
-- Use KEEP for state between actions:
DEFINE ACTION IncrementCounter
ON TOPIC "counter/increment" DO
    SET "current" WITH GET TOPIC "state/counter" AS INT
    KEEP TOPIC "state/counter" WITH {current} + 1

-- Use PUBLISH to drive routes, UIs, other systems:
DEFINE ACTION ForwardToDatabase
ON TOPIC "sensors/+/data" DO
    SET "zone" WITH TOPIC POSITION 2
    SET "val" WITH PAYLOAD AS DOUBLE
    PUBLISH TOPIC "db/insert/readings/" + {zone} WITH {val}
```

### PUBLISH TOPIC — non-retained, fires to current subscribers
```
PUBLISH TOPIC "output/data" WITH "value: " + {temp}
PUBLISH TOPIC "events/alert" WITH TIMESTAMP "ISO"
PUBLISH TOPIC "sensors/" + {zone} + "/processed" WITH {result}
PUBLISH TOPIC "output/state" WITH {state} RETAIN       -- optional MQTT retain flag
PUBLISH TOPIC "output/cmd" WITH {cmd} WITH RETAIN QOS1 -- optional RETAIN and QOS0/QOS1/QOS2
```
LoT has no JSON object literal (`WITH { "temp": {temp} }` is rejected). Build a structured
payload with PUBLISH MODEL (below) or return a dict from CALL PYTHON. Do not hand-build
JSON with escaped quotes (`"{\"a\": 1}"`) — a `\"` in a string literal fails to compile.
RETAIN / QOS apply to PUBLISH TOPIC only, never to KEEP TOPIC.

### PAYLOAD AS BYTES — forward binary payloads unchanged
```
DEFINE ACTION ForwardCameraFrame
ON TOPIC "cameras/+/frame" DO
    SET "cam" WITH TOPIC POSITION 2
    PUBLISH TOPIC "archive/cameras/" + {cam} + "/frame" WITH PAYLOAD AS BYTES
    KEEP TOPIC "state/cameras/" + {cam} + "/last" WITH PAYLOAD AS BYTES
```
Plain PAYLOAD goes through a UTF-8 string, which corrupts images, protobuf and other binary data.
`WITH PAYLOAD AS BYTES` on PUBLISH TOPIC or KEEP TOPIC passes the bytes through bit for bit. A string
transformation after it (`PAYLOAD AS BYTES TRIM`, FILTER, REPLACE) is a parse error, and an empty
payload is not published or kept.

### KEEP TOPIC — stored without broadcast, readable by GET TOPIC from any action
```
KEEP TOPIC "state/mode" WITH "running"
KEEP TOPIC "state/lastTemp" WITH {temp}
KEEP TOPIC "device/" + {id} + "/config" WITH {config}
```

Reading a KÉEPed value from another action:
```
SET "mode" WITH GET TOPIC "state/mode" AS STRING
SET "lastTemp" WITH GET TOPIC "state/lastTemp" AS DOUBLE
```

### KEEP ENV / KEEP SECRET — persist environment variables
```
KEEP ENV "COUNTER" WITH {counter} + 1
KEEP SECRET "API_KEY" WITH "sk-abc123"
```

### DELETE ENV / DELETE SECRET
```
DELETE ENV "OLD_CONFIG"
DELETE SECRET "OLD_KEY"
```

## Control Flow

### IF / THEN / ELSE
```
IF {temp} > 30 THEN
    PUBLISH TOPIC "alert" WITH "Hot!"
ELSE
    PUBLISH TOPIC "status" WITH "Normal"
```
Operators: ==, !=, >, <, >=, <=, AND, OR, CONTAINS, MATCHES REGEX "pattern", NOT MATCHES REGEX "pattern".
Word forms also work: EQUALS / IS (==), NOT EQUALS (!=), GREATER THAN / ABOVE (>), LESS THAN / BELOW (<).
Prefix `NOT` (also `ISN'T` / `AIN'T`) negates a boolean value or comparison: `IF NOT {running} THEN …`,
`SET "stopped" WITH NOT {running}`. It binds below comparisons and above AND/OR (`NOT {a} == {b}` means
`NOT ({a} == {b})`). A null or missing/empty value under `NOT` raises (no coerce to `false`).
There is no STARTS_WITH / ENDS_WITH — use `MATCHES REGEX "^abc"` /
`MATCHES REGEX "abc$"`. Do not compare a number with TRUE/FALSE (type mismatch at deploy).

```
DEFINE ACTION GateByFlag
ON TOPIC "machine/cmd" DO
    SET "running" WITH TRUE
    SET "stopped" WITH NOT {running}
    IF NOT {running} THEN
        PUBLISH TOPIC "machine/state" WITH "Stopped"
    ELSE
        PUBLISH TOPIC "machine/state" WITH "OK"
```

### ELSE IF — multi-way branch
```
IF {status} == "on" THEN
    PUBLISH TOPIC "led" WITH "1"
ELSE IF {status} == "off" THEN
    PUBLISH TOPIC "led" WITH "0"
ELSE
    PUBLISH TOPIC "led" WITH "unknown"
```
`ELIF` is accepted as a synonym for `ELSE IF`.

### SWITCH — match one value against several (also SELECT)
```
SWITCH {status}
    CASE "on" THEN
        PUBLISH TOPIC "led" WITH "1"
    CASE "off" THEN
        PUBLISH TOPIC "led" WITH "0"
    DEFAULT THEN
        PUBLISH TOPIC "led" WITH "unknown"
```
The subject is read once and compared with `==` to each CASE in order; the first match runs and
DEFAULT (optional, always last) runs when none does. Use `SWITCH PAYLOAD AS INT` to compare numbers.
There is no fall-through. To iterate over an array, object or string, use `FOR … IN` (below).

### REPEAT … UNTIL — loop (also LOOP / ITERATE)
```
SET "i" WITH 0
REPEAT
    SET "i" WITH {i} + 1
UNTIL {i} >= 3
```
The body runs before the condition is checked. A loop that reaches 1,000,000 iterations (the default
`LotRuntime.MaxLoopIterations`) without UNTIL holding raises `LOOP exceeded 1000000 iterations`, which
`TRY` / `CATCH` or `ON ERROR` can handle.

### FOR … IN and WHILE — iteration
```
DEFINE ACTION SumReadings
ON TOPIC "line/1/batch" DO
    SET "total" WITH 0
    FOR reading IN PAYLOAD.values
        IF {reading} < 0 THEN
            CONTINUE
        SET "total" WITH {total} + {reading}
    PUBLISH TOPIC "line/1/batch/total" WITH {total}
```
`FOR <var> IN <iterable>` (synonym `FOR EACH <var> IN`) binds `{var}` to each **element** of an
array, each own key (as a string) of an object, or each character of a string. A variable
declared `AS ARRAY OF DOUBLE` keeps DOUBLE elements, so `{reading} + 1` is not truncated.
A STRING is a string even when its text looks like JSON: `FOR c IN PAYLOAD` with payload `[1,2]`
visits 5 characters. A member path used directly (`FOR v IN PAYLOAD.values`) iterates the
array, or the keys of the object, it selects; `PAYLOAD AS ARRAY` or `SET a AS ARRAY = PAYLOAD.values`
gives an ARRAY you can keep in a variable. Each iteration may allocate at most 64 MB (`WHILE iteration
exceeded the 64 MB loop memory limit`), so a body like `SET s WITH {s} + {s}` stops with a catchable error.
`FOR` and `WHILE` raise `FOR exceeded 1000000 iterations` / `WHILE exceeded 1000000 iterations` at the cap.
These limits are broker settings (`LotRuntime.MaxLoopIterations`, `LotRuntime.LoopMemoryBytes`).
Every action run has a wall clock (`LotRuntime.ActionTimeoutSeconds`, default 30 s;
0 turns it off) that raises `LotActionTimeoutException` (`ERROR.CODE`) — blocking calls such as CALL PYTHON,
CALL LLM or CALL AGENT included.
A broker may also refuse WHILE / FOR / LOOP entirely (`Construct 'WHILE' is disabled on this broker`).

`SET tags AS ARRAY OF INT = [1, 2]` checks every element when the variable is set and at each
`.APPEND` on it: `ARRAY OF INT 'tags': element [2] is STRING "x", not INT`. INT takes whole numbers,
DOUBLE takes any number (INT widens), STRING / BOOL / OBJECT take only their type; NULL never matches.
`WHILE <condition>` repeats while the condition holds. `BREAK` leaves and `CONTINUE` skips to the
next iteration of the innermost `FOR` / `WHILE` / `LOOP`. Each loop is capped at 1,000,000 iterations
by default: exceeding it raises `FOR exceeded 1000000 iterations` (or `WHILE …`), catchable by `TRY` / `CATCH`
and `ON ERROR`. An empty loop body is a parse error.

## String Transformations

### FILTER (regex extraction)
```
SET "digits" WITH FILTER PAYLOAD USING REGEX "[0-9]+"
```

### REPLACE
```
SET "clean" WITH REPLACE "\n" WITH " " IN PAYLOAD
```
The source after IN is PAYLOAD, a variable, or a string. `IN RESULT` is only valid inside a chain.

### TRIM
```
SET "text" WITH PAYLOAD TRIM
```
TRIM takes no argument and trims the value before it — `TRIM PAYLOAD` is rejected.

### AND THEN (chaining)
```
SET "result" WITH FILTER PAYLOAD USING REGEX "[0-9]+" AND THEN TRIM
SET "tidy" WITH FILTER PAYLOAD USING REGEX "[a-z ]+" AND THEN REPLACE " " WITH "_" IN RESULT
```
The chain keyword is two words, `AND THEN` (`AND_THEN` is rejected). Start the chain with
FILTER or REPLACE; RESULT refers to the output of the previous step.

## Expressions

### Arithmetic: +, -, *, /, %
```
SET "result" WITH {a} + {b} * 2
```
Two integers divide as integers (`10 / 4` is `2`). Make an operand a decimal (`10.0 / 4`) or read it
`AS DOUBLE` to keep the fraction; `10 / 4 AS DOUBLE` casts a result that is already `2`.
Text in arithmetic must be a number: `PAYLOAD * 2` with payload `abc` (or `""`, or `1,5`) raises
`Cannot use 'abc' in math: not a number`; it never reads as 0. `+` joins when either side is a STRING
(a string literal, a STRING variable, `AS STRING`) and adds otherwise, so `PAYLOAD + 1` with payload
`4` is `5` while `PAYLOAD + "1"` is `41`. INT is 32-bit: INT arithmetic that overflows raises
(`Arithmetic operation resulted in an overflow.`), as does `AS INT` outside the 32-bit range inside `TRY` (elsewhere it is `0`);
`IS INT` is true only for text in that range.

### Casts with AS
`AS INT` / `AS DOUBLE` / `AS BOOL` follow the "TRY decides" rule (see **Language version** above).
Outside `TRY`, and outside an action with `ON ERROR`, they never raise: a missing, blank or non-numeric
value is `0` / `0.0` / `false`, and `AS BOOL` is TRUE for `true`, `yes`, `on` (any case) and any non-zero
number. Inside `TRY` or an action with `ON ERROR`, NULL, empty text and non-numeric text raise
(`Cannot convert 'abc' to INT`, `NULL cannot be converted AS INT`), an INT outside the 32-bit range raises,
and `AS BOOL` accepts only `true`, `false`, `1` or `0` (any case, trimmed) and raises otherwise.
A fraction truncates toward zero everywhere: `"3.9" AS INT` and `3.9 AS INT` are `3`, `-3.9 AS INT` is `-3`.
A BOOL converts: TRUE → 1 / 1.0, FALSE → 0 / 0.0.
`AS ARRAY` turns text holding a JSON array into an ARRAY and raises otherwise (`Cannot convert 'abc' to ARRAY`), in any scope.

```
DEFINE ACTION ReadSetpoint
ON TOPIC "line/1/setpoint" DO
    SET "loose" WITH PAYLOAD AS INT
    TRY
        SET "sp" WITH PAYLOAD AS INT
        KEEP TOPIC "line/1/setpoint/ok" WITH {sp}
    CATCH
        PUBLISH TOPIC "line/1/setpoint/error" WITH ERROR.MESSAGE
```

### String methods

Postfix string methods on a **clear receiver** only: braced `{s}.TRIM`, `PAYLOAD.TRIM`, a string
literal (`"hi".LENGTH`), or a parenthesised expression such as `(GET TOPIC "t").TRIM` or
`PAYLOAD.raw.UPPER`. A bare name the action has bound (a SET target, INPUT, RETURN name or FOR
variable) is a receiver too (`report.UPPER` is `{report}.UPPER`); an unbound bare name (`device.TRIM`)
stays a field path. Method names are **UPPERCASE** only: a lowercase name after a dot is a member
read (`{x}.trim` reads the key `trim`).
Zero-arg forms take no parentheses; argument forms use `(…)`. Math and string suffixes share one
postfix band — number-returning string methods may chain into math (`{s}.LENGTH.ABS`, `{s}.TRIM.LENGTH.CLAMP(0,10)`); math must not chain into string (`{x}.ROUND(1).LENGTH` / `{n}.ABS.UPPER` are parse errors).

| Method | Result | Notes |
|---|---|---|
| `.UPPER` / `.LOWER` | STRING | Culture-invariant |
| `.TRIM` | STRING | Leading/trailing whitespace |
| `.LENGTH` | INT | UTF-16 code units (`.NET string.Length`) |
| `.REPLACE(old, new)` | STRING | All occurrences; empty `old` is a runtime error (ON ERROR) |
| `.CONTAINS(s)` / `.STARTS_WITH(s)` / `.ENDS_WITH(s)` | BOOL | Ordinal comparison |
| `.SPLIT(sep)` | ARRAY of STRING | Empty `sep` is a runtime error |
| `.SLICE(start, end)` | STRING | `[start, end)` exclusive end; out-of-range clamped |
| `.MATCH(regex)` | BOOL | .NET dialect; 100 ms timeout; no-match → false; invalid/timeout → runtime error |
| `.EXTRACT(regex)` | STRING | First match, or `""`; same regex rules as `.MATCH` |

`GET TOPIC "t".TRIM` binds `.TRIM` to the topic string; write `(GET TOPIC "t").TRIM` for the payload.
After a member, an ALL-CAPS method applies to that member (`PAYLOAD.name.UPPER`). Inside an explicit
`.JSON.` path, a name after a dot (including method names and keywords) is read as a key, except a
final `.DELETE` — use `(PAYLOAD.JSON.t).UPPER` there.
Chaining is allowed: `{name}.TRIM.UPPER.SLICE(0, 2)`. Prefer these over `CALL PYTHON` for simple string transforms.
Infix `STARTS_WITH` / `ENDS_WITH` remain unimplemented; use the method forms.
**Null receivers and args** coerce to the empty string (`ConvertToString(null)` → `""`) — confirmed 2026-10-29.
A STRING receiver is text even when it holds JSON: with payload `[1,2]`, `PAYLOAD.LENGTH` is 5 and
`PAYLOAD.CONTAINS("1,")` is TRUE. `.LENGTH` / `.CONTAINS` / `.SLICE` count elements only on an ARRAY
(an ARRAY variable, `.SPLIT`, `.KEYS`, `AS ARRAY`, or a member path that selects an array such as
`PAYLOAD.values.LENGTH`). Methods that exist only for arrays (`[i]`, `.FIRST`, `.SUM`, …)
parse JSON-array text, since a string has no such meaning.
Datetime results chain: INT results (`.YEAR` … `.DAY_OF_WEEK`, `.DAY_OF_YEAR`, `.TO.INT`) take math
methods (`{ts}.YEAR.ABS`) and STRING results (`.FORMAT(…)`, `.TO.STRING`) take string methods
(`{ts}.FORMAT("MM").UPPER`); no parentheses needed.

Datetime values are all in UTC: `.DAY_OF_WEEK` is an INT, 1 (Monday) to 7 (Sunday).
An epoch number is **Unix milliseconds**: `.TO.INT` gives ms, `TIMESTAMP.NOW.UNIX` gives ms, and a
number (or whole-number text) read as a TIMESTAMP (`AS TIMESTAMP`, `TIMESTAMP.FROM(…)`) is ms.
`IS TIMESTAMP` accepts a number only in the ms range 2000–2100 (as text, a whole number only). (The 2.22 `TIMESTAMP "UNIX"` keeps seconds.)
`.FORMAT(pattern)` fields: `yyyy`, `yy`, `MM`, `M`, `dd`, `d`, `HH`, `H`, `mm`, `m`, `ss`, `s`, `fff`
(single letters are not zero-padded). Any other character is kept as written, so
`{ts}.FORMAT("yyyy-MM-ddTHH:mm")` keeps the `T`; quote words that contain field letters
(`"HH:mm 'Status'"`). No pattern raises; `YYYY` / `DD` are not fields and stay as text.

### Math methods

Postfix numeric methods on a **clear receiver** only: braced `{x}.ABS`, `PAYLOAD.ABS`, a member
(`PAYLOAD.temp.ABS`), a bound local, a numeric literal, or a parenthesised expression such as
`({a}+{b}).ROUND(1)` or `(GET TOPIC "t").ABS`. An unbound bare name (`building.floor`, `x.log`) stays a
field path. Method names are **UPPERCASE** only (`.ABS`, not `.abs`). Zero-arg forms take no parentheses;
argument forms use `(…)`. `.ABS`, `.ROUND`, `.CEIL`, `.FLOOR` and `.CLAMP` give an
INT when the receiver (and every CLAMP bound) is an INT, a DOUBLE otherwise; a receiver whose type is
known only at run time (`PAYLOAD.ABS`) counts as DOUBLE. `.SQRT`, `.POW`, `.LOG`, `.LOG10` and the
trigonometry methods always give a DOUBLE. `.SIN`, `.COS` and `.TAN` take **radians**, and `.ASIN`,
`.ACOS` and `.ATAN` return radians. Shares the postfix band with string methods.

| Method | Example | Edge behaviour |
|---|---|---|
| `.ABS` | `{temp}.ABS` | |
| `.ROUND` / `.ROUND(n)` | `{temp}.ROUND(2)` | `.ROUND` is `.ROUND(0)`. Midpoints AwayFromZero (`2.5` → `3`, `-2.5` → `-3`); a negative `n` rounds to tens, hundreds (`1250.ROUND(-2)` → `1300`) |
| `.CEIL` / `.FLOOR` | `{temp}.CEIL` | |
| `.CLAMP(min, max)` | `{temp}.CLAMP(0.0, 100.0)` | `min > max` raises a LoT runtime error (ON ERROR catchable) |
| `.SQRT` / `.POW(n)` | `{x}.SQRT` / `{x}.POW(2)` | Negative `.SQRT` → NaN (does not error) |
| `.LOG` / `.LOG10` | natural / base-10 log | Negative → NaN; `0` → `-Infinity` (does not error) |
| `.SIN` / `.COS` / `.TAN` | `{angle}.SIN` (radians) | |
| `.ASIN` / `.ACOS` / `.ATAN` | `{ratio}.ASIN` (result in radians) | Outside -1..1, `.ASIN` / `.ACOS` → NaN |
| `.SIN_DEG` / `.COS_DEG` / `.TAN_DEG` | `{deg}.SIN_DEG` (degrees in) | Exact at the usual angles (`180.SIN_DEG` → `0`) |
| `.ASIN_DEG` / `.ACOS_DEG` / `.ATAN_DEG` | `1.ASIN_DEG` → `90` (degrees out) | Result is in degrees |

Numeric functions are written with parentheses:

| Function | Returns | Notes |
|---|---|---|
| `MIN(a, b, …)` / `MAX(a, b, …)` | INT when every argument is INT, else DOUBLE | Two or more arguments (`MIN takes two or more arguments`) |
| `ATAN2(y, x)` | DOUBLE | Angle of the point (x, y) in radians. Exactly two arguments |
| `ATAN2_DEG(y, x)` | DOUBLE | Same, in degrees |

`MIN(…)` / `MAX(…)` with a parenthesis are these functions; `MIN OF TOPIC …` is still the topic
aggregate. Use the radian forms (`.SIN`, `ATAN2`) when the angle is already in radians, and the `_DEG` forms when it is in degrees.

A null or missing numeric receiver raises (no coerce to `0`); same for null in numeric
arithmetic (`SET "x" WITH NULL` then `{x} + 1`). `+` with a string operand stays concatenation.

`GET TOPIC "t".ABS` binds `.ABS` to the topic string; write `(GET TOPIC "t").ABS` for the payload.
Inside an explicit `.JSON.` path every segment is a key — use `(PAYLOAD.JSON.t).ABS` there, or the
short form `PAYLOAD.t.ABS`. Chaining is allowed: `{temp}.ABS.SQRT`. Prefer these over `CALL PYTHON` for simple numeric transforms.


### String concatenation
```
SET "msg" WITH "Temperature: " + {temp} + "°C"
```

### String interpolation — `${...}` (same result as `+`)
```
PUBLISH TOPIC "devices/${device_id}/status" WITH "online"
SET "msg" WITH "Temperature: ${temp}°C, next ${{count} + 1}"
```
`"a${x}b"` is exactly `("a" + ({x}) + "b")`: same stringification as `+` (NULL becomes empty text,
a BOOL `True`/`False`, JSON its raw text), and two numbers join (`"${a}${b}"` with 1 and 2 is `12`).
Both styles work and can be mixed in one expression; `+` stays the default in examples. Inside
`${...}` put one expression with no double quote: a bare name is `{name}`, anything else keeps its
normal meaning (`${PAYLOAD}`, `${TOPIC POSITION 2}`, `${reading.temp}`). Write `\$` for a literal
`$` (`\${` keeps `${` as text; a bare `$` needs no escape). Interpolation applies only where a string is an expression (PUBLISH/KEEP TOPIC, WITH, SET,
GET TOPIC, IF, CALL arguments). Trigger topics, model topics, GET JSON/ENV/SECRET names, TIMESTAMP
formats, REGEX patterns, REPLACE text, CALL PYTHON/MCP names and `SUM OF TOPIC "filter"` stay literal.

### RANDOM
```
SET "id" WITH RANDOM UUID
SET "roll" WITH RANDOM INT BETWEEN 1 AND 6
SET "val" WITH RANDOM DOUBLE BETWEEN 0.0 AND 1.0
```

### TIMESTAMP
```
SET "now" WITH TIMESTAMP "ISO"        -- 2026-01-31T14:05:09.123Z
SET "utc" WITH TIMESTAMP "UTC"        -- 2026-01-31 14:05:09
SET "unix" WITH TIMESTAMP "UNIX"      -- seconds since epoch
SET "ms" WITH TIMESTAMP "UNIX-MS"     -- milliseconds since epoch
SET "day" WITH TIMESTAMP "yyyy-MM-dd" -- any other string is a .NET date format
```
All timestamps are UTC; there is no local-time format. An unrecognised string is used as a
.NET custom format, so a typo yields odd text rather than an error.

## Integration Calls

### CALL ACTION — invoke another action
```
CALL ACTION "CalcAvg" WITH value1 = {a}, value2 = {b} RETURN avg
```
Unlike CALL PYTHON, the one-line form is valid here. For long argument lists, WITH and RETURN may also go
on indented lines; several outputs are comma-separated after RETURN:
```
DEFINE ACTION CheckBoilerTemp
ON TOPIC "boiler/+/temp" DO
    SET "temp" WITH PAYLOAD AS DOUBLE
    CALL ACTION AnalyzeReading
        WITH value = {temp}, threshold = 85
        RETURN is_above, difference, percentage
    IF {is_above} == TRUE THEN
        PUBLISH TOPIC "boiler/" + TOPIC POSITION 2 + "/alarm" WITH "over by " + {difference}
```
(`AnalyzeReading` is the callable from "Callable actions" above.) The callable must be deployed first (deploy fails with "Callable action … not found").
Calling the same callable twice in one action currently fails to compile — split it.


### ON ERROR — handle runtime failures

Sibling of `DO` at column 0 (after `RETURN` / `OUTPUT` on callables). At most one non-empty handler per site; empty `ON ERROR` is a parse error.

```
DEFINE ACTION SafeDivide
INPUT a AS INT
INPUT b AS INT
DO
    SET "result" WITH {a} / {b}
RETURN
    OUTPUT result
ON ERROR
    PUBLISH TOPIC "math/errors" WITH ERROR.MESSAGE
    SET "result" WITH 0
```

Triggered actions:

```
DEFINE ACTION SensorRead
ON TOPIC "sensors/+/data" DO
    PUBLISH TOPIC "out" WITH PAYLOAD
ON ERROR
    PUBLISH TOPIC "error_log" WITH ERROR.MESSAGE
```

- `ERROR.MESSAGE`, `ERROR.CODE`, `ERROR.SOURCE` are only valid inside the handler or a `CATCH` body (deploy-time error otherwise).
- `SOURCE` format: `action:Name`, `model:X`, or `route:Y/event`. `CODE` is implementation-defined (exception type name today).
- After the handler: rest of `DO` aborts; handled errors are **not** re-raised to `CALL ACTION`; unbound `OUTPUT`s are null unless the handler `SET`s them.
- The broker always publishes `$SYS/Coreflux/Actions/<name>/Error` (even when handled).
- Handler failure does not re-enter `ON ERROR` (system stream only).
- Catches runtime errors that escape the primary body (including member-access failures), not DEFINE-time validation errors.
- Adding `ON ERROR` makes the action body behave like one `TRY`: a cast that cannot convert (`"abc" AS INT`,
  NULL `AS DOUBLE`, `"maybe" AS BOOL`) and a failed `CALL PYTHON` raise and reach the handler instead of
  giving `0` / `false` / NULL. The handler body itself keeps the lenient rules.
- `ERROR.MESSAGE` / `ERROR.CODE` name the underlying failure (a connector timeout reads `TimeoutException`,
  not an `AggregateException` wrapper).
- A route `ADD EVENT … ON ERROR` handler sees the `PAYLOAD` and `TOPIC POSITION n` of the message that
  triggered the failed event (NULL / empty for a scheduled event).
- A model with `ON ERROR` waits for its `STORE IN` writes, so a missing (`Route not found: X`), disabled
  (`Connector 'X' is disabled`) or failing connector reaches the handler; the same holds for
  `PUBLISH MODEL` inside `TRY` or in an action with `ON ERROR`. Without a handler STORE stays
  fire-and-forget and a failure is only logged.


### TRY / CATCH — recover inside DO without aborting the action

Logic-level recovery **inside** an ACTION `DO` (including nested `IF` / `LOOP` / `SWITCH`). Not allowed in models, route events, `ON ERROR`, or inside `CATCH`.

```
DEFINE ACTION sensorRead
ON TOPIC "sensors/+/data" DO
    TRY
        PUBLISH TOPIC "sensors/" + TOPIC POSITION 1 + "/processed_data" WITH PAYLOAD
    CATCH
        PUBLISH TOPIC "error_log" WITH "Error sending payload with payload: " + PAYLOAD + " and error: " + ERROR.MESSAGE
    PUBLISH TOPIC "sensors/done" WITH "ok"
```

- Empty `TRY` or empty `CATCH` is a parse error. `TRY` in a model, route event, `ON ERROR`, or `CATCH` is a deploy-time parse error.
- A caught error does **not** publish `$SYS/.../Error`, does **not** run `ON ERROR`, does **not** call `ActionTracer.RecordError`, does **not** update `_lastErrors`, and does **not** bump FleetMetrics. After a successful `CATCH`, the rest of `DO` continues.
- An error raised inside `CATCH` escapes (no re-entry) to an outer `TRY`, else `ON ERROR` / `$SYS`.
- `ERROR.MESSAGE` / `CODE` / `SOURCE` are readable in `CATCH` (same meanings as `ON ERROR`).
- `DOUBLE / 0` yields `Infinity` and does **not** enter `CATCH`. Hard exceptions (`INT / 0`, status-read failures, math/string method domain raises) do. `WITH` argument evaluation errors on a `CALL ACTION` inside `TRY` are catchable.
- Genuine cancellation (`OperationCanceledException` / token-linked cancel) is **not** catchable by `TRY` or `ON ERROR`. HttpClient-style operation timeouts (`TaskCanceledException` with inner `TimeoutException`) **are** catchable via `LotCancellation.IsGenuineCancellation`. A first-run generated-C# compile failure is deploy/compile-class and is not catchable. `RegexMatchTimeoutException` remains catchable.
- A callee with its own `ON ERROR` swallows; the caller's `TRY` does not see that failure. When the caller's `TRY` catches a callee **without** `ON ERROR`, receiving `RETURN` / `OUTPUT` vars are **`NULL` after `CATCH`** unless later code `SET`s them.
- Side effects already completed in `TRY` before the failing statement (including `PUBLISH` / `KEEP`) are **not** rolled back.
- Inside the `TRY` body, casts and `CALL PYTHON` raise on failure (see **Language version**); the `CATCH`
  body keeps the lenient rules. The rule is lexical: an action called with `CALL ACTION` from inside `TRY`
  follows its own `TRY` / `ON ERROR`, though its errors still reach the caller's `TRY`.

### CALL PYTHON — invoke a Python function
```
CALL PYTHON "utils.calculate"
    WITH ({value})
    RETURN AS {result}
```
Format: "scriptName.functionName". Script must be deployed with broker.add_python first.
WITH and RETURN AS go on their own indented lines under CALL PYTHON. The one-line form
`CALL PYTHON "utils.calculate" WITH (...) RETURN AS {result}` is rejected by the parser.
The same indented layout applies to CALL MCP, CALL LLM and CALL AGENT.

### CALL MCP — invoke an MCP tool
```
CALL MCP "MyMcpRoute.search"
    WITH (query = "test")
    RETURN AS {result}
```
"RouteName.ToolName" in one string; named arguments inside parentheses. There is no TOOL keyword:
`CALL MCP "MyMcpRoute" TOOL "search"` is rejected (the string must contain exactly one dot).

To find the tool names and their parameters, read the retained topics the MCP connector publishes once
it connects: `$SYS/Coreflux/Routes/<Route>/Tools` (summary with the `tools` list) and
`$SYS/Coreflux/Routes/<Route>/Tools/<tool>` (description and `parameters`). Its `usage_example` and
`trigger_example` fields are ready to paste.

### CALL LLM — invoke an LLM route
```
CALL LLM "MyLlm.generate"
    WITH (prompt = "Summarize: " + {data})
    RETURN AS {answer}
```

### CALL AGENT — invoke an agent
```
CALL AGENT "MyAgent.execute"
    WITH (task = "Analyze data")
    RETURN AS {result}
```

### TRIGGER — trigger a route event
```
TRIGGER "MyDB" TO "sensor1" FOR "ReadSensors"
```
Order: connector name, TO the data to send, FOR the route event/mapping name. `WITH` is accepted in place of `TO`, but the data still comes before `FOR`. Writing the event name first and the data after `FOR` still parses, but sends the event name as the data to an event named after the data.

## PUBLISH MODEL — publish a model instance
```
PUBLISH MODEL SensorData TO "output/data" WITH
    temperature = {temp}
    status = "active"
```

On a protobuf model, `REPLACE` between the name and `TO` / `WITH` publishes a fresh
message and does not merge the previous bytes on that topic. Without `REPLACE`,
protobuf publish still merges. JSON publish merges either way.

```
PUBLISH MODEL Sp2ServerAudio REPLACE TO "sp2/server/audio" WITH
    payload_type = 2
    session_id = {session_id}
```

## Python Integration

Use Python when LOT expressions aren't enough: statistics, complex string manipulation,
JSON reshaping, external library math, or multi-step data processing.

### Step 1 — Write and deploy the script (once)
Every script MUST have `# Script Name: <Name>` in the first 10 lines.
Deploy with `broker.add_python(argument=...)` — the argument is the whole script, header included;
the name is read from the header (letters, digits, `_`; must not start with a digit).
In a project (`.lotnb`), Python cells load after the actions; project loading is covered by `broker-operations`.

```python
# Script Name: SensorUtils

import json, statistics

def analyze(readings_json):
    """Return mean/min/max for a JSON array of numbers."""
    readings = json.loads(readings_json) if isinstance(readings_json, str) else readings_json
    if not readings:
        return {"success": False, "error": "empty"}
    return {
        "success": True,
        "mean":   round(statistics.mean(readings), 2),
        "min":    min(readings),
        "max":    max(readings),
        "count":  len(readings)
    }

def classify(value, low, high):
    """Return 'low', 'normal', or 'high' based on thresholds."""
    v = float(value)
    if v < float(low):   return "low"
    if v > float(high):  return "high"
    return "normal"
```

### Step 2 — Call from a LOT action
```
DEFINE ACTION AnalyzeSensorBatch
ON TOPIC "sensors/batch" DO
    SET "readings" WITH PAYLOAD
    CALL PYTHON "SensorUtils.analyze"
        WITH ({readings})
        RETURN AS {stats}
    PUBLISH TOPIC "sensors/stats" WITH {stats}

DEFINE ACTION ClassifyReading
ON TOPIC "sensors/+/temp" DO
    SET "temp" WITH PAYLOAD AS DOUBLE
    CALL PYTHON "SensorUtils.classify"
        WITH ({temp}, 15, 75)
        RETURN AS {level}
    IF {level} == "high" THEN
        PUBLISH TOPIC "alerts/temp" WITH "HIGH: " + {temp}
```

### Rules for CALL PYTHON
- Format: `CALL PYTHON "ScriptName.function_name"`, then `WITH (arg1, arg2)` and
  `RETURN AS {result}` each on its own line indented under it
- Arguments are positional — order must match the function signature
- Pass scalars or variables. An array literal argument (`WITH ([1, 2, 3])`) fails to compile;
  pass an ARRAY variable instead. ARRAY values (and `.KEYS`) arrive as a Python `list`,
  OBJECT values as a `dict`, on both the embedded and the runner path. PAYLOAD and untyped values
  arrive as Python `str`; use `AS DOUBLE` / `AS INT` in LoT or `float()` in Python
- RETURN AS is a JSON string. A Python dict / list / number / bool is serialized
  automatically — do not require json.dumps(). A Python str (including json.dumps output)
  is kept as-is. A Python `None` returns LoT NULL: `{result} EQUALS NULL` and
  `{result} EQUALS EMPTY` are both true. `IsBlank` is null or `""`, so `""` matches only
  `EQUALS EMPTY`, not `EQUALS NULL`. Never the text "null".
  A failing call (Python exception, missing module or function, no runtime, or a wait that hits the
  action wall clock) inside `TRY`, or in an action with `ON ERROR`, raises (`CALL PYTHON mod.fn failed: …`)
  into CATCH or the handler. Anywhere else the failure is logged, the RETURN variable is NULL, and the
  action continues. Wrap the call in `TRY` when the action must not go on without a result.
  A top-level Python `bytes` return is plain base64 (nested bytes stay quoted base64 strings).
- Read fields with `{result}.key`. A missing key is LoT NULL. AS INT / DOUBLE / BOOL on it are 0 / false,
  except inside `TRY` or an action with `ON ERROR`, where they raise.
- PUBLISH … WITH {result} sends that same JSON string.
- Script must be deployed with `broker.add_python` before calling it
- Imports: modules available without install (no missing-pip warning) include `math`,
  `statistics`, `json`, `datetime`, `collections`, `re`, `csv`, `hashlib`, `base64`, `struct`,
  and other stdlib. The broker does not restrict imports. Third-party packages must be
  installed with `broker.install_python_package` first; a script whose top-level import is
  missing is rejected by add_python ("Python import failed")

### Parsing the returned JSON in LOT
```
DEFINE ACTION ProcessStats
ON TOPIC "sensors/run" DO
    SET "raw" WITH GET TOPIC "sensors/batch/data"
    CALL PYTHON "SensorUtils.analyze"
        WITH ({raw})
        RETURN AS {stats}
    SET "ok" WITH {stats}.success AS BOOL
    IF {ok} EQUALS TRUE THEN
        SET "avg" WITH {stats}.mean AS DOUBLE
        SET "lo" WITH {stats}.min AS DOUBLE
        SET "hi" WITH {stats}.max AS DOUBLE
        PUBLISH TOPIC "sensors/summary" WITH {stats}
        IF {hi} > 90 THEN
            PUBLISH TOPIC "alerts/overtemp" WITH "Max: " + {hi}
```

### PUBLISH MODEL + Python (combined pattern)
```
DEFINE MODEL SensorAnalysis COLLAPSED
    ADD STRING "timestamp"    WITH TIMESTAMP "UTC"
    ADD STRING "zone"
    ADD DOUBLE "mean"
    ADD DOUBLE "min"
    ADD DOUBLE "max"
    ADD STRING "status"

DEFINE ACTION AnalyzeZone
ON TOPIC "zones/+/readings" DO
    SET "zone" WITH TOPIC POSITION 2
    SET "raw" WITH PAYLOAD
    CALL PYTHON "SensorUtils.analyze"
        WITH ({raw})
        RETURN AS {stats}
    SET "avg" WITH {stats}.mean AS DOUBLE
    SET "lo" WITH {stats}.min AS DOUBLE
    SET "hi" WITH {stats}.max AS DOUBLE
    SET "status" WITH "normal"
    IF {hi} > 85 THEN
        SET "status" WITH "critical"
    PUBLISH MODEL SensorAnalysis TO "zones/" + {zone} + "/analysis" WITH
        zone   = {zone}
        mean   = {avg}
        min    = {lo}
        max    = {hi}
        status = {status}
```

## Complete Example — Sensor Monitor with Alerting
```
DEFINE ACTION SensorMonitor
ON TOPIC "factory/sensors/+/temperature" DO
    SET "zone" WITH TOPIC POSITION 3
    SET "temp" WITH PAYLOAD AS DOUBLE
    SET "ts" WITH TIMESTAMP "ISO"
    IF {temp} > 85 THEN
        PUBLISH TOPIC "factory/alerts/" + {zone} WITH "CRITICAL: " + {temp} + "°C at " + {ts}
        KEEP TOPIC "factory/alerts/" + {zone} + "/last" WITH {temp}
    ELSE
        IF {temp} > 70 THEN
            PUBLISH TOPIC "factory/warnings/" + {zone} WITH "WARNING: " + {temp} + "°C"
```

## Complete Example — Callable Conversion Utility
```
DEFINE ACTION CelsiusToFahrenheit
INPUT celsius AS DOUBLE
DO
    SET "fahrenheit" WITH {celsius} * 1.8 + 32
RETURN
    OUTPUT fahrenheit
```

## Common Mistakes

| WRONG | RIGHT | Why |
|-------|-------|-----|
| DEFINE ACTION "Heartbeat" | DEFINE ACTION Heartbeat | Action names are plain identifiers — no quotes |
| PUBLISH TOPIC "t" MESSAGE "v" | PUBLISH TOPIC "t" WITH "v" | MESSAGE is not valid here — use WITH |
| KEEP TOPIC "t" MESSAGE "v" | KEEP TOPIC "t" WITH "v" | Same — WITH, not MESSAGE |
| SET x TO "value" | SET "x" WITH "value" | Accepted, but quoted name + WITH is the canonical form |
| SET x "value" | SET "x" WITH "value" | SET requires WITH between name and value |
| TOPIC POSITION 0 | TOPIC POSITION 1 | 1-based; 0 deploys but yields an empty string |
| IF {x} > 5 | IF {x} > 5 THEN | IF always requires THEN |
| ON EVERY 10 SECONDS | ON EVERY 10 SECONDS DO | Trigger always requires DO |
| `DEFINE ACTION X\n    ON EVERY 1 SECONDS DO` | `DEFINE ACTION X\nON EVERY 1 SECONDS DO` | Trigger sits at column 0, NOT indented under DEFINE. Indenting the trigger creates a stray INDENT token before the trigger and the parser rejects the action. |
| temp (no braces) | {temp} | Variables always need curly braces |
| RETURN OUTPUT result | RETURN then OUTPUT result on separate lines | Single-line RETURN OUTPUT is rejected |
| RETURN OUTPUT a, b, c | RETURN then one OUTPUT per line | Comma-separated outputs are rejected |
| CALL PYTHON "S.f" WITH (x) RETURN AS {r} | WITH / RETURN AS on indented lines below | One-line CALL PYTHON/MCP/LLM/AGENT is rejected |
| SWITCH {x} / CASE "a" (no THEN) | CASE "a" THEN, block indented under it | Every CASE and DEFAULT needs THEN |
| PAYLOAD AND_THEN TRIM | PAYLOAD TRIM, or FILTER … AND THEN TRIM | Chain keyword is AND THEN (two words) |
| WITH { "k": {v} } | PUBLISH MODEL, or a dict from CALL PYTHON | No JSON object literal |
| PAYLOAD inside ON EVERY / ON START / ON CONNECT | GET TOPIC "…" AS DOUBLE | Only ON TOPIC / ON CHANGE have a message |
| CALL MCP "Route" TOOL "search" | CALL MCP "Route.search" (WITH / RETURN AS indented) | There is no TOOL keyword |
| PUBLISH … WITH PAYLOAD (binary data) | PUBLISH … WITH PAYLOAD AS BYTES | Plain PAYLOAD is decoded as UTF-8 text |

### Trigger indentation - the most common AI mistake

The trigger line (`ON EVERY ...`, `ON TOPIC ...`, `ON START`) MUST be at the
same column as `DEFINE ACTION`. Only the body is indented. Indenting the trigger
under `DEFINE ACTION` produces a stray INDENT token before the trigger and the
parser rejects the action.

```
-- WRONG: trigger indented under DEFINE (parser rejects with an unexpected INDENT)
DEFINE ACTION ToggleInput
    ON EVERY 1 SECONDS DO
        SET "current" WITH GET TOPIC "plc/input" AS BOOL
        IF {current} == true THEN
            PUBLISH TOPIC "plc/input" WITH false
        ELSE
            PUBLISH TOPIC "plc/input" WITH true

-- RIGHT: trigger at column 0, body indented 4 spaces
DEFINE ACTION ToggleInput
ON EVERY 1 SECONDS DO
    SET "current" WITH GET TOPIC "plc/input" AS BOOL
    IF {current} == true THEN
        PUBLISH TOPIC "plc/input" WITH false
    ELSE
        PUBLISH TOPIC "plc/input" WITH true
```

The same rule applies to every trigger type - `ON TOPIC`, `ON EVERY N <UNIT>`,
`ON EVERY <DAY> AT`, `ON START`. Callable actions use INPUT lines instead of ON.
When emitting the definition as a
JSON string, this means `\nON EVERY ...\n    BODY` - never `\n    ON EVERY ...\n        BODY`.
