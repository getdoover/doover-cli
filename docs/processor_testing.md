# Processor Testing Proposal

This note sketches a `doover` CLI system for testing processor, integration, and
report-generator applications from a local Doover project repository.

The goal is to test Python handler behavior locally while optionally using real
Doover Data as read-only input. The test runner should make it easy to exercise
every pydoover invocation shape without mutating production data unless the user
explicitly opts into a live write mode.

## Goals

- Run processor handlers locally from an unpublished project checkout.
- Exercise all pydoover handler entry points:
  - `on_message_create`
  - `on_aggregate_update`
  - `on_deployment`
  - `on_schedule`
  - `on_ingestion_endpoint`
  - `on_manual_invoke`
- Support integrations and report generators, not just generic processors.
- Support real production-like input data without writing processor output back
  to the server.
- Keep ad hoc CLI usage concise.
- Allow tests to be saved and reused in project files.
- Make dangerous live behavior explicit, especially for unpublished processors.

## Non-Goals

- Replacing `doover report compose`. That command composes a report using the
  older hosted-report-generator path. Processor testing should test the pydoover
  event path for report generators.
- Testing AWS Lambda infrastructure or deployed platform invocation paths. Live-local
  mode in this proposal still means local Python execution.
- Making production mutations by default.
- Providing a pytest integration in v1.
- Providing a formal assertion helper API in v1. V1 should run invocations and
  record output; test assertions can be designed after the runner behavior is
  stable.

## V1 Scope

The first implementation should support every pydoover invocation shape, because
the value of the tool is being able to test a processor the same way it can be
invoked in production.

V1 invocation support:

- `message_create`
- `aggregate_update`
- `deployment`
- `schedule`
- `ingestion`
- `manual_invoke`
- report generator schedule/manual flows
- local ingestion relay mode for testing webhook delivery against the local
  handler

V1 should not include deployed/platform invocation. All invocations still run
local Python.

V1 should also not include pytest generation or assertion helpers. Generated
files should run the invocation and return a result object containing logs,
recorded writes, generated files, status, and summary data. The CLI should print
the selected output view from that result.

V1 generated files should always use explicit environment setup:

```python
env = test.Environment()
env.data_client = test.processor.DataClient()
...
with env:
    result = await test.run(event)
```

Simple cases should still be concise through sensible defaults where a setting is
not relevant, but generated files should show the environment wiring so users can
edit the read, write, auth, and output behavior directly.

## Existing Platform Shape

Control creates processor resources from deployment config:

- `dv_proc_schedules` creates EventBridge schedule resources.
- `dv_proc_subscriptions` creates SNS subscriptions for message and aggregate
  events.
- `dv_proc_ingestion` creates Doover Data ingestion endpoints.
- deployment publishes an `on_deployment` SNS event.
- report generation can invoke `on_manual_invoke`.

Pydoover then normalizes all of those into a single event dispatch pipeline. This
means the CLI test runner can generate pydoover-compatible event payloads locally
without needing AWS resources for most tests.

## Execution Modes

### `local`

Runs the processor locally using fabricated test inputs.

Data setup:

- deployment config can come from local config export, CLI flags, or a saved
  test file.
- tag values, UI state, UI commands, channel aggregate, and message data can be
  supplied inline or from local JSON files.

Write behavior:

- no real writes.
- write calls are captured by a sandbox data client.

This mode should work for unpublished processors by default.

### `sandboxed-live`

Runs the processor locally, but fetches real setup/input data before invocation.

Data setup:

- use the user's CLI auth to fetch the application install, agent, deployment
  config, tag values, UI state, UI commands, connection data, latest channel
  aggregate, latest message, report metadata, or other requested fixture data.
- create an in-memory snapshot that looks like the pydoover processor upgrade
  payload.
- pass the snapshot into the local processor runner.

Write behavior:

- no processor writes are sent to Doover Data.
- write calls are captured with method, channel, agent, payload, files, and
  options.
- CLI output and returned result objects can inspect the captured writes.

This is the recommended default for production-adjacent testing.

### `live-local`

Runs the local processor, but treats it like a real processor with access to
real Doover Data reads and writes.

Data setup:

- use the user's CLI auth to fetch the same setup/input data as
  `sandboxed-live`.
- build the same local event payloads as `local` and `sandboxed-live`.
- run the local Python handler, not the deployed Lambda.

Write behavior:

- real writes can happen through the processor data client.
- because normal users likely cannot mint processor-equivalent scoped tokens,
  this mode will usually use the user's CLI token for real Data API calls.
- require `--writes allow` and a clear confirmation flag.
- if the processor application has not been published or does not match the
  selected install, require a bypass such as `--allow-unpublished`.

This mode is for checking local handler behavior while allowing real production
side effects. It is not a platform wiring test.

## Write Policies

Write policy should be orthogonal to execution mode.

### `record`

Default for `local` and `sandboxed-live`.

Processor write methods return plausible model objects but do not send HTTP
requests. The runner records attempted mutations.

Examples of recorded operations:

- `create_message`
- `update_message`
- `delete_message`
- `create_channel`
- `put_channel`
- `update_channel_aggregate`
- `delete_ingestion_endpoint`, if ever exposed through processor code
- file uploads attached to any write

Recorded writes should be rich typed objects, not only raw dictionaries. They
should still be easy to serialize for CLI output.

