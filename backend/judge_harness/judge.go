package main

import (
	"os"
	"syscall"
)

// compileOutputLimit bounds the compiler message returned to the competitor.
const compileOutputLimit = 16 * 1024

// shownOutputLimit bounds the output returned for an example test.
const shownOutputLimit = 16 * 1024

// judge compiles once, then runs the tests in order — samples first, as the
// executor lists them — stopping at the first that doesn't pass (ADR-0042 §5,
// "lazy judging"). The overall verdict is that test's, or accepted. A job with
// RunAll (an author's reference-solution check, #450) runs every test anyway,
// so the author sees each one's result; the verdict is still the first
// failure's.
func judge(job *Job, r runner) Result {
	res := Result{Nonce: job.Nonce, Tests: []TestResult{}}

	if len(job.Compile) > 0 {
		out, err := r.run(job.Compile, nil, job.CompileLimits, job.Work, true)
		if err != nil {
			return internalError(res, "running the compiler: "+err.Error())
		}
		res.CompileTimeMs = out.cpuMs
		res.CompileOutput = truncateText(out.output, compileOutputLimit)
		if out.wallTimedOut || out.cpuMs > job.CompileLimits.CPUMs {
			res.Verdict = VerdictCompileError
			res.CompileOutput = joinNote(res.CompileOutput, "Compilation took too long.")
			return res
		}
		if out.memoryExceeded {
			res.Verdict = VerdictCompileError
			res.CompileOutput = joinNote(res.CompileOutput, "Compilation used too much memory.")
			return res
		}
		if out.signal != nil || (out.exitCode != nil && *out.exitCode != 0) {
			res.Verdict = VerdictCompileError
			return res
		}
	}

	for _, t := range job.Tests {
		tr, err := runTest(job, t, r)
		if err != nil {
			return internalError(res, "running test "+t.Name+": "+err.Error())
		}
		res.Tests = append(res.Tests, tr)
		if tr.Verdict != VerdictAccepted {
			if res.Verdict == "" {
				res.Verdict = tr.Verdict
			}
			if !job.RunAll {
				return res
			}
		}
	}
	if res.Verdict == "" {
		res.Verdict = VerdictAccepted
	}
	return res
}

func runTest(job *Job, t Test, r runner) (TestResult, error) {
	// Opened by the harness (root, the only reader of the job directory) and
	// handed to the submission as its stdin: the submission can read this
	// input and nothing else.
	in, err := os.Open(t.Input)
	if err != nil {
		return TestResult{}, err
	}
	defer in.Close()

	out, err := r.run(job.Run, in, job.RunLimits, job.Work, false)
	if err != nil {
		return TestResult{}, err
	}
	tr := TestResult{
		Name:     t.Name,
		TimeMs:   out.cpuMs,
		WallMs:   out.wallMs,
		MemoryKB: out.peakKB,
		ExitCode: out.exitCode,
		Signal:   out.signal,
	}
	if t.ShowOutput {
		shown := truncateText(out.output, shownOutputLimit)
		tr.Output = &shown
	}
	tr.Verdict = classify(out, job.RunLimits)
	if tr.Verdict != VerdictAccepted {
		return tr, nil
	}
	answer, err := os.ReadFile(t.Answer)
	if err != nil {
		return TestResult{}, err
	}
	if !compareOutput(out.output, answer, job.Compare, job.Tolerance) {
		tr.Verdict = VerdictWrongAnswer
	}
	return tr, nil
}

// classify turns how a run ended into a verdict, before the output is
// compared. Order matters: a submission killed for running out of time is a
// time limit even though it also died of a signal.
func classify(out *outcome, lim Limits) string {
	killedByCPULimit := out.signal != nil &&
		(*out.signal == int(syscall.SIGXCPU) ||
			(*out.signal == int(syscall.SIGKILL) && out.cpuMs >= lim.CPUMs))
	switch {
	case out.wallTimedOut || out.cpuMs > lim.CPUMs || killedByCPULimit:
		return VerdictTimeLimit
	case out.outputExceeded:
		return VerdictOutputLimit
	case out.memoryExceeded || (lim.MemoryKB > 0 && out.peakKB > lim.MemoryKB):
		return VerdictMemoryLimit
	case out.signal != nil || (out.exitCode != nil && *out.exitCode != 0):
		return VerdictRuntimeError
	}
	return VerdictAccepted
}

func internalError(res Result, msg string) Result {
	res.Verdict = VerdictInternalError
	res.Error = msg
	return res
}

func truncateText(b []byte, limit int) string {
	if len(b) > limit {
		return string(b[:limit]) + "\n… (truncated)"
	}
	return string(b)
}

func joinNote(text, note string) string {
	if text == "" {
		return note
	}
	return text + "\n" + note
}
