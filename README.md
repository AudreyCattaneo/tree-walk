# Tree Walk

Walk a directory tree with a prune predicate and stable, name-sorted ordering. Standard library only.

```python
from tree_walk import walk

for entry in walk("."):
    print(entry.kind, entry.path)

# Skip .git and node_modules entirely
for entry in walk(".", prune=lambda e: e.name in {".git", "node_modules"}):
    print(entry.path)
```

## Why

`os.walk` yields `(dirpath, dirnames, filenames)` tuples and mutates `dirnames` in place for pruning. That works, but it makes the common case — "give me a flat, sorted stream of entries with a few folders skipped" — more awkward than it needs to be. This library yields `DirEntry` objects one at a time, already sorted by name, with a simple `prune` callback.

The trade-off: it holds nothing open and buffers one directory's listing at a time, so very wide directories cost memory proportional to their child count. It does not follow symlinks, does not do natural sort, and is not locale-aware. Ordering is by code point. One rule, no configuration.

## Edge cases you will hit

- **Symlinks to directories are not followed.** They appear as entries with `kind == "link"` and `is_symlink == True`, but their contents are not descended into. This prevents cycles. If you need to follow a symlink, resolve it and walk the target separately.
- **Unreadable subdirectories are skipped, not raised.** If `os.scandir` fails on a child directory (e.g. `PermissionError`), that branch is silently dropped and walking continues. The parent entry is still yielded. If you need strict failure, wrap the call and check for completeness yourself.
- **The root is always yielded first**, as a directory entry, even if it is empty or if `prune` returns true for it.
- **`prune` is called on directories only**, including the root. Files are never passed to it.

## Exports

- `walk(root, *, prune=None) -> Iterator[DirEntry]`
- `DirEntry` — frozen dataclass with fields `path`, `name`, `is_dir`, `is_file`, `is_symlink`, and a `kind` property returning `"dir"`, `"file"`, or `"link"`.
