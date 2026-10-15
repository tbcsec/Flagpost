// Command harness is the Flagpost code judge's in-container supervisor
// (ADR-0042 and its amendment).
//
// One harness runs per judging, as PID 1 of a throwaway container with no
// network. The executor uploads it alongside a root-only job file, the
// submission's source and the test data, then reads exactly one JSON line —
// the result — back from the container log.
//
// The harness runs as uid 0 holding only CAP_SETUID, CAP_SETGID and CAP_KILL.
// Every command it runs on the submission's behalf (the compile step and each
// test) runs as the unprivileged submission user with no capabilities, so the
// submission can't read the job file or the hidden test data, write the
// harness, signal it, or forge its result line. That uid split — not a
// read-only filesystem — is the trust boundary inside the container.
//
// The harness re-executes itself as a short-lived launcher ("__exec") for each
// command: the launcher applies rlimits and drops to the submission user, then
// execs the real command, so the limits and the uid change happen in the child
// without relying on anything special between fork and exec.
package main

import (
	"encoding/json"
	"fmt"
	"os"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == launchArg {
		launch(os.Args[2:]) // never returns
	}
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: harness <job.json>")
		os.Exit(2)
	}
	emit(judgeFile(os.Args[1]))
}

// judgeFile loads the job and judges it. Any harness-side failure becomes an
// internal_error result rather than a missing one, so the executor always has
// a line to read.
func judgeFile(path string) Result {
	job, err := loadJob(path)
	if err != nil {
		res := Result{Verdict: VerdictInternalError, Error: err.Error()}
		if job != nil {
			res.Nonce = job.Nonce
		}
		return res
	}
	if job.UID != 0 {
		submissionUID = job.UID
	}
	return judge(job, newSystemRunner(job.Scratch))
}

func emit(res Result) {
	line, err := json.Marshal(res)
	if err != nil {
		line = []byte(fmt.Sprintf(
			`{"nonce":%q,"verdict":%q,"error":"encoding the result failed"}`,
			res.Nonce, VerdictInternalError,
		))
	}
	os.Stdout.Write(append(line, '\n'))
}
