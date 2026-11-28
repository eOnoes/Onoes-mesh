# QFN075 source-only tests.
# Pure synthetic string tests for _same_archive_path. No archives, no owner.run,
# no approved_inputs execution.
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parent))

import cloud_owner_entry


PRIVATE_SENTINEL='PRIV-SENTINEL-7f3a9c-DO-NOT-ECHO'


class SameArchivePathTests(unittest.TestCase):
    def assert_bool(self,reported,approved,expected):
        with self.subTest(reported=reported,approved=approved,expected=expected):
            reported_before=[reported,approved] if isinstance(reported,list) else (reported,approved)
            result=cloud_owner_entry._same_archive_path(reported,approved)
            self.assertIs(type(result),bool)
            self.assertIs(result,expected)
            reported_after=[reported,approved] if isinstance(reported,list) else (reported,approved)
            self.assertEqual(reported_after,reported_before)
            self.assertNotIn(PRIVATE_SENTINEL,repr(result))

    def test_identical_absolute_path_accepted(self):
        if os.name=='nt':
            self.assert_bool('E:\\Backups\\cyony-2026-11-26.7z','E:\\Backups\\cyony-2026-11-26.7z',True)
        if os.name=='posix':
            self.assert_bool('/srv/backups/cyony-2026-11-26.7z','/srv/backups/cyony-2026-11-26.7z',True)
            self.assert_bool('/srv/backups/archive-a.7z','/srv/backups/archive-b.7z',False)
        always_absolute=str(Path.cwd()/'harmless-synthetic.7z')
        self.assert_bool(always_absolute,always_absolute,True)

    @unittest.skipUnless(os.name=='nt','Windows path semantics only on Windows')
    def test_windows_separator_and_case_variants_accepted(self):
        self.assert_bool('E:\\Backups\\Cyony-2026-11-26.7z','E:/Backups/cyony-2026-11-26.7z',True)
        self.assert_bool('e:/backups/cyony-2026-11-26.7z','E:\\BACKUPS\\CYONY-2026-11-26.7Z',True)

    def test_dots_are_never_collapsed_even_when_equal_after_collapse(self):
        # Both sides carry raw '.'/'..' components: Path would compare equal,
        # but the raw-component check must deny before any dot collapsing.
        self.assert_bool('E:\\Backups\\a\\..\\b\\archive.7z','E:\\Backups\\a\\..\\b\\archive.7z',False)
        self.assert_bool('E:/Backups/./archive.7z','E:/Backups/./archive.7z',False)

    def test_different_file_drive_or_directory_denied(self):
        self.assert_bool('E:\\Backups\\archive-a.7z','E:\\Backups\\archive-b.7z',False)
        self.assert_bool('D:\\Backups\\archive.7z','E:\\Backups\\archive.7z',False)
        self.assert_bool('E:\\Other\\archive.7z','E:\\Backups\\archive.7z',False)

    def test_relative_and_drive_relative_denied(self):
        self.assert_bool('archive.7z','archive.7z',False)
        self.assert_bool('.\\archive.7z','.\\archive.7z',False)
        self.assert_bool('\\archive.7z','\\archive.7z',False)
        if os.name=='nt':
            self.assert_bool('E:archive.7z','E:archive.7z',False)
            self.assert_bool('E:archive.7z','E:\\archive.7z',False)

    def test_dot_and_dotdot_aliases_denied_both_separator_forms(self):
        self.assert_bool('E:\\Backups\\.\\archive.7z','E:\\Backups\\archive.7z',False)
        self.assert_bool('E:/Backups/./archive.7z','E:/Backups/archive.7z',False)
        self.assert_bool('E:\\Backups\\x\\..\\archive.7z','E:\\Backups\\archive.7z',False)
        self.assert_bool('E:/Backups/x/../archive.7z','E:/Backups/archive.7z',False)
        self.assert_bool('E:\\Backups\\archive.7z','E:\\Backups\\.\\archive.7z',False)
        self.assert_bool('E:\\Backups\\archive.7z','E:\\Backups\\x\\..\\archive.7z',False)

    def test_malformed_types_denied(self):
        self.assert_bool('','E:\\Backups\\archive.7z',False)
        self.assert_bool('E:\\Backups\\archive.7z','',False)
        self.assert_bool(None,'E:\\Backups\\archive.7z',False)
        self.assert_bool('E:\\Backups\\archive.7z',None,False)
        self.assert_bool(True,True,False)
        self.assert_bool(False,False,False)
        self.assert_bool([],[],False)
        self.assert_bool({}, {},False)
        self.assert_bool(['E:\\Backups\\archive.7z'],['E:\\Backups\\archive.7z'],False)
        self.assert_bool('E:\\Backups\\arch\x00ive.7z','E:\\Backups\\arch\x00ive.7z',False)
        self.assert_bool(123,123,False)
        self.assert_bool(Path('E:\\Backups\\archive.7z'),Path('E:\\Backups\\archive.7z'),False)

    def test_same_basename_at_different_path_denied(self):
        self.assert_bool('E:\\Backups\\archive.7z','E:\\Staging\\archive.7z',False)

    def test_prefix_like_filename_denied(self):
        self.assert_bool('E:\\Backups\\archive.7z','E:\\Backups\\archive.7z.bak',False)
        self.assert_bool('E:\\Backups\\archive.7z.old','E:\\Backups\\archive.7z',False)

    def test_approved_input_also_validated(self):
        # An approved value that is itself malformed must be refused too.
        self.assert_bool('E:\\Backups\\archive.7z','relative\\archive.7z',False)
        self.assert_bool('E:\\Backups\\archive.7z',None,False)
        self.assert_bool('E:\\Backups\\archive.7z','E:\\Backups\\..\\archive.7z',False)

    def test_private_sentinel_never_leaked(self):
        for reported,approved in (
                (PRIVATE_SENTINEL,'E:\\Backups\\archive.7z'),
                ('E:\\Backups\\archive.7z',PRIVATE_SENTINEL)):
            with self.subTest(reported=reported):
                result=cloud_owner_entry._same_archive_path(reported,approved)
                self.assertIs(result,False)
                self.assertNotIn(PRIVATE_SENTINEL,repr(result))
                self.assertNotIn(PRIVATE_SENTINEL,str(result))


if __name__=='__main__':
    unittest.main()
