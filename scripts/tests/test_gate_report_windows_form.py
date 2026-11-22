# -*- coding: utf-8 -*-
"""S1C-024 (alpha 1 R2, native_preview): pytest short-summary rows in the Windows form.

pytest prints a row's file part relative to the invocation directory (config.cwd_relative_nodeid -> bestrelpath),
so on Windows it uses backslashes whenever the invocation directory is not the rootdir. The rows below are written
literally, so these tests run on any OS: the Linux emulation could not show the Windows separator, and the native
preview did. Proposed by the second opinion (non-authoritative); adopted by the auditor with a CRLF case, a
mixed-separator case and an end-to-end sidecar case added.

Commitment -> test (E27 (a), (b) "Windows output form"):
  W1 a row whose file part uses backslashes is listed with forward slashes and counted once   test_windows_relative_*, test_crlf_*
  W2 only the file part changes; a backslash inside a parameter id stays and the row is shown reduced   test_a_backslash_inside_*
  W3 a drive-letter path stays unsafe (counted in unsafe=, never NO_NAMES_FOUND)           test_a_drive_letter_*
  W4 the sidecar reader gives the same list for the Windows form as for the Linux form      test_the_sidecar_*
"""
import os
import sys

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import gate_report as gr  # noqa: E402

HEAD = '=' * 27 + ' short test summary info ' + '=' * 27
WIN = '..\\..\\..\\pytest-of-HH.AI_260806\\pytest-1640\\test_end_to_end_gate_runner_si0\\sample\\test_sample.py'
LIN = WIN.replace('\\', '/')


def section(*rows):
    return '\n'.join((HEAD,) + rows + ('3 failed, 1 passed in 0.10s',))


def three_rows(path):
    return section('FAILED ' + path + '::test_bad_one - assert 1 == 2',
                   'FAILED ' + path + '::test_bad_param[1] - assert 1 == 99',
                   'FAILED ' + path + '::test_bad_param[2] - assert 2 == 99')


def test_windows_relative_rows_are_listed_with_forward_slashes():
    items, unsafe, rows = gr.parse_failed_rows(three_rows(WIN))
    assert (items, unsafe, rows) == ([LIN + '::test_bad_one', LIN + '::test_bad_param[1]', LIN + '::test_bad_param[2]'], 0, 3)


def test_crlf_line_endings_with_windows_rows_give_the_same_list():
    text = three_rows(WIN).replace('\n', '\r\n')
    assert gr.parse_failed_rows(text) == gr.parse_failed_rows(three_rows(LIN))


def test_mixed_separators_in_the_file_part_are_all_turned_into_slashes():
    text = section('FAILED scripts\\tests/test_a.py::test_x - assert 0')
    assert gr.parse_failed_rows(text) == (['scripts/tests/test_a.py::test_x'], 0, 1)


def test_a_backslash_inside_a_parameter_id_is_not_rewritten_and_the_row_is_shown_reduced():
    text = section('FAILED scripts\\tests\\test_a.py::test_param[C:\\\\path\\\\x] - AssertionError')
    assert gr.parse_failed_rows(text) == (['scripts/tests/test_a.py::test_param[*]'], 0, 1)


def test_summary_name_changes_only_the_part_before_the_first_double_colon():
    assert gr.summary_name('a\\b.py::t[x\\y]') == 'a/b.py::t[x\\y]'
    assert gr.summary_name('a\\b.py') == 'a/b.py'
    assert gr.summary_name('a/b.py::t') == 'a/b.py::t'


def test_a_drive_letter_path_is_counted_as_unsafe_never_as_no_names_found(tmp_path):
    git = tmp_path / '.git'
    git.mkdir()
    (git / 'T-261122-local-gates.txt.precommit-run1-gate4.raw').write_text(
        section('FAILED D:\\other\\test_b.py::test_x - assert 0'), encoding='utf-8', newline='\n')
    lines = gr.failed_list_lines(str(tmp_path), 'T-261122', 'precommit', 'PRECOMMIT_NONZERO')
    assert lines == ['S1_FAILED_LIST kind=GATE_FAILED count=1 shown=0 unsafe=1']


def test_the_sidecar_reader_lists_the_windows_form_like_the_linux_form(tmp_path):
    git = tmp_path / '.git'
    git.mkdir()
    raw = git / 'T-261122-local-gates.txt.precommit-run1-gate1.raw'
    raw.write_text(three_rows(WIN), encoding='utf-8', newline='\n')
    windows = gr.failed_list_lines(str(tmp_path), 'T-261122', 'precommit', 'PRECOMMIT_NONZERO')
    raw.write_text(three_rows(LIN), encoding='utf-8', newline='\n')
    linux = gr.failed_list_lines(str(tmp_path), 'T-261122', 'precommit', 'PRECOMMIT_NONZERO')
    assert windows == linux and windows[0] == 'S1_FAILED_LIST kind=GATE_FAILED count=3 shown=3'
