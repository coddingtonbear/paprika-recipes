[Paprika](https://www.paprikaapp.com/) is a lovely recipe app, but your recipes are then trapped inside it. This tool checks them out into a directory of plain markdown files that you can edit in whatever you already use -- your editor, your note vault, your usual git workflow -- and then sync your changes back.

```bash
# First: clone your recipes into a folder somewhere
paprika-recipes clone you@example.com ~/recipes
cd ~/recipes
# Second: make your changes to whatever recipe using whatever editor
vim Khachapuri.md
# Finally: push up your changes to Paprika
paprika-recipes push
```

## Why

- **Your recipes become real files** -- one markdown file per recipe: editable, greppable, diffable, and perfectly at home in a git repository.
- **Made to live in a note vault** -- clone straight into Obsidian or anything like it: photos render inline, your own tags, aliases, and extra sections stay in the files without ever being uploaded, and a [frontmatter prefix](#keeping-out-of-your-vaults-way) keeps Paprika's fields from colliding with your vault's.
- **Two-way, not just export** -- edits you make locally go back to Paprika, changes you make in the app come down, and `status` shows you exactly what would be sent before anything is.
- **Photos sync in both directions** -- each recipe's photo is downloaded and embedded beneath its title, and adding, swapping, or deleting that embed line uploads, replaces, or removes the photo in Paprika.
- **Write new recipes in your editor** -- a markdown file with a `# Title` becomes a real Paprika recipe on the next `push`.
- **You already know the commands** -- `clone`, `pull`, `push`, `status`, `restore`, with `--dry-run` everywhere and `--json` plus meaningful exit codes when you are scripting.

Paprika has no official public API; this tool speaks the same sync protocol the apps themselves use. That fact shapes its manners: nothing is uploaded without `status` being able to show it to you first, anything can be undone before it is pushed, and deleting a recipe only ever moves it to Paprika's own trash.

**Contents**

<!-- regenerate with: npx markdown-toc -i readme.md -->

<!-- toc -->

- [Why](#why)
- [Installation](#installation)
- [Getting started](#getting-started)
  - [Writing a recipe yourself](#writing-a-recipe-yourself)
- [Commands](#commands)
- [How syncing works](#how-syncing-works)
  - [Keeping out of your vault's way](#keeping-out-of-your-vaults-way)
  - [Recipe files](#recipe-files)
- [Working with exported archives](#working-with-exported-archives)
- [Scripting](#scripting)
- [Upgrading from 2.x](#upgrading-from-2x)
- [Other tools](#other-tools)

<!-- tocstop -->

## Installation

```bash
uv tool install paprika-recipes
```

If [uv](https://docs.astral.sh/uv/) isn't your thing, `pipx install paprika-recipes` does the same job, and plain `pip install paprika-recipes` works in a virtualenv of your own.

## Getting started

There is nothing to set up. Check out your recipes:

```bash
paprika-recipes clone you@example.com ~/recipes
```

You'll be asked for your Paprika password. It goes into your system keyring, and the account is recorded in the directory itself, so nothing asks again — and if your password ever changes, you're simply asked for the new one the next time it doesn't work.

Every recipe becomes a markdown file:

```markdown
---
categories:
- Bread
rating: 4
source: simplyhomecooked.com
uid: 4C855813-25B8-41CD-96E7-5B38AA7AAAAF
---

# Khachapuri

![Photo of Khachapuri](attachments/D2246B0B-3E32-4C36-A9F9-6E5F53CD6EBD.jpg)

A Georgian cheese bread.

## Ingredients

- 3 1/2 cup all-purpose flour
- 1 tsp salt

## Directions

Combine the dry ingredients.

Bake for 20 minutes.
```

Edit them however you like, then:

```bash
paprika-recipes status   # what have I changed?
paprika-recipes push     # send it to Paprika
paprika-recipes pull     # bring down changes made elsewhere
paprika-recipes restore  # undo local changes
```

`status` tells you what `push` is going to do before you do it:

```
Changes not yet sent to Paprika:
  (use "paprika-recipes push" to send them)
  (use "paprika-recipes restore <recipe>..." to discard them)

        deleted:   Best-Ever Focaccia (will be moved to Paprika's trash)
        new file:  Brand New Thing (will be created in Paprika)
        modified:  One-Hour Pizza (rating)
        modified:  Vanilla Cupcake (formatting only; nothing to push)
```

Both `pull` and `push` accept `--dry-run` if you would rather see the whole plan first.

### Writing a recipe yourself

Write a markdown file with a `# Title`, and `push` will create it in Paprika. The sections Paprika can hold are the ones `clone` writes — `## Ingredients`, `## Directions`, `## Notes`, and `## Nutritional Information`, spelled exactly that way — plus any prose directly beneath the title, which becomes the description. A section by any other name follows the [usual rule](#how-syncing-works): it stays in your file, but nothing in Paprika receives it. The recipe gets a `uid:` written into its frontmatter at the moment it's created, and is an ordinary tracked recipe from then on. If you embed a photo from `attachments/` beneath the title, that goes up with it.

## Commands

| Command | What it does |
|---|---|
| `clone <email> [directory]` | Check an account's recipes out into a directory of markdown files, photos included. `--frontmatter-prefix` keeps Paprika's fields [out of a vault's way](#keeping-out-of-your-vaults-way). |
| `pull` | Bring down changes made in Paprika, reconciling them with any local edits. |
| `push` | Send local changes up: edits, new recipe files, photo changes, and deletions (into Paprika's trash). |
| `status` | Show what `push` would do without doing it. `--exit-code` makes it exit 1 when there are changes, after `git diff --exit-code`. |
| `restore <recipe>...` | Put recipes back the way they last arrived -- undoing an edit, or bringing back a deleted file. `--all` restores everything at once. |

`pull` and `push` both take `--dry-run`, and every command takes `--json` ([see Scripting](#scripting)). Two further commands work on exported archives rather than an account, and have [a section of their own](#working-with-exported-archives).

## How syncing works

The directory keeps a record of each recipe as it last arrived from Paprika, in a `.paprika` directory beside your files. That is what lets it tell the difference between a recipe you changed, a recipe that changed on the server, and one that changed in both places.

A few things are worth knowing:

**Changes on both sides are merged.** If you edited a recipe locally and it also changed in Paprika, `pull` reconciles the two: edits to different parts of the recipe both survive, and only genuinely overlapping edits need you. Those get the same conflict markers git uses:

```markdown
## Directions

<<<<<<< yours
Bake for 20 minutes.
=======
Bake for 25 minutes.
>>>>>>> paprika
```

The merged recipe is then just a local change like any other — `status` shows it, `push` sends it, `restore` throws it away. A recipe with markers still in it is refused by `push` until you have edited them out, so a half-resolved merge can never reach your account.

Two things can't be merged that way: the recipe's **name**, and any non-prose field like the **rating** or a time. There is nowhere in a rating to write "either 4 or 5, you decide", so if one of those changed on both sides, nothing is touched and you are told which field disagreed.

**Deleting a file moves the recipe to Paprika's trash.** Deletion syncs in both directions, but never destructively: a file you delete is pushed as a move into Paprika's own trash, where the app can still recover it, and a recipe you delete or trash in Paprika is removed from your directory on the next `pull`. Nothing is permanently destroyed by either.

**Anything can be undone before you push it.** `restore` puts a recipe back exactly the way it last arrived -- an edit, or the file itself if you deleted it:

```bash
paprika-recipes restore "Best-Ever Focaccia"   # by title
paprika-recipes restore ./Breads/Focaccia.md   # or by file
paprika-recipes restore --all                  # or everything
```

That includes a photo: restoring puts the embed back the way it arrived, and if you had swapped the image itself out, the substitute is discarded so that the next `pull` can put the original back — the one thing restore cannot do without the network is re-download it on the spot.

The one thing `restore` will not do is delete a recipe you created yourself and never pulled, since there is nothing to put such a file back to.

**Reformatting a file is not an edit.** Rewrapping a list or reordering the frontmatter changes the file without changing the recipe, and nothing gets uploaded for it.

**Photos sync, in both directions.** A recipe's photo is downloaded into an `attachments/` folder beside your files, and the recipe embeds it with ordinary markdown image markup directly beneath its title — so it shows up in your editor, your vault, and anywhere else markdown renders. If you tidy the attachment away by hand, the next `pull` quietly puts it back.

The embed line is also how you change the photo. To give a recipe one, drop the image into `attachments/` and write the embed yourself, spelled however you like:

```markdown
# Khachapuri

![fresh out of the oven](attachments/my dinner.jpg)
```

`push` then uploads it exactly the way the app would — a square thumbnail onto the recipe, the full picture into its photo gallery — and renames your file to the name the server chose, rewriting the embed to match. Deleting the embed line removes the photo from Paprika on the next push, and swapping the image file out for different bytes replaces it, even though the file's text never changed; `status` reports every one of these as `modified: (photo)` so nothing leaves without your having seen it. Anything reasonable is accepted — a PNG becomes a JPEG on the way up, a sideways phone photo is stood upright, and anything larger than the 2048-pixel bound the app itself observes is scaled down to it.

One honest caveat: the copy in *your* directory keeps its full size, but what another clone downloads is the app's own copy of the recipe photo, which is the thumbnail. The full picture still lives in the recipe's gallery in the app.

**Anything you add to a file is left alone.** If these files live in a note vault, you will likely add `tags:` or `aliases:` to the frontmatter, and quite possibly a section of your own:

```markdown
## Ingredients

- 1⅓ cups bread flour

## Substitutions

Bread flour works, but 00 flour is better.

## Directions

...
```

Paprika has nowhere to put that section, so it is never uploaded — but it is not discarded either. It stays where you left it, including when a `pull` rewrites the file around it, and it does not count as a change to the recipe.

If you want a line that genuinely begins with `##` inside your directions, just write it: we escape it on the way out (`\## Step one`) and unescape it on the way back, which is standard Markdown and previews as you'd expect. An *unescaped* `##` always means a section.

**Renaming a file is fine.** Recipes are tracked by the `uid` in their frontmatter, not by their filename or location, so you can rename files and sort them into folders freely.

### Keeping out of your vault's way

If your vault already uses `rating:`, `source:`, `categories:` or `created:` for something of its own, clone with a prefix:

```bash
paprika-recipes clone you@example.com ~/vault/Recipes --frontmatter-prefix paprika_
```

Every field Paprika owns is then written as `paprika_rating:`, `paprika_uid:` and so on — and, just as importantly, an *unprefixed* field is yours. It stays in the file and is never uploaded, even if it happens to share a name with one of ours.

The prefix is chosen when you clone and cannot be changed afterwards without rewriting every file, so decide at the start. If the two ever do get out of step — a plugin that prunes frontmatter it does not recognise, say — `push` will notice that your files have stopped being identifiable and refuse to do anything, rather than treating them as new recipes and your existing ones as deleted.

### Recipe files

The format is markdown with YAML frontmatter. The prose -- description, ingredients, directions, notes, nutritional information -- is passed through exactly as Paprika stores it, and everything else lives in the frontmatter.

Notably, ingredient amounts are *not* parsed. Paprika stores ingredients as a single blob of text, and real recipes contain lines like `185 g wet ingredients: 2 large eggs, 3 large egg yolks, and enough water to reach 185 g in total` -- there is no amount to extract, and guessing at one would only lose information. What you write is what Paprika gets.

## Working with exported archives

If you would rather not give this tool your account details at all, you can work with a `.paprikarecipes` export from the app instead. Export from Paprika, edit, import back:

```bash
paprika-recipes extract-archive export.paprikarecipes ./recipes/
paprika-recipes create-archive ./recipes/ new-export.paprikarecipes
```

| Command | What it does |
|---|---|
| `extract-archive <archive> <directory>` | Unpack a `.paprikarecipes` export into the same markdown files `clone` writes. |
| `create-archive <directory> <archive>` | Pack a directory of recipe files back into a `.paprikarecipes` archive. |

You get the same markdown files `clone` writes, so everything above about the format applies. Recipe photos are written into the same `attachments/` folder a cloned directory uses, embedded from their recipes, and folded back in when you repack — an archive stores them inline as base64, which is fine for a zip file and hopeless for a file you intend to read.

What this route does *not* have is any memory of where a recipe came from, so there is no `status`, no change detection and no conflict handling. It is a straight unpack and repack. If you want those, use `clone`.

`create-archive` searches subdirectories, and skips a `.paprika` directory if it finds one — so you can also point it at a directory you cloned, and get an archive out of your account. One caveat if you did that with `--frontmatter-prefix`: the archive commands have no directory to ask about a prefix and always read and write unprefixed files.

## Scripting

Every command takes `--json`, which writes a versioned document to stdout and moves everything else — the report, the progress bar, any prompts — to stderr:

```bash
paprika-recipes status --json
```

& you'll receive this output:

```json
{
  "version": 1,
  "unchanged": 81,
  "recipes": [
    {
      "uid": "4C855813-25B8-41CD-96E7-5B38AA7AAAAF",
      "name": "One-Hour Pizza",
      "path": "/home/you/recipes/One-Hour Pizza.md",
      "status": "modified",
      "conflicted": false,
      "changed_fields": ["rating"],
      "unsyncable": ["tags"]
    }
  ]
}
```

Exit codes say what happened without your having to read the output:

| code | meaning |
|---|---|
| 0 | everything asked for was done |
| 1 | it ran, but something needs you — a conflict, a recipe it would not push |
| 2 | the command line was malformed |
| 3 | could not log in |
| 4 | Paprika could not be reached, or refused what we sent |
| 5 | something about the directory or its files is wrong |

`status` exits 0 whether or not you have local changes, since having them is the ordinary state of a working directory. Pass `--exit-code` — after `git diff --exit-code` — to have it answer that question instead.

Because `--json` implies nobody is watching, it will not stop to ask for a password; run any command once from a terminal to get your credentials into the keyring first.

## Upgrading from 2.x

Version 3 is a rethink rather than an upgrade: 2.x moved YAML files up and down wholesale, while 3.x keeps markdown files under real change tracking. The old commands map like so:

| 2.x | Where it went |
|---|---|
| `download-recipes` | `clone` — which also remembers what it wrote, so that `status`, `pull` and `push` can know what changed since. |
| `upload-recipes` | `push` — which sends only what you actually changed, and shows you first. |
| `edit-recipe`, `create-recipe` | Retired. The whole point now is that recipes are ordinary files: edit them in your own editor, write a new one with a `# Title`, and `push`. |
| `store-password` | Retired. `clone` asks for your password the first time it needs it — and it reads the same keyring entry `store-password` wrote, so a password you stored under 2.x is found without asking. |
| `extract-archive`, `create-archive` | Still here, now reading and writing the same markdown files as everything else. |

The default account is gone too, along with the global config file: a directory remembers which account it was cloned from, and that is the whole configuration.

A directory that `download-recipes` wrote is not something 3.x can adopt — the files were YAML, and nothing recorded what they looked like when they arrived. Start over with `clone` into a fresh directory; your password is already in the keyring, so it is exactly one command.

## Other tools

Plenty of tools can get recipes *out* of Paprika as markdown. As far as I know, this is the only one that also gets your edits back *in* — the others are exporters, run once or on a schedule, with no memory of what you have changed since. If a one-time export is genuinely all you need, any of these will serve:

| | Reads from | Writes | Edits go back to Paprika | Photos |
|---|---|---|---|---|
| paprika-recipes | your account, or an archive | markdown | ✅ full two-way sync | ✅ both directions |
| [paprika-to-obsidian-markdown](https://github.com/jt196/paprika-to-obsidian-markdown) | `.paprikarecipes` archive | markdown (Obsidian/Dataview templates) | ❌ | download only |
| [paprika-to-markdown](https://github.com/simonhbor/paprika-to-markdown) | `.paprikarecipes` archive | markdown | ❌ | download only |
| [paprika-exporter](https://github.com/bojanrajkovic/paprika-exporter) (archived) | your account | markdown (Jekyll-flavored) | ❌ | — |
| [paprika-exporter](https://github.com/sstarcher/paprika-exporter) | your account | YAML | ❌ | download only |

Two neighbours doing a different job entirely: [kappari](https://github.com/johnwbyrd/kappari) documents the Paprika API rather than wrapping it, and [paprika-tools](https://github.com/aarons22/paprika-tools) exposes Paprika to AI agents as an MCP server rather than as files on disk.
