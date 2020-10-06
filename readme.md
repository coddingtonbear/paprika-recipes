# Paprika: Easily read and modify your `paprikarecipes` exported archives.

[Paprika](https://www.paprikaapp.com/) is a lovely recipe app that works a lot better than I was expecting it to, and although its recipe imports are usually fantastic, sometimes things are imported just slightly incorrectly and require manual touch-up. This is a library I built to make that just a little easier to do.

## Installation

```
pip install paprika-recipe
```

## Usage

The expected workflow for changing your recipes is a three-step process:

1. Extracting your `paprikarecipes` file to a directory.
2. Modifying the extracted yaml recipe files.
3. Compress your recipes back into an archive.

### Extracting

```
paprika-recipe extract-archive /path/to/your/export.paprikarecipes /path/to/extract/recipes/to/
```

### Compressing

```
paprika-recipe create-archive /path/you/earlier/extracted/recipes/to/ /path/to/a/new/export.paprikarecipes
```
