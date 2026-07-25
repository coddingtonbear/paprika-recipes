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
paprika-recipes clone ~/recipes
```

The first time, you'll be asked for your Paprika e-mail and password. The password goes into your system keyring and the e-mail is recorded in the directory itself, so nothing asks again — and if your password ever changes, you're simply asked for the new one the next time it doesn't work.

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

### Recipe files

The format is markdown with YAML frontmatter. The prose -- description, ingredients, directions, notes, nutritional information -- is passed through exactly as Paprika stores it, and everything else lives in the frontmatter.

Notably, ingredient amounts are *not* parsed. Paprika stores ingredients as a single blob of text, and real recipes contain lines like `185 g wet ingredients: 2 large eggs, 3 large egg yolks, and enough water to reach 185 g in total` -- there is no amount to extract, and guessing at one would only lose information. What you write is what Paprika gets.

## Working with exported archives

If you would rather not give this tool your account details at all, you can work with a `.paprikarecipes` export from the app instead. Export from Paprika, edit, import back:

```
paprika-recipes extract-archive export.paprikarecipes ./recipes/
paprika-recipes create-archive ./recipes/ new-export.paprikarecipes
```

You get the same markdown files `clone` writes, so everything above about the format applies. Recipe photos are written next to their recipe as ordinary image files (`Khachapuri.png` beside `Khachapuri.md`) and folded back in when you repack — an archive stores them inline as base64, which is fine for a zip file and hopeless for a file you intend to read.

What this route does *not* have is any memory of where a recipe came from, so there is no `status`, no change detection and no conflict handling. It is a straight unpack and repack. If you want those, use `clone`.

`create-archive` searches subdirectories, and skips a `.paprika` directory if it finds one — so you can also point it at a directory you cloned, and get an archive out of your account.