Example shape:

```python
RecordedWrite(
    method="update_channel_aggregate",
    agent_id=123456789,
    channel="status",
    data={"state": "running"},
    files=[],
    options={"log_update": True, "replace_keys": ["state"]},
    timestamp_ms=1780000000000,
)
```

Users should be able to inspect typed fields:

```python
for write in result.writes:
    print(write.method, write.channel, write.data)
```

and serialize them:

```python
result.writes.to_dicts()
```

### `block`

Fails the test when processor code attempts a write. This is useful when a test
is intended to prove that a handler is read-only.

### `allow`

Future mode for allowing writes to reach Doover Data from a locally running
processor. V1 should reject `--writes allow` until the live passthrough data
client and auth path are implemented.

## Read Policies

### `fixture`

All data comes from the test file or local files.

### `latest`

Fetch the latest message or aggregate from a real channel and use it as the test
event input.

### `snapshot`

Fetch a complete processor setup snapshot:

- deployment config for the app key
- tag values
- UI state
- UI commands
- connection data
- optionally selected channels/messages/timeseries

The snapshot can be cached to disk so the same test can be rerun offline.

### `mixed`

Use real setup data but override specific event fields or channel payloads from
CLI flags or test fixtures.

## Snapshot Schema

A snapshot is the local, serializable representation of the Doover Data state
needed to run a processor invocation. `sandboxed-live` should fetch real data
into a snapshot, then run the local processor against that snapshot with writes
captured or blocked.

Snapshots should be explicit, versioned, and safe to commit when generated in
fixture mode.

Proposed top-level shape:

```python
ProcessorSnapshot(
    schema_version=1,
    source=SnapshotSource(
        mode="sandboxed-live",
        generated_at="2026-06-19T05:00:00Z",
        doover_cli_version="0.3.2",
        profile="staging",
        command="doover processor test ...",
    ),
    app=SnapshotApp(
        local_name="digital_matter_integration",
        app_key="digital_matter_integration",
        app_id=123,
        app_install_id=456,
        app_install_name="Digital Matter Integration",
        type="integration",
    ),
    owner=SnapshotOwner(
        agent_id=123456789,
        organisation_id=987654321,
        is_org_processor=False,
    ),
    processor_info=SnapshotProcessorInfo(
        deployment_config={},
        tag_values={},
        ui_state={},
        ui_cmds={},
        connection_data={},
    ),
    channels={},
    messages={},
    timeseries={},
    files={},
)
```

The snapshot should be able to produce the pydoover `SubscriptionInfo`/upgrade
payload required by `Application._setup(...)`, but it should not store a real
bearer token by default. In sandboxed modes the token can be a sentinel value
owned by the test harness, because writes are intercepted and reads come from
the snapshot or controlled delegates.

### Required Fields

Every snapshot should include enough data to run `Application._setup(...)`:

- `agent_id`
- `organisation_id`
- `app_key`
- `deployment_config`
- `tag_values`
- `ui_state`
- `ui_cmds`
- `connection_data`
- a test token placeholder

For org processors/reports, `ui_state`, `ui_cmds`, and `connection_data` can be
empty/null in the same way Doover Data returns them.

### Optional Fixture Data

Optional sections should be selected by generated constants and
`use_live_snapshot(...)` parameters:

- `channels`: aggregate and metadata by channel name.
- `messages`: selected messages by channel and message id.
- `latest_messages`: selected latest messages by channel name.
- `timeseries`: channel/field/time-window datasets.
- `files`: downloaded attachments or generated file placeholders.
- `devices`: selected device IDs and optional device metadata.
- `device_map`: resolved `DEVICE_MAP` data when extended permissions request it.

### Secret Scrubbing

Snapshots and generated test files must not store:

- user bearer tokens
- refresh tokens
- ingestion endpoint tokens
- HMAC signing keys unless the user explicitly requests a local auth fixture
- private app config values marked secret
- raw headers that may contain credentials

If a value is needed to simulate auth locally, prefer a fake value:

```python
snapshot.ingestion.token = "test-token"
snapshot.processor_info.token = "test-processor-token"
```

### Mutation API

The snapshot returned by `use_live_snapshot(...)` should be a mutable Python
object. Users can modify it before entering the environment:

```python
snapshot = await env.data_client.reads.use_live_snapshot(
    agent_id=AGENT_ID,
    app_key=APP_KEY,
    channels=SNAPSHOT_CHANNELS,
    devices=DEVICE_IDS,
)

snapshot.processor_info.deployment_config["threshold"] = 42
snapshot.processor_info.tag_values.setdefault(APP_KEY, {})["enabled"] = True
snapshot.channels["telemetry"].aggregate.data["temperature"] = 21.5
```

The sandbox data client should read from the mutated snapshot, not from the
original fetched values.

Snapshot-loading helpers that may fetch from Doover Data or read snapshot files
should be async in generated examples. That keeps `use_live_snapshot(...)` and
`use_snapshot_file(...)` consistent.

### Snapshot Files

By default, `sandboxed-live` should fetch live data every time the test runs.
This keeps generated tests current and avoids accidentally treating old data as
truth.

Snapshots can still be saved explicitly for offline reruns or regression
fixtures. Saved snapshots should live beside the generated test in a
`snapshots/` folder:

