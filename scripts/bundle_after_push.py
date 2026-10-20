#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-118: bounded, post-push only, locally constructed ref-whitelist bundle."""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
TAIPEI = timezone(timedelta(hours=8))

OID = re.compile(r'^[0-9a-f]{40}$')
BRANCH = re.compile(r'^batch/[a-z0-9][a-z0-9._-]*$')
TRACKING = re.compile(r'^refs/remotes/origin/[A-Za-z0-9][A-Za-z0-9._/-]*$')

class BundleFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def git(root, *args, timeout=120):
    env = dict(os.environ)
    for name in list(env):
        if name.upper().startswith('GIT_'):
            del env[name]
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never'})
    try:
        r = subprocess.run(['git', *args], cwd=root, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise BundleFailure('GIT_UNAVAILABLE') from None
    if r.returncode != 0 or (not r.stdout and args[0] in ('for-each-ref',)):
        raise BundleFailure('GIT_NONZERO')
    return r.stdout.decode('utf-8', 'strict').strip()


def safe_directory(path):
    """No reparse/symlink ancestor, no redirected Downloads, no new directories."""
    if not path.is_dir() or os.path.realpath(path) != os.path.abspath(path):
        raise BundleFailure('DOWNLOADS_UNSAFE')
    for ancestor in (path, *path.parents):
        st = ancestor.lstat()
        if stat.S_ISLNK(st.st_mode) or (getattr(st, 'st_file_attributes', 0) & 0x400):
            raise BundleFailure('DOWNLOADS_UNSAFE')



def tracking_name_allowed(ref):
    """Safe ASCII subset of Git branch names; uppercase is valid, ref traversal is not.

    Keep production candidate BRANCH stricter; this predicate is for arbitrary
    existing remote-tracking branches, including historical Jules branches.
    """
    if not TRACKING.fullmatch(ref):
        return False
    suffix = ref[len('refs/remotes/origin/'):]
    if '..' in suffix or '@{' in suffix or suffix.endswith('.'):
        return False
    return all(part and part[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' and part not in ('.', '..') and not part.startswith('.')
               and not part.endswith('.') and not part.lower().endswith('.lock')
               for part in suffix.split('/'))


def preflight_remote_refs(root):
    """Read-only local/remote branch-name screening before any tracked edits.

    No fetch, update-ref, checkout, push or filesystem writes. A later bundle
    pass still checks the actual post-push ref set, closing time-of-check drift.
    """
    local = git(root, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/remotes/origin')
    for line in local.splitlines():
        if line.startswith('refs/remotes/origin/HEAD '):
            continue  # symbolic convenience pointer, never exported
        parts = line.split()
        if len(parts) != 2 or not tracking_name_allowed(parts[0]) or not OID.fullmatch(parts[1]):
            raise BundleFailure('REF_NOT_WHITELISTED')
    remote = git(root, 'ls-remote', '--refs', 'origin', 'refs/heads/*', timeout=120)
    if not remote:
        raise BundleFailure('REMOTE_REFS_EMPTY')
    for line in remote.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith('refs/heads/') or not OID.fullmatch(parts[0]):
            raise BundleFailure('REMOTE_REFS_INVALID')
        tracking = 'refs/remotes/origin/' + parts[1][len('refs/heads/'):]
        if not tracking_name_allowed(tracking):
            raise BundleFailure('REF_NOT_WHITELISTED')
    return True


def allowed_refs(root, branch, base, head):
    text = git(root, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/remotes/origin')
    found = {}
    for line in text.splitlines():
        # Git's origin/HEAD is a symbolic convenience pointer, never a bundle ref.
        if line.startswith('refs/remotes/origin/HEAD '):
            continue
        parts = line.split()
        if len(parts) != 2 or not tracking_name_allowed(parts[0]) or not OID.fullmatch(parts[1]):
            raise BundleFailure('REF_NOT_WHITELISTED')
        if parts[0] in found:
            raise BundleFailure('REF_DUPLICATE')
        found[parts[0]] = parts[1]
    if found.get('refs/remotes/origin/main') != base:
        raise BundleFailure('TRACKING_MAIN_DRIFT')
    candidate = 'refs/remotes/origin/' + branch
    existing = found.get(candidate)
    if existing is not None and existing != head:
        raise BundleFailure('TRACKING_CANDIDATE_DRIFT')
    if existing is None:
        # Create precisely the proven remote-tracking ref, no network or foreign refs.
        git(root, 'update-ref', candidate, head, '0'*40)
        found[candidate] = head
    return dict(sorted(found.items()))


def file_sha256(path):
    """Full-byte comparison in bounded memory; never log bundle bytes."""
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.digest()


def _regular_task_artifact(path):
    """Reject links, reparse points and multiply-linked files before touching a task artifact."""
    try:
        st = path.lstat()
    except OSError:
        raise BundleFailure('RECEIPT_IO_FAILED') from None
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or getattr(st, 'st_file_attributes', 0) & 0x400):
        raise BundleFailure('RECEIPT_UNSAFE')
    return st


def _receipt_bytes(path):
    """A separate read-back, not the in-memory data used to write the receipt."""
    _regular_task_artifact(path)
    try:
        return path.read_bytes()
    except OSError:
        raise BundleFailure('RECEIPT_IO_FAILED') from None


class _WindowsProtectedTemp:
    """A single Windows file object is verified and dispositioned under one handle.

    Share READ only: a concurrent writer, rename, replacement or unlink needs
    WRITE/DELETE sharing and is rejected for the lifetime of this handle.
    This is deliberately unavailable on POSIX: a path unlink there cannot be
    made identity-bound by repeating lstat/hash or by advisory flock.
    """

    def __init__(self, path):
        if os.name != 'nt':
            raise BundleFailure('TEMP_CLEANUP_PLATFORM_UNSUPPORTED')
        import ctypes
        from ctypes import wintypes
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.c = ctypes
        self.w = wintypes
        self.handle = None
        # Explicit prototypes are essential on 64-bit Windows: HANDLE must not
        # be truncated to ctypes' default int return value.
        self.k.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        self.k.CreateFileW.restype = wintypes.HANDLE
        self.k.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.k.CloseHandle.restype = wintypes.BOOL
        self.k.GetFileType.argtypes = (wintypes.HANDLE,)
        self.k.GetFileType.restype = wintypes.DWORD
        self.k.SetFilePointerEx.argtypes = (wintypes.HANDLE, ctypes.c_longlong,
                                             ctypes.c_void_p, wintypes.DWORD)
        self.k.SetFilePointerEx.restype = wintypes.BOOL
        self.k.ReadFile.argtypes = (wintypes.HANDLE, ctypes.c_void_p,
                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
        self.k.ReadFile.restype = wintypes.BOOL
        self.k.SetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                       ctypes.c_void_p, wintypes.DWORD)
        self.k.SetFileInformationByHandle.restype = wintypes.BOOL
        class ByHandleFileInfo(ctypes.Structure):
            _fields_ = [('dwFileAttributes', wintypes.DWORD),
                        ('ftCreationTime', wintypes.FILETIME),
                        ('ftLastAccessTime', wintypes.FILETIME),
                        ('ftLastWriteTime', wintypes.FILETIME),
                        ('dwVolumeSerialNumber', wintypes.DWORD),
                        ('nFileSizeHigh', wintypes.DWORD),
                        ('nFileSizeLow', wintypes.DWORD),
                        ('nNumberOfLinks', wintypes.DWORD),
                        ('nFileIndexHigh', wintypes.DWORD),
                        ('nFileIndexLow', wintypes.DWORD)]
        self.ByHandleFileInfo = ByHandleFileInfo
        self.k.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.POINTER(ByHandleFileInfo))
        self.k.GetFileInformationByHandle.restype = wintypes.BOOL
        h = self.k.CreateFileW(str(path), 0x80000000 | 0x00010000,
                               0x00000001, None, 3, 0x00200000, None)
        if h in (None, ctypes.c_void_p(-1).value):
            raise BundleFailure('TEMP_LOCK_FAILED')
        self.handle = h
        try:
            info = ByHandleFileInfo()
            if not self.k.GetFileInformationByHandle(h, ctypes.byref(info)):
                raise BundleFailure('TEMP_IDENTITY_FAILED')
            if (self.k.GetFileType(h) != 1 or info.nNumberOfLinks != 1
                    or info.dwFileAttributes & (0x10 | 0x400)):
                raise BundleFailure('TEMP_UNSAFE')
            self.size = (info.nFileSizeHigh << 32) | info.nFileSizeLow
            if self.size <= 0:
                raise BundleFailure('TEMP_UNSAFE')
        except BaseException:
            self.close()
            raise

    def sha256(self):
        if not self.k.SetFilePointerEx(self.handle, 0, None, 0):
            raise BundleFailure('TEMP_READ_FAILED')
        digest = hashlib.sha256()
        buf = self.c.create_string_buffer(1024 * 1024)
        done = self.w.DWORD(0)
        total = 0
        while True:
            if not self.k.ReadFile(self.handle, buf, len(buf), self.c.byref(done), None):
                raise BundleFailure('TEMP_READ_FAILED')
            if done.value == 0:
                break
            digest.update(buf.raw[:done.value])
            total += done.value
        if total != self.size:
            raise BundleFailure('TEMP_SOURCE_DRIFT')
        return digest.hexdigest()

    def delete(self):
        # FileDispositionInfo applies to this open file *object*, never a
        # second path lookup. Failure retains the temp and forbids READY.
        disposition = self.w.BOOL(1)
        if not self.k.SetFileInformationByHandle(self.handle, 4,
                                                   self.c.byref(disposition),
                                                   self.c.sizeof(disposition)):
            raise BundleFailure('TEMP_CLEANUP_FAILED')

    def close(self):
        if self.handle is not None:
            h, self.handle = self.handle, None
            if not self.k.CloseHandle(h):
                raise BundleFailure('TEMP_CLOSE_FAILED')

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _tb):
        self.close()


def _open_protected_temp(path):
    return _WindowsProtectedTemp(path)


def verified_receipt_and_cleanup(root, task_id, temp, target, branch, base, head, refs):
    """Only remove the task's own temp after durable exact-byte receipt read-back.

    No other stale temp, prior batch, historical S1 or Downloads file is eligible.
    Failure at any step leaves the temp in place for a separate maintenance decision;
    in particular, failure NEVER uses a best-effort fallback deletion.
    """
    receipt = Path(root) / '.git' / (task_id + '-bundle-receipt.json')
    if os.path.lexists(receipt):
        raise BundleFailure('RECEIPT_EXISTS')
    # The copy and Git ref contents were validated by the caller. Bind the
    # receipt to the two exact files and the complete exported ref snapshot.
    _regular_task_artifact(temp)
    _regular_task_artifact(target)
    # Acquire the protecting handle BEFORE receipt creation and retain it
    # without interruption through both verifications and disposition.
    # There is no path-based delete fallback on any platform.
    try:
        with _open_protected_temp(temp) as protected:
            try:
                tmp_size = protected.size
                out_size = target.stat().st_size
                tmp_sha = protected.sha256()
                out_sha = file_sha256(target).hex()
            except OSError:
                raise BundleFailure('RECEIPT_IO_FAILED') from None
            if tmp_size <= 0 or tmp_size != out_size or tmp_sha != out_sha:
                raise BundleFailure('RECEIPT_SOURCE_DRIFT')
            record = {
                'schema_version': 1,
                'task_id': task_id, 'base_oid': base, 'candidate_oid': head,
                'branch': branch, 'bundle_name': target.name,
                'bundle_sha256': out_sha, 'bundle_size': out_size,
                'temp_name': temp.name, 'refs': dict(sorted(refs.items())),
                'temporary_cleanup_policy': 'READBACK_EXACT_SAME_TASK_ONLY',
            }
            data = (json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
            try:
                with receipt.open('xb') as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
            except FileExistsError:
                raise BundleFailure('RECEIPT_EXISTS') from None
            except OSError:
                raise BundleFailure('RECEIPT_IO_FAILED') from None
            if _receipt_bytes(receipt) != data:
                raise BundleFailure('RECEIPT_READBACK_MISMATCH')
            _regular_task_artifact(target)
            try:
                if (target.stat().st_size != out_size or protected.sha256() != tmp_sha
                        or file_sha256(target).hex() != out_sha):
                    raise BundleFailure('RECEIPT_SOURCE_DRIFT')
            except OSError:
                raise BundleFailure('RECEIPT_IO_FAILED') from None
            protected.delete()
    except OSError:
        raise BundleFailure('TEMP_CLEANUP_FAILED') from None
    return receipt


def create_bundle(root, branch, base, head, downloads=None, now=None, task_id=None):
    if not BRANCH.fullmatch(branch) or not OID.fullmatch(base) or not OID.fullmatch(head) or base == head:
        raise BundleFailure('ARGUMENT_INVALID')
    root = str(Path(root).resolve(strict=True))
    downloads = Path(downloads) if downloads is not None else Path.home() / 'Downloads'
    safe_directory(downloads)
    timestamp = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    # User-visible filename binds both the verified origin/main and candidate.
    name = ('HH.AI_v2-' + timestamp.strftime('%Y%m%d-%H%M%S') + '-'
            + base[:7] + '-' + head[:7] + '.bundle')
    if not name.isascii():
        raise BundleFailure('NAME_INVALID')
    target = downloads / name
    if os.path.lexists(target):
        raise BundleFailure('BUNDLE_EXISTS')
    refs = allowed_refs(root, branch, base, head)
    if not task_id or not re.fullmatch(r'[A-Za-z0-9_-]+', task_id):
        raise BundleFailure('TASK_ID_INVALID')
    temp = Path(root) / '.git' / (task_id + '-bundle.tmp')
    receipt = Path(root) / '.git' / (task_id + '-bundle-receipt.json')
    if os.path.lexists(receipt):
        raise BundleFailure('RECEIPT_EXISTS')
    if os.path.lexists(temp):
        raise BundleFailure('TEMP_EXISTS')
    # The only permitted deletion is this task's newly produced temp AFTER a
    # durable receipt is written/read back; all failure paths preserve temp.
    try:
        git(root, 'bundle', 'create', str(temp), *refs, timeout=300)
        verify = git(root, 'bundle', 'verify', str(temp), timeout=300)
        if not verify and not temp.is_file():
            raise BundleFailure('VERIFY_EMPTY')
        heads = git(root, 'bundle', 'list-heads', str(temp), timeout=300)
        observed = {}
        for line in heads.splitlines():
            parts = line.split()
            if len(parts) != 2 or not OID.fullmatch(parts[0]) or parts[1] in observed:
                raise BundleFailure('LIST_HEADS_INVALID')
            observed[parts[1]] = parts[0]
        if observed != refs:
            raise BundleFailure('BUNDLE_REFS_MISMATCH')
        with temp.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            # Persist the sole accepted output before any receipt or unlink.
            # A read-back from the OS page cache alone cannot prove durability.
            dst.flush()
            os.fsync(dst.fileno())
        if not target.is_file() or target.stat().st_size != temp.stat().st_size:
            raise BundleFailure('COPY_MISMATCH')
        # An equal-length corrupted pack can pass list-heads and bundle verify.
        # Verify the entire copy before allowing the caller to report READY.
        if file_sha256(temp) != file_sha256(target):
            raise BundleFailure('COPY_HASH_MISMATCH')
        # Verify actual new file rather than trusting temporary artifact.
        real_heads = git(root, 'bundle', 'list-heads', str(target), timeout=300)
        if real_heads != heads:
            raise BundleFailure('COPY_VERIFY_FAILED')
        verified_receipt_and_cleanup(root, task_id, temp, target, branch, base, head, refs)
        return str(target)
    except FileExistsError:
        raise BundleFailure('BUNDLE_EXISTS') from None
    except (OSError, UnicodeError, ValueError):
        raise BundleFailure('BUNDLE_IO_FAILED') from None
