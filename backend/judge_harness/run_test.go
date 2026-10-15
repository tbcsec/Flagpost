package main

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// These tests spawn real processes and drop to the submission user, so they
// need root (CAP_SETUID/CAP_SETGID/CAP_KILL) — run them in a container:
//
//	docker run --rm -v "$PWD":/src -w /src golang:1.27 go test ./...
//
// They're skipped otherwise.

// testUID is the submission user for these tests: a dedicated high uid, as
// the executor gives each judging, rather than the 65534 default. The kernel
// counts a uid's processes host-wide, so on a host already running things as
// "nobody" the default would leave the tests' process cap short (they failed
// intermittently that way next to a 56-thread Erlang VM running as nobody).
const testUID = 1_234_567

func TestMain(m *testing.M) {
	// The runner re-executes the current binary as the launcher; under
	// `go test` that's this test binary, so route the launcher here too.
	if len(os.Args) > 1 && os.Args[1] == launchArg {
		launch(os.Args[2:])
	}
	submissionUID = testUID
	os.Exit(m.Run())
}

func needRoot(t *testing.T) {
	t.Helper()
	if os.Geteuid() != 0 {
		t.Skip("needs root to switch to the submission user")
	}
}

// workDir makes a scratch directory the submission user owns, like the /work
// tmpfs in the judge container.
func workDir(t *testing.T) string {
	t.Helper()
	dir, err := os.MkdirTemp("", "judge-work")
	if err != nil {
		t.Fatal(err)
	}
	os.Chown(dir, testUID, testUID)
	os.Chmod(dir, 0o755)
	t.Cleanup(func() { os.RemoveAll(dir) })
	return dir
}

func runLimits() Limits {
	return Limits{CPUMs: 2000, WallMs: 5000, MemoryKB: 256 * 1024, OutputBytes: 1 << 20, FileBytes: 1 << 20}
}

