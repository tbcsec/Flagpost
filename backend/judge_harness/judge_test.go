package main

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

// fakeRunner returns scripted outcomes: one for the compile step, then one per
// test, in order.
type fakeRunner struct {
	outcomes []*outcome
	calls    int
	compiles int
}

func (f *fakeRunner) run(argv []string, stdin *os.File, lim Limits, work string, compile bool) (*outcome, error) {
	if compile {
		f.compiles++
	}
	o := f.outcomes[f.calls]
	f.calls++
	return o, nil
}

func ok(output string) *outcome {
	zero := 0
	return &outcome{exitCode: &zero, output: []byte(output), cpuMs: 10, peakKB: 1000}
}

func code(n int) *int { return &n }

func writeTests(t *testing.T, answers ...string) []Test {
	t.Helper()
	dir := t.TempDir()
	var tests []Test
	for i, a := range answers {
		in := filepath.Join(dir, "in"+string(rune('a'+i)))
		ans := filepath.Join(dir, "ans"+string(rune('a'+i)))
		os.WriteFile(in, []byte("x\n"), 0o600)
		os.WriteFile(ans, []byte(a), 0o600)
		tests = append(tests, Test{Name: "t" + string(rune('a'+i)), Input: in, Answer: ans})
	}
	return tests
}

func baseJob(tests []Test) *Job {
	return &Job{
		Nonce:         "n",
		Work:          "/work",
		Run:           []string{"prog"},
		Compile:       nil,
		CompileLimits: Limits{CPUMs: 10000, WallMs: 20000, OutputBytes: 65536},
		RunLimits:     Limits{CPUMs: 1000, WallMs: 3000, MemoryKB: 65536, OutputBytes: 1024},
		Compare:       CompareToken,
		Tests:         tests,
	}
}

func TestJudgeAcceptsAndStopsAtFirstFailure(t *testing.T) {
	job := baseJob(writeTests(t, "1\n", "2\n", "3\n"))
	r := &fakeRunner{outcomes: []*outcome{ok("1"), ok("9"), ok("3")}}
	res := judge(job, r)
	if res.Verdict != VerdictWrongAnswer || len(res.Tests) != 2 || r.calls != 2 {
		t.Fatalf("got %+v after %d runs", res, r.calls)
	}
	if res.Nonce != "n" {
		t.Fatal("nonce not echoed")
	}

	r = &fakeRunner{outcomes: []*outcome{ok("1"), ok("2"), ok("3")}}
	if res := judge(job, r); res.Verdict != VerdictAccepted || len(res.Tests) != 3 {
		t.Fatalf("got %+v", res)
	}
}

func TestRunAllJudgesEveryTestAndKeepsTheFirstFailure(t *testing.T) {
	job := baseJob(writeTests(t, "1\n", "2\n", "3\n", "4\n"))
	job.RunAll = true
	r := &fakeRunner{outcomes: []*outcome{ok("1"), ok("9"), ok("3"), ok("8")}}
	res := judge(job, r)
	if res.Verdict != VerdictWrongAnswer || len(res.Tests) != 4 || r.calls != 4 {
		t.Fatalf("got %+v after %d runs", res, r.calls)
	}
	got := []string{}
	for _, tr := range res.Tests {
		got = append(got, tr.Verdict)
	}
	want := []string{VerdictAccepted, VerdictWrongAnswer, VerdictAccepted, VerdictWrongAnswer}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("per-test verdicts %v, want %v", got, want)
		}
	}

	r = &fakeRunner{outcomes: []*outcome{ok("1"), ok("2"), ok("3"), ok("4")}}
	if res := judge(job, r); res.Verdict != VerdictAccepted || len(res.Tests) != 4 {
		t.Fatalf("got %+v", res)
	}
}

func TestOutputIsReturnedOnlyWhereAsked(t *testing.T) {
	tests := writeTests(t, "1\n", "2\n")
	tests[0].ShowOutput = true
	job := baseJob(tests)
	r := &fakeRunner{outcomes: []*outcome{ok("1\n"), ok("2\n")}}
	res := judge(job, r)
	if res.Tests[0].Output == nil || *res.Tests[0].Output != "1\n" || res.Tests[1].Output != nil {
		t.Fatalf("got %+v", res.Tests)
	}
	// Shown even when the example fails — that's when it's most useful.
	r = &fakeRunner{outcomes: []*outcome{ok("7\n")}}
	res = judge(job, r)
	if res.Verdict != VerdictWrongAnswer || *res.Tests[0].Output != "7\n" {
		t.Fatalf("got %+v", res)
	}
}

