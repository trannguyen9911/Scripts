# Set Branch ID from selection lists

This UI Ruby script assigns **Branch ID** on pipes from your **Selection Lists**. Each list represents one branch: every pipe in a list gets **Branch ID = the list name**, so you can build branches from selection lists without editing pipes one by one.

## When to use

InfoWorks ICM can generate **long section views** from pipe **Branch IDs**. If you assign each branch’s pipes a distinct Branch ID (for example the same name as the selection list), you can organise multiple long sections as **separate pages in one long section window**.

Typical workflow:

1. Create one **Selection List** per branch.
2. Run this script to copy list names onto pipe Branch IDs.
3. Open or refresh long section views that use Branch ID.

## Demo video

[Long section view for branches.mp4](./Long%20section%20view%20for%20branches.mp4) — example of long sections organised by Branch ID (same folder as this readme).

## Script

| File | Description |
|------|-------------|
| `Set branch ID.rb` | Run from InfoWorks ICM (**Network → Run Ruby script**) |

## Before you run

- Open the **correct** network on the GeoPlan.
- Store **one Selection List per branch** in your selection-list subfolder (any names, any count).
- Each list should contain the **pipes** for that branch.

## Steps

1. Confirm selection lists are in the expected folder in the database tree.
2. Run **Network → Run Ruby script** and choose `Set branch ID.rb`.
3. If a pipe belongs to **more than one** list, read the conflict message and enter the correct Branch ID (or **Cancel** to skip that pipe).
4. Review the summary dialog. Open **Script Output** if you need the full list of selection list names.

## What it does

1. Finds **all Selection Lists** in the selection-list folder (including lists in a nested **Selection List Group**), sorted alphabetically by name.
2. For each list, loads the list and records which pipes belong to it.
3. Sets **Branch ID = list name** when a pipe appears in **one** list only.
4. When a pipe appears in **multiple** lists, shows a conflict message and prompts you to type the Branch ID. **Cancel** skips that pipe; the script continues with the rest.
5. Saves all updates in one transaction and commits the network.

## Important considerations

**Overlapping selection lists**

Each pipe can have only **one** Branch ID. If a pipe belongs to more than one selection list, the script reports the conflict and asks you to **manually specify** the Branch ID (or skip that pipe). Avoid overlap when you can; resolve conflicts when lists must share pipes.

**Selection list names**

Keep selection list names **simple**—they become Branch IDs as-is. Long or awkward names may be hard to read in long sections or other tools. You may need a separate step or script to simplify complex names before or after running this one.

## What you should expect

**After a successful run**

- Pipes in a single list have **Branch ID** equal to that list’s name.
- The summary lists each manually resolved conflict: pipe ID, selection lists involved, and the Branch ID you entered.
- It also shows how many pipes were updated and how many were skipped at a prompt.

**If something looks wrong**

- Check **Script Output** for the full list of selection lists that were processed.
- Confirm lists are under the correct subfolder, or set `SELECTION_LIST_FOLDER_NAME` in the script.

## Optional configuration

| Setting | Default | Purpose |
|---------|---------|---------|
| `SELECTION_LIST_FOLDER_NAME` | `nil` | Force a subfolder name; `nil` = automatic detection |

