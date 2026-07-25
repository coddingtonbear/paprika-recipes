# Paprika-Recipes: Keep your paprika recipes in a directory of markdown files

[Paprika](https://www.paprikaapp.com/) is a lovely recipe app, but your recipes live inside it. This tool checks them out into a directory of plain markdown files that you can edit in whatever you already use -- your editor, your note vault, your usual git workflow -- and then sync your changes back.

If you have used git, you already know the commands: `clone`, `pull`, `push`, `status`.

## Installation

```
pip install paprika-recipes
```

## Getting started

Store your account details in your system keyring:

```
paprika-recipes store-password
```

You'll be asked for your e-mail and password. After that the app fetches your password from the keyring rather than prompting you.

Then check out your recipes:

```
paprika-recipes clone ~/recipes
```

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

**Conflicts are reported, not merged.** If a recipe changed on both sides, neither copy is touched and you are told which fields differ. Recipes are prose, and a tool that silently interleaved two versions of your directions would be worse than one that asks you to look.

**Deleting a file moves the recipe to Paprika's trash.** Deletion syncs in both directions, but never destructively: a file you delete is pushed as a move into Paprika's own trash, where the app can still recover it, and a recipe you delete or trash in Paprika is removed from your directory on the next `pull`. Nothing is permanently destroyed by either.

**Anything can be undone before you push it.** `restore` puts a recipe back exactly the way it last arrived -- an edit, or the file itself if you deleted it:

```
paprika-recipes restore "Best-Ever Focaccia"   # by title
paprika-recipes restore ./Breads/Focaccia.md   # or by file
paprika-recipes restore --all                  # or everything
```

The one thing `restore` will not do is delete a recipe you created yourself and never pulled, since there is nothing to put such a file back to.

**Reformatting a file is not an edit.** Rewrapping a list or reordering the frontmatter changes the file without changing the recipe, and nothing gets uploaded for it.

**Your own frontmatter is left alone.** If these files live in a note vault, you will likely add `tags:` or `aliases:` of your own. Those are preserved across a `pull`; they are yours, and we neither interpret nor discard them.

**Renaming a file is fine.** Recipes are tracked by the `uid` in their frontmatter, not by their filename or location, so you can rename files and sort them into folders freely.

### Recipe files

The format is markdown with YAML frontmatter. The prose -- description, ingredients, directions, notes, nutritional information -- is passed through exactly as Paprika stores it, and everything else lives in the frontmatter.

Notably, ingredient amounts are *not* parsed. Paprika stores ingredients as a single blob of text, and real recipes contain lines like `185 g wet ingredients: 2 large eggs, 3 large egg yolks, and enough water to reach 185 g in total` -- there is no amount to extract, and guessing at one would only lose information. What you write is what Paprika gets.

## Working with exported archives

If you would rather not give the app your account details, you can work with a `.paprikarecipes` export from the app instead. This route has no sync and no change detection; it just unpacks and repacks the archive.

```
paprika-recipes extract-archive /path/to/export.paprikarecipes /path/to/extract/to/
paprika-recipes create-archive /path/you/extracted/to/ /path/to/new-export.paprikarecipes
```

## Other commands

`download-recipes` and `upload-recipes` predate the sync commands and copy your account to and from a directory of YAML files with no change tracking at all. `clone`/`pull`/`push` supersede them for almost every purpose.
