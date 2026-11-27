"""Disposable-data checks only; no model, services, credentials or filesystem writes."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'integrations'))
from local_worker_checks import evaluate_checks

def run(checks, originals=None, outputs=None):
    originals = {} if originals is None else originals
    outputs = {} if outputs is None else outputs
    return evaluate_checks(checks, originals, outputs)

class TextContainsTest(unittest.TestCase):
    def test_pass(self):
        r = run([{"type":"text_contains","path":"a.txt","fragments":["hello","wor+ld"]}],
                outputs={"a.txt":"pre hello wor+ld post".encode()})
        self.assertEqual(r, {"passed":True,"failures":[]})

    def test_missing_fragment(self):
        r = run([{"type":"text_contains","path":"a.txt","fragments":["hello","nope"]}],
                outputs={"a.txt":"hello".encode()})
        self.assertFalse(r["passed"])
        self.assertEqual(len(r["failures"]),1)
        self.assertTrue(r["failures"][0].startswith("1: "))

    def test_invalid_fragments_field(self):
        for bad in ([], "", ["x",""], None, "str"):
            r = run([{"type":"text_contains","path":"a","fragments":bad}],
                    outputs={"a":b"x"})
            self.assertFalse(r["passed"])
            self.assertTrue(r["failures"][0].startswith("1: "))

    def test_invalid_utf8(self):
        r = run([{"type":"text_contains","path":"a","fragments":["x"]}],
                outputs={"a":b"\xff\xfe"})
        self.assertFalse(r["passed"])

class JsonFieldsTest(unittest.TestCase):
    def test_pass_extra_fields_and_key_order(self):
        r = run([{"type":"json_fields","path":"o.json",
                  "fields":{"b":2,"a":{"y":[1,2],"x":"s"}}}],
                outputs={"o.json":b'{"a": {"x": "s", "y": [1, 2]}, "b": 2, "c": "extra"}'})
        self.assertEqual(r, {"passed":True,"failures":[]})

    def test_bool_versus_int(self):
        r = run([{"type":"json_fields","path":"o","fields":{"flag":True}}],
                outputs={"o":b'{"flag": 1}'})
        self.assertFalse(r["passed"])
        r = run([{"type":"json_fields","path":"o","fields":{"flag":1}}],
                outputs={"o":b'{"flag": true}'})
        self.assertFalse(r["passed"])
        r = run([{"type":"json_fields","path":"o","fields":{"flag":True}}],
                outputs={"o":b'{"flag": true}'})
        self.assertTrue(r["passed"])

    def test_number_type_int_float(self):
        r = run([{"type":"json_fields","path":"o","fields":{"n":1}}],
                outputs={"o":b'{"n": 1.0}'})
        self.assertTrue(r["passed"])
        r = run([{"type":"json_fields","path":"o","fields":{"n":2}}],
                outputs={"o":b'{"n": 3}'})
        self.assertFalse(r["passed"])

    def test_missing_key(self):
        r = run([{"type":"json_fields","path":"o","fields":{"a":1,"b":2}}],
                outputs={"o":b'{"a": 1}'})
        self.assertFalse(r["passed"])

    def test_json_none_versus_false(self):
        r = run([{"type":"json_fields","path":"o","fields":{"v":None}}],
                outputs={"o":b'{"v": false}'})
        self.assertFalse(r["passed"])

    def test_invalid_json_and_non_object(self):
        for payload in (b'{', b'[]', b'"str"', b'\xff\xfe'):
            r = run([{"type":"json_fields","path":"o","fields":{"a":1}}],
                    outputs={"o":payload})
            self.assertFalse(r["passed"])

    def test_invalid_fields_field(self):
        for bad in ([], {}, None, "x"):
            r = run([{"type":"json_fields","path":"o","fields":bad}],
                    outputs={"o":b'{"a": 1}'})
            self.assertFalse(r["passed"])

class PreserveSuffixTest(unittest.TestCase):
    ORIG = b"head\r\nMARKER\nkeep me \t now\r\n"

    def test_exact_suffix_pass(self):
        r = run([{"type":"preserve_suffix","path":"f","marker":"MARKER"}],
                originals={"f":self.ORIG},
                outputs={"f":b"changed prefix\r\nMARKER\nkeep me \t now\r\n"})
        self.assertEqual(r, {"passed":True,"failures":[]})

    def test_crf_changed_fails(self):
        r = run([{"type":"preserve_suffix","path":"f","marker":"MARKER"}],
                originals={"f":self.ORIG},
                outputs={"f":b"MARKER\nkeep me \t now\n"})
        self.assertFalse(r["passed"])

    def test_spacing_changed_fails(self):
        r = run([{"type":"preserve_suffix","path":"f","marker":"MARKER"}],
                originals={"f":self.ORIG},
                outputs={"f":b"MARKER\nkeep me  now\r\n"})
        self.assertFalse(r["passed"])

    def test_duplicate_marker_fails(self):
        r = run([{"type":"preserve_suffix","path":"f","marker":"MARKER"}],
                originals={"f":self.ORIG},
                outputs={"f":b"MARKER x MARKER\nkeep me \t now\r\n"})
        self.assertFalse(r["passed"])

    def test_missing_marker_fails(self):
        r = run([{"type":"preserve_suffix","path":"f","marker":"MARKER"}],
                originals={"f":self.ORIG},
                outputs={"f":b"no marker here\r\n"})
        self.assertFalse(r["passed"])

    def test_missing_original_fails(self):
        r = run([{"type":"preserve_suffix","path":"f","marker":"MARKER"}],
                outputs={"f":self.ORIG})
        self.assertFalse(r["passed"])

    def test_invalid_marker(self):
        for bad in ("", None, 5):
            r = run([{"type":"preserve_suffix","path":"f","marker":bad}],
                    originals={"f":self.ORIG}, outputs={"f":self.ORIG})
            self.assertFalse(r["passed"])

class PythonSyntaxTest(unittest.TestCase):
    def test_valid(self):
        r = run([{"type":"python_syntax","path":"m.py"}],
                outputs={"m.py":b"def f(x):\n    return x + 1\n"})
        self.assertEqual(r, {"passed":True,"failures":[]})

    def test_bom_accepted(self):
        r = run([{"type":"python_syntax","path":"m.py"}],
                outputs={"m.py":"\ufeffx = 1\n".encode("utf-8")})
        self.assertTrue(r["passed"])

    def test_invalid_syntax_no_source_in_diagnostic(self):
        r = run([{"type":"python_syntax","path":"m.py"}],
                outputs={"m.py":b"def f(:\n    pass\n"})
        self.assertFalse(r["passed"])
        self.assertNotIn("def f", r["failures"][0])

    def test_nested_syntax_error(self):
        r = run([{"type":"python_syntax","path":"m.py"}],
                outputs={"m.py":b"def f(x):\n    return x +\n"})
        self.assertFalse(r["passed"])

    def test_no_execution(self):
        # Candidate would explode if executed/imported; ast.parse must not run it.
        booby = b"import builtins\nbuiltins.__dict__['HARNESS_MARKER'] = 1\nraise RuntimeError('ran')\n"
        r = run([{"type":"python_syntax","path":"m.py"}], outputs={"m.py":booby})
        self.assertTrue(r["passed"])
        import builtins
        self.assertFalse(hasattr(builtins,"HARNESS_MARKER"))

class BatchAndMalformedTest(unittest.TestCase):
    def test_missing_candidate_is_failure(self):
        r = run([{"type":"text_contains","path":"a","fragments":["x"]},
                 {"type":"python_syntax","path":"b"}],
                outputs={"a":b"x"})
        self.assertFalse(r["passed"])
        self.assertEqual(len(r["failures"]),1)
        self.assertTrue(r["failures"][0].startswith("2: "))

    def test_none_candidate(self):
        r = run([{"type":"python_syntax","path":"b"}], outputs={"b":None})
        self.assertFalse(r["passed"])

    def test_unknown_type(self):
        r = run([{"type":"frobnicate","path":"a"}], outputs={"a":b"x"})
        self.assertFalse(r["passed"])
        self.assertTrue(r["failures"][0].startswith("1: "))

    def test_malformed_checks(self):
        for bad in ([None], [{"type":"text_contains"}], 42, "x"):
            r = run(bad if isinstance(bad,list) else [bad], outputs={"a":b"x"})
            self.assertFalse(r["passed"])

    def test_multiple_failures_numbered(self):
        checks = [{"type":"text_contains","path":"a","fragments":["q"]},
                  {"type":"unknown","path":"a"},
                  {"type":"python_syntax","path":"a"}]
        r = run(checks, outputs={"a":b"x"})
        self.assertEqual([f.split(":")[0] for f in r["failures"]],["1","2"])

    def test_inputs_not_mutated(self):
        checks = [{"type":"text_contains","path":"a","fragments":["x"]}]
        originals = {"a":b"x"}
        outputs = {"a":b"x"}
        import copy
        c1,o1,u1 = copy.deepcopy(checks), copy.deepcopy(originals), copy.deepcopy(outputs)
        run(checks, originals, outputs)
        self.assertEqual((checks,originals,outputs),(c1,o1,u1))

    def test_empty_checks_passes(self):
        self.assertEqual(run([]), {"passed":True,"failures":[]})

    def test_diagnostic_has_no_expected_content(self):
        r = run([{"type":"text_contains","path":"a","fragments":["SECRETFRAG"]}],
                outputs={"a":b"other"})
        self.assertNotIn("SECRETFRAG", r["failures"][0])

class IndependentStrictInputTests(unittest.TestCase):
    def test_duplicate_and_non_json_constants_rejected(self):
        for payload in (b'{"ok":true,"ok":true}', b'{"ok":true,"n":NaN}', b'{"ok":true,"n":Infinity}'):
            self.assertFalse(run([{"type":"json_fields","path":"x","fields":{"ok":True}}], outputs={"x":payload})['passed'])

    def test_invalid_unicode_marker_is_a_failure(self):
        self.assertFalse(run([{"type":"preserve_suffix","path":"x","marker":"\ud800"}], originals={"x":b'old'}, outputs={"x":b'new'})['passed'])

if __name__ == "__main__":
    unittest.main()