```text
tests/doover/digital_matter_integration/
  latest_ingestion.py
  snapshots/
    latest_ingestion.snapshot.json
```

Local-only tests use the same relative shape under `.local`:

```text
.local/tests/doover/digital_matter_integration/
  latest_ingestion.py
  snapshots/
    latest_ingestion.snapshot.json
```

Example snapshot command:

```bash
doover processor test snapshot \
  --app-install "Digital Matter Integration" \
  --agent 123456789 \
  --channel telemetry \
  --output tests/doover/digital_matter_integration/snapshots/latest_ingestion.snapshot.json
```

Generated test files can then reference a snapshot file:

```python
snapshot = await env.data_client.reads.use_snapshot_file(
    "snapshots/latest_ingestion.snapshot.json"
)
```

Snapshot files should include their own generated metadata and content hash.
Like generated test file hashes, snapshot hashes should be advisory for
overwrite/change detection and should not prevent loading.

### Missing Data Policy

A "missing read" means processor code asks the data client for something that
was not included in the configured test data.

Examples:

- the processor calls `fetch_channel_aggregate("status")`, but `status` was not
  listed in `channels=`.
- the processor calls `list_messages("events")`, but no messages for `events`
  were loaded.
- the processor fetches an attachment that was not downloaded into the snapshot.
- a report asks for timeseries fields that were not selected.

Snapshot-backed reads should have an explicit missing-data policy:

```python
env.data_client.reads.delegate_missing(False)
```

Recommended defaults:

- `local`: missing snapshot/fixture reads fail.
- `sandboxed-live`: missing reads fail by default after the initial snapshot is
  collected.
- `live-local`: missing reads call Doover Data using the configured auth.

Users can opt into delegation for exploratory work:

```python
env.data_client.reads.delegate_missing(True)
```

## CLI-First Interface

V1 should expose a small command set:

- `doover processor test run`: run a saved Python test file, or run an ad hoc
  invocation from CLI flags. When `--save` or `--save-local` is passed, this
  command also writes the generated Python file.
- `doover processor test promote`: copy a local generated test into the tracked
  test tree.
- `doover processor test clone`: create a new test file from an existing test
  without overwriting it.
- `doover processor test snapshot`: create or refresh an explicit snapshot file.

There should not be a separate `generate` command in v1. Generation is a side
effect of `run` when the user passes the correct save flag.

Ad hoc runs should be possible without creating a file.

Example shapes:

```bash
doover processor test run message-create \
  --app-install pump-monitor \
  --channel telemetry \
  --latest \
  --mode sandboxed-live \
  --writes record
```

```bash
doover processor test run aggregate-update \
  --app-install pump-monitor \
  --channel status \
  --request-data '{"mode": "auto"}' \
  --mode sandboxed-live \
  --writes block
```

```bash
doover processor test run ingestion \
  --app-install webhook-ingest \
  --body ./fixtures/webhook.json \
  --content-type application/json \
  --mode local
```

```bash
doover processor test run report \
  --app-install monthly-report \
  --manual \
  --report-fixture ./fixtures/report-message.json \
  --mode sandboxed-live \
  --writes record
```

The `run` flags should map directly onto a generated Python test file so users
can move from ad hoc testing to repeatable tests without learning a second
model.

### CLI Output

CLI output should be selectable. The default should show useful logs during the
run and then a concise summary tailored to the invocation type.

Default output:

- processor logs emitted during setup and handler execution.
- final status: success, skipped, error.
- invocation type.
- selected app/install/agent.
- read source summary: fixture, live snapshot, snapshot file, or live.
- write summary: number of captured/blocked/allowed writes grouped by method and
  channel.
- generated files/output directory, when relevant.
- report output summary for report invocations.

Selectable output options could include:

```bash
doover processor test run tests/doover/app/latest_ingestion.py --output summary
doover processor test run tests/doover/app/latest_ingestion.py --output logs
doover processor test run tests/doover/app/latest_ingestion.py --output writes
doover processor test run tests/doover/app/latest_ingestion.py --output json
doover processor test run tests/doover/app/latest_ingestion.py --output all
```

The default should be equivalent to `--output logs,summary`.

## Generated Python Test Files

Each saved invocation should be one runnable Python file. The CLI can generate
the file, but it does not need to own future edits. Users can edit generated
files or create new files by hand.

The imports used by generated tests should come from pydoover, not doover-cli.
That keeps the test files useful outside the CLI and puts the reusable harness
next to the processor framework it tests.

Example generated file:

```python
# Generated by doover-cli 0.3.2
# Command:
#   doover processor test run message-create --app-install pump-monitor --channel telemetry --latest --mode sandboxed-live --writes record --save latest_telemetry
# Generated-Content-SHA256: 7c4b-example

from pydoover.testing import ProcessorTest


APP_NAME = "pump_monitor"
APP_INSTALL_ID = 123456789  # pump-monitor
AGENT_ID = 123456789
APP_KEY = "pump_monitor"
SNAPSHOT_CHANNELS = ["deployment_config", "tag_values", "ui_state", "ui_cmds", "telemetry"]
CHANNEL = "telemetry"


async def run():
    test = ProcessorTest(
        APP_NAME,
        app_install=APP_INSTALL_ID,
    )

    event = await test.events.message_create(
        channel=CHANNEL,
        message_source="latest",
    )

    env = test.Environment()
    env.data_client = test.processor.DataClient()
    snapshot = await env.data_client.reads.use_live_snapshot(
        agent_id=AGENT_ID,
        app_install_id=APP_INSTALL_ID,
        app_key=APP_KEY,
        channels=SNAPSHOT_CHANNELS,
        latest_messages=[CHANNEL],
    )
    env.data_client.reads.delegate_missing(False)
    env.data_client.writes.capture()
    env.auth = test.auth.cli_user_for_reads()

    with env:
        result = await test.run(event)

    return result
```

