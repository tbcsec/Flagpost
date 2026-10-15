package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
)

// Verdicts, as stored on a judging (ADR-0042 §4 / #448).
const (
	VerdictAccepted      = "accepted"
	VerdictWrongAnswer   = "wrong_answer"
	VerdictTimeLimit     = "time_limit"
	VerdictMemoryLimit   = "memory_limit"
	VerdictOutputLimit   = "output_limit"
	VerdictRuntimeError  = "runtime_error"
	VerdictCompileError  = "compile_error"
	VerdictInternalError = "internal_error"
)

// Limits bound one command. Zero means "not enforced" for MemoryKB (the
// compile step is bounded by the container's memory cap instead).
type Limits struct {
	CPUMs       int64 `json:"cpu_ms"`
	WallMs      int64 `json:"wall_ms"`
	MemoryKB    int64 `json:"memory_kb"`
	OutputBytes int64 `json:"output_bytes"`
	FileBytes   int64 `json:"file_bytes"`
}

// Test is one test case: paths to its input and expected output, both in the
// root-only job directory.
type Test struct {
	Name   string `json:"name"`
	Input  string `json:"input"`
	Answer string `json:"answer"`
	// ShowOutput returns the submission's output for this test (capped), so a
	// competitor can compare it with an example's expected output. The executor
	// sets it only on example tests that run before any hidden test, so the
	// output can never reflect hidden input.
	ShowOutput bool `json:"show_output"`
}

// Job is the root-only job file the executor uploads. Placeholders in the
// commands ({source}, {work}) are already substituted by the executor.
type Job struct {
	Nonce string `json:"nonce"`
	Work  string `json:"work"`
	// Scratch lists every writable tmpfs mount (/dev/shm included). Files a
	// submission writes there live in memory, so their growth during a test
	// counts against its memory limit — otherwise a submission could hold data
	// in files to evade it.
	Scratch       []string `json:"scratch"`
	Compile       []string `json:"compile"`
	Run           []string `json:"run"`
	CompileLimits Limits   `json:"compile_limits"`
	RunLimits     Limits   `json:"run_limits"`
	Compare       string   `json:"compare"`
	Tolerance     float64  `json:"tolerance"`
	// CaseInsensitive compares letters regardless of case (ASCII only).
	CaseInsensitive bool   `json:"case_insensitive"`
	Tests           []Test `json:"tests"`
	// RunAll keeps going past a failing test (an author's reference-solution
	// check); otherwise judging stops at the first failure.
	RunAll bool `json:"run_all"`
	// UID is the user this judging's submission runs as; 0 means the default.
	UID int `json:"uid"`
}

// minSubmissionUID keeps the submission off root and the system accounts.
const minSubmissionUID = 1000

// TestResult is reported for every test that ran. It carries output only for
// a test marked ShowOutput: a submission's output on a hidden test could echo
// the hidden input back to the competitor, and its stderr is never kept.
type TestResult struct {
	Name     string  `json:"name"`
	Verdict  string  `json:"verdict"`
	TimeMs   int64   `json:"time_ms"`
	WallMs   int64   `json:"wall_ms"`
	MemoryKB int64   `json:"memory_kb"`
	ExitCode *int    `json:"exit_code"`
	Signal   *int    `json:"signal"`
	Output   *string `json:"output,omitempty"`
}

// Result is the single line the harness prints. The nonce comes from the
// root-only job file, so a line without it didn't come from this harness.
type Result struct {
	Nonce         string       `json:"nonce"`
	Verdict       string       `json:"verdict"`
	CompileOutput string       `json:"compile_output"`
	CompileTimeMs int64        `json:"compile_time_ms"`
	Tests         []TestResult `json:"tests"`
	Error         string       `json:"error,omitempty"`
}

func loadJob(path string) (*Job, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading the job file: %w", err)
	}
	var job Job
	if err := json.Unmarshal(raw, &job); err != nil {
		return nil, fmt.Errorf("parsing the job file: %w", err)
	}
	if err := job.validate(); err != nil {
		return &job, err
	}
	return &job, nil
}

func (j *Job) validate() error {
	switch {
	case j.Nonce == "":
		return errors.New("job has no nonce")
	case len(j.Run) == 0:
		return errors.New("job has no run command")
	case j.Work == "":
		return errors.New("job has no work directory")
	case len(j.Tests) == 0:
		return errors.New("job has no tests")
	case j.RunLimits.CPUMs <= 0 || j.RunLimits.WallMs <= 0:
		return errors.New("job has no run time limit")
	case j.RunLimits.OutputBytes <= 0:
		return errors.New("job has no output limit")
	case j.UID != 0 && j.UID < minSubmissionUID:
		return fmt.Errorf("job's submission uid %d is a system uid", j.UID)
	}
	switch j.Compare {
	case CompareToken, CompareExact, CompareFloat:
	default:
		return fmt.Errorf("unknown compare mode %q", j.Compare)
	}
	return nil
}
