# Chronos

A Splunk SOAR app that runs playbooks on a schedule **without creating containers**.

SOAR has no built-in way to run a playbook on a timer. The usual answer is an app that
ingests one empty event per tick so that something downstream reacts to it, which works
and leaves a container behind every time it fires. Chronos inverts that: it uses `on_poll`
to start the playbooks directly, and creates nothing at all.

```
ingestion cron -> asset "every 1 min" -> on_poll
                                           |
                                           +- read custom list
                                           |
                                           +- for each row:
                                              POST /rest/playbook_run
                                                playbook_id  = the row
                                                container_id = the fixed one
```

The asset is the schedule. The custom list is the job registry. The connector is the
dispatcher in between.

## Install

Download `Chronos.tgz` from [Releases](../../releases), then **Apps → Install App**.

To build it yourself:

```sh
./build.sh
```

## Setup

Three objects have to exist before an asset can be configured.

**A container.** Create one by hand, on a label your analysts do not work, and close it.
Every scheduled run attaches to it. Note the ID.

**An automation user.** Give it a role that can run playbooks and little else. Copy its
`ph-auth-token`.

**A custom list.** One playbook per row in the first column:

```
local/Daily Indicator Expiry        repo/name form, readable, survives re-import
127                                 numeric playbook id, also accepted
# local/Paused Job                  a leading # skips the row
```

There is no header row. Anything after the first column is ignored by the app, which
makes column two a good place for a note about why the job exists.

## Asset configuration

| Field | Notes |
|---|---|
| `base_url` | SOAR as reachable from this host, **including the port** — e.g. `https://127.0.0.1:8443` |
| `auth_token` | the automation user's `ph-auth-token` |
| `verify_server_cert` | off when using loopback, since the certificate will not match the address |
| `container_id` | the container every scheduled playbook runs against |
| `playbook_list` | name of the custom list for this schedule, **case sensitive** |
| `run_scope` | `new` or `all`, passed to each playbook run |

Then set the interval or a cron expression on the asset's **Ingest Settings** tab. The
label on that tab is required by the platform and unused by this app.

**Test connectivity** checks reachability, then the token and container, then the custom
list, and prints the row count. Whichever check fails names the field to fix.

## More than one schedule

Install the app once. For each cadence, create a custom list, an asset pointing at it, and
a cron expression on that asset.

| Interval | Asset | List | Schedule |
|---|---|---|---|
| every minute | `chronos_1_min` | `Chronos_1_min` | every 1 minute |
| hourly | `chronos_hourly` | `Chronos_hourly` | `0 * * * *` |
| nightly | `chronos_nightly` | `Chronos_nightly` | `0 2 * * *` |

Nothing in the connector knows how many exist. Each asset reads its own list and fails on
its own without touching the others.

## Notes

**Playbooks do not need to be active.** Chronos starts them by id over REST, so the
`active` flag and the label a playbook is attached to stop mattering for scheduled work.

**Nothing accumulates.** There is no state, no queue and no catch-up. If the app is stopped
for an hour, that hour simply does not run.

**One row failing does not stop the others.** A renamed playbook fails on its row, the rest
still run, and the poll reports the count.

## Extending it

The registry is a plain custom list, so anything that can write a row can schedule a
playbook. The obvious next step is a playbook that rebuilds the list from a naming
convention plus a label, so that scheduling becomes labelling. Have it count what it
matched and complain when the count is zero — a misspelled label would otherwise write an
empty list and silently stop the schedule.

## How this was built

Written with an AI coding assistant. The approach is the part that matters: SOAR has no
native playbook scheduler, and the common workaround — ingesting one empty event per tick
— leaves a container behind every time it fires. Chronos uses `on_poll` to POST directly
to `/rest/playbook_run` against a fixed container, so it creates nothing at all.

---

## License

MIT — see [LICENSE](LICENSE).
