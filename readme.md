# Paprika: Easily read and modify your paprika recipes

[Paprika](https://www.paprikaapp.com/) is a lovely recipe app that works a lot better than I was expecting it to, and although its recipe imports are usually fantastic, sometimes things are imported just slightly incorrectly and require manual touch-up. This is a library I built to make that just a little easier to do.

## Installation

```
pip install paprika-recipe
```

## Usage

### Modifying via Paprika's API

The expected workflow for changing your recipes when using this method is a three-step process:

1. Downloading your paprika recipes from your account.
2. Modifying the extracted yaml recipe files or creating new ones.
3. Uploading your changed or new recipes back to your account.

Before beginning, though, you will need to store your paprika account information in your system keyring by running:

```
paprika-recipe store-password
```

You'll be asked for your e-mail and password; after that point, this library will fetch your password from your system keyring instead of prompting you for it.

#### Downloading

```
paprika-recipe download-recipes your@email.address /path/to/export/your/recipes
```

#### Uploading

```
paprika-recipe upload-recipes your@email.address /path/to/where/you/exported/your/recipes
```

### Modifying via Exported Archives

The expected workflow for changing your recipes is a three-step process:

1. Extracting your `paprikarecipes` file to a directory.
2. Modifying the extracted yaml recipe files.
3. Compress your recipes back into an archive.

#### Extracting

```
paprika-recipe extract-archive /path/to/your/export.paprikarecipes /path/to/extract/recipes/to/

```

#### Compressing

```
paprika-recipe create-archive /path/you/earlier/extracted/recipes/to/ /path/to/a/new/export.paprikarecipes

```