func TestJudgeCompileError(t *testing.T) {
	job := baseJob(writeTests(t, "1\n"))
	job.Compile = []string{"cc"}
	r := &fakeRunner{outcomes: []*outcome{{exitCode: code(1), output: []byte("error: x")}}}
	res := judge(job, r)
	if res.Verdict != VerdictCompileError || res.CompileOutput != "error: x" || r.calls != 1 {
		t.Fatalf("got %+v", res)
	}

	r = &fakeRunner{outcomes: []*outcome{{exitCode: code(0), wallTimedOut: true}}}
	if res := judge(job, r); res.Verdict != VerdictCompileError {
		t.Fatalf("slow compile: got %+v", res)
	}

	r = &fakeRunner{outcomes: []*outcome{{memoryExceeded: true, signal: code(9)}}}
	if res := judge(job, r); res.Verdict != VerdictCompileError ||
		res.CompileOutput != "Compilation used too much memory." {
		t.Fatalf("memory-hungry compile: got %+v", res)
	}

	r = &fakeRunner{outcomes: []*outcome{ok("warning"), ok("1")}}
	res = judge(job, r)
	if res.Verdict != VerdictAccepted || r.compiles != 1 || res.CompileOutput != "warning" {
		t.Fatalf("got %+v", res)
	}
}

func TestClassify(t *testing.T) {
	lim := Limits{CPUMs: 1000, MemoryKB: 1000, OutputBytes: 10}
	sig := func(s syscall.Signal) *int { n := int(s); return &n }
	cases := []struct {
		name string
		out  outcome
		want string
	}{
		{"clean", outcome{exitCode: code(0), cpuMs: 999}, VerdictAccepted},
		{"cpu over", outcome{exitCode: code(0), cpuMs: 1001}, VerdictTimeLimit},
		{"wall", outcome{wallTimedOut: true, signal: sig(syscall.SIGKILL)}, VerdictTimeLimit},
		{"sigxcpu", outcome{signal: sig(syscall.SIGXCPU), cpuMs: 990}, VerdictTimeLimit},
		{"output", outcome{outputExceeded: true, signal: sig(syscall.SIGKILL)}, VerdictOutputLimit},
		{"memory watcher", outcome{memoryExceeded: true, signal: sig(syscall.SIGKILL)}, VerdictMemoryLimit},
		{"memory peak", outcome{exitCode: code(0), peakKB: 1001}, VerdictMemoryLimit},
		{"oom kill", outcome{signal: sig(syscall.SIGKILL), peakKB: 5000}, VerdictMemoryLimit},
		{"exit code", outcome{exitCode: code(3)}, VerdictRuntimeError},
		{"segfault", outcome{signal: sig(syscall.SIGSEGV)}, VerdictRuntimeError},
	}
	for _, c := range cases {
		if got := classify(&c.out, lim); got != c.want {
			t.Errorf("%s: got %s, want %s", c.name, got, c.want)
		}
	}
}

func TestJobValidation(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "job.json")
	os.WriteFile(path, []byte(`{"nonce":"n","work":"/w","run":["x"],"compare":"regex",
		"run_limits":{"cpu_ms":1,"wall_ms":1,"output_bytes":1},"tests":[{"name":"a"}]}`), 0o600)
	if _, err := loadJob(path); err == nil {
		t.Fatal("unknown compare mode accepted")
	}
	os.WriteFile(path, []byte(`{"nonce":"n","work":"/w","run":["x"],"compare":"token","uid":5,
		"run_limits":{"cpu_ms":1,"wall_ms":1,"output_bytes":1},"tests":[{"name":"a"}]}`), 0o600)
	if _, err := loadJob(path); err == nil {
		t.Fatal("a system uid was accepted for the submission")
	}
	if res := judgeFile(path); res.Verdict != VerdictInternalError || res.Nonce != "n" {
		t.Fatalf("invalid job: got %+v", res)
	}
	res := judgeFile(filepath.Join(dir, "missing.json"))
	if res.Verdict != VerdictInternalError || res.Error == "" {
		t.Fatalf("missing job: got %+v", res)
	}
}
