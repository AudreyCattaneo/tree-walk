import os
import shutil
import tempfile
import unittest

from tree_walk import walk, DirEntry


class _TempTree:
    """Context object that builds a known directory tree and cleans up."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="tree_walk_test_")

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def join(self, *parts):
        return os.path.join(self.root, *parts)

    def write(self, relpath, content=b""):
        full = self.join(relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(content)
        return full

    def mkdir(self, relpath):
        full = self.join(relpath)
        os.makedirs(full, exist_ok=True)
        return full


class TestWalkBasics(unittest.TestCase):
    def setUp(self):
        self.tree = _TempTree()

    def tearDown(self):
        self.tree.close()

    def _names(self, entries):
        return [e.name for e in entries]

    def test_root_is_yielded_first(self):
        entries = list(walk(self.tree.root))
        self.assertEqual(entries[0].path, os.path.normpath(self.tree.root))
        self.assertTrue(entries[0].is_dir)

    def test_empty_root_yields_only_root(self):
        entries = list(walk(self.tree.root))
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].is_dir)

    def test_files_and_dirs_sorted_by_name(self):
        # Names chosen so that code-point order differs from any naive
        # insertion order: uppercase sorts before lowercase.
        self.tree.write("Zebra.txt")
        self.tree.write("apple.txt")
        self.tree.write("sub/inner.txt")
        self.tree.mkdir("sub")

        entries = list(walk(self.tree.root))
        names = self._names(entries)

        # root first, then sorted children of root, then sorted children of sub
        self.assertEqual(names[0], os.path.basename(self.tree.root))
        # Children of root in sorted order: Zebra.txt, apple.txt, sub
        # (uppercase Z < lowercase a by code point)
        self.assertEqual(names[1:], ["Zebra.txt", "apple.txt", "sub", "inner.txt"])

    def test_depth_first_order(self):
        self.tree.mkdir("a")
        self.tree.mkdir("a/b")
        self.tree.write("a/b/c.txt")
        self.tree.write("a/x.txt")
        self.tree.write("top.txt")

        entries = list(walk(self.tree.root))
        names = self._names(entries)

        # root, then sorted children of root (a < top.txt by code point),
        # then a's children (b, x.txt), then b's child (c.txt). Depth-first:
        # after entering a, we fully descend a before moving to a's siblings.
        self.assertEqual(
            names,
            [os.path.basename(self.tree.root), "a", "b", "c.txt", "x.txt", "top.txt"],
        )


class TestPrune(unittest.TestCase):
    def setUp(self):
        self.tree = _TempTree()
        self.tree.write("keep/me.txt")
        self.tree.write("skip/secret.txt")
        self.tree.write("skip/deep/extra.txt")

    def tearDown(self):
        self.tree.close()

    def test_prune_skips_directory_contents(self):
        entries = list(walk(self.tree.root, prune=lambda e: e.name == "skip"))
        names = [e.name for e in entries]
        self.assertIn("skip", names)
        self.assertNotIn("secret.txt", names)
        self.assertNotIn("deep", names)
        self.assertNotIn("extra.txt", names)
        self.assertIn("keep", names)
        self.assertIn("me.txt", names)

    def test_prune_root_yields_root_only(self):
        entries = list(walk(self.tree.root, prune=lambda e: e.path == os.path.normpath(self.tree.root)))
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].is_dir)

    def test_prune_not_called_on_files(self):
        seen = []
        def p(e):
            seen.append(e)
            return False
        list(walk(self.tree.root, prune=p))
        # prune should only see directories
        for entry in seen:
            self.assertTrue(
                entry.is_dir,
                f"prune saw non-dir name: {entry.name}",
            )


class TestDirEntry(unittest.TestCase):
    def test_kind_for_file(self):
        e = DirEntry(path="/x", name="x", is_dir=False, is_file=True, is_symlink=False)
        self.assertEqual(e.kind, "file")

    def test_kind_for_dir(self):
        e = DirEntry(path="/x", name="x", is_dir=True, is_file=False, is_symlink=False)
        self.assertEqual(e.kind, "dir")

    def test_kind_for_symlink_is_link_even_if_target_is_dir(self):
        e = DirEntry(path="/x", name="x", is_dir=True, is_file=False, is_symlink=True)
        self.assertEqual(e.kind, "link")

    def test_frozen(self):
        e = DirEntry(path="/x", name="x", is_dir=False, is_file=True, is_symlink=False)
        with self.assertRaises(Exception):
            e.path = "/y"  # type: ignore[misc]


class TestSymlinks(unittest.TestCase):
    def setUp(self):
        self.tree = _TempTree()
        self.tree.write("real.txt", b"hi")
        self.tree.mkdir("realdir")
        self.tree.write("realdir/inside.txt")

    def tearDown(self):
        self.tree.close()

    def test_symlink_to_file_is_not_followed(self):
        link = self.tree.join("link.txt")
        os.symlink(self.tree.join("real.txt"), link)
        entries = list(walk(self.tree.root))
        link_entry = next(e for e in entries if e.name == "link.txt")
        self.assertTrue(link_entry.is_symlink)
        self.assertFalse(link_entry.is_dir)
        self.assertEqual(link_entry.kind, "link")

    def test_symlink_to_dir_is_not_descended(self):
        link = self.tree.join("linkdir")
        os.symlink(self.tree.join("realdir"), link)
        entries = list(walk(self.tree.root))
        names = [e.name for e in entries]
        self.assertIn("linkdir", names)
        # inside.txt lives under realdir; it should appear once (via realdir),
        # not a second time via the symlink.
        self.assertEqual(names.count("inside.txt"), 1)


class TestErrors(unittest.TestCase):
    def test_nonexistent_root_raises(self):
        with self.assertRaises(FileNotFoundError):
            list(walk("/this/path/does/not/exist/tree_walk_test"))

    def test_non_string_root_raises(self):
        with self.assertRaises(TypeError):
            list(walk(123))  # type: ignore[arg-type]

    def test_unreadable_subdir_does_not_abort_walk(self):
        tree = _TempTree()
        try:
            tree.write("readable.txt")
            secret = tree.mkdir("secret")
            tree.write("secret/hidden.txt")
            # Remove permission to read the directory. On non-root CI this
            # denies scandir. If running as root, this test is a no-op; we
            # detect that and skip the assertion rather than fail.
            os.chmod(secret, 0o000)
            entries = list(walk(tree.root))
            names = [e.name for e in entries]
            self.assertIn("readable.txt", names)
            # secret itself is still listed (it's an entry in its parent); only
            # its children are skipped.
            self.assertIn("secret", names)
            can_read_secret = os.access(secret, os.R_OK | os.X_OK)
            if not can_read_secret:
                self.assertNotIn("hidden.txt", names)
            else:
                self.skipTest("running as root or equivalent; permission test is moot")
        finally:
            # Restore so cleanup can remove it.
            os.chmod(tree.join("secret"), 0o700)
            tree.close()


if __name__ == "__main__":
    unittest.main()
