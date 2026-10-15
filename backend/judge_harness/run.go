package main

import (
	"bufio"
	"bytes"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// submissionUID is the unprivileged user every submission command runs as. It
// owns the scratch tmpfs and nothing else. The executor gives each judging its
// own (Job.UID), because the kernel counts a uid's processes host-wide: with a
// shared uid, one judging's fork-heavy submission would eat into a concurrent
// judging's process cap and fail its compiler. 65534 ("nobody") is the default.
var submissionUID = 65534

// launchArg is the hidden first argument that turns the harness into the
// per-command launcher.
const launchArg = "__exec"

// submissionMaxProcs caps the submission user's processes and threads
// (RLIMIT_NPROC). It must stay well below the container's pid limit (the
// executor sets 256): otherwise a fork bomb fills the container and the
// harness's own runtime can't start a thread, dying without a verdict. With
// this cap the submission's fork() fails first and the harness keeps its
// headroom. (The kernel counts the uid's processes host-wide, so a host
// running many other "nobody" processes would eat into it.)
const submissionMaxProcs = 128

// RLIMIT_NPROC isn't exported by package syscall; 6 on every Linux arch.
const rlimitNPROC = 6

// PR_SET_CHILD_SUBREAPER, likewise.
const prSetChildSubreaper = 36

const (
	// How often the memory watcher samples the submission's resident set.
	memoryPollInterval = 10 * time.Millisecond
	// After the command exits, how long to wait for its output pipe to close
	// once every leftover submission process has been killed.
	drainTimeout = 2 * time.Second
)

// outcome is what running one command produced.
type outcome struct {
	cpuMs          int64
	wallMs         int64
	peakKB         int64
	exitCode       *int
	signal         *int
	wallTimedOut   bool
	outputExceeded bool
	memoryExceeded bool
	output         []byte
}

// runner abstracts process execution so judge() is testable without spawning.
type runner interface {
	run(argv []string, stdin *os.File, lim Limits, work string, compile bool) (*outcome, error)
}

type systemRunner struct {
	self    string
	scratch []string
}

func newSystemRunner(scratch []string) *systemRunner {
	// Become a child subreaper: a process the submission orphans (a background
	// child, a double fork) is re-parented to the harness rather than to the
	// container's init, so the harness reaps it — and with it, its CPU time.
	// The harness is PID 1 in the judge container, where this is implicit; it
	// matters for running the harness anywhere else (its tests).
	syscall.RawSyscall(syscall.SYS_PRCTL, prSetChildSubreaper, 1, 0)
	self, err := os.Executable()
	if err != nil {
		self = "/proc/self/exe"
	}
	return &systemRunner{self: self, scratch: scratch}
}

// run executes argv as the submission user under lim. For the compile step,
// stderr is merged into the captured output and exceeding the output cap only
// truncates; for a test, stderr is discarded (it could echo hidden input) and
// exceeding the cap is a verdict, so the command is killed.
func (s *systemRunner) run(argv []string, stdin *os.File, lim Limits, work string, compile bool) (*outcome, error) {
	// Nothing from an earlier command may still be running: leftovers would
	// count against this one's memory and could hold its output pipe open.
	killSubmissionProcesses(true)

	r, w, err := os.Pipe()
	if err != nil {
		return nil, err
	}
	defer r.Close()

	cpuSoft := (lim.CPUMs + 999) / 1000 // seconds, rounded up
	if cpuSoft < 1 {
		cpuSoft = 1
	}
	// One second of slack past the limit: a submission that runs a little
	// over is still measured (and gets time_limit from the measurement) rather
	// than killed at exactly the limit, and SIGKILL follows one second later.
	cpuSoft++
	args := []string{
		launchArg,
		strconv.Itoa(submissionUID),
		strconv.FormatInt(cpuSoft, 10),
		strconv.FormatInt(lim.FileBytes, 10),
		work,
	}
	args = append(args, argv...)

	cmd := exec.Command(s.self, args...)
	cmd.Env = submissionEnv(work)
	cmd.Stdin = stdin // nil = /dev/null
	cmd.Stdout = w    // an *os.File: passed straight through, no copy goroutine
	if compile {
		cmd.Stderr = w
	} else {
		devnull, err := os.OpenFile(os.DevNull, os.O_WRONLY, 0)
		if err != nil {
			w.Close()
			return nil, err
		}
		defer devnull.Close()
		cmd.Stderr = devnull
	}
	// Own process group, so the whole tree can be signalled; and killed with
	// the harness should the harness itself die.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}

	out := &outcome{}
	var wallTimedOut, outputExceeded, memoryExceeded atomic.Bool
	var peakKB atomic.Int64

	start := time.Now()
	if err := cmd.Start(); err != nil {
		w.Close()
		return nil, err
	}
	w.Close() // the child holds the only write end now
	pgid := cmd.Process.Pid
	killTree := func() {
		syscall.Kill(-pgid, syscall.SIGKILL)
		killSubmissionProcesses(false)
	}

	// Output reader, capped: never buffer more than the limit (plus one byte
	// to know it was exceeded).
	var output bytes.Buffer
	readDone := make(chan struct{})
	go func() {
		defer close(readDone)
		n, _ := io.CopyN(&output, r, lim.OutputBytes+1)
		if n > lim.OutputBytes {
			outputExceeded.Store(true)
			if !compile {
				killTree()
			}
			// Keep draining for the compile step so the compiler isn't blocked
			// on a full pipe; the captured text is already truncated.
			io.Copy(io.Discard, r)
		}
	}()

	timer := time.AfterFunc(time.Duration(lim.WallMs)*time.Millisecond, func() {
		wallTimedOut.Store(true)
		killTree()
	})

	stopWatch := make(chan struct{})
	var watchWG sync.WaitGroup
	if lim.MemoryKB > 0 {
		// Scratch already in use (the compiled program, earlier tests' files)
		// isn't this test's; only growth from here on counts.
		scratchBase := scratchUsedKB(s.scratch)
		watchWG.Add(1)
		go func() {
			defer watchWG.Done()
			ticker := time.NewTicker(memoryPollInterval)
			defer ticker.Stop()
			for {
				select {
				case <-stopWatch:
					return
				case <-ticker.C:
					used := submissionRSSKB() + max(0, scratchUsedKB(s.scratch)-scratchBase)
					if used > peakKB.Load() {
						peakKB.Store(used)
					}
					if used > lim.MemoryKB {
						memoryExceeded.Store(true)
						killTree()
						return
					}
				}
			}
		}()
	}

	waitErr := cmd.Wait()
	out.wallMs = time.Since(start).Milliseconds()
	timer.Stop()
	close(stopWatch)
	watchWG.Wait()

	// The command is gone, but anything it forked may live on (possibly in a
	// new session, out of reach of the process group) holding the pipe open.
	// Kill every submission process, reap the zombies, then drain. What the
	// reaped processes used is the submission's too: CPU burnt in a child the
	// command never waited for would otherwise escape the time limit.
	descendants := killSubmissionProcesses(true)
	select {
	case <-readDone:
	case <-time.After(drainTimeout):
	}

	var exitErr *exec.ExitError
	if waitErr != nil && !errors.As(waitErr, &exitErr) {
		return nil, waitErr
	}
	state := cmd.ProcessState
	if ru, ok := state.SysUsage().(*syscall.Rusage); ok && ru != nil {
		out.cpuMs = tvMs(ru.Utime) + tvMs(ru.Stime)
		out.peakKB = ru.Maxrss // KB on Linux
	}
	out.cpuMs += descendants.cpuMs
	out.peakKB = max(out.peakKB, descendants.maxRSSKB)
	if p := peakKB.Load(); p > out.peakKB {
		out.peakKB = p
	}
	if ws, ok := state.Sys().(syscall.WaitStatus); ok {
		if ws.Signaled() {
			sig := int(ws.Signal())
			out.signal = &sig
		} else {
			code := ws.ExitStatus()
			out.exitCode = &code
		}
	}
	out.wallTimedOut = wallTimedOut.Load()
	out.outputExceeded = outputExceeded.Load()
	out.memoryExceeded = memoryExceeded.Load()
	out.output = output.Bytes()
	if int64(len(out.output)) > lim.OutputBytes {
		out.output = out.output[:lim.OutputBytes]
	}
	return out, nil
}

func tvMs(tv syscall.Timeval) int64 {
	return tv.Sec*1000 + int64(tv.Usec)/1000
}

// submissionEnv is the harness's environment (the image's, so PATH, JAVA_HOME
// and the like are right) with HOME and TMPDIR pointed at writable scratch —
// the submission user has no home directory.
func submissionEnv(work string) []string {
	env := make([]string, 0, len(os.Environ())+2)
	for _, kv := range os.Environ() {
		if strings.HasPrefix(kv, "HOME=") || strings.HasPrefix(kv, "TMPDIR=") {
			continue
		}
		env = append(env, kv)
	}
	return append(env, "HOME="+work, "TMPDIR=/tmp")
}

// --- the submission's processes -------------------------------------------------

type procInfo struct {
	pid    int
	zombie bool
	rssKB  int64
}

// submissionProcesses lists every process owned by the submission user.
func submissionProcesses() []procInfo {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil
	}
	var procs []procInfo
	for _, e := range entries {
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		if info, ok := readProcStatus(pid); ok {
			procs = append(procs, info)
		}
	}
	return procs
}