func runCmd(t *testing.T, argv []string, stdin *os.File, lim Limits) *outcome {
	t.Helper()
	out, err := newSystemRunner(nil).run(argv, stdin, lim, workDir(t), false)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func sh(script string) []string { return []string{"sh", "-c", script} }

func TestRunsAsTheSubmissionUser(t *testing.T) {
	needRoot(t)
	out := runCmd(t, sh("id -u; id -G; grep CapEff /proc/self/status"), nil, runLimits())
	got := string(out.output)
	want := strconv.Itoa(testUID) + "\n" + strconv.Itoa(testUID) + "\n"
	if !strings.HasPrefix(got, want) || !strings.Contains(got, "0000000000000000") {
		t.Fatalf("not dropped: %q", got)
	}
}

func TestJudgeRunsAsTheJobsUID(t *testing.T) {
	needRoot(t)
	dir := t.TempDir()
	write := func(name, body string) string {
		p := filepath.Join(dir, name)
		os.WriteFile(p, []byte(body), 0o600)
		return p
	}
	work := workDir(t)
	os.Chown(work, 123456, 123456)
	jobPath := write("job.json", `{"nonce":"n1","work":"`+work+`","uid":123456,
		"run":["id","-u"],"compare":"token",
		"run_limits":{"cpu_ms":1000,"wall_ms":3000,"output_bytes":1024},
		"tests":[{"name":"t","input":"`+write("in", "")+`","answer":"`+write("ans", "123456\n")+`"}]}`)
	defer func() { submissionUID = testUID }()
	res := judgeFile(jobPath)
	if res.Verdict != VerdictAccepted || res.Nonce != "n1" {
		t.Fatalf("got %+v", res)
	}
}

func TestCannotReadRootOnlyFiles(t *testing.T) {
	needRoot(t)
	secret := filepath.Join(t.TempDir(), "answer")
	os.WriteFile(secret, []byte("hidden"), 0o600)
	out := runCmd(t, []string{"cat", secret}, nil, runLimits())
	if string(out.output) != "" || out.exitCode == nil || *out.exitCode == 0 {
		t.Fatalf("read a root-only file: %+v %q", out, out.output)
	}
}

func TestStdinIsTheTestInput(t *testing.T) {
	needRoot(t)
	path := filepath.Join(t.TempDir(), "in")
	os.WriteFile(path, []byte("2 3\n"), 0o600) // root-only, opened by the harness
	in, _ := os.Open(path)
	defer in.Close()
	out := runCmd(t, sh(`read a b; echo $((a+b))`), in, runLimits())
	if string(out.output) != "5\n" {
		t.Fatalf("got %q", out.output)
	}
}

func TestCPUTimeLimit(t *testing.T) {
	needRoot(t)
	lim := runLimits()
	lim.CPUMs = 500
	out := runCmd(t, sh("while :; do :; done"), nil, lim)
	if classify(out, lim) != VerdictTimeLimit || out.cpuMs < 500 {
		t.Fatalf("got %s after %dms cpu", classify(out, lim), out.cpuMs)
	}
	// Killed by RLIMIT_CPU about a second past the limit — not left to the
	// wall-clock backstop.
	if out.wallMs > 4000 {
		t.Fatalf("took %dms wall", out.wallMs)
	}
}

func TestWallClockBackstop(t *testing.T) {
	needRoot(t)
	lim := runLimits()
	lim.WallMs = 300
	out := runCmd(t, []string{"sleep", "10"}, nil, lim)
	if !out.wallTimedOut || classify(out, lim) != VerdictTimeLimit || out.wallMs > 2000 {
		t.Fatalf("got %+v", out)
	}
}

func TestMemoryLimit(t *testing.T) {
	needRoot(t)
	lim := runLimits()
	lim.MemoryKB = 50 * 1024
	out := runCmd(t, []string{"perl", "-e", `$x = "a" x 300_000_000; sleep 2`}, nil, lim)
	if classify(out, lim) != VerdictMemoryLimit {
		t.Fatalf("got %s (peak %d KB)", classify(out, lim), out.peakKB)
	}
}

// Data parked in scratch files is memory too (the scratch dirs are tmpfs).
func TestScratchGrowthCountsAsMemory(t *testing.T) {
	needRoot(t)
	scratch, err := os.MkdirTemp("", "judge-scratch") // traversable by the submission user
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(scratch)
	if err := syscall.Mount("tmpfs", scratch, "tmpfs", 0, "size=64m,mode=1777"); err != nil {
		t.Skipf("can't mount a tmpfs here: %v", err)
	}
	defer syscall.Unmount(scratch, 0)
	lim := runLimits()
	lim.MemoryKB = 20 * 1024
	lim.FileBytes = 0
	out, err := newSystemRunner([]string{scratch}).run(
		sh("head -c 40000000 /dev/zero > "+scratch+"/blob && sleep 2"), nil, lim, workDir(t), false)
	if err != nil {
		t.Fatal(err)
	}
	if classify(out, lim) != VerdictMemoryLimit {
		t.Fatalf("got %s (peak %d KB)", classify(out, lim), out.peakKB)
	}
}

func TestOutputLimit(t *testing.T) {
	needRoot(t)
	lim := runLimits()
	lim.OutputBytes = 1000
	out := runCmd(t, []string{"yes"}, nil, lim)
	if classify(out, lim) != VerdictOutputLimit || len(out.output) != 1000 || out.wallMs > 2000 {
		t.Fatalf("got %s, %d bytes, %dms", classify(out, lim), len(out.output), out.wallMs)
	}
}

func TestFileSizeLimit(t *testing.T) {
	needRoot(t)
	lim := runLimits()
	lim.FileBytes = 1000
	out := runCmd(t, sh("head -c 100000 /dev/zero > big"), nil, lim)
	if classify(out, lim) != VerdictRuntimeError {
		t.Fatalf("wrote past RLIMIT_FSIZE: %+v", out)
	}
}

// A child that outlives the submission and holds its stdout open must not
// stall the harness (30s in the spike before CAP_KILL reaping).
func TestOrphansAreReaped(t *testing.T) {
	needRoot(t)
	start := time.Now()
	out := runCmd(t, sh("sleep 30 & setsid sleep 30 & echo hi"), nil, runLimits())
	if string(out.output) != "hi\n" || time.Since(start) > 3*time.Second {
		t.Fatalf("got %q after %s", out.output, time.Since(start))
	}
	if left := len(liveSubmissionProcesses()); left != 0 {
		t.Fatalf("%d submission processes survived", left)
	}
}

// CPU burnt by a process the submission never waits for — a background
// child, or a double-forked orphan — is still the submission's CPU time.
func TestCPUOfUnreapedDescendantsCounts(t *testing.T) {
	needRoot(t)
	lim := runLimits()
	lim.CPUMs = 500
	out := runCmd(t, sh("(while :; do :; done) & sleep 1.5; echo 5"), nil, lim)
	if classify(out, lim) != VerdictTimeLimit || out.cpuMs < 1000 {
		t.Fatalf("got %s after %dms cpu", classify(out, lim), out.cpuMs)
	}
	out = runCmd(t, sh("sh -c '(while :; do :; done) &' ; sleep 1.5; echo 5"), nil, lim)
	if classify(out, lim) != VerdictTimeLimit || out.cpuMs < 1000 {
		t.Fatalf("double fork: got %s after %dms cpu", classify(out, lim), out.cpuMs)
	}
}

func TestRuntimeErrorExitCode(t *testing.T) {
	needRoot(t)
	out := runCmd(t, sh("exit 3"), nil, runLimits())
	if classify(out, runLimits()) != VerdictRuntimeError || *out.exitCode != 3 {
		t.Fatalf("got %+v", out)
	}
}

func TestJudgeEndToEnd(t *testing.T) {
	needRoot(t)
	dir := t.TempDir()
	write := func(name, body string) string {
		p := filepath.Join(dir, name)
		os.WriteFile(p, []byte(body), 0o600)
		return p
	}
	job := &Job{
		Nonce:         "abc",
		Work:          workDir(t),
		Compile:       sh(`printf '#!/bin/sh\nread a b; echo $((a+b))\n' > prog && chmod +x prog && echo compiled`),
		Run:           []string{"./prog"},
		CompileLimits: Limits{CPUMs: 10000, WallMs: 20000, OutputBytes: 65536, FileBytes: 1 << 20},
		RunLimits:     runLimits(),
		Compare:       CompareToken,
		Tests: []Test{
			{Name: "s1", Input: write("1.in", "1 2\n"), Answer: write("1.ans", "3\n")},
			{Name: "h1", Input: write("2.in", "-5 5\n"), Answer: write("2.ans", "0\n")},
		},
	}
	res := judge(job, newSystemRunner(nil))
	if res.Verdict != VerdictAccepted || len(res.Tests) != 2 || res.CompileOutput != "compiled\n" {
		t.Fatalf("got %+v", res)
	}

	job.Tests[1].Answer = write("2b.ans", "1\n")
	if res := judge(job, newSystemRunner(nil)); res.Verdict != VerdictWrongAnswer {
		t.Fatalf("got %+v", res)
	}

	job.Compile = sh("echo 'syntax error' >&2; exit 1")
	if res := judge(job, newSystemRunner(nil)); res.Verdict != VerdictCompileError ||
		res.CompileOutput != "syntax error\n" || len(res.Tests) != 0 {
		t.Fatalf("got %+v", res)
	}
}

func liveSubmissionProcesses() []procInfo {
	var live []procInfo
	for _, p := range submissionProcesses() {
		if !p.zombie {
			live = append(live, p)
		}
	}
	return live
}