### File Contract

Generated files should follow a small contract:

- `async def run()` is the canonical test entrypoint.
- `run()` returns a `ProcessorTestResult`.
- `doover processor test run path/to/file.py` imports the file and runs `run()`.
- files should be import-safe; no test should execute at import time.
- generated files should not import from doover-cli.
- generated files should not contain bearer tokens.
- values provided by CLI params or tester prompts should be lifted into
  constants near the top of the file so they are easy to see and change.
- generated files should include provenance comments at the top:
  - doover-cli version
  - original command used to generate the file
  - generation timestamp, if useful
  - profile/environment name only if it is not sensitive
  - generated content hash so the CLI can tell whether the file has been edited
    since generation

The generated content hash should be advisory metadata, not a runtime
requirement. The CLI can use it to:

- report whether a source file was edited before clone/promote operations.
- show whether a local generated test was edited.
- decide whether `promote` can copy cleanly or should ask for confirmation.

The hash should cover the generated body excluding the hash line itself, so it is
stable and easy to recompute. If the hash does not match, the file should still
run normally.

The generated default should use `ProcessorTest` directly and should always
include an explicit `Environment()` block. Simple cases should still be easy to
read, but the generated file should show the actual mode/write/read/auth/output
configuration instead of hiding it in `ProcessorTest(...)` constructor flags.

### `ProcessorTest` Defaults And Overrides

`ProcessorTest` is the single public API for generated and custom tests. It
should support concise generated files while still exposing the pieces users may
want to edit:

- project/app resolution
- remote app install lookup
- live data helpers
- snapshot construction/loading
- event builders
- environment/data-client configuration
- processor execution
- result objects containing logs, writes, generated files, status, duration, and
  invocation metadata

Simple generated example:

```python
# Generated by doover-cli 0.3.2
# Command:
#   doover processor test run ingestion --app-install "Digital Matter Integration" --body fixtures/digital_matter_webhook.json --mode sandboxed-live --writes record --save latest_ingestion
# Generated-Content-SHA256: 7c4b-example

from pydoover.testing import ProcessorTest


APP_NAME = "digital_matter_integration"
APP_INSTALL_ID = 123456789  # Digital Matter Integration
AGENT_ID = 123456789
APP_KEY = "digital_matter_integration"
SNAPSHOT_CHANNELS = ["deployment_config", "tag_values", "ui_state", "ui_cmds"]
BODY_PATH = "fixtures/digital_matter_webhook.json"
CONTENT_TYPE = "application/json"


async def run():
    test = ProcessorTest(
        APP_NAME,
        app_install=APP_INSTALL_ID,
    )

    event = await test.events.ingestion(
        body_path=BODY_PATH,
        content_type=CONTENT_TYPE,
    )

    env = test.Environment()
    env.data_client = test.processor.DataClient()
    snapshot = await env.data_client.reads.use_live_snapshot(
        agent_id=AGENT_ID,
        app_install_id=APP_INSTALL_ID,
        app_key=APP_KEY,
        channels=SNAPSHOT_CHANNELS,
    )
    env.data_client.reads.delegate_missing(False)
    env.data_client.writes.capture()
    env.auth = test.auth.cli_user_for_reads()

    with env:
        result = await test.run(event)

    return result
```

The CLI can still treat `--mode sandboxed-live --writes record` as the source
configuration, but generated Python should expand that into explicit
environment wiring.

Expanded editable example:

```python
# Generated by doover-cli 0.3.2
# Command:
#   doover processor test run ingestion --app-install "Digital Matter Integration" --body fixtures/digital_matter_webhook.json --mode sandboxed-live --writes record --save latest_ingestion
# Generated-Content-SHA256: 7c4b-example

from pydoover.testing import ProcessorTest


APP_NAME = "digital_matter_integration"
APP_INSTALL_ID = 123456789  # Digital Matter Integration
AGENT_ID = 123456789
APP_KEY = "digital_matter_integration"
DEVICE_IDS = [987654321]
SNAPSHOT_CHANNELS = ["deployment_config", "tag_values", "ui_state", "ui_cmds"]
BODY_PATH = "fixtures/digital_matter_webhook.json"
CONTENT_TYPE = "application/json"
INVOCATION_URL = "http://localhost/test-webhook"


async def run():
    test = ProcessorTest(
        APP_NAME,
        app_install=APP_INSTALL_ID,
    )

    body = await test.files.json(BODY_PATH)
    body["Device"]["Serial"] = "TEST-123"

    # Create ingestion event.
    event = await test.events.ingestion(
        body=body,
        content_type=CONTENT_TYPE,
        invocation_url=INVOCATION_URL,
    )

    # Configure sandboxed-live execution explicitly.
    env = test.Environment()
    env.data_client = test.processor.DataClient()
    snapshot = await env.data_client.reads.use_live_snapshot(
        agent_id=AGENT_ID,
        app_install_id=APP_INSTALL_ID,
        app_key=APP_KEY,
        channels=SNAPSHOT_CHANNELS,
        devices=DEVICE_IDS,
    )
    env.data_client.writes.capture()
    env.auth = test.auth.cli_user_for_reads()

    with env:
        result = await test.run(event)

    return result
```