func readProcStatus(pid int) (procInfo, bool) {
	f, err := os.Open(filepath.Join("/proc", strconv.Itoa(pid), "status"))
	if err != nil {
		return procInfo{}, false
	}
	defer f.Close()
	info := procInfo{pid: pid}
	owned := false
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := sc.Text()
		switch {
		case strings.HasPrefix(line, "State:"):
			info.zombie = strings.Contains(line, "Z (zombie)")
		case strings.HasPrefix(line, "Uid:"):
			// Real, effective, saved, filesystem: any of them being the
			// submission user means it's the submission's process.
			for _, f := range strings.Fields(line)[1:] {
				if f == strconv.Itoa(submissionUID) {
					owned = true
				}
			}
		case strings.HasPrefix(line, "VmRSS:"):
			fields := strings.Fields(line)
			if len(fields) >= 2 {
				info.rssKB, _ = strconv.ParseInt(fields[1], 10, 64)
			}
		}
	}
	return info, owned
}

// submissionRSSKB is the resident memory of all the submission's processes.
func submissionRSSKB() int64 {
	var total int64
	for _, p := range submissionProcesses() {
		if !p.zombie {
			total += p.rssKB
		}
	}
	return total
}

// scratchUsedKB is how much of the scratch tmpfs mounts is in use.
func scratchUsedKB(dirs []string) int64 {
	var total int64
	for _, dir := range dirs {
		var st syscall.Statfs_t
		if syscall.Statfs(dir, &st) == nil {
			total += int64(st.Blocks-st.Bfree) * int64(st.Bsize) / 1024
		}
	}
	return total
}

