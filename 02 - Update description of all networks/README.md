# Update network descriptions

This Ruby script updates the **Description** field on every **model network** in your open InfoWorks ICM database. Each Description is set to that network’s **latest version number** and the **message from that commit**.

Use it when you want the database tree to show version information at a glance - for example after audits, handover, or standardising how networks are labelled.

## Demo video

[Update description of all network objects.mp4](./Update%20description%20of%20all%20network%20objects.mp4) - walkthrough of running the script in InfoWorks ICM (same folder as this readme).

## Script

| File | Description |
|------|-------------|
| `Update description of all network objects.rb` | Run from InfoWorks ICM (**Network → Run Ruby script**) |

## Before you run

- Open the **correct** database in InfoWorks ICM.
- Try a **copy** of the database the first time you use the script.
- The script reads **version history**; your PC must be able to run **ICMExchange** (the UI starts it automatically in the background).
- Updating Description **overwrites** the current text on each network with the formatted version line (unless it already matches).

## What it does

For every model network in the live database tree (not in the Recycle Bin):

1. Finds the **latest commit (version)** on that network.
2. Reads the **commit message** for that version.
3. Sets **Description** to:

   `Network version [number]. Comment: [commit message]`

Networks that already have exactly that text are **left unchanged**. If there is no version number available, the script uses `n/a` in place of the number. If the commit has no message, the text after `Comment:` is empty.

## Steps

1. Open the database in InfoWorks ICM.
2. Run **Update description of all network objects.rb**.
3. Read the confirmation message, then choose **Yes** to continue.
4. Wait until the summary dialog appears. It shows how many networks were updated, unchanged, or could not be updated, and **how long the run took**.
5. If descriptions do not appear immediately, refresh the database tree or close and reopen the database.

### Preview first (recommended)

At the top of the script, set `DRY_RUN = true`, then run it. You can confirm the database and network count **without** writing any changes. Set `DRY_RUN = false` when you are ready to update for real.

## What you should expect

**After a successful run**

- Each model network’s **Description** in the tree matches the latest version and commit message format above.
- The final dialog reports counts and **time taken** for the whole run (from confirmation through ICMExchange).

**If something goes wrong**

- Set `VERBOSE = true` at the top of the script, run again, and read **Script Output**.
- If the script reports that ICMExchange was not found, set `ICM_EXCHANGE_PATH` (see below) or contact your ICM administrator.

## Optional settings (top of script)

For administrators or support staff. Most users can leave the defaults.

| Setting | Default | What it does |
|---------|---------|--------------|
| `DRY_RUN` | `false` | Preview only; no Description changes |
| `ICM_EXCHANGE_PATH` | (empty) | Set only if ICMExchange is not found automatically |
| `VERBOSE` | `false` | Extra detail in **Script Output** |
| `DATABASE_PATH` | (empty) | Only when running the script directly via ICMExchange, not from the UI |

## For administrators (Exchange-only)

To run the script outside the UI:

```text
ICMExchange.exe "Update description of all network objects.rb"
```

Set `DATABASE_PATH` at the top of the script if Exchange cannot connect to the same database as the UI session.