Use the standard generated form when:

- the CLI generated the test
- the event input is simple
- the user mainly wants to rerun an invocation

Use a customized generated form when:

- input needs to be mutated programmatically
- multiple events need to be fired in one test
- setup needs custom snapshot data
- the test needs custom sandbox behavior
- users want to inspect intermediate reads, writes, logs, or generated files in
  normal Python
- the user wants to share helper functions across test files

### Explicit Environments

The environment should be an explicit object/context manager rather than only a
constructor option or hidden mode preset. That makes generated files easy to
modify because the exact test wiring is visible.

Preferred shape:

```python
# Generated by doover-cli 0.3.2
# Command:
#   doover processor test run ingestion --app-install "Digital Matter Integration" --body fixtures/webhook.json --mode sandboxed-live --writes record --save latest_ingestion
# Generated-Content-SHA256: 7c4b-example

from pydoover.testing import ProcessorTest


APP_NAME = "digital_matter_integration"
APP_INSTALL_ID = 123456789  # Digital Matter Integration
AGENT_ID = 123456789
APP_KEY = "digital_matter_integration"
DEVICE_IDS = [987654321]
SNAPSHOT_CHANNELS = ["deployment_config", "tag_values", "ui_state", "ui_cmds"]
BODY_PATH = "fixtures/webhook.json"


async def run():
    test = ProcessorTest(
        APP_NAME,
        app_install=APP_INSTALL_ID,
    )

    body = await test.files.json(BODY_PATH)
    event = await test.events.ingestion(body=body)

    env = test.Environment()
    env.data_client = test.processor.DataClient()
    snapshot = await env.data_client.reads.use_live_snapshot(
        agent_id=AGENT_ID,
        app_install_id=APP_INSTALL_ID,
        app_key=APP_KEY,
        channels=SNAPSHOT_CHANNELS,
        devices=DEVICE_IDS,
    )
    env.data_client.writes.capture()
    env.auth = test.auth.cli_user_for_reads()

    with env:
        result = await test.run(event)

    return result
```

This is intentionally verbose. A user should be able to change one piece without
having to understand a hidden preset. For example, changing from captured writes
to blocked writes should be a one-line edit:

```python
env.data_client.writes.block()
```

or changing a missing-read policy:

```python
env.data_client.reads.delegate_missing(False)
```

The lower-level pieces should be assignable/composable:

```python
env = test.Environment()
env.data_client = test.processor.DataClient()
snapshot = await env.data_client.reads.use_live_snapshot(
    agent_id=AGENT_ID,
    app_install_id=APP_INSTALL_ID,
    app_key=APP_KEY,
    channels=SNAPSHOT_CHANNELS,
    devices=DEVICE_IDS,
)
env.data_client.reads.delegate_missing(False)
env.data_client.writes.capture()
env.files.output_dir("tmp/reports")
env.auth = test.auth.cli_user_for_reads()
```

Snapshot setup should take explicit parameters so the generated file documents
what real data was collected. Useful parameters:

- `agent_id=`: primary agent/install owner.
- `organisation_id=`: when testing organisation-level processors/reports.
- `app_key=`: app key inside `deployment_config`.
- `app_install_id=`: selected app installation.
- `channels=`: aggregates/messages to include.
- `devices=`: device IDs to include for `DEVICE_LIST`, `DEVICE_MAP`, or report
  input.
- `messages=`: specific message fixtures to fetch by channel/id.
- `latest_messages=`: channels where the latest message should be captured.
- `timeseries=`: channel/field/time-window data needed by reports.
- `attachments=`: whether message/aggregate attachments should be downloaded.

Generated files should make these selectors explicit rather than burying them
inside an opaque snapshot file.

### Event Fixtures

Small event payloads can be embedded directly in the generated Python file:

```python
MESSAGE_DATA = {"temperature": 21.5}
```

Larger payloads should be written to fixture files beside the test, for example:

```text
tests/doover/digital_matter_integration/
  latest_ingestion.py
  fixtures/
    latest_ingestion_body.json
```

The generated file should expose the path as a top-level constant:

```python
BODY_PATH = "fixtures/latest_ingestion_body.json"
```

The CLI can choose inline vs file based on size and readability. A practical
default is:

- inline simple JSON objects under a small threshold.
- write larger JSON, binary bodies, attachments, or report fixture data to
  files.
- always write binary payloads to files.

Users should also be able to mutate the initial snapshot before running:

```python
snapshot = await env.data_client.reads.use_live_snapshot(
    agent_id=AGENT_ID,
    app_install_id=APP_INSTALL_ID,
    app_key=APP_KEY,
    channels=["deployment_config", "tag_values"],
    devices=DEVICE_IDS,
)

snapshot.deployment_config["threshold"] = 42
snapshot.tag_values.setdefault("digital_matter_integration", {})["enabled"] = True
snapshot.channels["telemetry"].aggregate.data["temperature"] = 21.5
```

