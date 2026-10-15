package main

import "testing"

func TestCompareOutput(t *testing.T) {
	cases := []struct {
		name, out, ans, mode string
		tol                  float64
		want                 bool
	}{
		{"token exact", "5\n", "5\n", CompareToken, 0, true},
		{"token ignores spacing", "1   2\n\n3  \r\n", "1 2\n3\n", CompareToken, 0, true},
		{"token missing newline", "5", "5\n", CompareToken, 0, true},
		{"token differs", "6\n", "5\n", CompareToken, 0, false},
		{"token extra token", "5 6\n", "5\n", CompareToken, 0, false},
		{"token case-sensitive", "yes\n", "YES\n", CompareToken, 0, false},
		{"token empty both", "", "\n", CompareToken, 0, true},
		{"token nbsp is not a separator", "1 2\n", "1 2\n", CompareToken, 0, false},
		{"exact equal", "5\n", "5\n", CompareExact, 0, true},
		{"exact missing newline", "5", "5\n", CompareExact, 0, false},
		{"exact spacing", "1  2\n", "1 2\n", CompareExact, 0, false},
		{"float within abs", "3.1415\n", "3.14159\n", CompareFloat, 1e-4, true},
		{"float outside", "3.14\n", "3.14159\n", CompareFloat, 1e-4, false},
		{"float relative", "1000001\n", "1000000\n", CompareFloat, 1e-6, true},
		{"float words must match", "ok 1.0\n", "ok 1\n", CompareFloat, 1e-6, true},
		{"float word differs", "no 1\n", "ok 1\n", CompareFloat, 1e-6, false},
		{"float nan never matches", "nan\n", "1\n", CompareFloat, 1e9, false},
		{"float count differs", "1 2\n", "1\n", CompareFloat, 1, false},
	}
	for _, c := range cases {
		if got := compareOutput([]byte(c.out), []byte(c.ans), c.mode, c.tol, false); got != c.want {
			t.Errorf("%s: got %v, want %v", c.name, got, c.want)
		}
	}
}

// Ignoring letter case (the standard ICPC/Kattis checker's default) — ASCII
// letters only, in every mode, and nothing else relaxed.
func TestCompareIgnoringCase(t *testing.T) {
	cases := []struct {
		name, out, ans, mode string
		tol                  float64
		want                 bool
	}{
		{"token", "yes\n", "YES\n", CompareToken, 0, true},
		{"still token-wise", "YES  NO\n", "yes no\n", CompareToken, 0, true},
		{"different word", "yes\n", "YEP\n", CompareToken, 0, false},
		{"exact keeps spacing", "Yes\n", "YES\n", CompareExact, 0, true},
		{"exact spacing still matters", "Yes \n", "YES\n", CompareExact, 0, false},
		{"float words", "OK 1.0\n", "ok 1\n", CompareFloat, 1e-6, true},
		{"ascii only", "\xc5\xbf\n", "s\n", CompareToken, 0, false},
		{"non-letters unchanged", "[\n", "{\n", CompareToken, 0, false},
	}
	for _, c := range cases {
		if got := compareOutput([]byte(c.out), []byte(c.ans), c.mode, c.tol, true); got != c.want {
			t.Errorf("%s: got %v, want %v", c.name, got, c.want)
		}
	}
}
