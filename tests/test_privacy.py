#!/usr/bin/env python3
"""tests/test_privacy.py — fixture-based FB-corpus privacy + pipeline tests.

No network, no LLM, no Facebook: everything runs against
tests/fixtures/apify_sample.json (raw Apify-shaped scrape, synthetic names),
the anonymizer CLI, the privacy gate CLI and the distiller/validator module
functions.

Covers the acceptance contract mechanically:
  * anonymizing the fixture produces member-<8hex> records with ZERO
    author-name occurrences (and drops every profile field),
  * the privacy gate is green on the anonymized output and FAILS on the
    poisoned fixtures (fb thread + distilled record),
  * FB distilled records validate against their source post text,
  * validate_distilled routes FB-source records to the FB validator.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "fixtures"
APIFY_FIXTURE = FIXTURES / "apify_sample.json"
SALT = "ci-fixture-test-salt-0123456789abcdef"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


privacy_common = load_module("privacy_common", SCRIPTS / "privacy_common.py")
fb_anonymize = load_module("fb_anonymize", SCRIPTS / "fb_anonymize.py")
validate_privacy = load_module("validate_privacy", SCRIPTS / "validate_privacy.py")
distill = load_module("distill", SCRIPTS / "distill.py")


def run_cli(script: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, FB_PSEUDONYM_SALT=SALT)
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def author_names() -> list[str]:
    payload = json.loads(APIFY_FIXTURE.read_text(encoding="utf-8"))
    return privacy_common.harvest_author_names(payload)


def anonymize(tmp: Path) -> Path:
    out = tmp / "fb-out"
    proc = run_cli("fb_anonymize.py", "--input", str(APIFY_FIXTURE), "--outdir", str(out))
    assert proc.returncode == 0, proc.stderr
    return out


class AnonymizeTests(unittest.TestCase):
    def test_expected_outputs_and_shape(self):
        with tempfile.TemporaryDirectory() as td:
            out = anonymize(Path(td))
            names = sorted(p.name for p in out.glob("*.json"))
            self.assertEqual(names, [
                "584126708394913-pfbid0SampleA4mN.json",
                "androidaps-users-pfbid0SampleB1wT.json",
                "xdrip-users-pfbid0SampleA1xY.json",
                "xdrip-users-pfbid0SampleA2zQ.json",
                "xdrip-users-pfbid0SampleA3pL.json",
            ])
            for path in out.glob("*.json"):
                rec = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(rec["source"], "facebook")
                self.assertEqual(set(rec) - privacy_common.FB_THREAD_KEYS, set())
                self.assertIn("facebook.com", rec["url"])
                for comment in rec["comments"]:
                    self.assertRegex(comment["pseudonym"], r"^member-[0-9a-f]{8}$")
                    self.assertEqual(set(comment) - privacy_common.FB_COMMENT_KEYS, set())

    def test_zero_author_name_occurrences(self):
        with tempfile.TemporaryDirectory() as td:
            out = anonymize(Path(td))
            authors = author_names()
            self.assertGreaterEqual(len(authors), 5)
            for path in out.glob("*.json"):
                rec = json.loads(path.read_text(encoding="utf-8"))
                texts = [rec["text"]] + [c["text"] for c in rec["comments"]]
                for text in texts:
                    self.assertEqual(privacy_common.name_leak_matches(authors, text), [],
                                     f"name leak in {path.name}: {text!r}")

    def test_drops_profile_fields_keeps_aggregates_only(self):
        with tempfile.TemporaryDirectory() as td:
            out = anonymize(Path(td))
            rec = json.loads((out / "xdrip-users-pfbid0SampleA1xY.json").read_text(encoding="utf-8"))
            blob = json.dumps(rec)
            for forbidden in ("postAuthor", "commentAuthor", "profileUrl", "postImages",
                              "\"reactions\":", "\"name\":", "Jordan Lee", "Alicia Chen",
                              "\"reactions\""):
                self.assertNotIn(forbidden, blob)
            self.assertIn('"reactions_count": 12', blob)  # aggregate kept
            self.assertEqual(len(rec["comments"]), 3)

    def test_deterministic_and_stable_pseudonyms(self):
        with tempfile.TemporaryDirectory() as td:
            first = anonymize(Path(td))
            second = anonymize(Path(td))
            first_blob = {p.name: p.read_bytes() for p in first.glob("*.json")}
            second_blob = {p.name: p.read_bytes() for p in second.glob("*.json")}
            self.assertEqual(first_blob, second_blob)  # same salt -> identical bytes
            # same author id across two posts maps to the same pseudonym
            a1 = json.loads((first / "xdrip-users-pfbid0SampleA1xY.json").read_text(encoding="utf-8"))
            a4 = json.loads((first / "584126708394913-pfbid0SampleA4mN.json").read_text(encoding="utf-8"))
            marco_in_a1 = [c["pseudonym"] for c in a1["comments"] if "receiver pairing" in c["text"]]
            marco_in_a4 = [c["pseudonym"] for c in a4["comments"] if "GATT cache" in c["text"]]
            self.assertEqual(marco_in_a1, marco_in_a4)

    def test_fails_closed_on_leak(self):
        payload = json.loads(APIFY_FIXTURE.read_text(encoding="utf-8"))
        payload[0]["postComments"][0]["commentText"] = "works per Alicia Chen"
        with tempfile.TemporaryDirectory() as td:
            leak_file = Path(td) / "leak.json"
            leak_file.write_text(json.dumps(payload), encoding="utf-8")
            proc = run_cli("fb_anonymize.py", "--input", str(leak_file), "--outdir", str(Path(td) / "out"))
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Alicia Chen", proc.stderr)
            self.assertFalse((Path(td) / "out").exists())  # nothing written


class PrivacyGateTests(unittest.TestCase):
    def _gate(self, *paths: str) -> subprocess.CompletedProcess:
        return run_cli("validate_privacy.py", "--raw", str(APIFY_FIXTURE), *paths)

    def test_green_on_anonymized_output(self):
        with tempfile.TemporaryDirectory() as td:
            out = anonymize(Path(td))
            proc = self._gate(str(out))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("0 leaks", proc.stdout)

    def test_fails_on_poisoned_fb_thread(self):
        proc = self._gate(str(FIXTURES / "poisoned_fb_thread.json"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Marco Ruiz", proc.stdout)

    def test_fails_on_poisoned_distilled(self):
        proc = self._gate(str(FIXTURES / "poisoned_distilled.json"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Priya Nair", proc.stdout)

    def test_hygiene_rejects_profile_fields(self):
        with tempfile.TemporaryDirectory() as td:
            out = anonymize(Path(td))
            path = out / "xdrip-users-pfbid0SampleA1xY.json"
            rec = json.loads(path.read_text(encoding="utf-8"))
            rec["user_name"] = "Alicia Chen"  # smuggled raw profile key
            path.write_text(json.dumps(rec), encoding="utf-8")
            proc = self._gate(str(out))
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("user_name", proc.stdout)

    def test_exact_name_matching_boundaries(self):
        hits = privacy_common.name_leak_matches(["Sam Okafor"], "please sample the text")
        self.assertEqual(hits, [])  # "Sam" must not match inside "sample"
        hits = privacy_common.name_leak_matches(["Alicia Chen"], "thanks, ALICIA  CHEN!")
        self.assertEqual(hits, ["Alicia Chen"])
        hits = privacy_common.name_leak_matches(["Alicia Chen"], "Alicia said hello")
        self.assertEqual(hits, [])  # partial first name alone is not the name


class DistillFbTests(unittest.TestCase):
    @staticmethod
    def _anonymized_a1() -> dict:
        with tempfile.TemporaryDirectory() as td:
            out = anonymize(Path(td))
            return json.loads((out / "xdrip-users-pfbid0SampleA1xY.json").read_text(encoding="utf-8"))

    def test_fb_record_validation(self):
        src = json.loads(APIFY_FIXTURE.read_text(encoding="utf-8"))[0]
        full = "\n".join([src["postText"]]
                          + [c.get("commentText", "") for c in src.get("postComments", [])])
        rec = {
            "title": "G6 keeps asking for calibration",
            "symptom": "The Dexcom G6 keeps asking for calibration twice a day and values freeze until a fingerstick is entered.",
            "cause": "The G6 receiver pairing stays active at the same time as xDrip+ with the native G6 toggle left on.",
            "fix": "Disable native mode on the transmitter in xDrip+ settings, then start the sensor again.",
            "settings_changed": ["allow native G6 → off"],
            "devices": ["Dexcom G6"],
            "android_versions": [],
            "driver_tags": ["native G6"],
            "confidence": "high",
            "evidence_quote": "Disable native mode on the transmitter in xDrip+ settings, then start the sensor again.",
        }
        self.assertEqual(distill.validate_record_fb(rec, full), [])
        bad = dict(rec, devices=["Medtrum Nano"])  # never mentioned
        self.assertTrue(any("Medtrum" in e for e in distill.validate_record_fb(bad, full)))
        bad2 = dict(rec, evidence_quote="Disable native mode … then start the sensor again.")
        self.assertTrue(any("verbatim" in e for e in distill.validate_record_fb(bad2, full)))

    def test_validate_distilled_routes_fb_records(self):
        """validate_distilled must route FB-source distilled records to the FB
        validator + fb_threads source, while leaving GitHub records alone."""
        vd = load_module("validate_distilled", SCRIPTS / "validate_distilled.py")
        post = self._anonymized_a1()
        good = {
            "source": "facebook", "group": post["group"],
            "group_url": post["group_url"], "url": post["url"],
            "title": "G6 keeps asking for calibration",
            "symptom": "xDrip+ keeps asking for calibration on a pre-calibrated Dexcom G6.",
            "cause": "The G6 receiver pairing stays active with the native G6 toggle on.",
            "fix": "Disable native mode on the transmitter in xDrip+ settings, then start the sensor again.",
            "settings_changed": ["allow native G6 → off"],
            "devices": ["Dexcom G6"], "android_versions": [],
            "driver_tags": ["native G6"], "confidence": "high",
            "evidence_quote": "Disable native mode on the transmitter in xDrip+ settings, then start the sensor again.",
        }
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fbdir = base / "fb_threads"
            fbdir.mkdir()
            distdir = base / "distilled"
            distdir.mkdir()
            corpusdir = base / "corpus"
            corpusdir.mkdir()
            (fbdir / "xdrip-users-pfbid0SampleA1xY.json").write_text(
                json.dumps(post, ensure_ascii=False), encoding="utf-8")
            (distdir / "xdrip-users-pfbid0SampleA1xY.json").write_text(
                json.dumps(good, ensure_ascii=False), encoding="utf-8")
            old = {a: getattr(vd, a) for a in ("CORPUS", "DISTILLED", "FB_THREADS")}
            import contextlib
            import io
            try:
                for attr, value in (("CORPUS", corpusdir), ("DISTILLED", distdir),
                                    ("FB_THREADS", fbdir)):
                    setattr(vd, attr, value)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(vd.main(), 0)
                    bad = dict(good, evidence_quote="made-up quote not in the post")
                    (distdir / "xdrip-users-pfbid0SampleA1xY.json").write_text(
                        json.dumps(bad, ensure_ascii=False), encoding="utf-8")
                    self.assertNotEqual(vd.main(), 0)
            finally:
                for attr, value in old.items():
                    setattr(vd, attr, value)

    def test_fb_distill_batch_selection_dry_run(self):
        """--source-type facebook dry-run picks undistilled fb posts without an
        LLM, and never touches the github state file."""
        with tempfile.TemporaryDirectory() as td:
            out = anonymize(Path(td))
            proc = run_cli("distill.py", "--source-type", "facebook",
                           "--source-dir", str(out), "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("fb posts: 5", proc.stdout)
            self.assertIn("xdrip-users-pfbid0SampleA1xY", proc.stdout)
            self.assertFalse((Path(td) / "state.json").exists())  # github state untouched


if __name__ == "__main__":
    unittest.main(verbosity=2)