An optional hook form could exist:

```python
snapshot = await env.data_client.reads.use_live_snapshot(
    agent_id=AGENT_ID,
    app_install_id=APP_INSTALL_ID,
    app_key=APP_KEY,
    channels=["deployment_config", "tag_values"],
    modify=lambda snapshot: snapshot.deployment_config.update({"threshold": 42}),
)
```

The explicit mutation style is easier to read and debug, so generated files
should prefer assigning the returned `snapshot` and editing it in normal Python
when a modification is required.

The CLI should not generate snapshot mutations in v1. Common mutation generators
can be added later once repeated patterns are clear.

Mode names can still exist, but they should be generation templates rather than
the only public API. For example, CLI `--mode sandboxed-live` can generate the
explicit setup above. V1 generated files should not use hidden template helpers;
any pydoover template helpers should be internal or future convenience APIs.

Suggested generated environment wiring:

Local:

```python
env = test.Environment()
env.data_client = test.processor.DataClient()
env.data_client.reads.use_fixtures()
env.data_client.writes.capture()
```

Sandboxed-live:

```python
env = test.Environment()
env.data_client = test.processor.DataClient()
snapshot = await env.data_client.reads.use_live_snapshot(
    agent_id=AGENT_ID,
    app_install_id=APP_INSTALL_ID,
    app_key=APP_KEY,
    channels=SNAPSHOT_CHANNELS,
    devices=DEVICE_IDS,
)
env.data_client.reads.delegate_missing(False)
env.data_client.writes.capture()
env.auth = test.auth.cli_user_for_reads()
```

Live-local:

```python
env = test.Environment()
env.data_client = test.processor.DataClient()
env.data_client.reads.use_live()
env.data_client.writes.capture()
env.auth = test.auth.cli_user()
```

Suggested behavior remains:

- `local`: fixture/snapshot reads only; writes captured by default.
- `sandboxed-live`: CLI fetches real setup/input data; writes captured or
  blocked by default.
- `live-local`: CLI user token can perform real Data API reads. V1 still records
  or blocks writes; real write passthrough is future work.

`ProcessorTest` should separate local app identity from remote context:

- first positional argument: local app selector, stored as the top-level key
  from `doover_config.json`
- `app_install=`: remote application installation lookup used for
  `sandboxed-live` and `live-local`
- `agent_id=` / `agent=`: optional remote agent selector when needed

For `local` mode, the local app name is enough. For `sandboxed-live` and `live-local`,
generated files should include `app_install=` unless the command can prove the
remote install is unambiguous. This avoids assuming that app config names,
application names, and install display names are the same.

For generated files, prefer stable IDs for remote resources and include readable
names as comments:

```python
APP_NAME = "digital_matter_integration"  # top-level doover_config.json key
APP_INSTALL_ID = 123456789  # Digital Matter Integration
AGENT_ID = 987654321  # Pump Station 1
```

Then pass IDs into the test:

```python
test = ProcessorTest(
    APP_NAME,
    app_install=APP_INSTALL_ID,
)
```

Commands:

```bash
doover processor test run tests/doover/pump_monitor/latest_telemetry_message.py
doover processor test run tests/doover/monthly_report/report_manual_rerun.py
```

The runner should also support running an ad hoc invocation immediately:

```bash
doover processor test run message-create \
  --app-install pump-monitor \
  --channel telemetry \
  --latest \
  --mode sandboxed-live \
  --writes record
```

### Saving Generated Tests

Ad hoc commands should support saving the generated invocation file.

Tracked save:

```bash
doover processor test run message-create \
  --app-install pump-monitor \
  --channel telemetry \
  --latest \
  --save latest_telemetry_message
```

Local-only save:

```bash
doover processor test run message-create \
  --app-install pump-monitor \
  --channel telemetry \
  --latest \
  --save-local latest_telemetry_message
```

Proposed locations:

- `--save`: write to a project test folder, for example
  `tests/doover/<app_name>/latest_telemetry_message.py`. This is intended to be
  committed.
- `--save-local`: write to an ignored local folder, for example
  `.local/tests/doover/<app_name>/latest_telemetry_message.py`.

V1 commands:

```bash
doover processor test run tests/doover/pump_monitor/latest_telemetry_message.py
doover processor test run message-create --app-install pump-monitor --channel telemetry --latest --save-local latest_telemetry_message
doover processor test promote .local/tests/doover/pump_monitor/latest_telemetry_message.py --to tests/doover/pump_monitor/
doover processor test clone tests/doover/app/latest_ingestion.py --to new_ingestion
doover processor test snapshot --app-install pump-monitor --output tests/doover/pump_monitor/snapshots/latest_telemetry.snapshot.json
```

Overwriting generated tests should not be supported. If a user wants a new copy
from an existing generated test, use the clone flow.

If the source file has a generated-content hash, the CLI can report whether it
has been edited. Clone should prompt before carrying forward the original
settings, because generated constants like `AGENT_ID`, `APP_INSTALL_ID`, or
`PROFILE_NAME` may no longer be the intended values.

## Local Project Discovery

When run inside a Doover project repository, the CLI should discover:

- app config from the existing Doover project files.
- processor entrypoint/module.
- application type: processor, integration, or report.
- deployment config defaults.
- local config schema and UI schema, if available.

