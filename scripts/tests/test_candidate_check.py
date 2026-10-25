"""
scripts/candidate_check.py（審查官端候選 commit 機械核對；B-115 C2 變更帳）的測試。

合成 repo 與提示詞沿用 test_prompt_builder 的 fixture：以 prompt_builder.build 產生真實提示詞，以作者檔建立
候選 commit，再設定 origin/main 與候選分支的 remote ref。GENERATED 在合成 repo 以注入函式代替（合成 repo
沒有判定器）；預設的 run_generated 另以本 repo 的真實 commit 驗證。
合成 commit 一律以 plumbing 建立（_make_commit），不 checkout、不 git add、不 git commit，所以結果不受使用者的
core.autocrlf、core.symlinks 或 hook 影響；windows_git_config 以 Git for Windows 預設重跑關鍵案例。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)

import batch_runner as br  # noqa: E402
import candidate_check as cc  # noqa: E402
import prompt_builder as pb  # noqa: E402
from test_prompt_builder import TASK, _definition, repo  # noqa: E402,F401  (repo 為 fixture)

BRANCH = "batch/unit-build-261009"


def _run(root, *args, env=None, data=None):
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, env=env, input=data)
    assert proc.returncode == 0, (args, proc.stderr)
    return proc.stdout.decode().strip()


def _cat(root, rev, path):
    proc = subprocess.run(["git", "cat-file", "blob", rev + ":" + path], cwd=root, capture_output=True)
    assert proc.returncode == 0, (rev, path, proc.stderr)
    return proc.stdout


def _make_commit(root, parent, files, modes=None):
    """以 parent 的 tree 加上 files（{路徑: 位元組}）建立 commit，只用 plumbing，不碰工作樹、index 或 hook。

    `hash-object --stdin`（不帶 --path）不套用任何輸入 filter，所以 blob 恰為給定位元組；core.autocrlf、
    core.symlinks、.gitattributes 與使用者的 hook 都不影響合成 commit（B116 R2 Windows S1 根因）。
    """
    index = Path(root).parent / ("synthetic-index-" + os.urandom(6).hex())
    env = dict(os.environ, GIT_INDEX_FILE=str(index), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    try:
        _run(root, "read-tree", parent, env=env)
        for path, content in sorted(files.items()):
            blob = _run(root, "hash-object", "-w", "--stdin", env=env, data=content)
            mode = (modes or {}).get(path, "100644")
            _run(root, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", env=env)
        tree = _run(root, "write-tree", env=env)
        return _run(root, "commit-tree", tree, "-p", parent, "-m", "synthetic", env=env)
    finally:
        if index.exists():
            index.unlink()


def _no_generated(repo_root, candidate):
    return None


class Batch:
    """合成的一批：Base、提示詞與照提示詞建立的候選 commit（plumbing 建立，工作樹始終不動）。"""

    def __init__(self, tmp_path, root, base, **over):
        self.root, self.base = root, base
        text, _, self.authored = pb.build(root, _definition(tmp_path, base, **over))
        self.prompt = tmp_path / (TASK + "-prompt.txt")
        self.prompt.write_bytes(text.encode("utf-8"))
        self.spec = br.load_spec(br.prompt_lines(text.encode("utf-8")), TASK)

    def files(self, generated=True):
        files = {path: content.encode("utf-8") for path, content in self.authored.items()}
        if generated:
            files.update({path: b'{"generated": true}\n' for path in br.GENERATED})
        return files

    def commit(self, edit=None, generated=True, parent=None, modes=None):
        files = self.files(generated)
        if edit:
            edit(files)
        head = _make_commit(self.root, parent or self.base, files, modes)
        _run(self.root, "update-ref", "refs/remotes/origin/main", self.base)
        _run(self.root, "update-ref", "refs/remotes/origin/" + BRANCH, head)
        return head

    def check(self, candidate, generated=_no_generated):
        return cc.check_candidate(self.root, str(self.prompt), candidate, generated)


def _code(fn, *args):
    with pytest.raises(cc.CheckError) as exc:
        fn(*args)
    return str(exc.value)


@pytest.fixture
def batch(tmp_path, repo):
    root, base = repo
    return Batch(tmp_path, root, base)


def test_candidate_built_from_the_prompt_passes(batch):
    head = batch.commit()
    task, paths, ops, authors = batch.check(head)
    assert (task, paths, authors) == (TASK, len(br.allowed_paths(batch.spec)), len(batch.spec["authors"]))
    assert ops == len(batch.spec["ops"]) and ops > 0


def _append(path, text):
    def edit(files):
        files[path] += text.encode("utf-8")
    return edit


def _replace(path, old, new):
    def edit(files):
        data = files[path].decode("utf-8")
        assert data.count(old) == 1
        files[path] = data.replace(old, new).encode("utf-8")
    return edit


def _add(path, content):
    def edit(files):
        files[path] = content
    return edit


@pytest.mark.parametrize("edit,code", [
    # 授權帳不變、實際多改一處（ledger 檔與程式檔）
    (_append("docs/BOARD.md", "| X-9 | smuggled |\n"), "LEDGER_MISMATCH"),
    (_replace("docs/BOARD.md", "| X-1 | row |", "| X-1 | ROW |"), "LEDGER_MISMATCH"),
    (_replace("scripts/tool.py", "return 10", "return 11"), "LEDGER_MISMATCH"),
    (_replace("scripts/new_tool.py", "new", "NEW"), "LEDGER_MISMATCH"),
    # 授權帳列了、實際沒改（把宣告的修改還原成 Base）
    (_replace("docs/BOARD.md", "# Board (v2)\n", "# Board\n"), "LEDGER_MISMATCH"),
    # CR 也算不同
    (_replace("docs/BOARD.md", "| X-1 | row |\n", "| X-1 | row |\r\n"), "LEDGER_MISMATCH"),
    # 範圍外的檔案
    (_add("docs/OTHER.md", b"x\n"), "SCOPE_MISMATCH"),
])
def test_any_change_outside_the_ledger_fails(batch, edit, code):
    assert _code(batch.check, batch.commit(edit)) == code


@pytest.fixture
def windows_git_config(tmp_path_factory, monkeypatch):
    """以 Git for Windows 預設（core.autocrlf=true、core.symlinks=false）作為唯一的使用者 Git 設定。"""
    cfg = tmp_path_factory.mktemp("windows-git") / "gitconfig"
    cfg.write_bytes(b"[core]\n\tautocrlf = true\n\tsymlinks = false\n[user]\n\tname = t\n\temail = t@t\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return cfg


def test_synthetic_commit_keeps_exact_bytes_under_windows_git_defaults(windows_git_config, repo):
    root, base = repo
    data = b"a\r\nb\nc\r\n"
    head = _make_commit(root, base, {"docs/CRLF.md": data})
    assert _cat(root, head, "docs/CRLF.md") == data


@pytest.mark.parametrize("edit,modes,code", [
    (None, None, None),
    (_replace("docs/BOARD.md", "| X-1 | row |\n", "| X-1 | row |\r\n"), None, "LEDGER_MISMATCH"),
    (None, {"scripts/new_tool.py": "120000"}, "MODE_MISMATCH"),
])
def test_results_do_not_depend_on_windows_git_defaults(windows_git_config, tmp_path, repo, edit, modes, code):
    """B116 R2 Windows S1：原測試以工作樹與 git add 建候選，core.autocrlf=true 把 CRLF 正規化成 LF，案例未真正改變。"""
    root, base = repo
    batch = Batch(tmp_path, root, base)
    head = batch.commit(edit, modes=modes)
    if code is None:
        assert batch.check(head)[0] == TASK
    else:
        assert _code(batch.check, head) == code


def test_mode_changes_and_non_regular_files_fail(batch):
    executable = batch.commit(modes={"scripts/tool.py": "100755"})
    assert _code(batch.check, executable) == "MODE_MISMATCH"
    # 新檔以 symlink 形式出現（blob 內容剛好等於作者檔也一樣）
    link = batch.commit(modes={"scripts/new_tool.py": "120000"})
    assert _code(batch.check, link) == "MODE_MISMATCH"


@pytest.mark.parametrize("mode,ok", [("100755", True), ("120000", False)])
def test_mode_must_be_a_regular_file_even_when_base_has_the_same_mode(tmp_path, repo, mode, ok):
    """第二意見 R1B N01：Base 與候選同為 symlink（120000）也要 FAIL；既有可執行一般檔案（100755）照常 PASS。"""
    root, base = repo
    path = "scripts/tool.py"
    base = _make_commit(root, base, {path: _cat(root, base, path)}, {path: mode})
    _run(root, "update-ref", "HEAD", base)      # prompt_builder.build 要求 HEAD 等於 Base；不 checkout
    _run(root, "read-tree", base)               # 不帶 -u：只同步 index，工作樹不動
    batch = Batch(tmp_path, root, base)
    head = batch.commit(modes={path: mode})
    assert cc._mode(root, base, path) == cc._mode(root, head, path) == mode
    if ok:
        assert batch.check(head)[0] == TASK
    else:
        assert _code(batch.check, head) == "MODE_MISMATCH"


def _source_state(root):
    """index 內容（不比 stat 快取）、HEAD、全部 ref 與工作樹狀態；查詢本身不寫 index。"""
    git_dir = Path(root) / ".git"
    return (_run(root, "--no-optional-locks", "ls-files", "--stage"), (git_dir / "HEAD").read_bytes(),
            _run(root, "for-each-ref"),
            _run(root, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all"))


ROUTING = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")


@pytest.mark.parametrize("variable", ROUTING)
def test_inherited_git_routing_never_touches_the_source_repo(batch, monkeypatch, variable):
    """第二意見 R1B B01：繼承的 GIT_* 不得把暫存 clone 的 checkout 或任何讀取導回 --repo，成功與失敗都一樣。"""
    head = batch.commit()
    before = _source_state(batch.root)
    target = {"GIT_INDEX_FILE": str(Path(batch.root) / ".git" / "index"),
              "GIT_DIR": str(Path(batch.root) / ".git"), "GIT_WORK_TREE": batch.root}[variable]
    monkeypatch.setenv(variable, target)
    monkeypatch.setenv("AS_IF_COMMITTED", "1")
    seen = []

    def fake_verifiers(repo_root, candidate):
        seen.append(sorted(k for k in os.environ if k.startswith("GIT_") or k == "AS_IF_COMMITTED"))
        cc._run_generated(repo_root, candidate)     # 真的 clone 與 checkout；判定器在合成 repo 不存在而 FAIL

    assert _code(batch.check, head, fake_verifiers) == "GENERATED_EXECUTION_RECORD_FAILED"
    assert seen == [[]]
    assert os.environ[variable] == target and os.environ["AS_IF_COMMITTED"] == "1"   # 呼叫後還原
    monkeypatch.delenv(variable)
    assert _source_state(batch.root) == before


@pytest.mark.parametrize("variable", ROUTING)
def test_default_generated_ignores_inherited_git_routing(monkeypatch, variable):
    before = _source_state(REPO_ROOT)
    monkeypatch.setenv(variable, {"GIT_INDEX_FILE": os.path.join(REPO_ROOT, ".git", "index"),
                                  "GIT_DIR": os.path.join(REPO_ROOT, ".git"), "GIT_WORK_TREE": REPO_ROOT}[variable])
    cc.run_generated(REPO_ROOT, REAL_CANDIDATE)
    monkeypatch.delenv(variable)
    assert _source_state(REPO_ROOT) == before


def test_declared_path_left_unchanged_fails_on_scope(batch):
    revert_tool = _add("scripts/tool.py", _cat(batch.root, batch.base, "scripts/tool.py"))
    assert _code(batch.check, batch.commit(revert_tool)) == "SCOPE_MISMATCH"


def test_missing_generated_files_fail_on_scope(batch):
    assert _code(batch.check, batch.commit(generated=False)) == "SCOPE_MISMATCH"


def test_refs_and_parent_are_bound(batch):
    head = batch.commit()
    _run(batch.root, "update-ref", "refs/remotes/origin/main", head)
    assert _code(batch.check, head) == "ORIGIN_MAIN_NOT_BASE"
    _run(batch.root, "update-ref", "refs/remotes/origin/main", batch.base)
    _run(batch.root, "update-ref", "refs/remotes/origin/" + BRANCH, batch.base)
    assert _code(batch.check, head) == "BRANCH_REF_NOT_CANDIDATE"
    _run(batch.root, "update-ref", "-d", "refs/remotes/origin/" + BRANCH)
    assert _code(batch.check, head) == "BRANCH_REF_UNAVAILABLE"
    _run(batch.root, "update-ref", "-d", "refs/remotes/origin/main")
    assert _code(batch.check, head) == "ORIGIN_MAIN_UNAVAILABLE"


def test_candidate_must_be_a_single_child_of_base(batch):
    middle = _make_commit(batch.root, batch.base, {"docs/OTHER.md": b"between\n"})
    head = batch.commit(parent=middle)
    assert _code(batch.check, head) == "PARENT_NOT_BASE"


@pytest.mark.parametrize("value,code", [
    ("8bfbe95", "CANDIDATE_SHA_INVALID"),
    ("8BFBE9526D09E69CF2ECC5C390875E3ABD36F5DA", "CANDIDATE_SHA_INVALID"),
    ("f" * 40, "CANDIDATE_UNAVAILABLE"),
])
def test_candidate_sha_is_validated(batch, value, code):
    batch.commit()
    assert _code(batch.check, value) == code


def test_generated_failure_fails(batch):
    head = batch.commit()

    def failing(repo_root, candidate):
        raise cc.CheckError("GENERATED_CONSISTENCY_FAILED")
    assert _code(batch.check, head, failing) == "GENERATED_CONSISTENCY_FAILED"


def test_generated_receives_repo_and_candidate(batch):
    head = batch.commit()
    seen = []
    batch.check(head, lambda r, c: seen.append((r, c)))
    assert seen == [(batch.root, head)]


def test_promotion_prompt_is_not_supported(batch, monkeypatch):
    head = batch.commit()
    spec = dict(batch.spec, kind="promotion")
    monkeypatch.setattr(br, "load_spec", lambda lines, task: spec)
    assert _code(batch.check, head) == "KIND_NOT_SUPPORTED"


def test_unsupported_author_source_kind_fails(batch, monkeypatch):
    head = batch.commit()
    spec = dict(batch.spec)
    spec["authors"] = {p: dict(e, source={"kind": "worktree"}) for p, e in batch.spec["authors"].items()}
    monkeypatch.setattr(br, "load_spec", lambda lines, task: spec)
    assert _code(batch.check, head) == "SOURCE_KIND_UNSUPPORTED"


def test_ledger_with_a_non_unique_anchor_fails(batch, monkeypatch):
    head = batch.commit()
    spec = dict(batch.spec)
    spec["ops"] = batch.spec["ops"] + [{"path": "docs/BOARD.md", "old": "| row |", "new": "| ROW |"}]
    monkeypatch.setattr(br, "load_spec", lambda lines, task: spec)
    assert _code(batch.check, head) == "LEDGER_ANCHOR_NOT_UNIQUE"


def test_ledger_whose_result_differs_from_author_hash_fails(batch, monkeypatch):
    head = batch.commit()
    spec = dict(batch.spec)
    spec["ops"] = [op for op in batch.spec["ops"] if op["path"] != "docs/BOARD.md"]
    monkeypatch.setattr(br, "load_spec", lambda lines, task: spec)
    assert _code(batch.check, head) == "LEDGER_PREWRITE_HASH_MISMATCH"


def test_tampered_prompt_spec_fails(batch):
    head = batch.commit()
    data = batch.prompt.read_bytes().replace(b'"kind": "production"', b'"kind": "bogus"', 1)
    batch.prompt.write_bytes(data)
    assert _code(batch.check, head) == "PROMPT_SPEC_INVALID"


def test_cli_fixed_lines_and_exit_codes(batch, monkeypatch, capsys):
    head = batch.commit()
    monkeypatch.setattr(cc, "run_generated", _no_generated)
    monkeypatch.setattr(cc.check_candidate, "__defaults__", (_no_generated,))
    assert cc.main(["--repo", batch.root, "--prompt", str(batch.prompt), "--candidate", head]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"CANDIDATE_CHECK TASK={TASK} CANDIDATE={head}"
    assert out[1:] == ["CANDIDATE_CHECK REFS=PASS PARENT=PASS",
                       f"CANDIDATE_CHECK SCOPE=PASS PATHS={len(br.allowed_paths(batch.spec))}",
                       f"CANDIDATE_CHECK LEDGER=PASS OPS={len(batch.spec['ops'])} AUTHORS={len(batch.spec['authors'])}",
                       "CANDIDATE_CHECK GENERATED=PASS", "CANDIDATE_CHECK RESULT=PASS"]
    assert cc.main(["--repo", batch.root, "--prompt", str(batch.prompt), "--candidate", batch.base]) == 1
    assert capsys.readouterr().out.splitlines() == ["CANDIDATE_CHECK FAIL BRANCH_REF_NOT_CANDIDATE"]
    bad = Path(batch.prompt).with_name("bogus.txt")
    bad.write_bytes(b"x")
    assert cc.main(["--repo", batch.root, "--prompt", str(bad), "--candidate", head]) == 1
    assert capsys.readouterr().out.splitlines() == ["CANDIDATE_CHECK FAIL PROMPT_NAME_INVALID"]


# ---------------------------------------------------------------------------
# 預設 GENERATED：以本 repo 的真實 commit 執行候選自己的判定器
# ---------------------------------------------------------------------------

REAL_CANDIDATE = "8bfbe9526d09e69cf2ecc5c390875e3abd36f5da"   # G2 第一批，POST-MAIN VERIFIED


def test_default_generated_runs_the_candidates_own_verifiers():
    cc.run_generated(REPO_ROOT, REAL_CANDIDATE)


def test_default_generated_fails_when_a_verifier_fails(monkeypatch):
    monkeypatch.setattr(cc, "GENERATED_COMMANDS",
                        cc.GENERATED_COMMANDS[:1] + (("FINGERPRINT", ["-c", "import sys; sys.exit(3)"]),))
    with pytest.raises(cc.CheckError) as exc:
        cc.run_generated(REPO_ROOT, REAL_CANDIDATE)
    assert str(exc.value) == "GENERATED_FINGERPRINT_FAILED"


def test_default_generated_fails_for_an_unknown_candidate():
    with pytest.raises(cc.CheckError) as exc:
        cc.run_generated(REPO_ROOT, "f" * 40)
    assert str(exc.value) == "GENERATED_CHECKOUT_FAILED"