// usage is what reaped processes consumed.
type usage struct {
	cpuMs    int64
	maxRSSKB int64
}

func (u *usage) add(ru *syscall.Rusage) {
	u.cpuMs += tvMs(ru.Utime) + tvMs(ru.Stime)
	u.maxRSSKB = max(u.maxRSSKB, ru.Maxrss)
}

// killSubmissionProcesses SIGKILLs every live submission process until none
// remain — including any that left the process group with setsid(). CAP_KILL
// is what lets the root harness signal another uid.
//
// With reap, it also reaps the zombies re-parented to the harness (it is a
// child subreaper), until none are left, so they don't accumulate against the
// container's pid limit — and returns what they used. Each reaped process's
// rusage covers it and the children it waited for itself; everything else is
// re-parented to the harness and reaped here in turn, so between this and the
// command's own rusage, every process the submission ran is counted once.
// Reap must only be used when no exec.Cmd is outstanding, or it could steal
// the command's exit status.
func killSubmissionProcesses(reap bool) usage {
	var used usage
	for i := 0; i < 200; i++ {
		live, zombies := 0, 0
		for _, p := range submissionProcesses() {
			if p.zombie {
				zombies++
				continue
			}
			live++
			syscall.Kill(p.pid, syscall.SIGKILL)
		}
		if reap {
			reapZombies(&used)
		}
		if live == 0 && (!reap || zombies == 0) {
			return used
		}
		time.Sleep(time.Millisecond)
	}
	return used
}