`doover_config.json` should be the root of app discovery. Tests should identify
the app they are testing by name:

```python
from pydoover.testing import ProcessorTest


APP_NAME = "digital_matter_integration"
APP_INSTALL_ID = 123456789  # Digital Matter Integration
BODY = {"hello": "world"}


async def run():
    test = ProcessorTest(
        APP_NAME,
        app_install=APP_INSTALL_ID,
    )

    event = await test.events.ingestion(body=BODY)

    env = test.Environment()
    env.data_client = test.processor.DataClient()
    env.data_client.reads.use_fixtures()
    env.data_client.writes.capture()

    with env:
        result = await test.run(event)

    return result
```

The app name passed to `ProcessorTest(...)` should resolve against the nearest
`doover_config.json` using this order:

1. exact top-level key in `doover_config.json`
2. exact `name` field inside an app config entry
3. exact `display_name`
4. if there is exactly one processor/integration/report entry, use it
5. otherwise fail with the available app names

For CLI ad hoc commands, an interactive prompt can be used when multiple apps
match. For generated test files, ambiguity should fail rather than prompt.

Entrypoint resolution should also be explicit and deterministic:

1. explicit `entrypoint=` argument in the test file
2. explicit CLI flag, for example `--entrypoint integration:handler`
3. `lambda_config.Handler` from the selected `doover_config.json` entry
4. convention fallback: `src/<app_name_as_module>/__init__.py:handler`
5. fail with a clear message explaining how to pass `entrypoint=`

The `lambda_config.Handler` parser should support the existing AWS-style values
such as `src.integration.handler` and local import conventions. A practical
resolution strategy:

1. try importing the module exactly as configured
2. add project root to `sys.path` and retry
3. add project `src/` to `sys.path`; if the handler starts with `src.`, strip
   that prefix and retry
4. import the resolved handler function and call it with the generated event and
   a lightweight fake Lambda context

This keeps tests close to the production entrypoint while still working with
local `src/` layouts.

Generated files should not include `entrypoint=` when it can be inferred. Only
include it if the user passed an explicit entrypoint override or discovery would
otherwise be ambiguous.

Per-app test folders are worth supporting for multi-app repos. Recommended
tracked layout:

```text
tests/
  doover/
    digital_matter_integration/
      latest_ingestion.py
      latest_message.py
    digital_matter_processor/
      aggregate_update.py
```

Recommended local-only layout:

```text
.local/
  tests/
    doover/
      digital_matter_integration/
        latest_ingestion.py
```

`--save` should default to `tests/doover/<app_name>/<test_name>.py`.
`--save-local` should default to
`.local/tests/doover/<app_name>/<test_name>.py`.
The CLI can allow overriding these paths, but the app-folder convention should
be the default because it mirrors common `src/` multi-app layouts and keeps test
names short.

Projects should add `.local/` to `.gitignore`; the CLI can warn if it is missing.
It should not modify `.gitignore` without asking.

## Event Construction

The runner should construct payloads matching pydoover's event models.

### Message Create

Inputs:

- channel name
- message data
- message id, author id, attachments, timestamp
- optional source: latest real message

### Aggregate Update

Inputs:

- channel name
- current aggregate
- request data
- author id
- organisation id
- optional source: real current aggregate

### Deployment

Inputs:

- agent id
- app id
- app install id
- app key
- app display name

### Schedule

Inputs:

- schedule id
- schedule config/timezone if useful for report tests
- setup snapshot

### Ingestion Endpoint

Inputs:

- ingestion id
- body bytes, base64 encoded into the event
- content type
- invocation URL
- setup snapshot

### Manual Invoke

Inputs:

- organisation id
- payload
- setup snapshot

This is especially important for report generators, where manual invoke expects
payload like `{"report_id": "..."}` and then reads the report message.

## Local Ingestion Relay

A local relay is part of the v1 `run` command. It makes ingestion testing feel
closer to production without deploying Lambda.

Command:

```bash
doover processor test run ingestion-relay \
  --app-install webhook-ingest \
  --port 8765 \
  --mode sandboxed-live \
  --writes record
```

Behavior:

- start a local HTTP server.
- accept requests matching the ingestion endpoint style.
- optionally verify HMAC headers and content type.
- build the same `on_ingestion_endpoint` event shape Doover Data builds.
- call the local handler directly through the same `ProcessorTest` runner path
  as other local invocations.
- return either a structured test result or the processor result.

This allows webhook providers or curl/Postman to target a local URL while the
processor still gets realistic ingestion event data.

The relay should not write a generated invocation file as part of handling each
request. If the user passes `--save` or `--save-local`, `run ingestion-relay`
can save the relay configuration as a runnable Python test file, but request
handling should still call the local handler directly.

Endpoint-auth test cases could include:

- valid bearer token accepted by the relay.
- missing/invalid bearer token rejected.
- valid HMAC accepted.
- missing HMAC rejected.
- invalid HMAC rejected.
- content type preserved in the event.
- raw body bytes preserved through base64 encoding and processor parsing.

For local handler tests, these checks can be implemented by the relay itself.
For real Doover Data ingestion endpoint auth tests, a future Doover Control
feature should provide a deployed/platform invocation path. That is outside this
CLI-local proposal for now.

