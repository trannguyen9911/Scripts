# Delete a model group permanently

This Ruby script removes a **model group** from your open InfoWorks ICM database **permanently**, together with everything stored under that group (for example networks, runs, and simulations). Removed data is **not** placed in the Recycle Bin.

Use it when you need to clear out a whole model group in one step from the **live** database tree - not for items that are already in the Recycle Bin (see [Recycle Bin and scripting](#recycle-bin-and-scripting) below.
## Demo video

[Demo.mp4](./Demo.mp4) - walkthrough of running the script in InfoWorks ICM (same folder as this readme).

## Script

| File | Description |
|------|-------------|
| `Delete a model group permanently.rb` | Run from InfoWorks ICM (**Network → Run Ruby script**) |

## Before you run

- Open the **correct** database in InfoWorks ICM.
- Prefer a **copy** of the database the first time you use the script.
- Deletion **cannot be undone**. Read the confirmation dialog carefully before you choose **Yes**.

## Steps

1. Open the database in InfoWorks ICM.
2. Run **Delete a model group permanently.rb** from the Ruby script menu.
3. In the list, choose the model group to remove. Each line is shown as **`Model group name | ID 12345`**, sorted by ID from lowest to highest.
4. Review the confirmation message (it includes an approximate count of child objects).
5. Choose **Yes** only if you intend to permanently delete that group and its contents.

### Dry run (recommended first time)

At the top of the script, set `DRY_RUN = true`, then run the script. You can step through the prompts and confirm the right group is selected **without** deleting anything. Set `DRY_RUN = false` when you are ready to delete for real.

## Optional settings (top of script)

These are for administrators or support staff. Most users can leave the defaults.

| Setting | Default | What it does |
|---------|---------|--------------|
| `DRY_RUN` | `false` | When `true`, no data is deleted |
| `USE_EXCHANGE_FALLBACK` | `true` | If deletion fails in the main session, the script tries again using ICMExchange |
| `ICM_EXCHANGE_PATH` | (empty) | Set only if ICMExchange is not found automatically |
| `VERBOSE` | `false` | Set to `true` to show extra detail in **Script Output** |

## Recycle Bin and scripting

InfoWorks ICM shows deleted items in the **Recycle Bin**, but **scripting does not provide a supported way to bulk permanently delete Recycle Bin contents** on many deployments (including cloud databases). Ruby scripts and ICMExchange are intended for objects in the **live** database tree.

**This script:**

- Lists and deletes **live** model groups only.
- Does **not** empty the Recycle Bin or delete items already stored there.

**To clear the Recycle Bin**, use InfoWorks ICM in the user interface - for example **Empty Recycle Bin** (where available for your database type) or **Advanced → Delete** on individual items.

## What you should expect

- After a successful run, the model group disappears from the database tree (not from a soft delete into the Recycle Bin).
- If deletion fails, set `VERBOSE = true`, run again, and check **Script Output**, or contact your ICM administrator.
