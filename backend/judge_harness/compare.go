package main

import (
	"bytes"
	"math"
	"strconv"
)

// Output comparison modes (JudgeProblem.compare_mode).
const (
	// CompareToken ignores differences in whitespace and blank lines: the
	// output and answer must be the same sequence of whitespace-separated
	// tokens. The default, and the usual contest rule.
	CompareToken = "token"
	// CompareExact requires byte-for-byte equality.
	CompareExact = "exact"
	// CompareFloat is token-wise, but two tokens that both parse as numbers
	// match when they differ by at most the tolerance, absolutely or relative
	// to the expected value.
	CompareFloat = "float"
)

func compareOutput(out, answer []byte, mode string, tolerance float64) bool {
	switch mode {
	case CompareExact:
		return bytes.Equal(out, answer)
	case CompareFloat:
		return compareTokens(out, answer, func(a, b []byte) bool {
			return bytes.Equal(a, b) || floatsClose(a, b, tolerance)
		})
	default:
		return compareTokens(out, answer, bytes.Equal)
	}
}

// isSpace is ASCII whitespace only: Unicode spaces (U+00A0 and friends) are
// part of a token, not separators, so an answer can't be matched by output
// that differs from it in non-ASCII bytes.
func isSpace(r rune) bool {
	return r == ' ' || r == '\t' || r == '\n' || r == '\r' || r == '\v' || r == '\f'
}

func compareTokens(out, answer []byte, same func(a, b []byte) bool) bool {
	got := bytes.FieldsFunc(out, isSpace)
	want := bytes.FieldsFunc(answer, isSpace)
	if len(got) != len(want) {
		return false
	}
	for i := range want {
		if !same(got[i], want[i]) {
			return false
		}
	}
	return true
}

func floatsClose(got, want []byte, tolerance float64) bool {
	g, errG := strconv.ParseFloat(string(got), 64)
	w, errW := strconv.ParseFloat(string(want), 64)
	if errG != nil || errW != nil {
		return false
	}
	if math.IsNaN(g) || math.IsNaN(w) || math.IsInf(g, 0) || math.IsInf(w, 0) {
		return false
	}
	diff := math.Abs(g - w)
	return diff <= tolerance || diff <= tolerance*math.Abs(w)
}
