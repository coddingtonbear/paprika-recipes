# Paprika-Recipes: Keep your paprika recipes in a directory of markdown files

[Paprika](https://www.paprikaapp.com/) is a lovely recipe app, but your recipes live inside it. This tool checks them out into a directory of plain markdown files that you can edit in whatever you already use -- your editor, your note vault, your usual git workflow -- and then sync your changes back.

If you have used git, you already know the commands: `clone`, `pull`, `push`, `status`.

## Installation

```
pip install paprika-recipes
```

## Getting started

There is nothing to set up. Check out your recipes:

```
paprika-recipes clone you@example.com ~/recipes
```

You'll be asked for your Paprika password. It goes into your system keyring, and the account is recorded in the directory itself, so nothing asks again — and if your password ever changes, you're simply asked for the new one the next time it doesn't work.

The account is named rather than remembered, deliberately. There is no default account to fall back on, because which account a directory belongs to decides what gets written into it and where everything in it is sent from then on.

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

```
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

Write a markdown file with a `# Title` and whatever sections you want, and `push` will create it in Paprika. It gets a `uid:` written into its frontmatter at that moment, and is an ordinary tracked recipe from then on.

### Scripting

Every command takes `--json`, which writes a versioned document to stdout and moves everything else — the report, the progress bar, any prompts — to stderr:

```
$ paprika-recipes status --json
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

```
paprika-recipes restore "Best-Ever Focaccia"   # by title
paprika-recipes restore ./Breads/Focaccia.md   # or by file
paprika-recipes restore --all                  # or everything
```

The one thing `restore` will not do is delete a recipe you created yourself and never pulled, since there is nothing to put such a file back to.

**Reformatting a file is not an edit.** Rewrapping a list or reordering the frontmatter changes the file without changing the recipe, and nothing gets uploaded for it.

**Photos come along.** A recipe's photo is downloaded into an `attachments/` folder beside your files, and the recipe embeds it with ordinary markdown image markup directly beneath its title — so it shows up in your editor, your vault, and anywhere else markdown renders. If you tidy the attachment away by hand, the next `pull` quietly puts it back.

For now the photo itself belongs to the app: deleting the embed line or writing your own does not remove or add a photo in Paprika, and `push` will say so rather than let you think it did. Adding and removing photos from the directory is planned; the embed is already the way you will do it.

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

```
paprika-recipes clone you@example.com ~/vault/Recipes --frontmatter-prefix paprika_
```

Every field Paprika owns is then written as `paprika_rating:`, `paprika_uid:` and so on — and, just as importantly, an *unprefixed* field is yours. It stays in the file and is never uploaded, even if it happens to share a name with one of ours.

The prefix is chosen when you clone and cannot be changed afterwards without rewriting every file, so decide at the start. If the two ever do get out of step — a plugin that prunes frontmatter it does not recognise, say — `push` will notice that your files have stopped being identifiable and refuse to do anything, rather than treating them as new recipes and your existing ones as deleted.

### Recipe files

The format is markdown with YAML frontmatter. The prose -- description, ingredients, directions, notes, nutritional information -- is passed through exactly as Paprika stores it, and everything else lives in the frontmatter.

Notably, ingredient amounts are *not* parsed. Paprika stores ingredients as a single blob of text, and real recipes contain lines like `185 g wet ingredients: 2 large eggs, 3 large egg yolks, and enough water to reach 185 g in total` -- there is no amount to extract, and guessing at one would only lose information. What you write is what Paprika gets.

## Working with exported archives

If you would rather not give this tool your account details at all, you can work with a `.paprikarecipes` export from the app instead. Export from Paprika, edit, import back:

```
paprika-recipes extract-archive export.paprikarecipes ./recipes/
paprika-recipes create-archive ./recipes/ new-export.paprikarecipes
```

You get the same markdown files `clone` writes, so everything above about the format applies. Recipe photos are written into the same `attachments/` folder a cloned directory uses, embedded from their recipes, and folded back in when you repack — an archive stores them inline as base64, which is fine for a zip file and hopeless for a file you intend to read.

What this route does *not* have is any memory of where a recipe came from, so there is no `status`, no change detection and no conflict handling. It is a straight unpack and repack. If you want those, use `clone`.

`create-archive` searches subdirectories, and skips a `.paprika` directory if it finds one — so you can also point it at a directory you cloned, and get an archive out of your account. One caveat if you did that with `--frontmatter-prefix`: the archive commands have no directory to ask about a prefix and always read and write unprefixed files.
