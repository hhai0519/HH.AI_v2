#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tests/test_secret_detection_matrix.py

Verification tests for secret detection coverage matrix (SEC-01 INC-2).
Exercises real scripts/secret_scan.py and shared/dlpSanitizer.js against
docs/governance/secret-detection-matrix.json and docs/governance/secret-inventory.json.
"""

import json
import os
import random
import string
import subprocess
import pytest

from scripts.secret_scan import scan_content_lines, SIGNATURE_PATTERNS

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Deterministic random generator for synthetic samples
_RNG = random.Random(20261005)


def _gen_random_token(length: int, alphabet: str) -> str:
    """
    Generates a random token of exact length using alphabet.
    Guarantees no placeholder/exemption words appear in the token.
    """
    exemption_words = [
        "SYNTHETIC", "FAKE", "EXAMPLE", "PLACEHOLDER",
        "REDACTED", "DUMMY", "TEST", "CHANGEME"
    ]
    while True:
        candidate = "".join(_RNG.choices(alphabet, k=length))
        upper = candidate.upper()
        if not any(w in upper for w in exemption_words):
            return candidate


def sanitize_dlp(text: str) -> str:
    """
    Calls real shared/dlpSanitizer.js sanitizeDlp via Node.js subprocess.
    Text is passed through stdin to avoid file writes and command line quoting issues.
    """
    script = (
        "const { sanitizeDlp } = require('./shared/dlpSanitizer.js');\n"
        "const fs = require('fs');\n"
        "const input = fs.readFileSync(0, 'utf-8');\n"
        "process.stdout.write(sanitizeDlp(input));\n"
    )
    res = subprocess.run(
        ["node", "-e", script],
        input=text,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT
    )
    if res.returncode != 0:
        raise RuntimeError(f"Node execution failed (code {res.returncode}):\n{res.stderr}")
    return res.stdout


def _load_inventory():
    path = os.path.join(REPO_ROOT, "docs", "governance", "secret-inventory.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_matrix():
    path = os.path.join(REPO_ROOT, "docs", "governance", "secret-detection-matrix.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _create_synthetic_samples():
    """
    Builds synthetic test samples using dynamic string concatenation.
    No full key-shaped literals appear in test source code.
    """
    alphanumeric = string.ascii_letters + string.digits
    digits = string.digits

    # Telegram: 8-10 digit bot id + colon + 35 chars
    telegram_sample = _gen_random_token(9, digits) + ":" + _gen_random_token(35, alphanumeric)

    # GitHub ghp_ (prefix + 36 alphanumeric)
    ghp_prefix = "".join(["gh", "p_"])
    ghp_sample = ghp_prefix + _gen_random_token(36, alphanumeric)

    # GitHub github_pat_ (prefix + 82 chars of [A-Za-z0-9_])
    pat_prefix = "".join(["git", "hub", "_pat_"])
    pat_sample = pat_prefix + _gen_random_token(82, alphanumeric + "_")

    # Notion ntn_ (prefix + 30 alphanumeric)
    ntn_prefix = "".join(["nt", "n_"])
    ntn_sample = ntn_prefix + _gen_random_token(30, alphanumeric)

    # Notion secret_ (prefix + 40 alphanumeric)
    secret_prefix = "".join(["sec", "ret_"])
    secret_sample = secret_prefix + _gen_random_token(40, alphanumeric)

    # Google API Key samples (AIza + exactly 35 chars from [0-9A-Za-z_-])
    google_prefix = "".join(["AI", "za"])
    # 1. AIzaSy prefix
    google_sy = google_prefix + "".join(["S", "y"]) + _gen_random_token(33, alphanumeric)
    # 2. Non-Sy prefix (starts with K9)
    google_non_sy = google_prefix + "K9" + _gen_random_token(33, alphanumeric)
    # 3. Ending with hyphen
    google_hyphen_end = google_prefix + "K" + _gen_random_token(33, alphanumeric) + "-"
    # 4. Ending with underscore
    google_underscore_end = google_prefix + "K" + _gen_random_token(33, alphanumeric) + "_"
    # 5. Middle hyphen (K + 16 chars + '-' + 17 chars = 35 chars)
    google_mid_hyphen = google_prefix + "K" + _gen_random_token(16, alphanumeric) + "-" + _gen_random_token(17, alphanumeric)

    return {
        "TELEGRAM_BOT_TOKEN": [telegram_sample],
        "GITHUB_TOKEN": [ghp_sample, pat_sample],
        "NOTION_TOKEN": [ntn_sample, secret_sample],
        "GOOGLE_API_KEY": [
            google_sy,
            google_non_sy,
            google_hyphen_end,
            google_underscore_end,
            google_mid_hyphen
        ]
    }


# ==============================================================================
# M1 Closure Test
# ==============================================================================

def test_m1_matrix_closure():
    """
    M1 封閉性：secret-inventory.json 之 format_class 集合必須等於矩陣 format_classes 之鍵集合。
    """
    inventory = _load_inventory()
    matrix = _load_matrix()

    inventory_classes = {entry["format_class"] for entry in inventory["entries"]}
    matrix_classes = set(matrix["format_classes"].keys())

    assert inventory_classes == matrix_classes, (
        f"Inventory format_classes mismatch matrix keys:\n"
        f"In inventory only: {inventory_classes - matrix_classes}\n"
        f"In matrix only: {matrix_classes - inventory_classes}"
    )


# ==============================================================================
# M2 REQUIRED Classes Detection & Sanitization Test
# ==============================================================================

def test_m2_required_classes():
    """
    M2 REQUIRED 類別：
    - scanner_detector 必須存在於 SIGNATURE_PATTERNS 之 ID。
    - scan_content_lines 產生該 ID。
    - sanitizeDlp 輸出含該 dlp_label、不含樣本原文。
    - 至少以三種包覆方式測試：前後為空白、前後為雙引號、前接冒號後接分號。
    - 涵蓋 Telegram 1 種、GitHub 2 種、Notion 2 種、Google 5 種邊界樣本。
    """
    matrix = _load_matrix()
    known_detector_ids = {det_id for det_id, _ in SIGNATURE_PATTERNS}
    samples_by_class = _create_synthetic_samples()

    # Three required wrapping formats
    wrappers = [
        lambda s: f" {s} ",
        lambda s: f'"{s}"',
        lambda s: f":{s};"
    ]

    for format_class, samples in samples_by_class.items():
        class_info = matrix["format_classes"][format_class]
        assert class_info["coverage"] == "REQUIRED", f"{format_class} must be REQUIRED"

        scanner_detector = class_info["scanner_detector"]
        dlp_label = class_info["dlp_label"]

        # Assert detector exists in scanner SIGNATURE_PATTERNS
        assert scanner_detector in known_detector_ids, (
            f"Detector {scanner_detector} for {format_class} not found in SIGNATURE_PATTERNS"
        )

        for sample in samples:
            for wrap in wrappers:
                wrapped_text = wrap(sample)

                # 1. Scanner verification
                findings = list(scan_content_lines(wrapped_text.encode("utf-8"), "test.txt"))
                detected_ids = [fid for fid, _ in findings]
                assert scanner_detector in detected_ids, (
                    f"Scanner failed to detect {scanner_detector} in wrapped text: {wrapped_text!r}"
                )

                # 2. DLP verification
                sanitized = sanitize_dlp(wrapped_text)
                assert dlp_label in sanitized, (
                    f"DLP failed to output label {dlp_label} for {format_class}. Got: {sanitized!r}"
                )
                assert sample not in sanitized, (
                    f"DLP leaked raw sample for {format_class} in sanitized output: {sanitized!r}"
                )


# ==============================================================================
# M3 Derived Class Test
# ==============================================================================

def test_m3_derived_class():
    """
    M3 衍生類別：把 Notion 合成樣本放入一段 JSON 標頭字串（例如 Authorization: Bearer <樣本>），
    scanner 與 DLP 皆須偵測（NOTION_CREDENTIAL 與 [DLP_NOTION_TOKEN]）。
    """
    samples = _create_synthetic_samples()["NOTION_TOKEN"]

    for sample in samples:
        header_json = json.dumps({"Authorization": f"Bearer {sample}"})

        # Scanner check
        findings = list(scan_content_lines(header_json.encode("utf-8"), "headers.json"))
        detected_ids = [fid for fid, _ in findings]
        assert "NOTION_CREDENTIAL" in detected_ids, (
            f"Scanner did not detect NOTION_CREDENTIAL in header JSON: {header_json!r}"
        )

        # DLP check
        sanitized = sanitize_dlp(header_json)
        assert "[DLP_NOTION_TOKEN]" in sanitized, (
            f"DLP did not output [DLP_NOTION_TOKEN] in header JSON: {sanitized!r}"
        )
        assert sample not in sanitized, (
            f"DLP leaked raw Notion token in sanitized header JSON: {sanitized!r}"
        )


# ==============================================================================
# M4 False Positive Counterexamples Test
# ==============================================================================

def test_m4_false_positive_counterexamples():
    """
    M4 誤報反例：
    - 40 位小寫 hex、UUID、過短之 ghp_ 前綴字串、一般文字，scanner 皆無 finding，
      DLP 輸出皆不含 [DLP_GITHUB_TOKEN]、[DLP_NOTION_TOKEN]、[DLP_GEMINI_KEY]；
      40 位 hex 經 DLP 後原樣不變。
    - Google 邊界反例（一律以 AIza 後接非 Sy 字元開頭）：
      AIza 後接 34 個字元、AIza 後接 36 個字元、AIza 前緊鄰一個英數字元，
      scanner 皆不得產生 GOOGLE_API_KEY，DLP 輸出皆不得含 [DLP_GEMINI_KEY]。
    """
    general_counterexamples = [
        # 40-char lowercase hex
        "c73dd28ce25c74caf46b9477410d7e405f0d7a46",
        # UUID
        "c305d930-b51a-4f5a-b0c4-9842f2b4c123",
        # Short ghp_ prefix string (under 36 chars after prefix)
        "".join(["gh", "p_"]) + "shorttoken123",
        # Ordinary text
        "The quick brown fox jumps over the lazy dog without any credentials."
    ]

    dlp_forbidden_labels = ["[DLP_GITHUB_TOKEN]", "[DLP_NOTION_TOKEN]", "[DLP_GEMINI_KEY]"]

    for text in general_counterexamples:
        # Scanner must produce zero findings
        findings = list(scan_content_lines(text.encode("utf-8"), "clean.txt"))
        assert len(findings) == 0, f"False positive in scanner for clean text: {text!r} -> {findings}"

        # DLP must not contain any of the specific labels
        sanitized = sanitize_dlp(text)
        for label in dlp_forbidden_labels:
            assert label not in sanitized, f"False positive in DLP for clean text: {text!r} got {label}"

    # 40-char hex must be preserved exactly by DLP
    hex_sample = "c73dd28ce25c74caf46b9477410d7e405f0d7a46"
    assert sanitize_dlp(hex_sample) == hex_sample, "40-char hex was altered by DLP"

    # Google boundary counterexamples (AIza followed by non-Sy char)
    google_prefix = "".join(["AI", "za"])
    alphanumeric = string.ascii_letters + string.digits

    # 1. AIza + 34 chars (too short: 'K' + 33 chars = 34 chars)
    google_too_short = google_prefix + "K" + _gen_random_token(33, alphanumeric)
    # 2. AIza + 36 chars (too long: 'K' + 35 chars = 36 chars)
    google_too_long = google_prefix + "K" + _gen_random_token(35, alphanumeric)
    # 3. AIza preceded by alphanumeric character
    google_preceding_alnum = "X" + google_prefix + "K" + _gen_random_token(34, alphanumeric)

    google_counterexamples = [
        ("too_short", google_too_short),
        ("too_long", google_too_long),
        ("preceding_alnum", google_preceding_alnum),
    ]

    for name, sample in google_counterexamples:
        wrapped = f" {sample} "
        findings = list(scan_content_lines(wrapped.encode("utf-8"), "google_negative.txt"))
        detected_ids = [fid for fid, _ in findings]
        assert "GOOGLE_API_KEY" not in detected_ids, (
            f"Google negative sample '{name}' triggered GOOGLE_API_KEY detector in scanner: {sample}"
        )

        sanitized = sanitize_dlp(wrapped)
        assert "[DLP_GEMINI_KEY]" not in sanitized, (
            f"Google negative sample '{name}' triggered [DLP_GEMINI_KEY] in DLP: {sanitized}"
        )


# ==============================================================================
# M5 Non-Format Classes Test
# ==============================================================================

def test_m5_non_format_classes():
    """
    M5 非格式類別：矩陣中 coverage 為 NOT_FORMAT_DETECTABLE 或 NOT_APPLICABLE 之類別必須附非空 reason，
    且不得具有 scanner_detector 或 dlp_label 欄位。
    """
    matrix = _load_matrix()

    for format_class, details in matrix["format_classes"].items():
        coverage = details.get("coverage")
        if coverage in ("NOT_FORMAT_DETECTABLE", "NOT_APPLICABLE"):
            assert "reason" in details, f"{format_class} must have a 'reason' field"
            assert isinstance(details["reason"], str) and len(details["reason"].strip()) > 0, (
                f"{format_class} must have a non-empty reason string"
            )
            assert "scanner_detector" not in details, (
                f"{format_class} with coverage {coverage} must not have scanner_detector"
            )
            assert "dlp_label" not in details, (
                f"{format_class} with coverage {coverage} must not have dlp_label"
            )