## Report Generator Testing

Keep `doover report compose` as-is.

Add processor-style report tests under the new runner:

- scheduled report test invokes `on_schedule`.
- manual rerun test invokes `on_manual_invoke`.
- sandboxed-live report tests fetch real report/deployment/device context but
  capture `create_message`, `update_message`, and file upload writes instead of
  publishing output to the real `reports` channel.

Expected output should include generated files in a local output directory and a
recorded write log showing what would have been uploaded. Generated report tests
should set an output directory in the environment, defaulting to `/tmp`, so users
can change it easily:

```python
OUTPUT_DIR = "/tmp/doover-processor-test/monthly_report"

env.files.output_dir(OUTPUT_DIR)
```

## Auth Recommendation

Use the user's CLI auth for setup and snapshot acquisition. In sandboxed modes,
do not expose that token to processor write paths.

Reasons:

- the user token may have broader permissions than the deployed processor should
  have.
- passing a user token into arbitrary local processor code increases the blast
  radius of a bug.
- pydoover's processor setup expects processor-style upgrade data, not a normal
  user session.
- the test runner wants to record or block writes, which is easier and safer
  when processor code talks to a sandbox data client.

Recommended sandboxed model:

1. The CLI authenticates as the user.
2. The CLI fetches real setup data needed for the test.
3. The CLI builds a processor setup snapshot.
4. The local processor receives a sandbox processor data client.
5. Reads are served from the snapshot or delegated through controlled read-only
   fetches using the user's CLI auth owned by the runner, not arbitrary
   processor code.
6. Writes are recorded or blocked by default.

For live writes, the current platform likely has to use the user's CLI token.
Doover Data's
`POST /agents/{agent_id}/token` endpoint is gated by `AgentTokenManage`, with a
fallback only for the control-plane agent or superusers, so normal users should
not be assumed able to mint short-lived processor-equivalent tokens.

Live auth modes should therefore be explicit:

- `user-token`: run local Python with the user's token and allow real writes.
  This is useful but dangerous, so it should require a clear flag such as
  `--allow-live-writes`.
- `scoped-token`: optional future/admin mode. The CLI asks Doover Data to mint a
  short-lived JWT with the same resolved `dv_proc_extended_permissions` as the
  installed processor. This only works for users or services allowed to manage
  agent tokens.

The user's token is only needed for real reads and setup in v1. Future live-write
support will need an additional confirmation path.

Generated sandboxed-live files should use an auth handle that is available to
the runner for setup and controlled read delegation, but is not passed through to
processor write calls:

```python
env.auth = test.auth.cli_user_for_reads(profile=PROFILE_NAME)
```

`cli_user_for_reads(...)` should resolve the configured Doover CLI profile and
let the runner fetch snapshots or delegated reads. It should not make the
processor data client a normal user-token client when writes are captured or
blocked.

Generated files can include a profile constant when a profile was explicitly
selected:

```python
PROFILE_NAME = "staging"

env.auth = test.auth.cli_user_for_reads(profile=PROFILE_NAME)
```

If no profile was specified, generated files should omit the profile or set
`PROFILE_NAME = None` and use the current CLI default at runtime. This makes
tracked tests more portable between users whose local profile names differ.

Generated provenance comments can include the data/control endpoint used during
generation when useful for debugging, but this should be informational. The
runtime profile/auth choice should come from the editable constants or the
current CLI environment.

Do not mint mini-tokens for normal tests. They are long-lived and intended for
embedded/device-style use.

## Implementation Shape

Likely split:

- `doover_cli.processor_test`: Typer command group.
- `doover_cli.processor_test.discovery`: local project detection.
- `doover_cli.processor_test.events`: event builders.
- `doover_cli.processor_test.snapshot`: live data snapshot loading/caching.
- `doover_cli.processor_test.sandbox`: fake/guarded processor data client.
- `doover_cli.processor_test.runner`: imports app, patches data client, invokes
  `pydoover.processor.run_app` or `Application._handle_event`.
- `doover_cli.processor_test.generate`: internal generator used by `run --save`
  and `run --save-local` to turn CLI flags into Python test files.
- `doover_cli.processor_test.relay`: optional local HTTP ingestion relay.

The reusable testing API should live in pydoover. In particular:

- `pydoover.testing.ProcessorTest`
- event builders
- sandbox/recording processor data client
- snapshot model/loaders that do not depend on doover-cli state
- result models for logs, recorded writes, generated files, status, duration,
  and invocation metadata

doover-cli should focus on project discovery, fetching authenticated live data,
generating Python files, and command UX.

## Future Work

These features are useful, but should wait until after the v1 runner and file
format are stable:

- pytest integration and generated pytest wrappers.
- assertion helpers for writes, logs, report files, return values, and raised
  errors.
- richer comparison modes such as exact payload matching, partial matching,
  JSONPath-like selectors, or custom Python predicates.

## Open Questions

- What local project layouts need to be supported for processor entrypoint
  discovery beyond `lambda_config.Handler` and common `src/` layouts?
- Should a local relay simulate token/HMAC auth by default, or only when the
  test asks for auth checks?
- What exact threshold should decide whether a fixture is embedded inline or
  written to a fixture file?
- What exact fields should be included in `ProcessorTestResult` beyond logs,
  writes, status, generated files, and duration?
  xc 
