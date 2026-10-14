# Delete a Run by ID

This Ruby script **permanently** removes a **Run** object and its simulations when you cannot delete that run in the InfoWorks ICM database tree.

## When to use this script

Use it if you see **Error 50: Attempting to access a recycled object** when you try to delete or open a run.

<img width="505" height="227" alt="image" src="https://github.com/user-attachments/assets/d2112d54-ce48-4e2e-8008-25b9f9bbae0b" />



That usually means the run still **refers to database objects used in the run setup** (for example a model network, rainfall event, level, or initial conditions) that were **already removed**. If those items were deleted from the Recycle Bin (**Empty Recycle Bin**) or removed permanently, they **cannot be restored**, and the run is left with a broken link. InfoWorks ICM then blocks normal delete because it tries to load those missing objects.

This script deletes the run **by its Run ID** without opening those broken links, so you can clear the orphaned run from your database.

## What this script does not do

- It does **not** recover or recreate deleted networks, rainfall files, or other objects the run pointed to.
- It does **not** place the run in the Recycle Bin. Deletion is **permanent** and **cannot be undone**.

Use a **copy** of the database the first time you run the script.

## Script

| File | Description |
|------|-------------|
| `Delete_run_by_ID.rb` | Run from InfoWorks ICM (**Network → Run Ruby script**) |

## Before you run

- Open the **correct** database in InfoWorks ICM.
- Find the **Run ID** you need to remove (from the database tree or object properties on the run, if the UI allows it).
- Read the confirmation dialog and check the Run ID carefully.

## Steps

1. Open the database in InfoWorks ICM.
2. Run **Delete_run_by_ID.rb** from the Ruby script menu.
3. Enter the **Run ID** when prompted, or set `RUN_ID` at the top of the script before you run it.
4. Review the confirmation message (Run ID, number of simulations, and permanent-delete warning).
5. Choose **Yes** only if you intend to permanently delete that run.
6. Commit the database if your site requires commits after structural changes.

### Dry run (recommended first time)

At the top of the script, set `DRY_RUN = true`, then run the script. You can confirm the correct Run ID and simulation count **without** deleting anything. Set `DRY_RUN = false` when you are ready to delete for real.

## Optional settings (top of script)

Most users can leave the defaults.

| Setting | Default | What it does |
|---------|---------|--------------|
| `RUN_ID` | `0` | Run to delete; `0` asks for the ID when the script runs |
| `DRY_RUN` | `false` | When `true`, no data is deleted |
| `USE_EXCHANGE_FALLBACK` | `true` | If deletion fails in the main session, the script tries again in a separate process |
| `VERBOSE` | `false` | Set to `true` to show extra detail in **Script Output** |

## If deletion still fails

- Set `VERBOSE = true`, run again, and check **Script Output**.
- Do not rely on opening run properties if that already triggers Error 50.
- Restore from backup, remove the whole **Model Group** if that is acceptable for your project, or contact your InfoWorks ICM administrator.
