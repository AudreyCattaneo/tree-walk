"""Core directory walker with prune rules and stable ordering.

Design decisions (stated plainly so tests and users share one reading):

- Ordering is by name, ascending, using Python's default string comparison
  (code-point order). Not locale-aware, not natural order. One rule, no
  compromises.

- ``prune`` is a predicate receiving a DirEntry for a directory. If it returns
  True, that directory is yielded but its contents are not descended into.
  This lets callers decide "keep the folder, skip the children" which is the
  common case for e.g. ``.git``.

- Symlinks to directories are NOT followed. They are yielded as entries of kind
  "link". Following symlinks during a walk is a recipe for cycles and is a
  separate problem; this library does not attempt it.

- Errors from ``os.scandir`` (e.g. PermissionError) on subdirectories are
  swallowed: that branch is skipped and walking continues. Errors on the root
  itself propagate, since a nonexistent or unreadable root has nothing to walk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional


@dataclass(frozen=True)
class DirEntry:
    """A single entry discovered during a walk.

    A thin, serializable view over ``os.DirEntry`` so callers can store entries
    in lists without holding open file descriptors or OS resources.
    """

    path: str
    name: str
    is_dir: bool
    is_file: bool
    is_symlink: bool

    @property
    def kind(self) -> str:
        """Coarse kind: 'dir', 'file', or 'link'.

        A symlink is reported as 'link' regardless of what it points at, so a
        broken symlink still has a stable kind. Use ``is_dir``/``is_file`` if
        you need the target's type instead.
        """
        if self.is_symlink:
            return "link"
        if self.is_dir:
            return "dir"
        return "file"


def _to_entry(path: str, scanned: os.DirEntry) -> DirEntry:
    # ``is_dir``/``is_file`` on os.DirEntry follow symlinks by default, which is
    # what we want for the is_dir/is_file fields. ``is_symlink`` does not.
    return DirEntry(
        path=path,
        name=scanned.name,
        is_dir=scanned.is_dir(),
        is_file=scanned.is_file(),
        is_symlink=scanned.is_symlink(),
    )


def _descend(
    current: str,
    prune: Optional[Callable[[DirEntry], bool]],
) -> Iterator[DirEntry]:
    """Yield entries in ``current`` and recurse depth-first into subdirs."""
    try:
        with os.scandir(current) as it:
            scanned = sorted(it, key=lambda e: e.name)
    except OSError:
        # Permission denied, vanished directory, etc. We stop descending
        # this branch but continue with any siblings. Raising would abort the
        # whole walk; that's a worse default for a tree walker.
        return

    for entry in scanned:
        full = os.path.join(current, entry.name)
        de = _to_entry(full, entry)
        yield de
        # Only descend into real directories. Symlinks to directories have
        # is_dir True (because os.DirEntry.is_dir follows symlinks), but we
        # deliberately skip them to avoid cycles. Check is_symlink first.
        if de.is_dir and not de.is_symlink:
            if prune is not None and prune(de):
                continue
            yield from _descend(full, prune)


def walk(
    root: str,
    *,
    prune: Optional[Callable[[DirEntry], bool]] = None,
) -> Iterator[DirEntry]:
    """Yield DirEntry objects for ``root`` and everything beneath it.

    The ``root`` directory itself is yielded first, then its contents in
    name-sorted order. Subdirectories are descended into depth-first.

    ``prune``, if given, is called with each directory entry (including
    ``root``). If it returns true, the directory is yielded but not entered.

    Ordering is by name ascending (code-point order). This is deliberately
    simple and deterministic across platforms; we do not attempt natural sort
    or locale-aware sort, both of which introduce ambiguity.
    """
    if not isinstance(root, str):
        raise TypeError("root must be a string path")

    root = os.path.normpath(root)

    # We treat ``root`` as a directory and yield it. If it doesn't exist,
    # os.scandir below raises FileNotFoundError, which we let propagate rather
    # than guessing at a friendlier error.
    root_entry = DirEntry(
        path=root,
        name=os.path.basename(root),
        is_dir=True,
        is_file=False,
        is_symlink=os.path.islink(root),
    )
    yield root_entry

    if prune is not None and prune(root_entry):
        return

    # Validate the root exists and is readable before walking. This raises
    # FileNotFoundError for nonexistent roots and PermissionError for unreadable
    # ones, matching caller expectations for the top-level call.
    with os.scandir(root):
        pass

    yield from _descend(root, prune)
