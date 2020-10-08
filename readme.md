# Paprika: Easily read and modify your paprika recipes

[Paprika](https://www.paprikaapp.com/) is a lovely recipe app that works a lot better than I was expecting it to, and although its recipe imports are usually fantastic, sometimes things are imported just slightly incorrectly and require manual touch-up. This is a library I built to make that just a little easier to do.

## Installation

```
pip install paprika-recipes
```

## Usage

### Modifying via Paprika's API

#### Modifying one of your existing recipes

You can modify a recipe on your Paprika account by running the following

```
paprika-recipes edit-recipe your@email.address
```

You'll be presented with a list of recipes on your account and after
you select the recipe you'd like to edit, your editor will be opened
to allow you to make the modifications you want to make.
Just save and close your editor to upload your updated recipe to Paprika.

If you have decided that you've made a mistake and would like to abort,
just delete all of the contents of the file before saving and closing
your editor. We won't update your recipe if you do that.

You can also provide search parameters as command-line arguments to
limit the list of recipes presented to you, and if your search terms
match just one of your recipes, we'll open the editor straight away.

#### Creating a new recipe on your Paprika account

You can create a new recipe on your Paprika account by running the following

```
paprika-recipes create-recipe your@email.address
```

Your editor will be opened to a brand new empty recipe. Just write out
your recipe's instructions and whatever other fields you'd like to fill
out, then save and close your editor -- we'll upload your recipe to your
Paprika account as soon as your editor has closed.

If you have decided that you've made a mistake and would like to abort,
just delete all of the contents of the file before saving and closing
your editor. We won't update your recipe if you do that.

#### Downloading your whole recipe collection

If you want to download your whole recipe archive instead of editing or creating a single recipe at a time, you can download your whole recipe collection into a directory on your computer.

The expected workflow for changing your recipes when using this method is a three-step process:

1. Downloading your paprika recipes from your account.
2. Modifying the extracted yaml recipe files or creating new ones.
3. Uploading your changed or new recipes back to your account.

Before beginning, though, you will need to store your paprika account information in your system keyring by running:

```
paprika-recipes store-password
```

You'll be asked for your e-mail and password; after that point, this library will fetch your password from your system keyring instead of prompting you for it.

##### Downloading

```
paprika-recipes download-recipes your@email.address /path/to/export/your/recipes
```

##### Uploading

```
paprika-recipes upload-recipes your@email.address /path/to/where/you/exported/your/recipes
```

### Modifying via Exported Archives

The expected workflow for changing your recipes is a three-step process:

1. Extracting your `paprikarecipes` file to a directory.
2. Modifying the extracted yaml recipe files.
3. Compress your recipes back into an archive.

#### Extracting

```
paprika-recipes extract-archive /path/to/your/export.paprikarecipes /path/to/extract/recipes/to/

```

#### Compressing

```
paprika-recipes create-archive /path/you/earlier/extracted/recipes/to/ /path/to/a/new/export.paprikarecipes

```