func reapZombies(used *usage) {
	for {
		var ws syscall.WaitStatus
		var ru syscall.Rusage
		pid, err := syscall.Wait4(-1, &ws, syscall.WNOHANG, &ru)
		if pid <= 0 || err != nil {
			return
		}
		used.add(&ru)
	}
}

// --- the launcher -----------------------------------------------------------------

// launch runs in the child: apply limits, become the submission user, and exec
// the command. Args: <uid> <cpu seconds> <file size bytes> <work dir> <argv...>.
// It never returns.
func launch(args []string) {
	if len(args) < 5 {
		launchFail("launcher: bad arguments")
	}
	uid, err0 := strconv.Atoi(args[0])
	cpu, err1 := strconv.ParseUint(args[1], 10, 64)
	fsize, err2 := strconv.ParseUint(args[2], 10, 64)
	if err0 != nil || err1 != nil || err2 != nil || uid < minSubmissionUID {
		launchFail("launcher: bad limits")
	}
	work, argv := args[3], args[4:]

	// Lowering limits needs no privilege. The CPU limit's hard ceiling is one
	// second past the soft one: SIGXCPU first, then SIGKILL.
	must(syscall.Setrlimit(syscall.RLIMIT_CPU, &syscall.Rlimit{Cur: cpu, Max: cpu + 1}))
	if fsize > 0 {
		must(syscall.Setrlimit(syscall.RLIMIT_FSIZE, &syscall.Rlimit{Cur: fsize, Max: fsize}))
	}
	must(syscall.Setrlimit(syscall.RLIMIT_CORE, &syscall.Rlimit{Cur: 0, Max: 0}))
	must(syscall.Setrlimit(rlimitNPROC, &syscall.Rlimit{Cur: submissionMaxProcs, Max: submissionMaxProcs}))
	// Should the container's memory cap be hit, the kernel's OOM killer must
	// choose the submission, never the harness. Raising one's own score needs
	// no privilege.
	_ = os.WriteFile("/proc/self/oom_score_adj", []byte("1000"), 0)

	// Drop to the submission user: supplementary groups first, then gid, then
	// uid (after which the process holds no capabilities at all).
	must(syscall.Setgroups([]int{}))
	must(syscall.Setresgid(uid, uid, uid))
	must(syscall.Setresuid(uid, uid, uid))
	// chdir after the drop: root has no DAC override into the scratch dir.
	must(os.Chdir(work))

	path, err := lookPath(argv[0])
	if err != nil {
		launchFail(err.Error())
	}
	err = syscall.Exec(path, argv, os.Environ())
	launchFail("exec " + argv[0] + ": " + err.Error())
}

func must(err error) {
	if err != nil {
		launchFail("launcher: " + err.Error())
	}
}

func launchFail(msg string) {
	os.Stderr.WriteString(msg + "\n")
	os.Exit(127)
}

func lookPath(name string) (string, error) {
	if strings.Contains(name, "/") {
		return name, nil
	}
	return exec.LookPath(name)
}
