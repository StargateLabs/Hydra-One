"""serve/server.py - plan v0.3 P8: OpenAI and Anthropic endpoints over any engine that maps token ids to tokens.

    python -m serve.server --engine mock --port 8095            (a scripted engine, for clients and tests)
    python -m serve.server --engine strata --config strata.json --port 8080   (the real engine, resident)

Endpoints: POST /v1/chat/completions (OpenAI, stream and non-stream), POST /v1/messages (Anthropic, stream and
non-stream), GET /v1/models, GET /models, GET /props, GET /slots, GET /health, GET /mcp. One sequence at a time behind a FIFO (plan: one resident sequence).
Tools from MCP servers (serve/mcp.py, `"mcp_servers"` in the config or --mcp-config) are offered only to requests that
ask for them with `"strata_mcp": true` - the web app does; other clients see exactly the API they always saw.
Images (optional, when the config has a "vision" entry): OpenAI image_url parts and Anthropic image blocks (base64
data, http(s) URLs or local file paths) go through `strata-vision` (the model's mmproj file) and reach the engine as
embeddings (`GENI`).  JPEG/PNG/BMP/GIF go straight in; WebP, TIFF, AVIF, ... (agents like omp send WebP) are
converted to PNG first with Pillow.
Requests whose prompt plus max tokens exceed the engine's context are REJECTED with 400, never truncated.
An unset (or 0, or -1) max tokens means "unlimited": whatever the prompt leaves of the context.

The engine boundary is `Engine.generate(prompt_ids, max_new, sampling, cancel) -> iterator of token ids`.
`StrataEngine` keeps one `strata --serve` process resident (weights, expert arena and VRAM tier load once) and
talks to it over stdin/stdout; `MockEngine` is a scripted stand-in that makes every API path testable without a GPU.
"""
from __future__ import annotations

import argparse
import collections
import base64
import hashlib
import hmac
import codecs
import ctypes
import json
import os
import pathlib
import queue
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Protocol
from urllib.parse import parse_qs, urlsplit

DATA = pathlib.Path(__file__).resolve().parents[1].parent / "Strata-data"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))   # run as a script (run-<model>.bat) as well as a module
from serve.frontend import (ChatTemplate, Event, OutputParser, anthropic_to_messages,  # noqa: E402
                            images_of, openai_to_messages)
from serve.mcp import McpCancelled, hub_from_config  # noqa: E402
from serve.winjob import contain  # noqa: E402
from serve.structured import StructuredOutputError, prepare_format, validated_json  # noqa: E402

IM_END = "<|im_end|>"
IMAGE_PAD = "<|image_pad|>"
VISION_START = "<|vision_start|>"
# #123: what closes the thinking when it reaches reasoning_budget_tokens (the model's own end-of-thinking tag after it)
REASONING_WRAP_UP = "\n\nI have thought about this long enough; time to give my answer.\n</think>\n\n"
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")
CTX_SLACK = 8               # `strata --serve` rejects prompt + max_new + 8 > context: keep the same margin here
# The live tok/s is a rate over a window, not a mean since the first token: a mean reads ~1/elapsed at the first
# token (the Monitor showed five-digit numbers) and then undershoots for the first second of every answer.
RATE_WINDOW_S = 2.0
RATE_MIN_SPAN_S = 0.25      # younger than this there is no rate yet: the mean so far, with the span floored here
# #481: a running request whose engine prints nothing (no T, PP or any other line) for this long has lost step with the
# server (the engine's main thread waits, untimed, for its next command): the engine is ended and the request fails;
# the next request starts it again.  The config's "engine_silence_s" sets it (0: wait forever, as before).
ENGINE_SILENCE_S = 300.0
# ... except while a prompt is read: a PP line comes once per chunk (up to 32768 tokens with --prefill auto, issue
# #282), and the slowest PCs read ~100 tok/s, so a first chunk can take minutes before the first line.  Until the first
# PP the wait adds the chunk's tokens at PP_FLOOR_TOK_S; after one, a chunk may take PP_SLACK x the last one's time.
PP_CHUNK_MAX = 32768
PP_FLOOR_TOK_S = 50.0
PP_SLACK = 3.0


# ------------------------------------------------------------------------------------------------ engines
class Engine(Protocol):
    max_context: int
    def generate(self, ids: list[int], max_new: int, sampling: dict, cancel: threading.Event) -> Iterator[int]: ...


class MockEngine:
    """Replays a scripted completion (text) as token ids, one per step, then the end-of-turn token.  Given a list of
    scripts, each request gets the next one and the last one repeats (a tool call, then the answer after it)."""

    def __init__(self, tokenizer, script: str | list[str], max_context: int = 32768, delay_s: float = 0.0):
        self.tok, self.max_context, self.delay = tokenizer, max_context, delay_s
        end = tokenizer.encode(IM_END, parse_special=True)
        self.scripts = [tokenizer.encode(x, parse_special=True) + end for x in ([script] if isinstance(script, str)
                                                                                 else script)]
        self.script, self.turns = self.scripts[0], 0
        self.last_prompt: list[int] = []

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        self.last_prompt = list(ids)
        self.last_embeddings = embeddings
        if len(self.scripts) > 1:
            self.script = self.scripts[min(self.turns, len(self.scripts) - 1)]
            self.turns += 1
        for t in self.script[:max_new]:
            if cancel.is_set():
                return
            if self.delay:
                time.sleep(self.delay)
            yield t


class EngineDied(RuntimeError):
    """The engine process ended in the middle of a request (issue #27: on Linux, the out-of-memory killer)."""


class EngineStarting(RuntimeError):
    """The engine is (re)starting and has not said READY yet (#344): no context size to plan a request with - a 503,
    not a 400 about the prompt."""


class ModelBusy(RuntimeError):
    """Explicit model controls must not interrupt active or queued requests."""


class EngineSilent(EngineDied):
    """#481: the engine said nothing for too long during a request (or never acknowledged a STOP): the two sides lost
    step - the engine waiting for its next command, the server for this request's end - and the server ended it.  An
    EngineDied, so the request ends with an error and the next one starts the engine again."""


class EngineStuck(RuntimeError):
    """The engine process did not end after QUIT, terminate and kill: the server keeps it (and says so) rather than
    reporting its GPU and RAM as given back."""


class GpuBusy(RuntimeError):
    """The model is unloaded and the GPU has less free VRAM than min_free_vram_mib: something else (a game, another
    model server) is using it, so the engine is not started into the little that is left."""


ENGINE_REQUEST = re.compile(
    # "+ 12288 of 98179 read": a request cancelled while its prompt was read (#471)
    r"prompt (?P<prompt>\d+) tokens = (?P<reused>\d+) reused \+ \d+(?: of \d+)? read in (?P<read>[\d.]+) ms "
    r"\((?P<pp>[\d.]+) tok/s\), "
    r"(?P<gen>\d+) generated in (?P<gen_ms>[\d.]+) ms \((?P<tg>[\d.]+) tok/s\)")


_echoing: set[str] = set()      # the logs echo_requests already follows (restart() runs StrataEngine.__init__ again)

DRAFT_HEAD_FAIL = "the draft head does not fit"
DRAFT_HEAD_HINT = ("a smaller draft vocabulary needs less VRAM: --draft-vocab cyrillic (English, code and the Cyrillic "
                   "script) or --draft-vocab en (English and code, ~215 MiB less than the default). Start once with "
                   "it - START-HERE.bat --draft-vocab en (Windows) or ./setup.sh --draft-vocab en - and the model "
                   "keeps it; or a smaller --context in setup.")


def start_failure_hint(log: str | None, offset: int) -> str:
    """#474: what to change when the engine stopped at the start because the MTP draft head did not fit the VRAM
    left: the engine's own `strata mtp:` lines after that failure (0.1.36+: what it needs, what is free, the smaller
    subsets), else the same advice in words for an older engine.  "" for any other failure: the log says why."""
    if not log:
        return ""
    try:
        with open(log, "rb") as f:
            f.seek(offset)
            text = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""
    if DRAFT_HEAD_FAIL not in text:
        return ""
    said = [x.strip()[len("strata mtp: "):] for x in text.splitlines()
            if x.strip().startswith("strata mtp: ") and ("draft head over" in x or "hint:" in x)]
    return ". mtp: " + DRAFT_HEAD_FAIL + ". " + (" ".join(said) if said else "Hint: " + DRAFT_HEAD_HINT)


def start_log_tail(log: str | None, offset: int, n: int = 20) -> str:
    """#496: the last n lines this start wrote to the engine log, for the error when the engine ended before READY -
    whatever the failure, the engine's own reason is in them (people posted the traceback without the log).  "" when
    there is no log or nothing in it from this start."""
    if not log:
        return ""
    try:
        with open(log, "rb") as f:
            f.seek(0, 2)
            start = max(offset, f.tell() - 64 * 1024)   # enough for 20 lines, never an earlier start's
            f.seek(start)
            text = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""
    lines = text.splitlines()[1 if start > offset else 0:]   # not a line cut in half
    lines = [x.rstrip() for x in lines if x.strip()][-n:]
    if not lines:
        return ""
    return "\nthe engine log's last lines:\n" + "\n".join("  " + x for x in lines)


def echo_requests(log_path: str, offset: int) -> None:
    """STRATA_REQUEST_LINES=1: one stdout line per finished request, from the engine's own summary in its log.

    The engine's stderr goes to the log file (the start narrator reads it), so a supervisor that only sees this
    process's output - a tray, llama-swap - has no per-request numbers. This re-states the engine's line with the
    total the two times make: `request prompt P cached C output O prompt_read R ms total S ms prefill X tok/s decode Y
    tok/s` (prompt_read: the time the engine spent reading the prompt's new tokens, not a time to first token).
    """
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue
            m = ENGINE_REQUEST.search(line)
            if m:
                read_ms, gen_ms = float(m["read"]), float(m["gen_ms"])
                print("[strata] request prompt %s cached %s output %s prompt_read %.0f ms total %.0f ms prefill %s "
                      "tok/s decode %s tok/s" % (m["prompt"], m["reused"], m["gen"], read_ms, read_ms + gen_ms, m["pp"],
                                                 m["tg"]), flush=True)


def experts_loading_words(args: list, size: str) -> str:
    """#505: what the start does with the experts, by the engine's flags (generate.cpp's option parsing): a RAM budget
    copies the hottest N GiB into RAM (--resident-budget-gib), the resident low-RAM mode the ones the GPU does not hold
    (--resident-experts), plain --mmap-experts reads them from the model files through the OS file cache (nothing is
    loaded into RAM up front); otherwise all of them go into RAM."""
    if "--resident-budget-gib" in args:
        try:
            n = f"up to {float(args[args.index('--resident-budget-gib') + 1]):g} GiB"
        except (IndexError, ValueError):
            n = "a RAM budget"
        return (f"loading the most-used experts into RAM ({n}; the rest are read from the model files as needed) "
                "and locking part of them for the GPU.")
    if "--resident-experts" in args:
        return (f"loading the experts the GPU does not hold into RAM (of {size}) and locking part of them for the "
                "GPU.")
    if "--mmap-experts" in args:
        return (f"mapping the experts from the model files ({size}, --mmap-experts): they are not loaded into RAM - "
                "the OS file cache reads them as the GPU's expert cache fills and as requests need them.")
    return f"loading the experts into RAM ({size}) and locking part of them for the GPU."


def narrate_start(log_path: str, offset: int, args: list, done: threading.Event, heartbeat=20.0) -> None:
    """While the engine starts, say in the server window what it is doing, from its log: the start reads tens of GB
    into RAM and locks part of it for the GPU, and on many PCs everything is slow or frozen for a minute or more -
    people closed the window thinking it had hung.  The warning comes at that step, not after it."""
    gb = 0.0
    if "--native" in args:                              # about the size of the experts it will read
        try:
            gb = os.path.getsize(args[args.index("--native") + 1]) / 1e9
        except (OSError, IndexError):
            pass
    size = f"about {gb:.0f} GB" if gb >= 1 else "tens of GB"
    loading = experts_loading_words(args, size)
    t0 = last = time.time()
    said = set()

    def say(key, text):
        nonlocal last
        if key not in said:
            said.add(key)
            last = time.time()
            print(text, flush=True)

    say("weights", "[strata] starting the engine: reading the model's weights ...")
    pos = offset
    while not done.wait(0.5):
        try:
            with open(log_path, "rb") as f:
                f.seek(pos)
                chunk = f.read()
        except OSError:
            chunk = b""
        if chunk.count(b"\n"):
            cut = chunk.rfind(b"\n") + 1
            pos += cut
            for line in chunk[:cut].decode("utf-8", "replace").splitlines():
                if "PLE on" in line or "expert arena:" in line or "experts via mmap" in line:   # #505: mapped
                    say("arena", f"[strata] {loading}\n"
                                 "         YOUR PC CAN BE SLOW OR STOP RESPONDING FOR 1-3 MINUTES NOW - this is normal.\n"
                                 "         Please wait and don't close this window; the browser opens when it is ready.")
                elif " loaded " in line and "GiB at" in line:
                    say("loaded", "[strata] experts loaded: " + line.split(" loaded ", 1)[1].strip() +
                        f" ({time.time() - t0:.0f} s so far)")
                elif "expert cache " in line and " slots, " in line and "auto" not in line:
                    n = line.split("expert cache ", 1)[1].split(";")[0].replace(" slots,", " experts,").strip()
                    say("cache", f"[strata] filling the GPU's expert cache ({n}) ...")
                elif "session is up" in line:
                    say("up", "[strata] almost ready ...")
        if time.time() - last > heartbeat:
            last = time.time()
            print(f"[strata] still starting ({time.time() - t0:.0f} s) - please wait ...", flush=True)


class StrataEngine:
    """The resident engine: `strata --serve` reads `GEN <max_new> <ids>` lines and streams `T <id>` lines, then
    `DONE ...`.  Requests are serialized by the service's FIFO, so one pipe is enough.

    Per-request sampling rides the same line as engine-side keys between max_new and the ids
    (`temperature=F top_p=F top_k=N seed=N`, the engine's own spelling).  An absent temperature keeps the
    engine's default, which is greedy; `temperature=0` means the same thing, so it is not forwarded.
    """
    silence_s = ENGINE_SILENCE_S         # #481: main() sets the config's engine_silence_s (survives restart())
    silent_note = None                   # #481: why the server ended a silent engine (death_note says it)

    def __init__(self, exe: str, args: list[str], cwd: str | None = None, log: str | None = None,
                 env: dict | None = None, lazy: bool = False):
        self.spawn = (exe, list(args), cwd, log, env)   # to start it again after it died (issue #27)
        paths = {k: v for k, v in zip(args, args[1:]) if k in ("--native", "--pack")}
        self.model_path = paths.get("--native") or paths.get("--pack", "pack/full")
        self.log_path = log
        self.proc, self.pump, self.log = None, None, None
        self.ended, self.unloaded = True, True
        self.max_context = int(args[args.index("--max-context") + 1]) if "--max-context" in args else 4096
        self.can_stop = False            # the engine honours a STOP line mid-request (READY <ctx> stop)
        self.last = {}
        self.info = {}                   # INFO key=value facts (engine 0.1.8+): kv, expert slots, ... (Monitor tab)
        self.prefill_tok_s_mean = None
        self.progress = None             # (read, total) prompt tokens while a prompt is read, from PP lines
        self.silent_note = None
        try:                            # a ready-made engine's BUILD.json says its version
            build = json.loads((Path(exe).parent / "BUILD.json").read_text())
            self.info["version"] = build.get("version")
            # the About tab shows the whole stack, not just the version
            self.info["backend"] = build.get("backend")
            self.info["rocm"] = build.get("rocm")
            self.info["hipblaslt"] = build.get("hipblaslt_version")
            self.info["archs"] = build.get("archs")
            self.info["platform"] = build.get("platform")
        except (OSError, ValueError):
            self.info["version"] = None
        if lazy:
            return
        self.unloaded = False            # `ended` stays True until READY (below): not alive while starting (#344)
        self.log = open(log, "a", encoding="utf-8") if log else subprocess.DEVNULL
        load_started=time.perf_counter()
        self.info['startup_started_at']=time.time()
        self.info.pop('startup_total_s',None)
        loading = threading.Event()                     # set once READY: the narrator below stops
        log_start = os.path.getsize(log) if log else 0  # where this start's lines begin (start_failure_hint)
        self.startup_log_offset=log_start
        if log:
            threading.Thread(target=narrate_start, args=(log, os.path.getsize(log), args, loading),
                             daemon=True).start()
            # once per log: the follower keeps reading the same (appended) log across restarts and reloads
            if os.environ.get("STRATA_REQUEST_LINES") and os.path.abspath(log) not in _echoing:
                _echoing.add(os.path.abspath(log))
                threading.Thread(target=echo_requests, args=(log, os.path.getsize(log)), daemon=True).start()
        self.proc = subprocess.Popen([exe, "--serve", *args], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.log, text=True, encoding="utf-8", bufsize=1, env=env)
        contain(self.proc)                               # ends with the server, however it ends (Windows)
        self.max_context = 0
        for line in self.proc.stdout:
            if line.startswith("INFO "):
                for kv in line.split()[1:]:
                    k, _, v = kv.partition("=")
                    self.info[k] = int(v) if v.lstrip("-").isdigit() else v
            if line.startswith("READY"):
                f = line.split()
                self.max_context = int(f[1])
                self.can_stop = "stop" in f[2:]
                break
        loading.set()
        self.info['startup_total_s']=round(time.perf_counter()-load_started,3)
        self.startup_log_offset=log_start
        if self.max_context <= 0:
            try:                                        # its pipes and our handle on its log (the log stays)
                self.proc.wait(timeout=5)
                self.proc.stdin.close()
                self.proc.stdout.close()
                if log:
                    self.log.close()
            except (OSError, subprocess.TimeoutExpired):
                pass
            raise EngineDied("the engine exited before it was ready" + (f" (see {log})" if log else "") +
                               start_failure_hint(log, log_start) + start_log_tail(log, log_start))
        # (from PR #41, midhatn) a locally built engine can sit next to another release's BUILD.json: engines that
        # report their own version (INFO engine=, 0.1.8+) win, the manifest stays the fallback for older ones
        if self.info.get("engine"):
            self.info["version"] = str(self.info["engine"])
        self.ended = False                              # READY: alive from here (restart() set it True, #344)
        # the engine's stdout on a thread, so a request can wait with a timeout (heartbeats, cancel checks)
        self.lines: queue.Queue = queue.Queue()
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()

    def _pump(self):
        proc, lines = self.proc, self.lines             # this process's: a restart replaces both (#344)
        for line in proc.stdout:
            lines.put(line)
        if self.proc is proc:                           # a killed engine's pump must not mark its successor dead
            self.ended = True                           # its output closed: it is gone, even before the OS says so
        lines.put(None)

    def death_note(self) -> str:
        """Why the engine most likely ended, from the end of its log: its own watchdog (issue #29), else RAM."""
        if getattr(self, "silent_note", None):          # #481: the server ended it, not the OS or the engine itself
            return self.silent_note
        tail = ""
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 4096))
                tail = f.read().decode("utf-8", "replace")
        except (OSError, TypeError):
            pass
        for line in reversed(tail.splitlines()):
            if "issue #29" in line:
                return ("The engine stopped itself because it had stopped making progress - a hang it caught. Its log "
                        "line: " + line.strip() + " - please report it at github.com/Niko1221/Strata/issues.")
        rc = self.proc.poll()
        last = next((x.strip() for x in reversed(tail.splitlines()) if x.strip().startswith(("strata", "ERR"))), "")
        if rc is not None and rc >= 0 and last:          # it ended by itself: its own last words say why (#215)
            return (f"The engine exited (code {rc}). Its last log line: {last} - if that does not explain it, please "
                    "report it at github.com/Niko1221/Strata/issues with the log.")
        return ("The usual cause is running out of RAM: Linux then ends the biggest program (check: sudo dmesg | "
                "grep -i -E 'killed process|out of memory'); Windows slows down instead. Close other programs or use a "
                "smaller model (Q2_0 / IQ2_XS).")

    def alive(self) -> bool:
        return self.proc is not None and not getattr(self, "ended", False) and self.proc.poll() is None

    def exit_code(self):
        if self.proc is None:
            return None
        try:
            return self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return None

    def unload(self):
        """Release GPU/RAM between requests, retaining the spawn config for automatic reloading."""
        self.close()
        self.unloaded = True

    def restart(self):
        """Start the engine again (the same command) after it died; the new process has its own line queue."""
        self.close()
        info = dict(self.info)
        # #344: not alive until READY - __init__ sets max_context to 0 and blocks until the engine says READY, and a
        # request that saw alive() in that window skipped load() and failed with "context (0)".  __init__ clears
        # `ended` itself once READY (before its pump thread can set it again).
        self.ended = True
        self.__init__(*self.spawn)
        self.info = {**info, **self.info}

    def _parse_done(self, line):
        f = line.split()
        self.last = {"generated": int(f[1]), "prompt_tokens": int(f[2]), "prompt_ms": float(f[3]),
                     "decode_ms": float(f[4]), "finish": f[5]}
        if len(f) >= 9:                                   # the conversation cache's fields (engine 0.1.3+)
            self.last.update(drafts_accepted=int(f[6]), drafts_offered=int(f[7]), reused=int(f[8]))
        if len(f) >= 11:                                  # decode hit rate fields
            self.last.update(hits=int(f[9]), lookups=int(f[10]))
        if len(f) >= 14:                                  # the expert tiers (engine 0.1.31+): RAM / file blobs, file MB
            self.last.update(ram_blobs=int(f[11]), file_blobs=int(f[12]), file_mb=float(f[13]))
        if len(f) >= 15:                                  # #471 (engine 0.1.36+): the prompt tokens actually read
            self.last.update(prompt_read=int(f[14]))

    @staticmethod
    def sampling_keys(sampling: dict) -> str:
        keys = ""
        t = sampling.get("temperature")
        if isinstance(t, (int, float)) and float(t) > 0.0:
            keys += f" temperature={float(t)!r}"
        tp = sampling.get("top_p")
        if isinstance(tp, (int, float)) and float(tp) < 1.0:
            keys += f" top_p={float(tp)!r}"
        tk = sampling.get("top_k")
        if isinstance(tk, int) and not isinstance(tk, bool) and tk >= 0:
            # the engine's sampled path keeps at most 64 candidates: 0 ("off") and wider lists get all 64
            keys += f" top_k={tk if 1 <= tk <= 64 else 64}"
        mp = sampling.get("min_p")
        if isinstance(mp, (int, float)) and 0.0 < float(mp) <= 1.0:
            keys += f" min_p={float(mp)!r}"
        rp = sampling.get("repetition_penalty")
        rp_on = isinstance(rp, (int, float)) and float(rp) != 1.0
        pf = sampling.get("frequency_penalty")
        pf_on = isinstance(pf, (int, float)) and float(pf) != 0.0
        pp = sampling.get("presence_penalty")
        pp_on = isinstance(pp, (int, float)) and float(pp) != 0.0
        if rp_on:
            keys += f" penalty_repeat={float(rp)!r}"
        if pf_on:
            keys += f" penalty_freq={float(pf)!r}"
        if pp_on:
            keys += f" penalty_present={float(pp)!r}"
        if rp_on or pf_on or pp_on:
            # a penalty without a window counts over nothing: the engine's default is the last 64 tokens
            pln = sampling.get("penalty_last_n")
            if isinstance(pln, int) and not isinstance(pln, bool) and pln > 0:
                keys += f" penalty_last_n={pln}"
            else:
                keys += " penalty_last_n=64"
        seed = sampling.get("seed")
        if isinstance(seed, int) and seed > 0:
            keys += f" seed={seed}"
        # setup's calibration (tools/calibrate.py): engine settings for this request only, measured without a restart
        tune = sampling.get("strata_tune")
        if isinstance(tune, dict):
            for k in ("pcie_frac", "spec_min_p"):
                v = tune.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) <= 1.0:
                    keys += f" {k}={float(v)!r}"
        return keys + StrataEngine.projection_key(sampling)

    @staticmethod
    def projection_key(sampling: dict) -> str:
        """`cvec=0|1`: the experimental-speed-projection control vector for this request, when the engine was
        started with one (--control-vector-scaled; an engine without one ignores the key).  Absent = on."""
        on = sampling.get("experimental_speed_projection")
        return f" cvec={int(on)}" if isinstance(on, bool) else ""

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        """Yields token ids, and None as a heartbeat every 10 s while the engine is quiet (reading a long prompt):
        the HTTP layer turns it into an SSE comment, which keeps clients' watchdogs calm and notices a client that
        has gone.  A consumer that stops early (or `cancel`) makes the engine STOP, so it does not run to max_new."""
        self.progress = None
        self.prefill_tok_s_mean = None
        # an image request takes the same sampling keys as text (#75: it used to decode greedily whatever was asked)
        head = f"GENI {int(max_new)}{self.sampling_keys(sampling or {})} {embeddings}" if embeddings else \
            f"GEN {int(max_new)}{self.sampling_keys(sampling or {})}"
        try:
            self.proc.stdin.write(f"{head} {','.join(str(int(t)) for t in ids)}\n")
            self.proc.stdin.flush()
        except OSError:                                  # the pipe is gone: the engine died (not the client)
            raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})") from None
        done = False
        # #481: how long the engine may stay silent from here.  Until the first line: the request's first prompt
        # chunk at the slowest prompt reading on top of silence_s; a PP line resets it to its own chunk's time.
        silence = float(self.silence_s or 0)
        allow = silence + min(len(ids), PP_CHUNK_MAX) / PP_FLOOR_TOK_S if silence > 0 else 0.0
        heard, read_to = time.monotonic(), 0
        try:
            while True:
                wait = 10.0
                if allow > 0:
                    wait = min(wait, allow - (time.monotonic() - heard))
                    if wait <= 0:
                        done = True                       # no STOP and no drain: nothing is listening
                        raise self._silent(f"the engine said nothing for {time.monotonic() - heard:.0f} s during "
                                           "the request")
                try:
                    line = self.lines.get(timeout=wait)
                except queue.Empty:
                    if cancel.is_set():
                        return
                    if wait >= 10.0:
                        yield None                        # the 10 s heartbeat (the deadline's short waits are not)
                    continue
                if line is None:
                    done = True
                    raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})")
                heard = time.monotonic()                  # any line is output: T, PP, RESUME, INFO ...
                if line.startswith("T "):
                    allow = silence
                    if cancel.is_set():
                        return
                    yield int(line[2:])
                elif line.startswith("PP "):
                    f = line.split()
                    if len(f) >= 3 and f[1].isdigit() and f[2].isdigit():
                        self.progress = (int(f[1]), int(f[2]))             # prompt progress, one per chunk: also a heartbeat (the
                        self.prefill_tok_s_mean = float(f[4]) if len(f) >= 5 else None
                        rate, chunk = self.prefill_tok_s_mean or 0.0, int(f[1]) - read_to
                        read_to = int(f[1])
                        if silence > 0 and rate > 0 and chunk > 0:   # #481: the next chunk, as long as this one
                            allow = max(silence, PP_SLACK * chunk / rate)
                    if cancel.is_set():                   # lines reset the 10 s wait, so without this a long prompt
                        return                            # would send no keep-alives at all)
                    yield None
                elif line.startswith("RESUME "):          # the reused tokens: the first chunk starts after them
                    try:
                        read_to = int(line.split()[1])
                    except (IndexError, ValueError):
                        pass
                elif line.startswith("DONE"):
                    self._parse_done(line)
                    done = True
                    return
                elif line.startswith("ERR"):
                    done = True
                    raise ValueError(line[4:].strip())
        finally:
            if not done:                                  # the consumer stopped early: stop the engine, drain to DONE
                if self.can_stop:
                    try:
                        self.proc.stdin.write("STOP\n")
                        self.proc.stdin.flush()
                    except OSError:
                        pass
                # #481: never an untimed wait here - it holds the request FIFO, and an engine that lost step never
                # answers.  An engine that honours STOP gets the current allowance in all (a STOP during a prompt
                # chunk is seen after it); an older one runs on to max_new, so each line only has to come in time.
                heard = time.monotonic()
                while True:
                    left = allow - (time.monotonic() - heard) if allow > 0 else None
                    try:
                        if left is not None and left <= 0:
                            raise queue.Empty
                        line = self.lines.get(timeout=left)
                    except queue.Empty:
                        raise self._silent("the engine did not finish the request after it was stopped (STOP) "
                                           f"within {allow:.0f} s") from None
                    if line is None or line.startswith("ERR"):
                        break
                    if line.startswith("DONE"):
                        self._parse_done(line)
                        break
                    if not self.can_stop:
                        heard = time.monotonic()

    def _silent(self, what: str) -> EngineSilent:
        """#481: end an engine that lost step with the server (its main thread waits for a command the server never
        sends), so the next request starts it again: killed now, its GPU and RAM go back with the process."""
        self.silent_note = ("The engine and the server lost step (issue #481; a very slow PC can raise "
                            "\"engine_silence_s\" in the config, 0 = wait forever). If it happens again, please add "
                            "the end of the engine log to github.com/Niko1221/Strata/issues/481.")
        self.ended = True                               # not alive from now: the next request restarts it
        proc = self.proc
        try:
            proc.kill()
            proc.wait(timeout=20)                       # restart() -> close() handles one that is still exiting
        except (OSError, AttributeError, subprocess.TimeoutExpired):
            pass
        return EngineSilent(f"{what}; the server ended the engine")

    def close(self):
        """End the engine process: QUIT first (the engine frees its memory itself - unpinning tens of GB can take
        a while), then terminate, then kill, each given 20 s.  Raises EngineStuck when it still runs after all three."""
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write("QUIT\n")
                    self.proc.stdin.flush()
                    self.proc.stdin.close()  # Windows' detached stdin reader must see EOF before shutdown
                    self.proc.wait(timeout=20)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    self.proc.terminate()
                    self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                raise EngineStuck("Strata is still releasing GPU/RAM; retry unloading after it exits") from None
        except OSError:
            pass
        finally:
            if self.proc.poll() is not None:
                if self.pump is not None:
                    self.pump.join(timeout=2)
                self.proc.stdin.close()
                self.proc.stdout.close()
                if self.log not in (None, subprocess.DEVNULL):
                    self.log.close()
                self.proc = None
                self.ended = True
                self.progress, self.last = None, {}



def find_mmproj(cfg: dict, native: str | None) -> Path | None:
    """The model's image projector (mmproj-*.gguf), looked for where setup.py puts it.

    setup.py writes it into the models dir; a checkout may also keep it beside the model's shards.
    Returns None rather than guessing a path that does not exist.
    """
    cands: list[Path] = []
    if native:
        cands.append(Path(native).parent)
    base = Path(cfg.get("cwd") or ".")
    cands += [base.parent / "Strata-data" / "models", base / "models", base / "Strata-data" / "models"]
    for d in cands:
        try:
            hit = sorted(Path(d).glob("mmproj-*.gguf"))
        except OSError:
            hit = []
        if hit:
            return hit[0]
    return None


class Vision:
    """The resident image encoder: `strata-vision` (llama.cpp mtmd + the mmproj file) reads `ENC <image> <out>`
    lines and writes each image's embeddings; results are cached by the image's hash, so a conversation that
    sends the same picture again (every turn, with most clients) encodes it once."""

    def __init__(self, cfg: dict, log=None, env: dict | None = None):
        args = [cfg["exe"], "--mmproj", cfg["mmproj"], "--model", cfg["model"]]
        if cfg.get("gpu"):
            args.append("--gpu")
        if cfg.get("threads"):
            args += ["--threads", str(cfg["threads"])]
        if cfg.get("max_tokens"):
            args += ["--max-tokens", str(cfg["max_tokens"])]
        self.dir = Path(tempfile.mkdtemp(prefix="strata-vision-"))
        self.spawn = (args, log, env)                   # to start it again after an unload
        self.stopped = False
        try:
            self._start()
        except Exception:
            self.dir.rmdir()
            raise
        self.lock = threading.Lock()
        self.cache: dict[str, tuple[Path, int]] = {}

    def _start(self):
        args, log, env = self.spawn
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log or subprocess.DEVNULL,
                                     text=True, encoding="utf-8", bufsize=1, env=env)
        contain(self.proc)
        line = self.proc.stdout.readline()
        if not line.startswith("READY"):
            self.proc.kill()
            self.proc.wait(timeout=10)
            raise RuntimeError("the vision encoder did not start: " + line.strip())
        self.stopped = False

    def alive(self) -> bool:
        return not self.stopped and self.proc.poll() is None

    def unload(self):
        """Stop the encoder process (its VRAM or RAM goes back); the encoded images stay cached on disk."""
        self.close()
        self.stopped = True

    def restart(self):
        """Start the encoder again after an unload (or if it died); the cache of encoded images is kept."""
        try:
            self.proc.kill()
        except OSError:
            pass
        self._start()

    @staticmethod
    def load(source: str) -> bytes:
        if source.startswith("data:"):
            return base64.b64decode(source.split(",", 1)[1])
        if source.startswith(("http://", "https://")):
            req = urllib.request.Request(source, headers={"User-Agent": "strata"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        path = source[7:] if source.startswith("file://") else source
        if path and os.path.isfile(path):
            return Path(path).read_bytes()
        raise ValueError("an image must be a data: URL, an http(s) URL or a local file path")

    @staticmethod
    def normalize(data: bytes) -> bytes:
        """The formats strata-vision's decoder (stb_image) reads pass through; anything else is converted to PNG."""
        if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:2] == b"BM" or \
                data[:6] in (b"GIF87a", b"GIF89a"):
            return data
        try:
            import io
            from PIL import Image
        except ImportError:
            raise ValueError("this image format needs Pillow (python -m pip install pillow); JPEG, PNG, BMP and "
                             "GIF work without it") from None
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
        except Exception as e:
            raise ValueError(f"the image could not be read ({e})") from None
        if im.mode in ("RGBA", "LA", "P") and "transparency" in im.info or im.mode in ("RGBA", "LA"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))   # transparent areas become white, not black
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()

    def encode(self, source: str) -> tuple[Path, int]:
        """-> (embeddings file, number of image tokens)."""
        data = self.normalize(self.load(source))
        key = hashlib.sha256(data).hexdigest()[:32]
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            img, out = self.dir / f"{key}.img", self.dir / f"{key}.sve"
            img.write_bytes(data)
            try:
                self.proc.stdin.write(f"ENC {img} {out}\n")
                self.proc.stdin.flush()
                line = self.proc.stdout.readline().strip()
            finally:                                                   # #352: also when the encoder's pipe is gone
                img.unlink(missing_ok=True)
            if not line.startswith("OK"):
                raise ValueError("the image could not be read: " + (line[4:] if line.startswith("ERR") else
                                                                     "the vision encoder stopped"))
            self.cache[key] = (out, int(line.split()[1]))
            if len(self.cache) > 64:                                   # oldest first
                old = next(iter(self.cache))
                self.cache.pop(old)[0].unlink(missing_ok=True)
            return self.cache[key]

    def close(self):
        try:
            self.proc.stdin.write("QUIT\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def gpu_list(cfg: dict) -> list[int]:
    """The config's "gpu": one card (2), or several for a layer split ([0, 2] or "0,2"), numbered as nvidia-smi
    numbers them; [] when it names none."""
    g = cfg.get("gpu")
    if g is None or g == "":
        return []
    items = g if isinstance(g, (list, tuple)) else str(g).split(",")
    return [int(str(x).strip()) for x in items if str(x).strip() != ""]


def engine_silence_s(cfg: dict) -> float:
    """#481: the config's "engine_silence_s" - seconds an engine may print nothing during a request before the server
    ends it (default ENGINE_SILENCE_S; 0 = wait forever).  ValueError for anything but a number >= 0."""
    v = cfg.get("engine_silence_s")
    if v is None:
        return ENGINE_SILENCE_S
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        raise ValueError(f'"engine_silence_s" must be a number of seconds >= 0 (0 = no limit), not {v!r}')
    return float(v)


def engine_args(cfg: dict) -> list[str]:
    """The engine's arguments: the config's, and with several GPUs the layer split across them ("layer_split" in the
    config: "auto" by default, or the first layer of each later GPU's share, e.g. "18" or "16,32")."""
    args = list(cfg["args"])
    if cfg.get("vision") and "--vision" not in args:
        args.append("--vision")
    if len(gpu_list(cfg)) > 1 and "--layer-split" not in args:
        args += ["--layer-split", str(cfg.get("layer_split") or "auto")]
    # opt-in: an auto split runs on the first card alone when it holds every profiled expert and the KV
    if len(gpu_list(cfg)) > 1 and cfg.get("split_skip_if_fits") and "--split-skip-if-fits" not in args:
        args.append("--split-skip-if-fits")
    return learned_profile_args(cfg, args)


_pcie_probe_cache: dict = {}       # log path -> (value, read at): the line is written once per engine start


def pcie_probe_gbs(log_path: str | None) -> float | None:
    """The host->device PCIe bandwidth the engine measured at start, from its log's newest
    `PCIe probe: N GB/s host->device` line, or None.  Windows exposes no PCIe counter for a GPU (WMI and PDH
    have none and AMD's ADL answers "not supported" on RDNA3), so this measured figure is what the Monitor's
    PCIe tile can honestly show; re-read at most every 30 s (the line only appears at each engine start)."""
    if not log_path:
        return None
    key = os.path.abspath(log_path)
    hit = _pcie_probe_cache.get(key)
    now = time.time()
    if hit and now - hit[1] < 30:
        return hit[0]
    value = None
    try:
        with open(log_path, "rb") as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size - 65536))   # the line is at the end of the newest start
            found = re.findall(r"PCIe probe:\s*([0-9.]+)\s*GB/s host->device", f.read().decode("utf-8", "replace"))
        if found:
            value = float(found[-1])
    except (OSError, ValueError):
        value = None
    _pcie_probe_cache[key] = (value, now)
    return value


def profile_shape(path: str) -> tuple[int, int] | None:
    """An expert profile's (layers, experts per layer), from its header (tools/make_profile.py's format), or None
    when the file is missing, is not one or is shorter than the pairs its header promises."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
            size = os.fstat(f.fileno()).st_size
    except OSError:
        return None
    if len(head) < 24 or head[:4] != b"STRP":
        return None
    _, nl, ne, _, n = struct.unpack("<5I", head[4:])
    return (nl, ne) if size >= 24 + 4 * n else None


def learned_profile_args(cfg: dict, args: list[str]) -> list[str]:
    """#477 (opt-in): "expert_profile_save": "<path>" in the config has the engine (0.1.36+) save what its adaptive
    tier learned there - on QUIT and every "expert_profile_save_every" minutes (10 by default, 0 = at QUIT only) -
    and the next start begins from it instead of the config's --expert-profile, when it is a profile of the same
    model (its header's layers and experts match); otherwise from the config's own, as before.  A relative path is
    the engine's (the config's "cwd").  Without the key, the arguments are the config's, unchanged."""
    save = cfg.get("expert_profile_save")
    if not isinstance(save, str) or not save.strip() or "--expert-profile-save" in args:
        return args
    args = args + ["--expert-profile-save", save]
    every = cfg.get("expert_profile_save_every")
    if isinstance(every, (int, float)) and not isinstance(every, bool) and every >= 0:
        args += ["--expert-profile-save-every", str(every)]
    if "--expert-profile" in args[:-1]:
        i = args.index("--expert-profile") + 1
        here = cfg.get("cwd") or "."
        learned = profile_shape(save if os.path.isabs(save) else os.path.join(here, save))
        base = profile_shape(args[i] if os.path.isabs(args[i]) else os.path.join(here, args[i]))
        if learned is not None and learned == base:
            args[i] = save
    return args


def hip_visible(cfg: dict) -> list[int]:
    """AMD: the devices the engine should see, as the HIP runtime numbers them (HIP_VISIBLE_DEVICES).

    On Linux setup's KFD order is HIP's order, so the config's "gpu" is it.  On Windows setup finds the cards in the
    display-adapter order, and an integrated Radeon that HIP also enumerates takes ordinal 0 and pushes the discrete
    card to 1 (#325): setup records the ordinal `strata-device --list-devices` gave the card as "hip_ordinal", which
    wins for a one-card config.  Without it (a config from before), the config's "gpu"."""
    ordinal = cfg.get("hip_ordinal")
    if ordinal is not None and str(ordinal).strip() != "" and len(gpu_list(cfg)) <= 1:
        try:
            return [int(str(ordinal).strip())]
        except ValueError:
            pass
    return gpu_list(cfg)


def child_env(cfg: dict) -> dict:
    """The engine's environment: the CUDA libraries setup installed (pip's nvidia packages, or the toolkit that
    compiled it) first on the library search path."""
    env = dict(os.environ)
    if hip_visible(cfg) and cfg.get("backend") == "hip":   # AMD: numbered as HIP numbers them (hip_visible)
        env["HIP_VISIBLE_DEVICES"] = ",".join(str(i) for i in hip_visible(cfg))
    elif gpu_list(cfg):                              # issue #51: the GPU(s) to run on, numbered as nvidia-smi does; CUDA's
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"      # own default order (fastest first) can number the cards otherwise
        env["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in gpu_list(cfg))
    for k, v in (cfg.get("env") or {}).items():      # engine settings the config carries (AMD: the GEMM tuning table)
        env[str(k)] = str(v)
    dirs = [d for d in cfg.get("lib_dirs") or [] if Path(d).is_dir()]
    if dirs:
        var = "PATH" if os.name == "nt" else "LD_LIBRARY_PATH"
        env[var] = os.pathsep.join(dirs + ([env[var]] if env.get(var) else []))
    return env


def vision_env(cfg: dict, env: dict) -> dict:
    """The image encoder's environment: the engine's, unless the config's vision section names its own "cuda_device"
    (numbered like nvidia-smi) - then the encoder runs on that card alone, so a spare GPU can hold it while the engine
    keeps all of its own cards' VRAM (#408, Efs-O).  Without it, nothing changes."""
    dev = (cfg.get("vision") or {}).get("cuda_device")
    if dev is None:
        return env
    env = dict(env)
    if cfg.get("backend") == "hip":
        env["HIP_VISIBLE_DEVICES"] = str(dev)
    else:
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        env["CUDA_VISIBLE_DEVICES"] = str(dev)
    return env


class ByteTokenizer:
    """Tiny stand-in tokenizer for tests without the pack: one id per UTF-8 byte, specials as ids >= 256."""
    SPECIALS = ["<|im_start|>", "<|im_end|>", "<|endoftext|>", "<|vision_start|>", "<|image_pad|>", "<|vision_end|>"]

    def encode(self, text, parse_special=False):
        out, i = [], 0
        while i < len(text):
            for k, s in enumerate(self.SPECIALS):
                if parse_special and text.startswith(s, i):
                    out.append(256 + k)
                    i += len(s)
                    break
            else:
                out.extend(text[i].encode("utf-8"))
                i += 1
        return out

    def decode(self, ids, errors="replace"):
        raw = bytearray()
        for t in ids:
            raw += self.SPECIALS[t - 256].encode() if t >= 256 else bytes([t])
        return raw.decode("utf-8", errors=errors)


# ------------------------------------------------------------------------------------------------ core
class Detokenizer:
    """Incremental decode: each token's bytes go through an incremental UTF-8 decoder, which emits the complete
    characters and holds a multi-byte character split across tokens until it is complete (invalid bytes become
    U+FFFD, as a whole decode with errors="replace" makes them).  Constant time per token - the old re-decode of
    every generated id cost 2 ms per token after 8K tokens and 4 ms after 16K (perf-review F-1).  A tokenizer
    without `token_bytes` (the tests' byte tokenizer) keeps the re-decode."""

    def __init__(self, tok):
        self.tok, self.ids, self.sent = tok, [], 0
        self.inc = codecs.getincrementaldecoder("utf-8")(errors="replace") if hasattr(tok, "token_bytes") else None

    def pending(self) -> bool:
        """A character is split across the tokens so far: its first bytes are held."""
        if self.inc is not None:
            return bool(self.inc.getstate()[0])
        return self.tok.decode(self.ids).endswith("\ufffd")

    def push(self, t: int) -> str:
        if self.inc is not None:
            return self.inc.decode(self.tok.token_bytes(t))
        self.ids.append(t)
        text = self.tok.decode(self.ids)
        if text.endswith("�"):
            return ""
        delta, self.sent = text[self.sent:], len(text)
        return delta


class Service:
    def __init__(self, engine: Engine, tokenizer, template: ChatTemplate, model_name: str = "qwen3.8-flash-next",
                 vision: Vision | None = None, sampling_defaults: dict | None = None,
                 fit_max_tokens: bool = False):
        self.engine, self.tok, self.template, self.model, self.vision = engine, tokenizer, template, model_name, vision
        self.fit_max_tokens = fit_max_tokens          # --fit-max-tokens: clamp the output cap instead of 400
        self.aliases: list[str] = []                  # #297: other names of the model (the config's `aliases`)
        self.sampling_defaults = dict(sampling_defaults or {})   # the run config's `sampling` block
        self.shared = {}                              # the web app's Chat settings for every client (POST /settings)
        self.shared_path = None                       # where they are kept between starts (next to the config)
        self.fifo = threading.Lock()
        from serve.benchmark_lab import BenchmarkLab
        self.benchmark_lab = BenchmarkLab(ROOT)
        from serve.optional_backends import OptionalBackends
        self.optional_backends = OptionalBackends(ROOT, discover_models=not isinstance(engine, MockEngine))
        self.optional_backends.graph_config=lambda: (getattr(self,'cfg',{}) or {}).get('hydra_graph_inference',{})
        self.optional_backends.memory_snapshot=lambda: self.telemetry.snapshot() if getattr(self,'telemetry',None) else {}
        from serve.optional_benchmark import OptionalBenchmark
        self.optional_benchmark = OptionalBenchmark(self.optional_backends)
        from serve.optional_catalogue import OptionalCatalogue
        self.optional_catalogue = OptionalCatalogue(self.optional_backends)
        from serve.local_training import LocalTraining
        self.local_training = LocalTraining(self.optional_backends)
        from serve.local_export import LocalExport
        self.local_export = LocalExport(self.optional_backends)
        from serve.update_center import UpdateCenter
        self.update_center = UpdateCenter(ROOT, port=getattr(self, 'port', None))
        self.update_center.operational_idle=lambda: not self.loaded() and self.optional_backends.status()['status']=='idle' and self.local_audio.status()['status']=='idle' and self.local_speech.status()['status']=='idle' and not self.local_separation.lock.locked() and not (ROOT/'data/.gpu-campaign.lock').exists()
        self.update_center.configuration_provider=lambda:getattr(self,'cfg_path',None)
        self.update_center.installed_provider=lambda: {'strata':{'installed_version':self.engine.info['version'],'installed_source':'engine_reported_version'}} if getattr(self.engine,'info',{}).get('version') else {}
        from serve.local_audio import LocalAudio
        self.local_audio = LocalAudio(ROOT)
        from serve.local_speech import LocalSpeech
        self.local_speech = LocalSpeech(ROOT)
        from serve.local_separation import LocalSeparation
        self.local_separation = LocalSeparation(ROOT)
        from serve.local_visual_generation import LocalVisualGeneration
        self.local_visual = LocalVisualGeneration(self.optional_backends)
        from serve.local_generative_audio import LocalGenerativeAudio
        self.local_generative_audio = LocalGenerativeAudio(ROOT)
        from serve.audiocraft_setup import AudioCraftSetup
        self.audiocraft_setup=AudioCraftSetup(ROOT)
        previous_idle = self.update_center.operational_idle
        self.update_center.operational_idle = lambda: previous_idle() and not self.local_visual.status()['busy'] and not self.local_generative_audio.status()['busy'] and not self.audiocraft_setup.status()['busy']
        from serve.voicestudio import VoiceStudio
        self.voicestudio = VoiceStudio(ROOT)
        from serve.unsloth_workspace import UnslothWorkspace
        self.unsloth_workspace=UnslothWorkspace(ROOT,self.update_center.operational_idle)
        from serve.colibri_workspace import ColibriWorkspace
        self.colibri_workspace=ColibriWorkspace(ROOT,self.update_center.operational_idle)
        self.optional_backends.external_api_lease=self.colibri_workspace.api_lease_matches
        self.optional_backends.external_api_metadata=self.colibri_workspace.api_metadata
        self.native_workspace = None
        self.automatic_updates = None
        from serve.antigravity_web import OriginalWeb
        self.antigravity_web=OriginalWeb(ROOT,busy=lambda:self.optional_backends.request_lock.locked())
        import atexit
        atexit.register(self.antigravity_web.close)
        from serve.local_integration_jobs import AirLLMSetup
        self.airllm_setup = AirLLMSetup(ROOT, lambda:self.update_center.operational_idle() and self.update_center.job.get('state') not in ('downloading','preparing','validating','resolving','installing_candidate','validating_python') and self.update_center.harness_updates.status().get('state')!='installing')
        from serve.local_integration_jobs import OpenWebUISetup
        self.open_webui_setup=OpenWebUISetup(ROOT,lambda:self.airllm_setup.idle())
        idle_before_integrations=self.update_center.operational_idle
        self.update_center.operational_idle=lambda:idle_before_integrations() and self.airllm_setup.job['state']!='preparing' and not self.voicestudio._busy.locked()
        self.embeddings = threading.local()           # the current request's image embeddings file (GENI)
        self.api_key = ""                              # when set, /v1/* needs it (Bearer or x-api-key)
        # #321: browser pages of these origins may call /v1/* (CORS; "*" = any page - only with an api_key that
        # matters); empty = no CORS headers at all, as before
        self.cors_origins: list[str] = []
        # #321: origins that count as Strata's own page for /settings and MCP tools, e.g. the web app reached through a
        # reverse proxy or tunnel whose Host differs ("https://strata.example.com"); never a wildcard
        self.trusted_origins: list[str] = []
        # DNS rebinding: extra Host names this server answers to (the config's allowed_hosts, $STRATA_ALLOWED_HOSTS;
        # "*" = any), and every name it answers to, which serve() works out from the address it listens on
        self.allowed_hosts: list[str] = []
        self.host_names: set[str] = set(LOOPBACK_NAMES)
        self.status = {"busy": False, "queued": 0}      # GET /status: what the model is doing right now
        self.rate = collections.deque(maxlen=32)        # (time, generated) samples for the live tok/s window
        # #332: the API request monitor (/api-monitor) keeps the last 100 requests' prompts and answers in memory,
        # so it is off unless the config's "api_monitor" (or --api-monitor) turns it on
        self.api_monitor = False
        self.api_requests = collections.deque(maxlen=100)  # bounded I/O in memory; no headers or API keys
        self.request_trace = threading.local()
        self.history = collections.deque(maxlen=500)    # the last finished requests, newest last (GET /metrics)
        # since the server started (the Monitor's totals, issue #35)
        self.totals = {"since": time.time(), "requests": 0, "prompt_tokens": 0, "reused": 0, "output_tokens": 0,
                       "prompt_ms": 0.0, "decode_ms": 0.0,
                       "drafts_offered": 0, "drafts_accepted": 0}   # #457: the MTP drafts, summed where reported
        self.last_timings = None                         # the last finished request's, llama.cpp's names (/v1/status)
        self.last_request_at = None                      # when a request last started or finished
        self.started_at = time.time()
        self.status_lock = threading.Lock()
        self.mcp = None                                  # serve/mcp.py's McpHub when MCP servers are configured
        # sharing the GPU with other programs (all off by default): unload the engine after this many idle seconds,
        # only start it again when this much VRAM is free, and run this command first (e.g. to unload another
        # server's model); the next request after an unload starts the engine again
        self.idle_unload_s = 0
        self.min_free_vram_mib = 0
        self.before_load = None
        self.reasoning_budget_tokens = 0                 # #123: the config's default thinking budget (0: none)
        self.anthropic_think_unasked = True               # #278: "anthropic_thinking": "on_request" -> False
        # Power Manager: monitors GPU power/temp/speed, computes efficiency, applies soft thermal throttling
        from serve.power_manager import PowerManager, PowerConfig
        self.power_manager = PowerManager(PowerConfig(mode="balanced"))
        self.stop_ids = set(tokenizer.encode(IM_END, parse_special=True) +
                            tokenizer.encode("<|endoftext|>", parse_special=True))

    def loaded(self) -> bool:
        return not hasattr(self.engine, "alive") or self.engine.alive()

    def set_aliases(self, aliases) -> None:
        """#297: the config's `aliases` - a list of names (or one comma-separated string), like llama-server's --alias.
        ValueError for anything else."""
        if aliases is None:
            aliases = []
        if isinstance(aliases, str):
            aliases = aliases.split(",")
        if not isinstance(aliases, list) or not all(isinstance(x, str) for x in aliases):
            raise ValueError(f"aliases={aliases!r}: expected a list of model names")
        names = []
        for x in (x.strip() for x in aliases):
            if x and x != self.model and x not in names:
                names.append(x)
        self.aliases = names

    def model_names(self) -> list[str]:
        return list(dict.fromkeys([self.model, *self.aliases, "strata"]))

    def model_for(self, req) -> str:
        """The name to answer with: the request's own when it is the model's name or an alias (#297), else the model's.
        Other names are still served, as before."""
        asked = req.get("model") if isinstance(req, dict) else None
        return asked if isinstance(asked, str) and asked in self.aliases else self.model

    def reasoning_budget(self, req) -> int | None:
        """#123: the most tokens this request may think, or None: the request's `reasoning_budget_tokens`, else the
        config's.  0 (or less) means no budget, so a request can turn a configured one off.  ValueError (a 400) for
        anything that is not a whole number."""
        value = (req or {}).get("reasoning_budget_tokens") if isinstance(req, dict) else None
        if value is None:
            value = self.reasoning_budget_tokens
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"reasoning_budget_tokens={value!r}: expected a whole number of tokens (0: no budget)")
        return value if value > 0 else None

    def _vision_down(self) -> bool:
        return self.vision is not None and hasattr(self.vision, "alive") and not self.vision.alive()

    def free_vram_mib(self) -> int | None:
        """Free VRAM on the engine's (first) GPU, from NVML (AMD backend: amdgpu's sysfs files, #301); None when it can't
        be read (then nothing is refused)."""
        try:
            if getattr(self, "backend", None) == "hip":
                from serve.telemetry import free_vram_mib
                return free_vram_mib(int(getattr(self, "gpu_index", 0) or 0), amd=True)
            from serve.telemetry import _Nvml
            nv = _Nvml(int(getattr(self, "gpu_index", 0) or 0))
            if not nv.ok():
                return None
            m = nv.Mem()
            if nv.lib.nvmlDeviceGetMemoryInfo(nv.dev, ctypes.byref(m)) != 0:
                return None
            return int(m.free >> 20)
        except Exception:
            return None

    def ensure_loaded(self):
        """Start the engine if it is not running (unloaded, or it died - issue #27), after the before_load hook and
        the free-VRAM check.  The caller holds self.fifo."""
        if getattr(self,'airllm_setup',None) and self.airllm_setup.job['state']=='preparing':
            raise RuntimeError('Attendi la preparazione AirLLM prima di avviare il motore')
        if getattr(self,'switch_in_progress',False):raise GpuBusy('Cambio modello in corso')
        from serve.gpu_lease import reserved,owns_inherited_validation_lease
        if reserved(ROOT) and not owns_inherited_validation_lease(ROOT):raise GpuBusy('Risorse riservate a una operazione locale; attendi la conclusione')
        if self.loaded() and not self._vision_down():
            return
        from serve.benchmark_monitor import competing_benchmark
        if getattr(self,'benchmark_lab',None) and self.benchmark_lab.active():
            raise GpuBusy('Campagna Benchmark in corso. Attendi la conclusione o arrestala dalla pagina Benchmark.')
        benchmark = competing_benchmark(getattr(self, 'port', None))
        if benchmark:
            raise GpuBusy(f"Benchmark isolato in corso ({benchmark}). Attendi la fine del test prima di caricare il motore.")
        if self.before_load:
            cmd = self.before_load
            print(f"[strata] before loading: {cmd if isinstance(cmd, str) else ' '.join(map(str, cmd))}", flush=True)
            try:
                subprocess.run(cmd, shell=isinstance(cmd, str), timeout=120, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError) as e:
                print(f"[strata] the before_load command failed ({e}); loading anyway", flush=True)
        if self.min_free_vram_mib:
            free = self.free_vram_mib()
            deadline = time.time() + 15                 # memory another process just gave back can take a moment
            while free is not None and free < self.min_free_vram_mib and time.time() < deadline:
                time.sleep(0.5)
                free = self.free_vram_mib()
            if free is not None and free < self.min_free_vram_mib:
                raise GpuBusy(f"the GPU is in use by another program: {free} MiB of VRAM free, the model needs "
                              f"{self.min_free_vram_mib} (min_free_vram_mib) - it stays unloaded until that is free")
        if self._vision_down():                         # first, as at a start: a GPU encoder takes its VRAM before
            print("[strata] starting the vision encoder again ...", flush=True)   # the engine sizes its cache
            self.vision.restart()
        if self.loaded():
            return
        if getattr(self.engine, "unloaded", False):
            print("[strata] loading the model again (it was unloaded) ...", flush=True)
        else:
            code = self.engine.exit_code() if hasattr(self.engine, "exit_code") else None
            print(f"[strata] the engine had stopped (exit code {code}); starting it again "
                  "(a minute or two) ...", flush=True)
        self.engine.restart()
        print("[strata] the engine is running again", flush=True)

    def _say_died(self, e: Exception) -> None:
        """The server window's line for an engine that died (or was ended, #481) in the middle of a request."""
        note = self.engine.death_note() if hasattr(self.engine, "death_note") else ""
        log = getattr(self.engine, "log_path", None)
        print(f"[strata] {e}. {note} The next request starts the engine again."
              f"{' Its log: ' + log if log else ''}", flush=True)

    def load(self):
        """POST /load and every generation request: start the engine now if it is unloaded (raises GpuBusy)."""
        # a request is on its way: the idle thread must not unload between this and the request's own start
        self.last_request_at = time.time()
        if self.loaded() and not self._vision_down():
            return
        trace = getattr(self.request_trace, "record", None)
        waiting = time.perf_counter()
        with self.fifo:
            loading = time.perf_counter()
            if trace is not None:
                with self.status_lock:
                    trace["queue_s"] += round(loading - waiting, 3)
                    trace["state"] = "loading"
            try:
                self.ensure_loaded()
            finally:
                if trace is not None:
                    with self.status_lock:
                        trace["load_s"] += round(time.perf_counter() - loading, 3)
                        trace["state"] = "queued"

    def unload(self, idle_for: float | None = None) -> str:
        """Stop the engine between requests: "unloaded", "not loaded", "busy" (a request is running or waiting, or
        with idle_for: one ran more recently than that) or "unsupported"."""
        if not hasattr(self.engine, "unload"):
            return "unsupported"
        if not self.fifo.acquire(blocking=False):
            return "busy"
        try:
            if not self.engine.alive():
                return "not loaded"
            with self.status_lock:
                if self.status.get("busy") or self.status.get("queued"):
                    return "busy"
            if idle_for is not None and time.time() - (self.last_request_at or self.started_at) < idle_for:
                return "busy"
            self.engine.unload()
            if self.vision is not None and hasattr(self.vision, "unload"):
                self.vision.unload()
            print(f"[strata] model unloaded{f' after {idle_for:.0f} s idle' if idle_for else ''}; "
                  "the next request loads it again", flush=True)
            return "unloaded"
        finally:
            self.fifo.release()

    def start_idle_unload(self):
        if not self.idle_unload_s or not hasattr(self.engine, "unload"):
            return
        print(f"[strata] the model unloads after {self.idle_unload_s} s without requests", flush=True)

        def loop():
            while True:
                time.sleep(max(1.0, min(30.0, self.idle_unload_s / 4)))
                try:
                    self.unload(idle_for=self.idle_unload_s)
                except EngineStuck as e:                # tried again at the next turn; the thread keeps running
                    print(f"[strata] idle unload: {e}", flush=True)
        threading.Thread(target=loop, daemon=True).start()

    def resource_state(self) -> dict:
        """GET /config: the resource budgets this server is running with, read from its own config's args."""
        cfg = getattr(self, "cfg", None) or {}
        args = list(cfg.get("args") or [])

        def get(flag, default=None):
            if flag in args:
                i = args.index(flag)
                if i + 1 < len(args):
                    try:
                        return int(args[i + 1])
                    except (TypeError, ValueError):
                        return default
            return default

        out = {"vram_reserve_mib": get("--vram-reserve-mib", 0), "kv_resident": get("--kv-resident"),
               "max_context": get("--max-context") or self.engine.max_context,
               "config": getattr(self, "cfg_path", None)}
        try:
            import shutil as _sh
            out["disk_free_gib"] = round(_sh.disk_usage(str(ROOT)).free / 2**30, 1)
        except OSError:
            pass
        return out

    def start_setup(self, model: str) -> dict:
        """POST /setup-download: run the official setup.py for this model in the background (it downloads the
        GGUF shards, prepares the pack and writes run-<model>.bat; --no-start leaves the running server alone).

        One at a time: a second call while one runs returns its state instead of starting another (the download
        is tens of GB and setup itself refuses to run twice)."""
        with self.status_lock:
            run = getattr(self, "_setup", None)
            if run and run.get("proc") and run["proc"].poll() is None:
                return {"status": "running", "model": run["model"], "log": run["log"],
                        "note": "a download is already running"}
        import subprocess
        setup = ROOT / "setup.py"
        if not setup.exists():
            raise ValueError(f"setup.py not found in {ROOT}")
        log = ROOT / f"setup-{model}.log"
        cmd = [sys.executable, str(setup), "--model", model, "--no-start", "--yes"]
        try:
            with open(log, "ab") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} setup.py {' '.join(cmd[2:])}\n".encode())
                proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
        except OSError as e:
            raise ValueError(f"could not start setup.py: {e}")
        with self.status_lock:
            self._setup = {"proc": proc, "model": model, "log": str(log), "started": time.time()}
        print(f"[strata] setup.py {model} started (pid {proc.pid}), log: {log}", flush=True)
        return {"status": "started", "model": model, "pid": proc.pid, "log": str(log)}

    def catalogue_state(self) -> dict:
        from serve import catalogue as cat
        from serve.catalogue_verified import fit_host
        host=cat.host();backend=getattr(self,'cfg',{}).get('backend','unknown')
        entries=[]
        for entry in getattr(self,'cat_entries',[]):
            if fit_host(entry['quant'],entry['download_gib'],host,backend,entry['on_disk'])[0]:
                entries.append({**entry,'fit':{**entry['fit'],'host':host}})
        return {'entries':entries,'official':[],'job':dict(getattr(self,'cat_job',{}) or self._last_catalogue_job()),
                'host':host,'backend':backend,'prepared':self.prepared_models(),
                'disk':{'free_gib':host['free_gib']},'checked_at':getattr(self,'cat_checked_at',None)}

    def _last_catalogue_job(self):
        try:return json.loads((ROOT/'data/catalogue-last-job.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}

    def catalogue_inspect(self,repo: str,quant: str=None) -> dict:
        from serve import catalogue as cat
        from serve import catalogue_verified as verified
        if quant is None:
            groups=verified.repo_info(repo)['groups']
            quant=next((q for q in ('IQ3_XXS','IQ2_XS','Q2_0','IQ3_S','IQ1_M') if q in groups),None)
        if not quant:raise ValueError('Nessuna quantizzazione supportata')
        return verified.inspect(repo,quant,cat.host(),getattr(self,'cfg',{}).get('backend','unknown'),ROOT)

    def catalogue_search(self,query: str) -> dict:
        from serve import catalogue as cat
        from serve import catalogue_verified as verified
        result=verified.search(query,cat.host(),getattr(self,'cfg',{}).get('backend','unknown'),ROOT)
        self.cat_entries=result['results'];self.cat_checked_at=result['checked_at']
        return result

    def start_catalogue_fetch(self,repo: str,quant: str,key: str=None,mtp: bool=False) -> dict:
        from serve import catalogue as cat
        if mtp:raise ValueError('Le teste MTP separate non sono validate in questo flusso; nessun download avviato')
        from serve.gpu_lease import reserved
        if self.benchmark_lab.active() or reserved(ROOT):raise ValueError('Attendi la fine della campagna Benchmark')
        with self.status_lock:
            if getattr(self,'cat_job',{}).get('state') in ('starting','downloading','verifying','packing','registering'):
                raise ValueError('Una preparazione è già in corso')
            self.cat_job={'state':'starting','repo':repo,'quant':quant,'started':time.time()}
        try:
            info=self.catalogue_inspect(repo,quant)
            chiave=key or info['key']
            if not re.fullmatch(r'[a-z0-9_]{1,32}',chiave):raise ValueError('Identificatore del modello non valido')
            if (ROOT/f'strata-{chiave}.json').exists():raise ValueError('Configurazione già presente; non viene sovrascritta')
            pack=cat.DATA/'packs'/chiave
            if pack.exists():raise ValueError('Pack già presente; non viene sovrascritto')
            self.cat_job.update(key=chiave,revision=info['revision'],files=info['files'],inspection=info,
                                download_gib=info['download_gib'],download_bytes=info['download_bytes'],log=str(ROOT/f'strata-catalogo-{chiave}.log'))
            threading.Thread(target=self._catalogue_worker,args=(repo,quant,chiave,False),daemon=True).start()
            return dict(self.cat_job)
        except Exception as exc:
            self.cat_job.update(state='failed',error=str(exc));raise

    def _catalogue_worker(self,repo: str,quant: str,chiave: str,mtp: bool=False) -> None:
        from serve import catalogue as cat
        from serve.configuration import atomic_json
        log=Path(self.cat_job['log']);files=list(self.cat_job['files']);revision=self.cat_job['revision']
        try:
            self.cat_job.update(state='downloading',step=1)
            dest=cat.DATA/'models'/chiave;dest.mkdir(parents=True,exist_ok=True)
            from huggingface_hub import snapshot_download
            from serve.download_progress import DownloadProgress
            expected=int(self.cat_job['download_bytes'])
            def publish_progress(progress):self.cat_job['progress']=progress
            cached=sum(f['bytes'] for f in self.cat_job['inspection'].get('file_metadata',[]) if (dest/f['path']).is_file() and (dest/f['path']).stat().st_size==f['bytes'])
            tracker=DownloadProgress(expected,publish_progress,cached=cached)
            snapshot_download(repo_id=repo,revision=revision,allow_patterns=files,local_dir=str(dest),max_workers=4,tqdm_class=tracker.progress_class())
            tracker.finish()
            self.cat_job.update(state='verifying',verification=dict(files_total=len(files),verified_files=0))
            for item in self.cat_job['inspection']['file_metadata']:
                with (dest/item['path']).open('rb') as source:
                    actual=hashlib.file_digest(source,'sha256').hexdigest()
                if actual!=item['sha256']:raise ValueError('Verifica SHA256 fallita: '+item['path'])
                self.cat_job['verification']['verified_files']+=1

            self.cat_job.update(state='packing',step=2)
            first=next((f for f in files if re.search(r'-00001-of-\d{5}\.gguf$',f)),files[0])
            final=cat.DATA/'packs'/chiave;staging=cat.DATA/'packs'/('.'+chiave+'-'+uuid.uuid4().hex[:8])
            command=[sys.executable,str(ROOT/'tools/iq_pack.py'),'--gguf',str(dest/first),'--out',str(staging),'--compat-bf16']
            with log.open('ab') as output:subprocess.run(command,cwd=str(ROOT),stdout=output,stderr=subprocess.STDOUT,check=True)
            if final.exists():raise ValueError('Pack creato da un altro lavoro; non viene sovrascritto')
            staging.rename(final)
            self.cat_job.update(state='registering',step=3)
            config=self._catalogue_register(chiave,dest,files)
            self.cat_job.update(state='done',step=3,config=config,pack=str(final))
            atomic_json(ROOT/'data/catalogue-last-job.json',dict(self.cat_job))
        except Exception as exc:self.cat_job.update(state='failed',error=str(exc))

    def _catalogue_register(self,chiave: str,dest: pathlib.Path,files: list) -> str:
        from serve.model_inventory import inspect_config
        from gguf_reader import GGUFFile
        from make_profile import read_profile,write_profile
        model=json.loads((ROOT/'strata-iq3_xxs.json').read_text(encoding='utf-8-sig'))
        args=list(model['args']);shards=sorted(f for f in files if f.lower().endswith('.gguf') and 'mmproj' not in f.lower() and 'mtp/' not in f.lower())
        if not shards:raise ValueError('Shard del modello mancanti')
        first=next((f for f in shards if re.search(r'-00001-of-\d{5}\.gguf$',f)),shards[0])
        ple=next((f for f in shards if GGUFFile(dest/f).find('per_layer_token_embd.weight')),None)
        if ple is None:raise ValueError('Tabella PLE non trovata negli shard')
        def setf(flag,value):
            if flag in args:args[args.index(flag)+1]=str(value)
            else:args.extend([flag,str(value)])
        pack=ROOT.parent/'Strata-data/packs'/chiave
        setf('--pack',pack);setf('--native',dest/first);setf('--ple-gguf',dest/ple)
        experts=self.cat_job['inspection']['experts'];directory=ROOT/'data/catalogue'/chiave;directory.mkdir(parents=True,exist_ok=True)
        base_pairs=read_profile(ROOT/'data/expert-profile.bin')
        pairs=[p for p in base_pairs if p[1]<experts];profile=directory/'expert-profile.bin'
        if profile.exists():raise ValueError('Profilo già presente; non viene sovrascritto')
        write_profile(profile,pairs,n_expert=experts);setf('--expert-profile',profile)
        # A newly downloaded checkpoint must not silently inherit another model's draft or encoder.
        for flag in ('--mtp','--mtp-draft-vocab'):
            if flag in args:i=args.index(flag);del args[i:i+2]
        model.pop('vision',None);model.pop('expert_profile_save',None)
        model.update(args=args,tokenizer=str(pack/'tokenizer'),model_name='qwen3.8-flash-next-'+chiave,log=str(ROOT/f'strata-{chiave}.log'))
        inspection=self.cat_job['inspection']
        model['catalogue']={k:inspection.get(k) for k in ('repo','quant','author','revision','download_gib','layout')}
        model['display_name']=('Qwen3.8 Flash Next Hybrid · IQ3/Q2 · shefowl' if inspection['repo']=='shefowl/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-Hybrid-GGUF' else inspection['title']+' · '+inspection['quant']+' · '+inspection['author'])
        model.pop('model',None)
        out=ROOT/f'strata-{chiave}.json'
        with out.open('x',encoding='utf-8') as output:json.dump(model,output,ensure_ascii=False,indent=2)
        ready=inspect_config(out)
        if not ready['ready']:raise ValueError('Preparazione incompleta: '+ready['error'])
        return str(out)

    def prepared_models(self) -> list:
        from serve.model_inventory import inventory
        return inventory(ROOT)

    def start_switch(self, model: str) -> dict:
        """POST /switch-model: passa a un'altra configurazione GIA' PREPARATA, sulla stessa porta.

        Il modello in uso e' deciso dalla configurazione con cui il server e' partito, quindi cambiarlo
        vuol dire riavviare il server con un'altra configurazione. Il server attuale tiene la porta:
        percio' lancia un aiutante che aspetta che si liberi e poi avvia l'altro, e subito dopo esce."""
        from serve.model_inventory import inspect_config
        from serve.benchmark_monitor import competing_benchmark
        if self.benchmark_lab.active() or competing_benchmark(getattr(self,'port',None)):
            raise ValueError('Attendi la conclusione del benchmark prima di cambiare modello')
        if getattr(self,'cat_job',{}).get('state') in ('starting','downloading','verifying','packing','registering'):
            raise ValueError('Attendi la preparazione del catalogo')
        disponibili = {}
        for f in sorted(ROOT.glob("strata-*.json")):
            if ".bak" in f.name:
                continue
            disponibili[f.stem[len("strata-"):].lower().replace("-", "_")] = f
        chiave = model.strip().lower().replace("-", "_").replace(" ", "_")
        target = disponibili.get(chiave)
        if target is None:
            raise ValueError("nessuna configurazione pronta per %r: usa prima 'Scarica e configura'. "
                             "Pronte adesso: %s" % (model, ", ".join(sorted(disponibili)) or "nessuna"))
        porta = int(getattr(self, "port", 0) or 8090)
        ready=inspect_config(target)
        if not ready['ready']:raise ValueError('Modello non pronto: '+ready['error'])
        target_cfg=json.loads(target.read_text(encoding='utf-8-sig'))
        target_model=target_cfg.get('model_name') or target_cfg.get('model')
        if Path(getattr(self,'cfg_path','') or '.').resolve()==target.resolve():
            return {'status':'already_active','model':chiave,'target_model':target_model}
        if not self.fifo.acquire(blocking=False):raise ValueError('Attendi la fine della richiesta in corso')
        try:
            self.switch_in_progress=True
            if self.loaded():self.engine.unload()
        except BaseException:
            self.switch_in_progress=False
            raise
        finally:self.fifo.release()
        aiuto = ROOT / "serve" / "_switch.py"
        if not aiuto.exists():
            self.switch_in_progress=False
            raise ValueError("manca serve/_switch.py")
        import subprocess as _sp
        import threading
        flag = 0
        for nome in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):
            flag |= getattr(_sp, nome, 0)
        log = ROOT / f"strata-cambio-{chiave}.log"
        try:
            with open(log, "ab") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} cambio modello richiesto -> {target.name}\n".encode())
                _sp.Popen([sys.executable, str(aiuto), str(target), str(porta), str(ROOT)],
                          cwd=str(ROOT), stdout=fh, stderr=_sp.STDOUT, stdin=_sp.DEVNULL,
                          creationflags=flag, close_fds=True)
        except OSError as e:
            self.switch_in_progress=False
            raise ValueError(f"non riesco ad avviare il cambio: {e}")
        threading.Timer(2.5, lambda: os._exit(0)).start()
        print(f"[strata] cambio modello -> {target.name} sulla porta {porta}; questo server esce", flush=True)
        return {"status": "switching", "model": chiave, "target_model":target_model,"config": str(target), "port": porta,
                "note": "il server si riavvia: la pagina si riconnette da sola fra qualche secondo"}

    def setup_state(self) -> dict:
        """GET /config's setup half: whether a download runs, its model and its log's tail."""
        with self.status_lock:
            run = getattr(self, "_setup", None)
        if not run:
            return {"status": "idle"}
        alive = bool(run.get("proc")) and run["proc"].poll() is None
        tail = ""
        try:
            with open(run["log"], "rb") as f:
                f.seek(max(0, os.fstat(f.fileno()).st_size - 2000))
                tail = f.read().decode("utf-8", "replace").strip().splitlines()[-1][-200:]
        except OSError:
            pass
        return {"status": "running" if alive else "done", "model": run["model"], "log": run["log"], "last": tail}

    def set_resources(self, vram_reserve_mib=None, kv_resident=None, max_context=None, validate_only=False) -> dict:
        """Write resource budgets into this server's config (`args`) and return what changed.

        The values are the engine's own flags, so they apply at the next engine start: --vram-reserve-mib
        (VRAM left to the desktop), --kv-resident (context kept in VRAM: more = faster, less VRAM for experts)
        and --max-context (the window).  Nothing is guessed: an unknown or out-of-range value is refused."""
        cfg = dict(getattr(self, "cfg", None) or {})
        args = list(cfg.get("args") or [])
        changed = {}

        def put(flag, value, low, high):
            nonlocal args                          # += would otherwise make `args` local to this nested function
            if value is None:
                return
            from serve.configuration import whole_number
            n = whole_number(value, flag, low, high)
            if flag in args:                       # replace the flag's current value in place
                i = args.index(flag)
                if i + 1 < len(args):
                    if args[i + 1] != str(n):
                        args[i + 1] = str(n)
                        changed[flag.lstrip("-").replace("-", "_")] = n
                else:
                    args.append(str(n))
                    changed[flag.lstrip("-").replace("-", "_")] = n
            else:
                args.extend([flag, str(n)])
                changed[flag.lstrip("-").replace("-", "_")] = n

        put("--vram-reserve-mib", vram_reserve_mib, 0, 16384)
        put("--kv-resident", kv_resident, 2048, 262144)
        put("--max-context", max_context, 2048, 262144)
        def effective(flag):
            return int(args[args.index(flag) + 1]) if flag in args else None
        kv, ctx = effective("--kv-resident"), effective("--max-context")
        if kv is not None and ctx is not None and kv > ctx:
            raise ValueError("--kv-resident cannot exceed --max-context")
        if validate_only:
            return changed
        if not changed:
            return {}
        cfg["args"] = args
        path = getattr(self, "cfg_path", None)
        if path:
            try:
                from serve.configuration import atomic_json
                atomic_json(path, cfg)
            except OSError as e:
                raise ValueError(f"could not write {path}: {e}")
        self.cfg = cfg
        if hasattr(self.engine, "spawn"):
            exe, _, cwd, log, env = self.engine.spawn
            self.engine.spawn = (exe, engine_args(cfg), cwd, log, env)
        return changed

    def set_vision(self, on) -> dict:
        if on is None:
            return {}
        if not isinstance(on, bool):
            raise ValueError("vision must be true or false")
        if not self.fifo.acquire(blocking=False):
            raise GpuBusy("images cannot be changed while the model is serving a request")
        try:
            return self._set_vision_locked(on)
        finally:
            self.fifo.release()

    def _set_vision_locked(self, on) -> dict:
        """Images on/off: writes this config's `vision` block and starts or stops the encoder now.

        The encoder is built here as at startup. A changed image mode unloads the
        engine, whose next lazy start allocates the correct rotary-position table.
        It stays off unless asked for, because the encoder's
        memory comes on top of the experts already in RAM on a 64 GB PC.
        """
        if on is None:
            return {}
        if not isinstance(on, bool):
            raise ValueError("vision must be true or false")
        cfg = dict(getattr(self, "cfg", None) or {})
        want = bool(on)
        path = getattr(self, "cfg_path", None)

        def write():
            if path:
                try:
                    from serve.configuration import atomic_json
                    atomic_json(path, cfg)
                except OSError as e:
                    raise ValueError(f"could not write {path}: {e}")
            self.cfg = cfg

        args = list(cfg.get("args") or [])
        native = None
        if "--native" in args and args.index("--native") + 1 < len(args):
            native = args[args.index("--native") + 1]

        if want:
            if not native:
                raise ValueError("this config has no --native shard: the image encoder needs it")
            mm = find_mmproj(cfg, native)
            if mm is None:
                raise ValueError("no mmproj file (the model's image projector): images cannot be enabled")
            cwd = Path(cfg.get("cwd") or ".")
            exe = cwd / "engine" / ("strata-vision.exe" if os.name == "nt" else "strata-vision")
            if not exe.exists():
                raise ValueError(f"the image encoder is not installed: {exe}")
            cfg["vision"] = {"exe": str(exe), "mmproj": str(mm), "model": str(native),
                             "gpu": False, "max_tokens": 300,      # setup.py VISION["cpu"]["max_tokens"]
                             "threads": max(1, (os.cpu_count() or 8) // 2)}
            candidate = None
            if self.vision is None:
                log = open(cfg["log"], "a", encoding="utf-8") if cfg.get("log") else None
                try:
                    candidate = Vision(cfg["vision"], log=log, env=vision_env(cfg, dict(os.environ)))
                except (OSError, RuntimeError) as e:
                    if log: log.close()
                    raise ValueError(f"could not enable images: {e}") from e
            try:
                write()
            except Exception:
                if candidate:
                    candidate.unload()
                    if log: log.close()
                raise
            if candidate:
                self.vision = candidate
        else:
            cfg.pop("vision", None)
            cfg["args"] = [a for a in args if a != "--vision"]
            write()
            if self.vision is not None:
                try:
                    self.vision.unload()
                finally:
                    self.vision = None
        if hasattr(self.engine, "spawn"):
            exe, old_args, cwd, log, env = self.engine.spawn
            new_args = engine_args(cfg)
            self.engine.spawn = (exe, new_args, cwd, log, env)
            if ("--vision" in old_args) != ("--vision" in new_args) and self.engine.alive():
                self.engine.unload()
        return {"vision": want}

    def set_shared(self, defaults) -> dict:
        """The Chat settings every client gets for what it leaves out; {} / None = clients use their own again."""
        shared = clean_shared_defaults(defaults)
        if self.shared_path:
            try:
                if shared:
                    from serve.configuration import atomic_json
                    atomic_json(self.shared_path, shared)
                else:
                    Path(self.shared_path).unlink(missing_ok=True)
            except OSError as e:
                raise ValueError(f"could not save shared settings: {e}") from e
        self.shared = shared
        return self.shared

    def with_shared(self, req: dict, api: str) -> dict:
        """The request with the shared thinking level and max tokens filled in where it has none of its own."""
        s = self.shared
        if not s:
            return req
        req = dict(req)
        if "max_tokens" in s and not req.get("max_tokens") and not req.get("max_completion_tokens"):
            req["max_tokens"] = s["max_tokens"]
        effort = s.get("reasoning_effort")
        if effort:
            if api == "openai":
                ctk = req.get("chat_template_kwargs") if isinstance(req.get("chat_template_kwargs"), dict) else {}
                if not req.get("reasoning_effort") and not req.get("reasoning") and \
                        "enable_thinking" not in ctk and "reasoning_effort" not in ctk:
                    req["reasoning_effort"] = effort
            elif not req.get("thinking") and not req.get("output_config"):
                if effort == "none":
                    req["thinking"] = {"type": "disabled"}
                else:
                    req["output_config"] = {"effort": effort}
        return req

    def start_telemetry(self):
        """The hardware sampler behind GET /metrics (serve/telemetry.py), recording this server's tok/s too."""
        if getattr(self, "telemetry", None) is None:
            from serve.telemetry import Telemetry
            self.telemetry = Telemetry(extra=lambda: {"tok_s": self._tok_s(), "tok_s_mean": self._tok_s_mean(),
                                                    "prefill_tok_s_mean": self._prefill_tok_s_mean()},
                                       gpu_index=int(getattr(self, "gpu_index", 0) or 0),
                                       gpu_indices=getattr(self, "gpu_indices", None),
                                       amd=getattr(self, "backend", None) == "hip")

    def _tok_s(self):
        """tok/s over the last RATE_WINDOW_S seconds.  Returns 0.0 while nothing is generating."""
        with self.status_lock:
            s = dict(self.status)
            rate = list(self.rate)
        if not s.get("busy") or not s.get("first_token"):
            return 0.0
        now = time.time()
        newest = rate[-1] if rate else None
        oldest = next(((t, g) for t, g in rate if now - t <= RATE_WINDOW_S), None)
        if newest and oldest and newest[0] - oldest[0] >= RATE_MIN_SPAN_S:
            return max(0.0, (newest[1] - oldest[1]) / (newest[0] - oldest[0]))
        return s["generated"] / max(RATE_MIN_SPAN_S, now - s["first_token"])

    def _tok_s_mean(self):
        """The whole-request mean since the first token (the old formula), kept so the two can be compared."""
        with self.status_lock:
            s = dict(self.status)
        if not s.get("busy") or not s.get("first_token"):
            return 0.0
        return s["generated"] / max(1e-6, time.time() - s["first_token"])

    def _prefill_tok_s_mean(self):
        """Engine-reported mean over newly read tokens, excluding the cached prefix."""
        with self.status_lock:
            reading = self.status.get("busy") and self.status.get("first_token") is None
        return getattr(self.engine, "prefill_tok_s_mean", None) if reading else 0.0

    def begin_request(self, path, req):
        """#332: a monitor record for this request, or None when the monitor is off (nothing is kept then)."""
        if not self.api_monitor:
            return None
        raw = json.dumps(req, ensure_ascii=False, indent=2)
        record = {"id": uuid.uuid4().hex[:12], "path": path, "model": req.get("model") or self.model,
                  "started_at": time.time(), "state": "queued", "stream": bool(req.get("stream")),
                  "response_format": (req.get("response_format") or {}).get("type")
                  if isinstance(req.get("response_format"), dict) else None,
                  "input": raw[:262144], "input_truncated": len(raw) > 262144,
                  "output": "", "reasoning": "", "output_truncated": False, "reasoning_truncated": False,
                  "queue_s": 0.0, "load_s": 0.0, "first_token_s": None,
                  "_clock": time.perf_counter()}
        with self.status_lock:
            self.api_requests.append(record)
        self.request_trace.record = record
        return record

    def request_records(self, request_id=None):
        with self.status_lock:
            records = list(self.api_requests)
            if request_id:
                record = next((r for r in records if r["id"] == request_id), None)
                if record is None:
                    return None
                return {k: v for k, v in record.items() if not k.startswith("_")}
            return [{k: v for k, v in r.items()
                     if k not in ("input", "output", "reasoning", "response") and not k.startswith("_")}
                    | {"wallclock_s": r.get("wallclock_s", round(time.perf_counter() - r["_clock"], 3))}
                    for r in reversed(records)]

    def metrics(self, all_requests=False) -> dict:
        """GET /metrics: what the Monitor tab shows - the engine's facts, what it is doing, the last requests, and
        the hardware (with a minute of history per series)."""
        with self.status_lock:
            s = dict(self.status)
            hist = list(self.history)
            totals = dict(self.totals)
        now = time.time()
        progress = getattr(self.engine, "progress", None)
        if s.get("busy") and s.get("first_token") is None:
            state = "reading"
        elif s.get("busy"):
            state = "generating"
        elif not self.loaded():
            state = "unloaded"
        else:
            state = "idle"
        live = {"state": state, "queued": s.get("queued", 0), "phase": s.get("phase") if s.get("busy") else None,
                "prompt_tokens": s.get("prompt_tokens") if s.get("busy") else None,
                "prompt_read": None, "prompt_total": None, "generated": s.get("generated") if s.get("busy") else None,
                "max_tokens": s.get("max_tokens") if s.get("busy") else None,
                "elapsed_s": round(now - s["started"], 1) if s.get("busy") and s.get("started") else None,
                "tok_s": round(self._tok_s(), 1) if state == "generating" else None,
                "tok_s_mean": round(self._tok_s_mean(), 1) if state == "generating" else None,
                "prefill_tok_s_mean": getattr(self.engine, "prefill_tok_s_mean", None) if s.get("busy") else None,
                "tok_s_window_s": RATE_WINDOW_S if state == "generating" else None}
        if state == "reading" and progress:
            live["prompt_read"], live["prompt_total"] = progress
        engine = {"model": self.model, "max_context": self.engine.max_context, "images": self.vision is not None,
                  **dict(getattr(self.engine, "info", {}) or {})}
        from serve.startup_timing import snapshot as startup_snapshot
        startup=startup_snapshot(getattr(self.engine,'log_path',None),engine.get('startup_total_s'),getattr(self.engine,'startup_log_offset',0))
        if startup:engine['startup']=startup
        # Windows gives no PCIe GPU counter (WMI/PDH have none, AMD's ADL says "not supported" on RDNA3), so the
        # Monitor's PCIe tile would stay empty on an AMD card: hand it the link speed the ENGINE measured at start
        # (`PCIe probe: N GB/s host->device`, in its log) instead of inventing a live throughput.
        pcie = pcie_probe_gbs(getattr(self.engine, "log_path", None))
        if pcie is not None:
            engine["pcie_probe_gbs"] = pcie
        tel = self.telemetry.snapshot() if getattr(self, "telemetry", None) else {"now": {}, "history": {}, "static": {}}
        # Update power manager with fresh telemetry (power, temp, speed)
        hw_now = tel.get("now", {})
        if hw_now:
            self.power_manager.update(
                power_w=hw_now.get("gpu_power", 0.0),
                temp_c=hw_now.get("gpu_temp", 0.0),
                speed_tps=live.get("tok_s") or 0.0,
            )
        pm_state = self.power_manager.get_state()
        power_info = {
            "enforcement": "advisory",
            "mode": self.power_manager.config.mode,
            "power_w": round(pm_state.power_w, 1) if hw_now.get("gpu_power") is not None else None,
            "temp_c": round(pm_state.temp_c, 1) if hw_now.get("gpu_temp") is not None else None,
            "speed_tps": round(pm_state.speed_tps, 1),
            "efficiency": round(pm_state.efficiency, 2) if hw_now.get("gpu_power") else None,
            "throttling": pm_state.throttling,
            "throttle_reason": pm_state.throttle_reason,
            "cooldown_s": round(pm_state.cooldown_s, 1),
            "temp_limit": self.power_manager.config.temp_limit(),
            "power_limit": self.power_manager.config.power_limit(),
        }
        from serve.diagnostics import diagnose
        diagnostics = diagnose(getattr(self, "cfg", None) or {}, engine, tel["now"], self.loaded(), self.vision is not None)
        optional = self.optional_backends.status(include_models=False)
        if optional.get('publisher')=='colibri' and optional.get('status')=='ready':optional['colibri']=self.colibri_workspace.monitor_snapshot()
        from serve.performance_profile_guard import inspect_profile
        performance_profile=inspect_profile(ROOT,getattr(self,'cfg',None) or {},engine,tel['now'],self.loaded())
        from serve.instrumentation import active_instrumentation
        instrumentation=active_instrumentation(engine,optional,tel['now'])
        active_backend={'id':'optional' if optional['status'] in ('ready','loading') else 'strata',
                        'model':optional['public_model'] if optional['status'] in ('ready','loading') else self.model}
        from serve.hydra_native import status as native_hydra_status
        hydra_identity=native_hydra_status(self)
        return {"hydra_native":hydra_identity,"instrumentation":instrumentation,"performance_profile":performance_profile,"active_backend":active_backend,"optional_backend": optional, "diagnostics": diagnostics, "engine": engine, "live": live, "requests": hist[::-1][:None if all_requests else 12],
                "requests_kept": len(hist), "totals": totals, "hardware": tel["now"],
                "hardware_static":
 tel["static"], "history": tel["history"], "time": now,
                "power": power_info, "efficiency_sample": tel.get('efficiency_sample')}

    def v1_status(self) -> dict:
        """GET /v1/status: what this server is and does, for a client that would rather ask than guess (a front-end
        that polls its OpenAI-compatible server's status, collabosm's for one): the model and its window, images,
        the APIs, what is running, and the last request's timings in llama.cpp's names.  /metrics has the rest."""
        with self.status_lock:
            s, totals = dict(self.status), dict(self.totals)
            last_t, last_at = (dict(self.last_timings) if self.last_timings else None), self.last_request_at
        tel = self.telemetry.snapshot() if getattr(self, "telemetry", None) else {"now": {}, "static": {}}
        hw, static = tel.get("now") or {}, tel.get("static") or {}

        def scaled(v, unit, digits=0):
            return round(v / unit, digits) if isinstance(v, (int, float)) else None

        busy, ctx = bool(s.get("busy")), self.engine.max_context
        images = self.vision is not None
        return {
            "service": "strata", "model": self.model,
            "loaded": self.loaded(), "auto_load": hasattr(self.engine, "restart"),
            "structured_output": {"formats": ["json_object", "json_schema"], "method": "prompt_and_validate",
                                  "constrained_decoding": False, "stream_buffered": True},
            "engine": (getattr(self.engine, "info", {}) or {}).get("version"),
            "started": int(self.started_at), "uptime_s": int(time.time() - self.started_at),
            "cache_max_tokens": ctx,
            "context": {"native": ctx, "max_positions": ctx},
            "concurrency": {"serving": 1, "requested": 1},       # one request at a time; more wait their turn
            "dialects": ["/v1/chat/completions", "/v1/messages"],
            "vision": {"enabled": images, "available": images, "error": None},
            "activity": {"requests": totals["requests"] + int(busy), "in_flight": int(busy) + int(s.get("queued") or 0),
                         "last_request_at": int(last_at) if last_at else None},
            "last_timings": last_t,
            "machine": {
                "at": int(time.time()),
                "gpu": {"name": static.get("gpu_name"), "used_mib": scaled(hw.get("gpu_mem_used"), 2 ** 20),
                        "total_mib": scaled(hw.get("gpu_mem_total"), 2 ** 20), "util_pct": hw.get("gpu_util"),
                        "temp_c": hw.get("gpu_temp"), "power_w": hw.get("gpu_power")} if static.get("gpu_name") else None,
                "ram": {"used_gib": scaled(hw.get("ram_used"), 2 ** 30, 1),
                        "total_gib": scaled(hw.get("ram_total"), 2 ** 30, 1)} if hw.get("ram_total") else None}}

    def prepare(self, messages, tools, kwargs, max_new=None, *, graph_context=True):
        """-> (ids, thinking, max_new). An unset or non-positive max_new (some clients send -1) means "unlimited":
        the rest of the context."""
        if graph_context and getattr(self, 'hydra_native_state', {}).get('enabled') \
                and (getattr(self, 'cfg', {}) or {}).get('hydra_graph_inference'):
            try:
                from serve.hydra_graph import prepare as prepare_graph_context
                messages = prepare_graph_context(self, messages, tools, kwargs, max_new)
                self._hydra_graph_hook_error = None
            except Exception as exc:
                # Optional subsystem/import failure must leave native preparation usable.
                self._hydra_graph_hook_error = type(exc).__name__[:64]
        prompt = self.template.render(messages, tools=tools, **kwargs)
        ids = self.tok.encode(prompt, parse_special=True)
        self.embeddings.path = None
        images = images_of(messages)
        if images:
            if self.vision is None:
                raise ValueError("this server was started without the vision encoder (run setup again and choose "
                                 "'vision'), so it cannot read images")
            pad = self.tok.encode(IMAGE_PAD, parse_special=True)[0]
            start = self.tok.encode(VISION_START, parse_special=True)[0]
            # Encode only while the engine is idle: the engine and the image encoder (a separate process) must not
            # run on the GPU at the same time - an encode during a running request left that request stuck at
            # "reading the prompt" with CPU and GPU busy, for good (reproduced).  So encoding takes its turn in the
            # same FIFO as the requests.
            with self.fifo:
                encoded = [self.vision.encode(src) for src in images]
            # one <|image_pad|> per image -> one per image token.  Only the markers the template writes for an image
            # (right after <|vision_start|>) are images: the same text inside a message (an agent reading these docs,
            # #150) is kept as plain text, or it took an image's place and the counts no longer matched.
            literal = self.tok.encode(IMAGE_PAD, parse_special=False)
            out, k = [], 0
            for j, t in enumerate(ids):
                if t == pad and j > 0 and ids[j - 1] == start and k < len(encoded):
                    out += [pad] * encoded[k][1]
                    k += 1
                elif t == pad:
                    out += literal
                else:
                    out.append(t)
            if k != len(encoded):
                raise ValueError("the prompt and its images do not match")
            ids = out
            combined = self.vision.dir / f"req-{uuid.uuid4().hex[:12]}.sve"
            with open(combined, "wb") as f:
                for path, _ in encoded:
                    f.write(path.read_bytes())
            self.embeddings.path = combined
        if self.engine.max_context <= 0:                # #344: (re)starting, not a prompt that is too long
            raise EngineStarting("the engine is starting (a minute or two); try again shortly")
        room = self.engine.max_context - CTX_SLACK - len(ids)
        if max_new is None or max_new <= 0 or (self.fit_max_tokens and room < 1):
            if room < 1:
                raise ValueError(f"prompt ({len(ids)} tokens) leaves no room to answer in the context "
                                 f"({self.engine.max_context}); requests are never truncated")
            max_new = room
        elif max_new > room:
            if not self.fit_max_tokens:
                raise ValueError(f"prompt ({len(ids)} tokens) + max tokens ({max_new}) exceeds the context "
                                 f"({self.engine.max_context}); requests are never truncated. Send a smaller "
                                 f"max_tokens (at most {max(0, room)} here), or add \"fit_max_tokens\": true to the "
                                 "model's strata-<model>.json to shorten it to the room left (#545)")
            max_new = max(1, room)          # --fit-max-tokens: a shorter completion beats a 400
        return ids, kwargs.get("enable_thinking", True) is not False, max_new

    def _note(self, n, evs):
        with self.status_lock:
            s = self.status
            s["generated"] = n
            if s.get("first_token") is None:
                s["first_token"] = time.time()
            self.rate.append((time.time(), n))          # the live rate's window over the last RATE_WINDOW_S
            for ev in evs:
                if ev.kind == "reasoning":
                    s["phase"] = "thinking"
                elif ev.kind == "content":
                    s["phase"] = "answering"
                elif ev.kind == "tool_start":
                    s["phase"], s["tool"] = f"writing a tool call: {ev.call.name}", ev.call.name
                elif ev.kind == "tool_call":
                    s["phase"] = "tool call complete"
                s["tail"] = ((s.get("tail") or "") + (ev.text or ""))[-600:]

    def _progress(self, last_print, every=1.0):
        """A progress line in the server window every `every` seconds while a request runs."""
        now = time.time()
        if now - last_print < every:
            return last_print
        with self.status_lock:
            s = dict(self.status)
        el = now - s.get("started", now)
        if s.get("first_token") is None:
            pr = getattr(self.engine, "progress", None)   # (position reached, prompt tokens): a reused prefix counts
            done = f"{pr[0]:,} of {pr[1]:,}" if pr and pr[1] else f"{s.get('prompt_tokens', 0):,}"   # as read (#29)
            print(f"[strata] reading the prompt: {done} tokens, {el:.0f} s so far", flush=True)
        else:
            rate = s["generated"] / max(1e-6, now - s["first_token"])
            print(f"[strata] {s['phase']}: {s['generated']} of max {s.get('max_tokens')} tokens, {rate:.1f} tok/s, "
                  f"{el:.0f} s", flush=True)
        return now

    def run(self, ids, thinking, tools, max_new, sampling, cancel) -> Iterator[tuple[str, object]]:
        """Yields ("event", Event) as text arrives, then ("done", {"finish": .., "completion_tokens": ..})."""
        budget = self.reasoning_budget(sampling) if thinking else None   # #123: opt-in, off by default
        defaults = {**self.sampling_defaults, **self.shared}   # the config's, then the Chat settings shared with apps
        if defaults:                   # the request's own fields win (explicit 0 stays greedy)
            req_values = {k: v for k, v in (sampling or {}).items() if v is not None}
            sampling = {**defaults, **req_values}
        parser = OutputParser(thinking=thinking, tools=tools, stream_tools=True)
        detok, n, finish = Detokenizer(self.tok), 0, "length"
        timings, before = None, None                    # this request's timings; the engine's `last` before it
        raw_ids = []                                    # every generated id (STRATA_DEBUG: dump raw model text)
        emb = getattr(self.embeddings, "path", None)
        # Identity token: only a DONE line replaces engine.last, so a request that died, errored or was
        # disconnected must not have the PREVIOUS request's decode figures recorded as its own.
        engine_last0 = getattr(self.engine, "last", None)
        trace = getattr(self.request_trace, "record", None)
        waiting = time.perf_counter()
        with self.status_lock:
            self.status["queued"] += 1
        try:
            with self.fifo:
                try:
                    with self.status_lock:
                        if trace is not None:
                            trace["queue_s"] += round(time.perf_counter() - waiting, 3)
                            trace["state"] = "generating"
                        self.status["queued"] -= 1
                    # issue #27: it died in an earlier request (or was unloaded) - start it again instead of failing
                    self.ensure_loaded()
                    with self.status_lock:
                        self.status.update(busy=True, phase="reading the prompt", prompt_tokens=len(ids),
                                           generated=0, started=time.time(), first_token=None, tool=None, tail="",
                                           max_tokens=max_new)
                        self.last_request_at = time.time()
                        self.rate.clear()               # the previous request's samples must not leak into this one
                    before = getattr(self.engine, "last", None)
                    last_print = time.time()
                    prompt, thought = ids, 0            # thought: the reasoning tokens so far (the budget's count)
                    while True:
                        from serve.hydra_native import generate as native_generate
                        gen = native_generate(self,prompt,max_new-n,sampling,cancel,embeddings=emb) if emb \
                            else native_generate(self,prompt,max_new-n,sampling,cancel)
                        seg, wrap, leaving = [], False, False   # this pass's tokens; the budget is reached; closed
                        try:
                            for t in gen:
                                if t is None:               # heartbeat while the engine is quiet
                                    last_print = self._progress(last_print)
                                    yield "ping", None
                                    continue
                                n += 1
                                if trace is not None and trace["first_token_s"] is None:
                                    with self.status_lock:
                                        trace["first_token_s"] = round(time.perf_counter() - trace["_clock"], 3)
                                if t in self.stop_ids:
                                    finish = "stop"
                                    raw_ids.append(t)
                                    break
                                raw_ids.append(t)
                                seg.append(t)
                                evs = parser.feed(detok.push(t))
                                self._note(n, evs)
                                last_print = self._progress(last_print)
                                for ev in evs:
                                    yield "event", ev
                                if budget and parser.state == "reasoning":
                                    thought += 1
                                    # at a clean point: no tag held back, no character split across tokens
                                    if thought >= budget and not parser.buf and not detok.pending():
                                        wrap = True
                                        break
                        except EngineDied as e:
                            finish = "error"
                            self._say_died(e)
                            raise
                        except ValueError as e:             # the engine's ERR line (it may have ended after it)
                            finish = "error"
                            print(f"[strata] the engine reported an error: {e}", flush=True)
                            raise
                        except GeneratorExit:               # the client went away: an engine that never acknowledges
                            leaving = True                  # the STOP below is ended, but no error replaces this
                            raise
                        finally:
                            try:
                                gen.close()             # STOP+drain to THIS request's DONE while still holding the
                                #                         fifo, so a stop-token break can't leave the shared engine
                                #                         queue mid-drain for the next request to read as its own DONE
                            except EngineSilent as e:   # #481: the STOP was never acknowledged: the engine is ended
                                finish = "error"
                                self._say_died(e)
                                if not leaving and not cancel.is_set():
                                    raise
                        if not wrap or cancel.is_set():
                            break
                        # #123: the thinking reached reasoning_budget_tokens.  Close it the way the model would (a
                        # short wrap-up and </think>) and let it answer: the next pass's prompt is this one plus what
                        # was generated plus the wrap-up, so the engine continues from the prefix it already holds.
                        budget = None
                        extra = self.tok.encode(REASONING_WRAP_UP, parse_special=True)
                        if max_new - n - len(extra) < 1:
                            break                       # no room left to answer: "length", as without a budget
                        print(f"[strata] thinking budget reached ({thought} tokens): wrapping up the thinking",
                              flush=True)
                        for t in extra:
                            n += 1
                            raw_ids.append(t)
                            evs = parser.feed(detok.push(t))
                            self._note(n, evs)
                            for ev in evs:
                                yield "event", ev
                        prompt = prompt + seg + extra
                    if cancel.is_set():
                        finish = "cancel"
                except GeneratorExit:                   # the client disconnected mid-stream
                    finish = "disconnect"
                    raise
                finally:
                    # #266: settle this request's status, history and totals while still holding the fifo: once
                    # it is released the next request sets its own status, which this must not record or clear
                    with self.status_lock:
                        if self.status.get("busy"):
                            # only this request's DONE counts: same object means no DONE arrived (death, error,
                            # disconnect)
                            last = dict(getattr(self.engine, "last", {}) or {}) \
                                if getattr(self.engine, "last", None) is not engine_last0 else {}
                            started = self.status.get("started", time.time())
                            cvec = (getattr(self.engine, "info", {}) or {}).get("cvec", 0)
                            loaded = str(cvec) not in ("0", "", "None")
                            hit_rate = round(last["hits"] / last["lookups"], 3) if last.get("lookups") else None
                            seen = prompt_tokens_seen(len(ids), last)   # #471: < len(ids) when cancelled mid-read
                            self.history.append({
                                "projection": (sampling or {}).get("experimental_speed_projection") is not False
                                if loaded else None,
                                "time": started, "duration_s": round(time.time() - started, 1), "finish": finish,
                                "prompt_tokens": seen, "reused": last.get("reused"), "output_tokens": n,
                                # the request's whole prompt, and the tokens read of it (None: an older engine)
                                "prompt_total": len(ids), "prompt_read": last.get("prompt_read"),
                                "engine_generated": last.get("generated"),
                                "prompt_ms": last.get("prompt_ms"), "decode_ms": last.get("decode_ms"),
                                "decode_tok_s": round(last["generated"] / (last["decode_ms"] / 1000), 1)
                                if n and last.get("generated") and last.get("decode_ms") else None,
                                "hit_rate": hit_rate, "ram_blobs": last.get("ram_blobs"),
                                "file_blobs": last.get("file_blobs"), "file_mb": last.get("file_mb"),
                                # #457: the speculative drafts from the DONE line (None: the engine did not say)
                                "drafts_offered": last.get("drafts_offered"),
                                "drafts_accepted": last.get("drafts_accepted")})
                            t = self.totals
                            t["requests"] += 1
                            t["prompt_tokens"] += seen
                            t["reused"] += last.get("reused") or 0
                            t["output_tokens"] += n
                            t["prompt_ms"] += last.get("prompt_ms") or 0.0
                            t["decode_ms"] += last.get("decode_ms") or 0.0
                            t["drafts_offered"] += last.get("drafts_offered") or 0
                            t["drafts_accepted"] += last.get("drafts_accepted") or 0
                            fresh = getattr(self.engine, "last", None)
                            if fresh is not None and fresh is not before:      # the engine's clock for THIS request
                                timings = request_timings(seen, n, last)
                                self.last_timings = dict(timings, at=int(time.time())) if timings else None
                            self.last_request_at = time.time()
                            now = time.time()
                            el = now - self.status.get("started", now)
                            ft = self.status.get("first_token")
                            rate = n / max(1e-6, now - ft) if ft else 0.0
                            hit_msg = f", expert cache {hit_rate*100:.1f}% hit" if hit_rate is not None else ""
                            print(f"[strata] done: {n} tokens in {el:.0f} s ({rate:.1f} tok/s) "
                                  f"({finish}, cancel={cancel.is_set()}){hit_msg}", flush=True)
                            if finish == "length" and parser.state == "reasoning":   # #530
                                print("[strata] the reply reached max tokens while still thinking, so it has no "
                                      "answer: a thinking budget (reasoning_budget_tokens, in the request or in "
                                      "strata-<model>.json for every request) leaves room to answer", flush=True)
                            if os.environ.get("STRATA_DEBUG") and raw_ids:
                                print(f"[strata] raw: {self.tok.decode(raw_ids)!r}", flush=True)
                        self.status["busy"] = False
                        self.status.pop("tail", None)            # #212: the answer's end is not kept once it is done
                        self.status.pop("tool", None)
        finally:
            if emb:
                Path(emb).unlink(missing_ok=True)
        for ev in parser.finish():
            yield "event", ev
        yield "done", {"finish": finish, "completion_tokens": n, "reused": (timings or {}).get("cache_n", 0),
                       "timings": timings}


def prompt_tokens_seen(prompt_tokens: int, last: dict) -> int:
    """#471: the prompt tokens a request got through - all of them, unless the engine's DONE line says a cancel stopped
    its prompt read part-way (then the reused ones plus those read).  /metrics' history and totals count these, so a
    cancelled read is neither recorded as the whole prompt nor given a rate from tokens it never read.  An engine
    before 0.1.36 does not say (no `prompt_read`): the whole prompt, as before."""
    read = last.get("prompt_read")
    if read is None or last.get("finish") != "cancel":
        return prompt_tokens
    return min(prompt_tokens, int(last.get("reused") or 0) + int(read))


def request_timings(prompt_tokens: int, generated: int, last: dict) -> dict | None:
    """One request's `timings` in llama.cpp's names (what its clients show as speed), from the engine's own clock
    (StrataEngine.last): prompt_n is what was read, cache_n what the conversation cache already held.  None when the
    engine keeps no clock (MockEngine)."""
    if last.get("prompt_ms") is None:
        return None
    cache_n = int(last.get("reused") or 0)
    prompt_n, prompt_ms, decode_ms = max(0, prompt_tokens - cache_n), float(last["prompt_ms"]), float(last.get("decode_ms") or 0)
    decoded = int(last.get("generated") or generated)          # the engine's count gives its rate, as /metrics does
    return {"cache_n": cache_n, "prompt_n": prompt_n, "prompt_ms": round(prompt_ms, 1),
            "prompt_per_token_ms": round(prompt_ms / prompt_n, 3) if prompt_n else None,
            "prompt_per_second": round(prompt_n / (prompt_ms / 1000), 1) if prompt_n and prompt_ms > 0 else None,
            "predicted_n": generated, "predicted_ms": round(decode_ms, 1),
            "predicted_per_token_ms": round(decode_ms / decoded, 3) if decoded else None,
            "predicted_per_second": round(decoded / (decode_ms / 1000), 1) if decoded and decode_ms > 0 else None,
            # the speculative drafts, as llama.cpp names them (from PR #83, @mikicvi): only when the engine reported them
            **({"draft_n": int(last["drafts_offered"]), "draft_n_accepted": int(last["drafts_accepted"])}
               if last.get("drafts_offered") is not None else {})}


def _debug_req(api, req, messages, tools, max_new, thinking, prompt_tokens):
    """One compact line per request while diagnosing blank/empty turns. Set STRATA_DEBUG=1 to enable."""
    if not os.environ.get("STRATA_DEBUG"):
        return
    last = messages[-1] if messages else {}
    body = last.get("content")
    if isinstance(body, list):
        body = " ".join(p.get("text", "") for p in body if isinstance(p, dict))
    preview = (str(body or "")[:80]).replace("\n", " ")
    print(f"[strata] req {api}: msgs={len(messages)} tools={len(tools or [])} "
          f"max_tokens_raw={req.get('max_tokens')!r}/{req.get('max_completion_tokens')!r} "
          f"max_new={max_new} thinking={thinking} stream={bool(req.get('stream'))} "
          f"prompt_tokens={prompt_tokens} last={last.get('role')!r}:{preview!r}", flush=True)


# ------------------------------------------------------------------------------------------------ MCP tool loop
def run_with_mcp(svc: Service, hub, messages, tools, kw, ids, thinking, max_new, max_req, sampling, cancel,
                 mcp_names):
    """Service.run with the MCP tools executed here: the model writes a call to an MCP tool, the server runs it, adds
    the call and its result to the conversation and lets the model continue - up to `max_rounds` times.  Yields what
    Service.run yields (text, thinking, the request's own tool calls) plus ("mcp", {...}) for the tool activity, and
    one ("done", ...) at the very end with the output tokens of every round.

    `mcp_names`: the MCP tools this request offered; any other call is one of the request's own tools and ends the
    turn as always (the client answers it).  MCP calls written in the same answer are then not run (their results
    could not reach the model before the client's)."""
    max_rounds = int(hub.settings["max_rounds"])
    total, rounds, done = 0, 0, None
    messages = list(messages)
    finalizing = False
    while True:
        if rounds >= max_rounds and not finalizing:
            finalizing = True
            tools = None
            kw = {**kw, "enable_thinking": False}
            messages.append({"role": "user", "content": "Return the final answer to my request using the tool results already obtained. Do not request more tools; explain any missing information."})
            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_req)
            yield "mcp", {"event": "limit", "max_rounds": max_rounds}
        text, reasoning, calls, own_calls = [], [], [], 0
        announced = {}
        for kind, x in svc.run(ids, thinking, tools, max_new, sampling, cancel):
            if kind == "done":
                done = x
                continue
            if kind == "event":
                ev: Event = x
                if ev.call is not None and ev.call.name in mcp_names:
                    if ev.kind == "tool_start":          # the model has started writing a call: say so at once
                        announced[ev.call.id] = ev.call.name
                        yield "mcp", {"event": "start", "id": ev.call.id, "name": ev.call.name}
                    elif ev.kind == "tool_call":
                        calls.append(ev.call)
                    continue                             # its argument pieces are not streamed to the client
                if ev.kind == "tool_call":
                    own_calls += 1
                elif ev.kind == "content":
                    text.append(ev.text)
                elif ev.kind == "reasoning":
                    reasoning.append(ev.text)
            yield kind, x
        total += done["completion_tokens"]
        pending = set(announced) - {c.id for c in calls}
        run_them = calls and not pending and not own_calls and done["finish"] in ("stop", "length") and not cancel.is_set()
        if run_them and rounds >= max_rounds:
            yield "mcp", {"event": "limit", "max_rounds": max_rounds}
            run_them = False
        if not run_them:
            reason = "Richiesta interrotta" if cancel.is_set() else "Limite di chiamate raggiunto" if rounds >= max_rounds else "Il modello non ha completato gli argomenti: limite di token raggiunto" if pending else "Chiamata affidata al client" if own_calls else "Il modello ha terminato senza una chiamata eseguibile"
            for identity in set(announced) | {c.id for c in calls}:
                yield "mcp", {"event": "result", "id": identity, "name": announced.get(identity), "ok": False,
                              "skipped": True, "reason": "incomplete" if identity in pending else "limit" if rounds >= max_rounds else "cancelled" if cancel.is_set() else "client",
                              "text": reason, "chars": len(reason), "truncated": False, "ms": 0}
            break
        rounds += 1
        results = []
        for c in calls:
            s, tool = hub.routes().get(c.name, (None, c.name))
            yield "mcp", {"event": "call", "id": c.id, "name": c.name, "server": s.name if s else None,
                          "tool": tool, "arguments": c.arguments, "round": rounds}
            # The call runs on a thread while this generator keeps yielding heartbeats: they reach the client as
            # keep-alives, which is how a client that went away (the web app's Stop) is noticed during a slow tool.
            box = {}

            def work(c=c, box=box):
                try:
                    box["r"] = hub.call(c.name, c.arguments, cancel)
                except McpCancelled:
                    box["cancelled"] = True
            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            try:
                while worker.is_alive():
                    worker.join(1.0)
                    if worker.is_alive():
                        yield "ping", None
            except GeneratorExit:
                cancel.set()                             # the client is gone: stop the tool too
                raise
            if "r" not in box:
                break
            r = box["r"]
            print(f"[strata] tool {c.name}: {'ok' if r['ok'] else 'error'}, {r['chars']:,} characters in "
                  f"{r['ms'] / 1000:.1f} s{' (truncated for the model)' if r['truncated'] else ''}", flush=True)
            results.append(r["text"])
            yield "mcp", {"event": "result", "id": c.id, **{k: r[k] for k in ("ok", "text", "chars", "truncated", "ms")}}
        if cancel.is_set() or len(results) < len(calls):
            done = {**done, "finish": "cancel"}
            break
        messages.append({"role": "assistant", "content": "".join(text).strip(),
                         **({"reasoning_content": "".join(reasoning).strip()} if reasoning else {}),
                         "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in calls]})
        messages += [{"role": "tool", "content": r} for r in results]
        ids, thinking, max_new = svc.prepare(messages, tools, kw, max_req)
    yield "done", {**done, "completion_tokens": total, "prompt_tokens": len(ids)}


# ------------------------------------------------------------------------------------------------ OpenAI
def openai_chunks(svc: Service, req: dict, ids, thinking, tools, max_new, cancel, run=None):
    """`run`: the events to send instead of Service.run's (run_with_mcp); its ("mcp", {...}) items become chunks with
    an empty delta and a `strata_mcp` field, which only the web app reads."""
    cid, created = "chatcmpl-" + uuid.uuid4().hex[:24], int(time.time())
    model = svc.model_for(req)

    def chunk(delta, finish=None):
        return {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    yield chunk({"role": "assistant", "content": ""})
    calls = 0
    streamed = {}                                  # tool call id -> index, for calls sent piece by piece
    finished = set()                               # ... and the ones whose final tool_call came (#211)
    for kind, x in run if run is not None else svc.run(ids, thinking, tools, max_new, req, cancel):
        if kind == "ping":
            yield None
        elif kind == "mcp":
            c = chunk({})
            c["strata_mcp"] = x
            yield c
        elif kind == "event":
            ev: Event = x
            if ev.kind == "reasoning" and ev.text:
                yield chunk({"reasoning_content": ev.text})
            elif ev.kind == "content" and ev.text:
                yield chunk({"content": ev.text})
            elif ev.kind == "tool_start":
                streamed[ev.call.id] = calls
                calls += 1
                yield chunk({"tool_calls": [{"index": streamed[ev.call.id], "id": ev.call.id, "type": "function",
                                             "function": {"name": ev.call.name, "arguments": ""}}]})
            elif ev.kind == "tool_args":
                yield chunk({"tool_calls": [{"index": streamed[ev.call.id], "function": {"arguments": ev.text}}]})
            elif ev.kind == "tool_call" and ev.call.id in streamed:
                finished.add(ev.call.id)
            elif ev.kind == "tool_call":
                yield chunk({"tool_calls": [{"index": calls, "id": ev.call.id, "type": "function",
                                             "function": {"name": ev.call.name,
                                                          "arguments": json.dumps(ev.call.arguments, ensure_ascii=False)}}]})
                calls += 1
        else:
            # a streamed call without its final tool_call is one the output ended inside: not "tool_calls" (#211)
            whole = calls and streamed.keys() <= finished
            finish = "tool_calls" if whole and x["finish"] == "stop" else {"cancel": "stop"}.get(x["finish"], x["finish"])
            last = chunk({}, finish)
            pt = x.get("prompt_tokens", len(ids))     # after MCP rounds: the last round's prompt
            last["usage"] = {"prompt_tokens": pt, "completion_tokens": x["completion_tokens"],
                             "total_tokens": pt + x["completion_tokens"],
                             # the part of the prompt the conversation cache already held (OpenAI's field)
                             "prompt_tokens_details": {"cached_tokens": x.get("reused") or 0}}
            if x.get("timings"):
                last["timings"] = x["timings"]          # llama.cpp's field: the speed its clients show
            yield last


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


def openai_collect(chunks) -> dict:
    content, reasoning, by_index, last, mcp = [], [], {}, None, []
    for c in chunks:
        if c is None:                              # a heartbeat
            continue
        if c.get("strata_mcp"):
            mcp.append(c["strata_mcp"])
        d = c["choices"][0]["delta"]
        content.append(d.get("content") or "")
        reasoning.append(d.get("reasoning_content") or "")
        for tc in d.get("tool_calls") or []:       # streamed calls arrive in pieces: merge them by index
            cur = by_index.setdefault(tc.get("index", len(by_index)), {"id": None, "type": "function",
                                                                        "function": {"name": "", "arguments": ""}})
            cur["id"] = tc.get("id") or cur["id"]
            fn = tc.get("function") or {}
            cur["function"]["name"] += fn.get("name") or ""
            cur["function"]["arguments"] += fn.get("arguments") or ""
        last = c
    calls = [by_index[i] for i in sorted(by_index)]
    if last["choices"][0]["finish_reason"] != "tool_calls":
        calls = [c for c in calls if _is_json(c["function"]["arguments"])]   # a call the output ended inside (#211)
    msg = {"role": "assistant", "content": "".join(content) or None}
    if "".join(reasoning):
        msg["reasoning_content"] = "".join(reasoning)
    if calls:
        msg["tool_calls"] = calls
    if mcp:
        msg["strata_mcp"] = mcp
    out = {"id": last["id"], "object": "chat.completion", "created": last["created"], "model": last["model"],
           "choices": [{"index": 0, "message": msg, "finish_reason": last["choices"][0]["finish_reason"]}],
           "usage": last["usage"]}
    if last.get("timings"):
        out["timings"] = last["timings"]
    if last.get('strata_execution'):out['strata_execution']=last['strata_execution']
    return out


def structured_chunks(chunks, validator):
    """Buffer structured streams so a client never receives unvalidated content."""
    buffered = []
    heartbeat = time.monotonic()
    try:
        for chunk in chunks:
            if chunk is not None:
                buffered.append(chunk)
            if chunk is None or time.monotonic() - heartbeat >= 1:
                heartbeat = time.monotonic()
                yield None
        result = openai_collect(buffered)
        choice = result["choices"][0]
        content = validated_json(choice["message"]["content"], validator, choice["finish_reason"])
        yield buffered[0]
        delta = {"content": content}
        if choice["message"].get("reasoning_content"):
            delta["reasoning_content"] = choice["message"]["reasoning_content"]
        yield {**buffered[0], "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
        yield buffered[-1]
    finally:
        chunks.close()


# ------------------------------------------------------------------------------------------------ Anthropic
def anthropic_events(svc: Service, req: dict, ids, thinking, tools, max_new, cancel):
    mid = "msg_" + uuid.uuid4().hex[:24]
    yield "message_start", {"type": "message_start", "message": {
        "id": mid, "type": "message", "role": "assistant", "model": svc.model_for(req), "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": len(ids), "output_tokens": 0}}}
    index, open_kind, used_tool = -1, None, False

    def close():
        return ("content_block_stop", {"type": "content_block_stop", "index": index})

    streamed, finished = set(), set()              # calls sent piece by piece; those whose final tool_call came (#211)
    for kind, x in svc.run(ids, thinking, tools, max_new, req, cancel):
        if kind == "ping":
            yield None
            continue
        if kind == "event":
            ev: Event = x
            if ev.kind == "tool_args":
                yield "content_block_delta", {"type": "content_block_delta", "index": index,
                                              "delta": {"type": "input_json_delta", "partial_json": ev.text}}
                continue
            if ev.kind == "tool_call" and ev.call.id in streamed:
                finished.add(ev.call.id)
                continue
            want = {"reasoning": "thinking", "content": "text", "tool_call": "tool_use", "tool_start": "tool_use"}[ev.kind]
            if ev.kind not in ("tool_call", "tool_start") and not ev.text:
                continue
            if ev.kind == "tool_start":
                streamed.add(ev.call.id)
                used_tool = True
            if open_kind != want or want == "tool_use":
                if open_kind is not None:
                    yield close()
                index += 1
                open_kind = want
                block = {"thinking": {"type": "thinking", "thinking": "", "signature": ""},
                         "text": {"type": "text", "text": ""},
                         "tool_use": {"type": "tool_use", "id": ev.call.id if ev.call else "", "name":
                                      ev.call.name if ev.call else "", "input": {}}}[want]
                yield "content_block_start", {"type": "content_block_start", "index": index, "content_block": block}
            if want == "thinking":
                yield "content_block_delta", {"type": "content_block_delta", "index": index,
                                              "delta": {"type": "thinking_delta", "thinking": ev.text}}
            elif want == "text":
                yield "content_block_delta", {"type": "content_block_delta", "index": index,
                                              "delta": {"type": "text_delta", "text": ev.text}}
            elif ev.kind == "tool_start":
                pass                                # its input follows as tool_args pieces
            else:
                used_tool = True
                yield "content_block_delta", {"type": "content_block_delta", "index": index, "delta": {
                    "type": "input_json_delta", "partial_json": json.dumps(ev.call.arguments, ensure_ascii=False)}}
        else:
            if open_kind is not None:
                yield close()
            stop = "tool_use" if used_tool and streamed <= finished and x["finish"] == "stop" else \
                {"stop": "end_turn", "length": "max_tokens", "cancel": "end_turn"}[x["finish"]]
            # the final counts, Anthropic's way: input_tokens leaves out what the conversation cache already held,
            # which is cache_read_input_tokens (message_start could only say the whole prompt)
            reused = min(x.get("reused") or 0, len(ids))
            yield "message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                    "usage": {"input_tokens": len(ids) - reused, "cache_read_input_tokens": reused,
                                              "output_tokens": x["completion_tokens"]}}
            yield "message_stop", {"type": "message_stop"}


def anthropic_collect(events) -> dict:
    msg, blocks = None, []
    for item in events:
        if item is None:                           # a heartbeat
            continue
        name, e = item
        if name == "message_start":
            msg = e["message"]
        elif name == "content_block_start":
            blocks.append(dict(e["content_block"]))
        elif name == "content_block_delta":
            d, b = e["delta"], blocks[-1]
            if d["type"] == "text_delta":
                b["text"] += d["text"]
            elif d["type"] == "thinking_delta":
                b["thinking"] += d["thinking"]
            else:                                  # input_json_delta pieces: parsed when complete
                b["_json"] = b.get("_json", "") + d["partial_json"]
        elif name == "content_block_stop" and blocks and "_json" in blocks[-1]:
            b = blocks[-1]
            try:
                b["input"] = json.loads(b.pop("_json") or "{}")
            except ValueError:                     # a call the output ended inside (#211): it has no input to give
                blocks.pop()
        elif name == "message_delta":
            msg["stop_reason"] = e["delta"]["stop_reason"]
            msg["usage"].update(e["usage"])
    msg["content"] = blocks
    return msg


# ------------------------------------------------------------------------------------------------ HTTP
def start_harness_idle_stop(svc):
    """Release harnesses that nobody used for a while.

    A harness is only stopped when it is ready, its activity is readable and it reports no
    open session. Conversation archives live in data/<kind>-home on disk, so nothing is
    lost: the harness starts again from the same home. Enabled with
    STRATA_HARNESS_IDLE_STOP=<seconds>; disabled by default.
    """
    budget = float(os.environ.get("STRATA_HARNESS_IDLE_STOP", "0") or 0)
    if not budget:
        return

    def loop():
        while True:
            time.sleep(max(30.0, min(300.0, budget / 4)))
            for kind in ("opencode", "dsh", "trueforge", "hermes"):
                try:
                    harness = agent_harness_for(svc, kind)
                    if not harness.idle_stop_s:
                        harness.idle_stop_s = budget
                    if not harness.idle_should_stop():
                        continue
                    harness.stop()
                    print(f"[strata] {kind} released after {budget:.0f}s without use", flush=True)
                except Exception as error:                     # a failing kind must not stop the loop
                    print(f"[strata] idle release of {kind}: {error}", flush=True)

    threading.Thread(target=loop, daemon=True).start()


def agent_harness_for(svc, kind="opencode", host=None):
    """Lazily build one agent-harness manager (`opencode` or `dsh`) beside Strata.

    Built on first use, not in Service.__init__, so a server that never opens a Harness
    tab pays nothing and never imports serve.agent_harness (which pulls psutil through
    gpu_lease). Each harness is fed by this same server's model and by the same MCP servers
    the chat page uses; its own config is written under data/.
    """
    kinds = {"claude": ("agent_harness_claude", 0), "opencode": ("agent_harness", 4096), "dsh": ("agent_harness_dsh", 3080),"trueforge":("agent_harness_trueforge",8790),"hermes":("agent_harness_hermes",9120)}
    if kind not in kinds:
        kind = "opencode"
    attr, port = kinds[kind]
    with svc.status_lock:
        harness = getattr(svc, attr, None)
        if harness is not None:
            if not harness.status().get('busy'):
                from serve.harness_model import local_selection
                selection = local_selection(svc)
                if kind=='claude':
                    harness.model='strata'
                    harness.context_budget=selection['context']
                    harness.output_budget=selection['output']
                else:harness.model_id = 'strata'
                harness.model_context = selection['context']
                harness.model_output = selection['output']
                harness.api_key = svc.api_key
            return harness
        from serve.agent_harness import AgentHarness
        page = f"http://{host}" if host else "http://127.0.0.1:8080"
        own = urlsplit(page)
        if own.port == 8090:
            port += 100
        from serve.headroom_integration import ensure_proxy
        inference_base = ensure_proxy(ROOT, f'http://{own.hostname}:{own.port or 80}')
        if kind == 'claude':
            from serve.claude_harness import ClaudeHarness
            harness = ClaudeHarness(ROOT, base_url=inference_base, model_id='strata', api_key=svc.api_key)
            from serve.harness_model import local_selection
            selection=local_selection(svc)
            harness.model='strata'
            harness.context_budget=selection['context']
            harness.output_budget=selection['output']
            setattr(svc, attr, harness)
            return harness
        from serve.harness_model import local_selection
        selection = local_selection(svc)
        harness = AgentHarness(
            ROOT, kind=kind, port=port, api_key=svc.api_key, model_id="strata",
            cors_origin=page if kind == "opencode" else None,
            base_url=inference_base+"/v1",
            model_context=selection["context"],
            model_output=selection["output"],
        )
        setattr(svc, attr, harness)
        return harness


def make_handler(svc: Service):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"                       # SSE ends by closing the connection

        record = None                                       # #332: this request's monitor record, if kept
        watch_done = None                                   # #430 #431: stops this request's disconnect watcher

        def log_message(self, fmt, *args):
            pass

        def parse_request(self):
            """Without an API key, every request (any method) first passes the Host check: DNS rebinding protection
            (host_allowed).  With a key a rebinding page cannot authenticate, so the check is skipped: tunnels and
            proxies that pass their own name on keep working."""
            if not super().parse_request():
                return False
            host = self.headers.get("Host")
            if svc.api_key or host_allowed(host, svc.host_names, "*" in svc.allowed_hosts):
                return True
            print(f"[strata] refused a request for Host {host!r} from {self.client_address[0]}: not a name this server "
                  f"answers to (add it to \"allowed_hosts\" in the config or STRATA_ALLOWED_HOSTS, or set an API key)",
                  flush=True)
            self._json(403, {"error": {"type": "forbidden", "message":
                             f"Host {host!r} is not allowed (DNS rebinding protection). Reaching Strata under this "
                             f"name on purpose? Add it to \"allowed_hosts\" in the config (strata-<model>.json) or to "
                             f"the STRATA_ALLOWED_HOSTS environment variable, or set an API key (\"api_key\"), which "
                             f"turns this check off"}})
            return False

        def _foreign_page(self,allow_multipart=False) -> bool:
            """Without an API key, a /v1 POST from a browser page of another site (any site can POST text/plain
            there without a CORS preflight) would burn GPU time: an Origin header must name an allowed page, and
            then the body must be JSON.  No Origin (curl, the SDKs, other servers): any content type, as before."""
            origin = self.headers.get("Origin")
            if svc.api_key or not origin:
                return False
            if not origin_allowed(origin, self.headers.get("Host"), svc.host_names,
                                  [*svc.trusted_origins, *svc.cors_origins]):
                print(f"[strata] refused an API request from the web page {origin!r} (no API key; add its host to "
                      f"\"allowed_hosts\" or its origin to \"cors_origins\" in the config)", flush=True)
                self._json(403, {"error": {"type": "forbidden", "message":
                                 f"web pages of {origin} may not use this server without an API key; set \"api_key\", "
                                 f"or add the page's host to \"allowed_hosts\" (or its origin to \"cors_origins\") "
                                 f"in the config"}})
                return True
            content_type=self.headers.get("Content-Type", "")
            if not content_type.startswith("application/json") and not (allow_multipart and content_type.startswith('multipart/form-data;')):
                self._json(415, {"error": {"message": "send application/json"}})
                return True
            return False

        def _watch_client(self, cancel: threading.Event) -> None:
            """#430 #431: cancel the request as soon as its client hangs up.  A non-streamed request writes nothing
            until it ends, and a streamed one only a keep-alive per prompt chunk (and the first write after a hang-up
            usually still succeeds), so a dropped request kept the engine busy until its answer or the whole prompt
            was done.  Every 0.5 s: the socket readable with nothing to read (EOF) means the client closed it.  A
            request is HTTP/1.0 and fully read here, so no later bytes are expected - data is not a hang-up."""
            done = self.watch_done = threading.Event()
            sock = self.connection

            def watch():
                while not done.wait(0.5) and not cancel.is_set():
                    try:
                        readable, _, _ = select.select([sock], [], [], 0)
                        gone = bool(readable) and sock.recv(1, socket.MSG_PEEK) == b""
                    except (ConnectionError, TimeoutError):
                        gone = True
                    except (OSError, ValueError):            # the socket was closed here: the request has ended
                        return
                    if gone:
                        self._note(outcome="disconnected")
                        cancel.set()
                        return

            threading.Thread(target=watch, daemon=True, name="strata-client-watch").start()

        def _note(self, **values):
            """#332: what the monitor shows about this request (nothing when the monitor is off)."""
            if self.record is not None:
                with svc.status_lock:
                    self.record.update(values)

        def _cors(self):
            """#321: CORS headers for an API path (/v1/*) and an origin the config lists in cors_origins - nothing
            otherwise, so a browser keeps every other page away from the API, /settings, /unload and the MCP tools."""
            if not svc.cors_origins or not self.path.split("?")[0].startswith("/v1/"):
                return
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if "*" in svc.cors_origins:
                allow = "*"
            elif origin and origin in svc.cors_origins:
                allow = origin
                self.send_header("Vary", "Origin")
            else:
                return
            self.send_header("Access-Control-Allow-Origin", allow)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            # the headers the preflight asks for (SDKs add their own; "*" does not cover Authorization)
            asked = self.headers.get("Access-Control-Request-Headers")
            self.send_header("Access-Control-Allow-Headers",
                             asked or "Authorization, Content-Type, x-api-key, anthropic-version, anthropic-beta")
            self.send_header("Access-Control-Max-Age", "600")

        def do_OPTIONS(self):
            # a CORS preflight: no credentials come with it, so no API key; the headers only for cors_origins
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _read_body(self):
            if not hasattr(self, "_body"):
                self._body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            return self._body

        def _json(self, code, obj):
            # Closing a Windows socket with an unread POST body can reset the
            # connection before the client receives the response, including successful
            # actions such as /unload. Drain small bodies with a bounded wait.
            if self.command == "POST" and not hasattr(self, "_body"):
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    if 0 < size <= 65536:
                        old_timeout = self.connection.gettimeout()
                        try:
                            self.connection.settimeout(2)
                            self._read_body()
                        finally:
                            self.connection.settimeout(old_timeout)
                except (OSError, ValueError):
                    pass
            if self.record is not None:
                with svc.status_lock:
                    self.record["http_status"] = code
                    raw = json.dumps(obj, ensure_ascii=False, indent=2)
                    self.record.update(response=raw[:262144], response_truncated=len(raw) > 262144)
                    for key in ("error", "usage", "timings"):
                        if key in obj:
                            self.record[key] = obj[key]
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not svc.api_key:
                return True
            auth = self.headers.get("Authorization", "")
            given = auth[7:].strip() if auth.lower().startswith("bearer ") else self.headers.get("x-api-key", "")
            if hmac.compare_digest(given.encode(), svc.api_key.encode()):   # #213: constant-time
                return True
            self._json(401, {"error": {"type": "authentication_error", "message": "missing or wrong API key"}})
            return False

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            if os.environ.get('HYDRA_LAB_MODE')!='1' and path.startswith('/lab/benchmarks/api/'):
                if not self._authorized():return
                from serve.hydra_lab_integration import readonly_route
                try:readonly_route(self,ROOT,path)
                except (ValueError,OSError) as exc:self._json(404,{'error':str(exc)})
                return
            if os.environ.get('HYDRA_LAB_MODE')=='1' and path.startswith('/lab/benchmarks/'):
                from serve.hydra_lab_integration import route,service_lab
                try:route(self,service_lab(svc),'GET',path)
                except (OSError,ValueError) as exc:self._json(503,{'error':str(exc)})
                return
            from serve.hydra_native import route as hydra_native_route
            if hydra_native_route(self,svc,path):return
            from serve.original_harness_routes import get as original_get
            if original_get(self,svc,path):return
            from serve.generation_routes import get as generation_get
            if generation_get(self,svc,path):return
            from serve.native_workspace_routes import get as native_get
            if native_get(self,svc,path):return
            from serve.automatic_update_routes import get as automatic_get
            if automatic_get(self,svc,path):return
            from serve.model_engine_routes import get as model_engine_get
            if model_engine_get(self,svc,path):return
            if path == '/multimedia-capabilities':
                if self._authorized():
                    from serve.multimedia_capabilities import capabilities
                    self._json(200,capabilities(svc))
                return
            if path == '/inference-backends':
                if self._authorized():self._json(200,svc.optional_backends.status())
                return
            if path == '/local-separation':
                if self._authorized():self._json(200,svc.local_separation.status())
                return
            if path == '/local-speech':
                if self._authorized():self._json(200,svc.local_speech.status())
                return
            if path == '/local-speech/library' or path.startswith('/local-speech/artifact/'):
                if not self._authorized():return
                from serve.audio_library import AudioLibrary
                library=AudioLibrary(ROOT)
                try:
                    if path.endswith('/library'):self._json(200,{'items':library.list(),'limit_items':100,'limit_bytes':1024**3})
                    else:
                        data=library.read(path.removeprefix('/local-speech/artifact/'))
                        self.send_response(200);self.send_header('Content-Type','audio/wav');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','private, no-store');self.end_headers();self.wfile.write(data)
                except (OSError,ValueError) as error:self._json(404,{'error':{'message':str(error)}})
                return
            if path == '/local-audio':
                if self._authorized():self._json(200,svc.local_audio.status())
                return
            if path == '/voicestudio/engines':
                try:self._json(200,svc.voicestudio.engines())
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/open-webui/documents':
                from serve.open_webui_runtime import library as open_webui_library
                self._json(200,open_webui_library(ROOT));return
            if path == '/open-webui':
                from serve.open_webui_runtime import status as open_webui_status
                self._json(200,svc.open_webui_setup.status());return
            if path == '/airllm':
                if self._authorized():self._json(200,svc.airllm_setup.status())
                return
            if path == '/voicestudio/workspace':
                if not self._own_page('Profili vocali di questa pagina'):return
                try:self._json(200,svc.voicestudio.workspace())
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/voicestudio/activities':
                if not self._own_page('Attività vocali di questa pagina'):return
                try:self._json(200,svc.voicestudio.activities())
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/voicestudio','/voicestudio/voices','/voicestudio/setup'):
                if not self._authorized():return
                try:self._json(200,svc.voicestudio.voices() if path.endswith('/voices') else svc.voicestudio.setup() if path.endswith('/setup') else svc.voicestudio.status())
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/harness/antigravity/status':
                if self._authorized():
                    from serve.antigravity_desktop import status
                    self._json(200,{'status':'desktop','desktop':status(ROOT),'web':svc.antigravity_web.status()})
                return
            if path == '/local-training':
                if self._authorized():self._json(200,svc.local_training.status())
                return
            if path == '/updates/health':
                if self._authorized():self._json(200,svc.update_center.dependency_supervisor.status())
                return
            if path == '/updates':
                if self._authorized():self._json(200,svc.update_center.status())
                return
            if path == '/local-export':
                if self._authorized():self._json(200,svc.local_export.status())
                return
            if path == '/optional-catalogue':
                if self._authorized():self._json(200,svc.optional_catalogue.status())
                return
            if path == '/benchmark-lab':
                if self._authorized():
                    data=svc.benchmark_lab.status();data['operational_loaded']=svc.loaded()
                    optional=svc.optional_backends.status();job,history=svc.optional_benchmark.status()
                    data['optional_ready']=optional['status']=='ready'
                    if data['optional_ready']:
                        active_name=next((m['name'] for m in optional.get('local_models',[]) if m.get('path')==optional.get('model_path')),optional['public_model'])
                        data['models'].insert(0,dict(id='optional_active',label=active_name+' · '+optional.get('backend','Motore locale')+' · '+optional['device_requested'],ready=True))
                    for model in optional.get('local_models',[]):
                        if model.get('runtime_supported') is False:continue
                        if data['optional_ready'] and model['path']==optional.get('model_path'):continue
                        data['models'].append(dict(id='optional_local:'+model['path'],label=model['name']+' · '+model.get('format','GGUF')+' · Unsloth',ready=True,requires_load=True))
                    from serve.benchmark_state import merge_benchmark_state
                    data=merge_benchmark_state(data,job,history,optional.get('public_model') if data['optional_ready'] else None)
                    self._json(200,data)
                return
            if path.startswith("/fonts/"):
                # the web app's font (Outfit, OFL: serve/web/fonts); the page falls back to the system font
                name = path[len("/fonts/"):]
                f = ROOT / "serve" / "web" / "fonts" / name
                if "/" in name or "\\" in name or not name.endswith(".woff2") or not f.is_file():
                    self._json(404, {"error": {"message": "not found"}})
                    return
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "font/woff2")
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/web/"):
                # the web app's own files (serve/web): styles, script, icon sprite - same origin, no CDN
                name = path[len("/web/"):]
                types = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                         ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
                         ".jpeg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon"}
                # Only this public evidence snapshot is served as JSON; configs
                # and other JSON files remain outside the static-file allowlist.
                if name == "performance-evidence.json":
                    types[".json"] = "application/json; charset=utf-8"
                f = ROOT / "serve" / "web" / name
                ext = os.path.splitext(name)[1]
                if "/" in name or "\\" in name or ext not in types or not f.is_file():
                    self._json(404, {"error": {"message": "not found"}})
                    return
                body = f.read_bytes()
                import hashlib
                etag='"'+hashlib.sha256(body).hexdigest()+'"'
                if self.headers.get('If-None-Match')==etag:
                    self.send_response(304);self.send_header('ETag',etag);self.send_header('Cache-Control','no-cache');self.end_headers();return
                self.send_response(200)
                self.send_header('ETag',etag)
                self.send_header("Content-Type", types[ext])
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/metrics":
                if self._authorized():
                    # the last 12 requests; `?requests=all` every one kept (the Monitor's "Show all", issue #35)
                    result = svc.metrics(all_requests="requests=all" in self.path)
                    from serve.benchmark_monitor import snapshot
                    result['benchmark'] = snapshot()
                    self._json(200, result)
                return
            if path == "/api/requests" and svc.api_monitor:
                if self._authorized():
                    request_id = parse_qs(urlsplit(self.path).query).get("id", [None])[0]
                    records = svc.request_records(request_id)
                    self._json(404 if records is None else 200,
                               {"error": {"message": "request no longer retained"}} if records is None else
                               records if request_id else {"requests": records, "retention": 100, "persistent": False,
                                                          "loaded": svc.loaded(), "auto_load": hasattr(svc.engine, "restart")})
                return
            if path == "/settings":
                if self._authorized():
                    self._json(200, {"shared": bool(svc.shared), "defaults": svc.shared})
                return
            if path == "/power":
                if self._authorized():
                    self._json(200, svc.power_manager.get_state().__dict__ | {
                        "mode": svc.power_manager.config.mode,
                        "temp_limit": svc.power_manager.config.temp_limit(),
                        "power_limit": svc.power_manager.config.power_limit(),
                        "history": [s.__dict__ for s in svc.power_manager.get_history()],
                    })
                return
            if path == "/config":
                if self._authorized():
                    self._json(200, {**svc.resource_state(), "setup": svc.setup_state(),
                                     "prepared": svc.prepared_models()})
                return
            if path == "/catalogue":
                if self._authorized():
                    self._json(200, svc.catalogue_state())
                return
            if path == "/benchmarks":
                if self._authorized():
                    from serve.diagnostics import benchmark_reports
                    from serve.benchmark_records import best_groups
                    result=benchmark_reports(ROOT)
                    from serve.optional_reports import reports as optional_reports
                    result['reports'] += optional_reports(ROOT)
                    if os.environ.get('HYDRA_LAB_MODE')=='1' and os.environ.get('HYDRA_LAB_PROFILE'):
                        from serve.hydra_lab_integration import existing_reports,service_lab
                        rows=existing_reports(service_lab(svc).benchmarks)
                        present={r.get('hydra_run_id') for r in result['reports']}
                        result['reports'] += [r for r in rows if r['hydra_run_id'] not in present]
                    result['best_groups']=best_groups(ROOT,svc.model)
                    optional=svc.optional_backends.status()
                    if optional['status']=='ready':
                        from serve.optional_reports import best_groups as optional_best
                        result['best_groups']=optional_best(optional_reports(ROOT),optional['public_model'])
                    self._json(200, result)
                return
            if path == "/mcp":
                # the MCP servers, their state and tools (the web app's switch and Monitor card)
                if self._authorized():
                    self._json(200, svc.mcp.status() if svc.mcp else {"servers": [], "tools": 0})
                return
            if path in ('/harness/mcp','/harness/browser-mcp','/harness/memory-mcp'):
                self._json(405,{'error':{'message':'This stateless MCP bridge accepts POST only'}});return
            if path.startswith("/harness/"):
                # one agent harness beside Strata (the Harness tabs): installed? running? where?
                parts = path.split("/")
                if len(parts) == 4 and parts[2] in ("opencode", "dsh", "trueforge", "hermes", "claude") and parts[3] == "status":
                    if self._authorized():
                        from serve.harness_model import local_selection
                        snapshot = {**agent_harness_for(svc, parts[2], self.headers.get("Host")).status(), 'binding': local_selection(svc)}
                        if parts[2] == 'claude':
                            from serve.claude_desktop import status as desktop_status
                            snapshot['desktop'] = desktop_status(ROOT)
                        self._json(200, snapshot)
                return
            if path in ('/updates/restart-pending','/updates/restart','/updates/restart-dismiss'):
                if not self._own_page('riavvio dopo aggiornamento gestito da questa pagina'):return
                from serve.update_restart import restart_pending,clear_restart_pending,restart_command
                if path.endswith('/dismiss'):
                    self._json(200,{'dismissed':bool(clear_restart_pending(ROOT))});return
                if path.endswith('/restart-pending'):
                    pending=restart_pending(ROOT)
                    self._json(200,{'pending':pending});return
                import subprocess,sys
                try:
                    if not svc.update_center.operational_idle() or not svc.automatic_updates.activities_idle():raise ValueError('Il riavvio attende la fine delle attività in corso')
                    pending=restart_pending(ROOT)
                    if pending:pending['restarting']=True
                    self._json(202,{'restarting':True,'component':(pending or {}).get('component')})
                    self.wfile.flush()
                except (OSError,RuntimeError,ValueError) as error:
                    self._json(400,{'error':{'message':str(error)}});return
                # The new process starts only after this one released the port.
                svc.automatic_restart();return
            if path == '/chat/archive':
                # Durable copy of the browser's chat archive: a lost profile or a private
                # window must never cost a conversation.
                if not self._own_page('archivio conversazioni gestito da questa pagina'):return
                from serve.chat_archive import read_archive,save_archive
                if self.command=='POST':
                    if not 0<int(self.headers.get('Content-Length',0))<=24*1024**2:
                        self._json(413,{'error':{'message':'Archivio conversazioni oltre il limite'}});return
                    try:
                        rows=json.loads(self._read_body())
                        if not isinstance(rows,list):raise ValueError('Atteso un elenco di conversazioni')
                        count=save_archive(ROOT,rows)
                        self._json(200,{'saved':count})
                    except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                    return
                self._json(200,{'conversations':read_archive(ROOT)})
                return
            if path == "" or (path == "/api-monitor" and svc.api_monitor):
                from serve.web_asset_versions import versioned_html
                body = versioned_html(ROOT / "serve" / "web" / ("monitor.html" if path else "index.html"))
                if os.environ.get("HYDRA_LAB_MODE")=="1":
                    from serve.hydra_lab_integration import render_lab_html
                    body=render_lab_html(body)
                from serve.hydra_lab_integration import history_html
                body=history_html(body,ROOT)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                # No caching on the page itself: without this the browser keeps serving an older
                # dashboard (older markup, older metrics) while the files on disk are current.
                self.send_header("Cache-Control", "no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path in ("/health", "/api/health"):
                data={"status": "ok", "max_context": svc.engine.max_context, "model": svc.model,
                                 "images": svc.vision is not None, "api_key": bool(svc.api_key),
                                 "loaded": svc.loaded(), "service": "strata"}
                owner=getattr(svc,'cfg',{}).get('benchmark_owner')
                if owner:data['benchmark_owner']=owner
                self._json(200,data)
            elif path == "/status":
                if not self._authorized():                  # #212: it shows the end of the last answer
                    return
                with svc.status_lock:
                    s = dict(svc.status)
                now = time.time()
                if s.get("busy"):
                    s["elapsed_s"] = round(now - s["started"], 1)
                    if s.get("first_token"):
                        s["tokens_per_s"] = round(svc._tok_s(), 1)
                        s["tokens_per_s_mean"] = round(svc._tok_s_mean(), 1)
                for k in ("started", "first_token"):
                    s.pop(k, None)
                self._json(200, s)
            elif path in ("/v1/models", "/models"):
                if self._authorized():
                    loaded = svc.loaded()
                    model = {"id": svc.model, "object": "model", "status": {"value": "loaded"},
                             "meta": {"n_ctx": svc.engine.max_context},
                             "architecture": {"input_modalities": ["text", "image"] if svc.vision is not None else ["text"],
                                              "output_modalities": ["text"]}}
                    if not loaded and (svc.idle_unload_s or getattr(svc.engine, "unloaded", False)):
                        model["status"] = {"value": "unloaded"}   # like llama-server's router: listed, loads on use
                        loaded = True
                    if svc.aliases:                       # #297: the aliases, and each one listed under its own id
                        model["aliases"] = list(svc.aliases)
                    data = [model, *({**model, "id": x, "alias_of": svc.model} for x in svc.aliases)]
                    data=data if loaded else []
                    optional=svc.optional_backends.status()
                    if optional['status']=='ready':data.append({'id':optional['public_model'],'object':'model','owned_by':'local','status':{'value':'loaded'}})
                    from serve.harness_model import local_selection
                    selection=local_selection(svc)
                    data=[row for row in data if row['id']!='strata']
                    if loaded or optional.get('status')=='ready':
                        data.append({'id':'strata','object':'model','alias_of':selection['model'],
                                     'meta':{'n_ctx':selection['context']},'owned_by':'local',
                                     'status':{'value':'loaded' if optional.get('status')=='ready' or svc.loaded() else 'unloaded'}})
                    from serve.claude_desktop import gateway_models
                    self._json(200, {"object": "list", "data": gateway_models(data)})
            elif path == "/props":
                if self._authorized():
                    self._props()
            elif path == "/slots":
                if self._authorized():
                    loaded = not hasattr(svc.engine, "alive") or svc.engine.alive()
                    with svc.status_lock:
                        busy = bool(svc.status.get("busy"))
                    slot = {"id": 0, "n_ctx": svc.engine.max_context, "is_processing": busy}
                    self._json(200, [slot] if loaded else [])
            elif path == "/v1/status":
                if self._authorized():
                    result=svc.v1_status();optional=svc.optional_backends.status()
                    result['active_backend']=dict(engine=optional.get('backend') if optional['status']=='ready' else 'Strata',
                        model=optional.get('public_model') if optional['status']=='ready' else svc.model,
                        context=optional.get('context_per_slot') if optional['status']=='ready' else None,
                        model_max_context=optional.get('model_max_context') if optional['status']=='ready' else None,
                        state=optional['status'] if optional['status']=='ready' else 'loaded' if svc.loaded() else 'unloaded')
                    self._json(200,result)
            else:
                self._json(404, {"error": {"message": "not found"}})

        def do_POST(self):
            if not self._authorized():
                return
            path = self.path.split("?")[0].rstrip("/")   # issue #55: Claude Code posts /v1/messages?beta=true
            if os.environ.get('HYDRA_LAB_MODE')=='1' and path.startswith('/lab/benchmarks/'):
                from serve.hydra_lab_integration import route,service_lab
                try:route(self,service_lab(svc),'POST',path)
                except (OSError,ValueError) as exc:self._json(503,{'error':str(exc)})
                return
            from serve.hydra_native import route as hydra_native_route
            if hydra_native_route(self,svc,path,post=True):return
            from serve.hydra_control import route as hydra_control_route
            if hydra_control_route(self,svc,path):return
            from serve.original_harness_routes import post as original_post
            if original_post(self,svc,path):return
            from serve.generation_routes import post as generation_post
            if generation_post(self,svc,path):return
            from serve.native_workspace_routes import post as native_post
            if native_post(self,svc,path):return
            from serve.automatic_update_routes import post as automatic_post
            if automatic_post(self,svc,path):return
            if path == '/open-webui/prepare':
                if not self._own_page('Runtime Open WebUI interno richiesto da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=1024:raise ValueError('Invalid Open WebUI preparation request')
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict):raise ValueError('Invalid Open WebUI preparation request')
                    self._json(202,svc.open_webui_setup.prepare(payload.get('version')))
                except (OSError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/open-webui/documents/upload','/open-webui/documents/metadata','/open-webui/documents/read','/open-webui/documents/search-library','/open-webui/documents/search','/open-webui/documents/remove','/open-webui/documents/attach','/open-webui/documents/cancel','/open-webui/documents/import-embedding','/open-webui/context'):
                if not self._own_page('Funzioni Open WebUI interne richieste da questa pagina'):return
                try:
                    limit=12*1024*1024 if path.endswith('/upload') else 2*1024*1024 if path.endswith('/context') else 16384
                    if not 0<int(self.headers.get('Content-Length',0))<=limit:raise ValueError('Open WebUI request exceeds size limit')
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict):raise ValueError('Invalid Open WebUI request')
                    from serve import open_webui_runtime
                    if path.endswith('/import-embedding'):result=open_webui_runtime.import_embedding(ROOT,payload)
                    elif path.endswith('/cancel'):result=open_webui_runtime.cancel(ROOT)
                    elif path.endswith('/context'):result=open_webui_runtime.context(ROOT,payload.get('messages'))
                    else:result={'metadata':open_webui_runtime.metadata,'read':open_webui_runtime.read,'search-library':open_webui_runtime.search_library,'upload':open_webui_runtime.upload,'search':open_webui_runtime.search,'remove':open_webui_runtime.remove,'attach':open_webui_runtime.attach}[path.rsplit('/',1)[1]](ROOT,payload)
                    self._json(200,result)
                except (OSError,RuntimeError,ValueError,KeyError,TypeError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/airllm/prepare','/airllm/rollback'):
                if not self._own_page('installazione AirLLM isolata gestita da questa pagina'):return
                try:
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict):raise ValueError('Invalid AirLLM setup request')
                    self._json(202,svc.airllm_setup.rollback() if path.endswith('/rollback') else svc.airllm_setup.prepare(payload.get('version')))
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/chat/context/compact':
                if not self._own_page('Compattazione richiesta da questa chat'):return
                if not 0<int(self.headers.get('Content-Length',0))<=2*1024*1024:
                    self._json(413,{'error':{'message':'Contesto oltre il limite di compattazione'}});return
                try:
                    from serve.context_compaction import prepare
                    self._json(200,prepare(json.loads(self._read_body()),root=ROOT))
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/voicestudio/audiobook/render':
                if not self._own_page('Audiolibro gestito da questa pagina'):return
                try:
                    from serve.voicestudio_render import forward
                    forward(self,svc.voicestudio)
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/voicestudio/audiobook/cancel':
                if not self._own_page('Audiolibro gestito da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=4096:raise ValueError('Richiesta interruzione non valida.')
                    from serve.voicestudio_render import cancel
                    self._json(200,cancel(svc.voicestudio,json.loads(self._read_body())))
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/voicestudio/launch','/voicestudio/speech','/voicestudio/connect-mcp','/voicestudio/install','/voicestudio/engine/select','/voicestudio/web/start','/voicestudio/stop','/voicestudio/pronunciation','/voicestudio/profile','/voicestudio/job'):
                if not self._own_page('VoiceStudio gestito da questa pagina'):return
                try:
                    if path.endswith('/web/start'):
                        result=svc.voicestudio.ensure_web()
                        server=svc.mcp.servers.get('voicestudio') if svc.mcp else None
                        if server and (result.get('starting') or server.status in ('failed','idle','stopped')):
                            if result.get('starting') and server.status=='ready':server.close()
                            def reconnect_voice():
                                deadline=time.monotonic()+120
                                while time.monotonic()<deadline:
                                    if result.get('starting') and svc.voicestudio._web_process is None:return
                                    if server.start(quiet=True,reuse_ready=True):return
                                    time.sleep(2)
                            threading.Thread(target=reconnect_voice,daemon=True).start()
                            result['mcp_reconnecting']=True
                    elif path.endswith('/engine/select'):result=svc.voicestudio.select_engine(json.loads(self._read_body()))
                    elif path.endswith('/launch'):result=svc.voicestudio.launch()
                    elif path.endswith('/stop'):
                        result=svc.voicestudio.stop()
                        if result.get('stopped') and svc.mcp and 'voicestudio' in svc.mcp.servers:svc.mcp.servers['voicestudio'].close()
                    elif path.endswith('/connect-mcp'):result=svc.voicestudio.connect_mcp(ROOT)
                    elif path.endswith('/install'):result=svc.voicestudio.install(json.loads(self._read_body()))
                    elif path.endswith('/pronunciation'):result=svc.voicestudio.pronunciation(json.loads(self._read_body()))
                    elif path.endswith('/profile'):
                        if not 0<int(self.headers.get('Content-Length',0))<=28*1024*1024:raise ValueError('Richiesta del profilo oltre il limite consentito.')
                        result=svc.voicestudio.profile(json.loads(self._read_body()))
                    elif path.endswith('/job'):
                        if not 0<int(self.headers.get('Content-Length',0))<=28*1024*1024+4096:raise ValueError('Richiesta attività oltre il limite consentito.')
                        result=svc.voicestudio.job_action(json.loads(self._read_body()))
                    else:result=svc.voicestudio.speech(json.loads(self._read_body()))
                    self._json(200,result)
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/harness/antigravity/web/start':
                if not self._own_page('Antigravity originale dentro questa pagina'):return
                try:self._json(200,svc.antigravity_web.start())
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/harness/antigravity/web/stop':
                if not self._own_page('Antigravity integrato gestito da questa pagina'):return
                svc.antigravity_web.close();self._json(200,{'ok':True,'stopped':True});return
            if path == '/harness/antigravity/desktop':
                if not self._own_page('Antigravity Desktop aperto da questa pagina'):return
                try:
                    from serve.original_harness_routes import antigravity
                    self._json(200,antigravity(svc).start())
                except (OSError,RuntimeError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/local-separation/stop':
                if not self._own_page('separazione audio gestita da questa pagina'):return
                svc.local_separation.stop();self._json(200,svc.local_separation.status());return
            if path == '/local-separation/run':
                if not self._own_page('separazione audio gestita da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=16*1024**2+4096:raise ValueError('Separation request exceeds limit')
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict):raise ValueError('Send a JSON object')
                    self._json(200,svc.local_separation.run(payload))
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/local-speech/library/import':
                if not self._own_page('importazione audio locale gestita da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=16*1024**2+4096:raise ValueError('Audio upload exceeds limit')
                    from serve.audio_edit import import_audio
                    self._json(200,import_audio(ROOT,json.loads(self._read_body())))
                except (OSError,ValueError,EOFError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/local-speech/library/export':
                if not self._own_page('esportazione audio locale gestita da questa pagina'):return
                import wave
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=4096:raise ValueError('Audio export request exceeds limit')
                    from serve.audio_edit import export_audio
                    payload=json.loads(self._read_body());data,mime=export_audio(ROOT,payload)
                    self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Content-Disposition','attachment; filename="audio.'+payload['format']+'"');self.send_header('Cache-Control','private, no-store');self.end_headers();self.wfile.write(data)
                except (OSError,ValueError,EOFError,wave.Error) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/local-speech/library/edit':
                if not self._own_page('modifica audio locale gestita da questa pagina'):return
                import wave
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=4096:raise ValueError('Audio edit request exceeds limit')
                    from serve.audio_edit import edit_audio
                    self._json(200,edit_audio(ROOT,json.loads(self._read_body())))
                except (OSError,ValueError,EOFError,wave.Error) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/local-speech/library/delete':
                if not self._own_page('gli audio generati possono essere rimossi da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=4096:raise ValueError('Audio library request exceeds limit')
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict) or payload.get('confirm') is not True:raise ValueError('Confirm generated audio removal')
                    from serve.audio_library import AudioLibrary
                    self._json(200,AudioLibrary(ROOT).delete(payload.get('id')))
                except (OSError,ValueError) as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/updates/harness-install','/updates/harness-activate','/updates/harness-rollback'):
                if not self._own_page('aggiornamenti harness gestiti da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=4096:raise ValueError('Request size limit')
                    payload=json.loads(self._read_body());kind=payload.get('kind')
                    if kind not in ('opencode','dsh','trueforge','browser','memory','hermes','claude'):raise ValueError('Unknown harness')
                    svc.update_center.harness_updates.status()
                    if path.endswith('/harness-install'):svc.update_center.harness_updates.start(kind,payload.get('version'))
                    elif kind in ('browser','memory'):
                        for agent_kind in ('opencode','dsh','trueforge','hermes','claude'):
                            if agent_harness_for(svc,agent_kind,self.headers.get('Host')).status().get('busy'):
                                raise ValueError('Agente occupato: browser e memoria saranno aggiornabili al termine del lavoro')
                        from serve.shared_agent_services import activate_shared_service
                        activate_shared_service(svc,kind,rollback=path.endswith('/harness-rollback'))
                    else:
                        from serve.harness_activation import activate_managed
                        activate_managed(svc,kind,lambda:agent_harness_for(svc,kind,self.headers.get('Host')),rollback=path.endswith('/harness-rollback'))
                    self._json(200,svc.update_center.status())
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/updates/health-check','/updates/repair-missing'):
                if not self._own_page('ripristino dipendenze gestito da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=4096:raise ValueError('Dependency request exceeds 4 KiB')
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict):raise ValueError('Send a JSON object')
                    result=svc.update_center.check_dependency_health() if path.endswith('/health-check') else svc.automatic_updates.recover_missing()
                    self._json(200,result)
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/updates/validate-visual-python','/updates/select-visual-python','/updates/rollback-visual-python','/updates/validate-document-python','/updates/select-document-python','/updates/rollback-document-python','/updates/validate-inference-python','/updates/validate-audio-python','/updates/select-audio-python','/updates/rollback-audio-python','/updates/select-inference-python','/updates/rollback-inference-python','/updates/llama-gpu-activate','/updates/llama-gpu-rollback','/updates/soup-prepare','/updates/soup-activate','/updates/soup-rollback','/updates/check','/updates/stage','/updates/cancel','/updates/prepare','/updates/validate','/updates/activate','/updates/rollback','/updates/dependencies','/updates/install-dependencies','/updates/select-python','/updates/rollback-python','/updates/validate-python','/updates/validate-inference'):
                if not self._own_page('aggiornamenti gestiti da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=4096:raise ValueError('Update request exceeds 4 KiB')
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict):raise ValueError('Send a JSON object')
                    svc.update_center.status()
                    result=svc.update_center.visual_python('validate') if path.endswith('/validate-visual-python') else svc.update_center.visual_python('activate') if path.endswith('/select-visual-python') else svc.update_center.visual_python('rollback') if path.endswith('/rollback-visual-python') else svc.update_center.document_python('validate') if path.endswith('/validate-document-python') else svc.update_center.document_python('activate') if path.endswith('/select-document-python') else svc.update_center.document_python('rollback') if path.endswith('/rollback-document-python') else svc.update_center.audio_python('validate') if path.endswith('/validate-audio-python') else svc.update_center.audio_python('activate') if path.endswith('/select-audio-python') else svc.update_center.audio_python('rollback') if path.endswith('/rollback-audio-python') else svc.update_center.inference_python('validate') if path.endswith('/validate-inference-python') else svc.update_center.inference_python('activate') if path.endswith('/select-inference-python') else svc.update_center.inference_python('rollback') if path.endswith('/rollback-inference-python') else svc.update_center.activate_llama_gpu() if path.endswith('/llama-gpu-activate') else svc.update_center.rollback_llama_gpu() if path.endswith('/llama-gpu-rollback') else svc.update_center.prepare_soup(payload.get('version')) if path.endswith('/soup-prepare') else svc.update_center.activate_soup() if path.endswith('/soup-activate') else svc.update_center.rollback_soup() if path.endswith('/soup-rollback') else svc.update_center.validate_strata_inference() if path.endswith('/validate-inference') else svc.update_center.check() if path.endswith('/check') else svc.update_center.cancel() if path.endswith('/cancel') else svc.update_center.validate_python() if path.endswith('/validate-python') else svc.update_center.select_python() if path.endswith('/select-python') else svc.update_center.select_python(rollback=True) if path.endswith('/rollback-python') else svc.update_center.install_dependencies() if path.endswith('/install-dependencies') else svc.update_center.dependency_plan(payload.get('environment'),payload.get('component'),payload.get('version')) if path.endswith('/dependencies') else svc.update_center.activate() if path.endswith('/activate') else svc.update_center.rollback(payload.get('component','llama.cpp')) if path.endswith('/rollback') else svc.update_center.validate(payload.get('model_path')) if path.endswith('/validate') else svc.update_center.prepare() if path.endswith('/prepare') else svc.update_center.stage(payload.get('component'),payload.get('asset_id'))
                    self._json(200,result)
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/local-export/preflight','/local-export/start','/local-export/stop'):
                if not self._own_page('conversione locale gestita da questa pagina'):return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=65536:raise ValueError('Conversion request exceeds 64 KiB')
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict):raise ValueError('Send a JSON object')
                    if path.endswith('/preflight'):result=svc.local_export.preflight(payload)
                    elif path.endswith('/stop'):result=svc.local_export.stop()
                    else:
                        with svc.fifo:
                            result=svc.local_export.start(payload,not svc.loaded() and svc.local_training.status()['status']!='running')
                    self._json(200,result)
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/local-speech/start','/local-speech/stop','/local-speech/generate','/v1/audio/speech'):
                if path.startswith('/local-speech/') and not self._own_page('voce locale gestita da questa pagina'):return
                if path.startswith('/v1/') and self._foreign_page():return
                try:
                    length=int(self.headers.get('Content-Length',0))
                    if not 0<length<=65536:raise ValueError('Speech request exceeds 64 KiB')
                    payload=json.loads(self._read_body())
                    if not isinstance(payload,dict):raise ValueError('Send a JSON object')
                    if path.endswith('/start'):result=svc.local_speech.start(payload)
                    elif path.endswith('/stop'):
                        if payload.get('automatic_idle'):
                            if not svc.local_speech.request_lock.acquire(blocking=False):
                                self._json(200,{'busy':True});return
                            try:result=svc.local_speech.stop()
                            finally:svc.local_speech.request_lock.release()
                        else:result=svc.local_speech.stop()
                    else:result=svc.local_speech.generate(payload)
                    if path=='/v1/audio/speech':
                        import base64
                        data=base64.b64decode(result['audio_base64']);self.send_response(200);self.send_header('Content-Type','audio/wav');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                    else:self._json(200,result)
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/local-audio/process':
                if not self._own_page('audio locale gestito da questa pagina'):return
                try:
                    import base64
                    from serve.local_audio import process_audio
                    if not 0<int(self.headers.get('Content-Length',0))<=29*1024**2:raise ValueError('Audio request exceeds limit')
                    payload=json.loads(self._read_body())
                    data=base64.b64decode(payload.get('audio_base64',''),validate=True)
                    audio,metrics=process_audio(data,payload.get('name',''),payload.get('start',0),payload.get('duration',60),payload.get('normalize',False))
                    self._json(200,{'audio_base64':base64.b64encode(audio).decode('ascii'),'metrics':metrics})
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/local-audio/start','/local-audio/stop','/local-audio/transcribe','/v1/audio/transcriptions','/v1/audio/translations'):
                if path.startswith('/local-audio/') and not self._own_page('audio locale gestito da questa pagina'):return
                if path.startswith('/v1/') and self._foreign_page(allow_multipart=True):return
                try:
                    import base64
                    size=int(self.headers.get('Content-Length',0))
                    if size<=0 or size>32*1024**2:raise ValueError('Audio request exceeds 32 MiB or is empty')
                    raw=self._read_body();content_type=self.headers.get('Content-Type','')
                    if content_type.startswith('multipart/form-data'):
                        from email.parser import BytesParser
                        from email import policy
                        multipart=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
                        values={};audio=None;name='audio.wav'
                        for part in multipart.iter_parts():
                            key=part.get_param('name',header='content-disposition')
                            if key=='file':audio=part.get_payload(decode=True);name=part.get_filename() or name
                            elif key in ('language','response_format','model'):values[key]=part.get_content()
                        if audio is None:raise ValueError('Audio file missing')
                        payload=values
                    else:
                        payload=json.loads(raw)
                        if not isinstance(payload,dict):raise ValueError('Send a JSON object')
                        audio=base64.b64decode(payload.get('audio_base64',''),validate=True);name=payload.get('name','audio.wav')
                    if path.endswith('/start'):result=svc.local_audio.start(payload)
                    elif path.endswith('/stop'):
                        if payload.get('automatic_idle'):
                            if not svc.local_audio.request_lock.acquire(blocking=False):
                                self._json(200,{'busy':True});return
                            try:result=svc.local_audio.stop()
                            finally:svc.local_audio.request_lock.release()
                        else:result=svc.local_audio.stop()
                    else:
                        if payload.get('response_format','json') not in ('json','text'):raise ValueError('Supported transcription formats: json, text')
                        result=svc.local_audio.transcribe(audio,name,payload.get('language','auto'),path.endswith('/translations') or payload.get('translate') is True,model=payload.get('model'))
                    if payload.get('response_format')=='text':
                        data=result['text'].encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                    else:self._json(200,result)
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/local-training/start','/local-training/stop','/local-training/preflight','/local-training/upload','/local-training/split','/local-training/session'):
                if not self._own_page('il training locale può essere gestito da questa pagina'):return
                try:
                    if path.endswith('/upload') and not 0<int(self.headers.get('Content-Length',0))<=8*1024**2:raise ValueError('Dataset request exceeds upload limit')
                    payload=json.loads(self._read_body() or b'{}')
                    if not isinstance(payload,dict):raise ValueError('Send a JSON object')
                    with svc.fifo:
                        result=svc.local_training.session(payload) if path.endswith('/session') else svc.local_training.split_dataset(payload) if path.endswith('/split') else svc.local_training.upload_dataset(payload) if path.endswith('/upload') else svc.local_training.preflight(payload) if path.endswith('/preflight') else svc.local_training.start(payload,operational_idle=not svc.loaded()) if path.endswith('/start') else svc.local_training.stop()
                    self._json(200,result)
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/optional-catalogue/search','/optional-catalogue/download','/optional-catalogue/cancel','/optional-catalogue/details','/optional-catalogue/delete'):
                if not self._own_page('il catalogo può essere gestito da questa pagina'):return
                try:
                    payload=json.loads(self._read_body() or b'{}')
                    if not isinstance(payload,dict):raise ValueError('Invia un oggetto JSON')
                    if path.endswith('/delete'):
                        if payload.get('confirm') is not True:raise ValueError('Conferma la rimozione del modello selezionato')
                        training=svc.local_training.status()
                        with svc.fifo:result=svc.optional_catalogue.delete_local(payload.get('path'),operational_idle=not svc.loaded() and svc.local_export.status()['status']!='running',training_model=training.get('model') if training.get('status')=='running' else None)
                    elif path.endswith('/details'):result=svc.optional_catalogue.details(payload.get('id'))
                    elif path.endswith('/search'):result=svc.optional_catalogue.search(payload)
                    elif path.endswith('/download'):result=svc.optional_catalogue.download(payload.get('id'))
                    else:svc.optional_catalogue.cancel.set();result=svc.optional_catalogue.status()
                    self._json(200,result)
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path in ('/harness/mcp','/harness/browser-mcp','/harness/memory-mcp'):
                from serve.trueforge_setup import bridge_token,bridge_response
                authorization=self.headers.get('Authorization','')
                if not hmac.compare_digest(authorization,'Bearer '+bridge_token(ROOT)):
                    self._json(401,{'error':{'message':'MCP bridge authentication required'}});return
                try:
                    if not 0<int(self.headers.get('Content-Length',0))<=65536:raise ValueError('MCP request limit')
                    request=json.loads(self._read_body());response=bridge_response(svc.mcp,request,prefix='browser__' if path.endswith('browser-mcp') else 'memory__' if path.endswith('memory-mcp') else None)
                    self._json(200 if response is not None else 202,response or {})
                except Exception as error:self._json(400,{'error':{'message':str(error)}})
                return
            if path == '/harness/claude/desktop':
                if not self._own_page("Claude Desktop ufficiale aperto da questa pagina"): return
                try:
                    from serve.original_harness_routes import claude
                    self._json(200, claude(svc).start())
                except Exception as error: self._json(400, {'error': {'message': str(error)}})
                return
            if path in ('/harness/claude/run', '/harness/claude/new-session'):
                if not self._own_page("Claude Code gestito da questa pagina"): return
                try:
                    harness = agent_harness_for(svc, 'claude', self.headers.get('Host'))
                    if path.endswith('/run'):
                        if not 0 < int(self.headers.get('Content-Length', 0)) <= 65536: raise ValueError('Limite richiesta Claude Code')
                        payload = json.loads(self._read_body())
                        model = payload.get('model') or harness.model if isinstance(payload, dict) else None
                        optional = svc.optional_backends.status()
                        if model not in svc.model_names() and model != optional.get('public_model'): raise ValueError('Seleziona un modello locale disponibile')
                        if isinstance(model, str) and model.startswith('local/') and optional.get('status') != 'ready': raise ValueError('Il modello locale selezionato non è pronto')
                        harness.context_budget = int((optional.get('context_per_slot') or 8192) if model.startswith('local/') else (getattr(svc, 'max_context', 0) or 131072))
                        harness.output_budget = min(2048, max(128, harness.context_budget // 4))
                        self._json(202, harness.run(payload))
                    else: self._json(200, harness.new_session())
                except Exception as error: self._json(400, {'error': {'message': str(error)}})
                return
            if path.startswith("/harness/"):
                parts = path.split("/")
                if len(parts) == 4 and parts[2] in ("opencode", "dsh", "trueforge", "hermes", "claude") and parts[3] in ("start", "stop", "connect"):
                    if not self._own_page("l'harness può essere gestito da questa pagina"): return
                    try:
                        harness = agent_harness_for(svc, parts[2], self.headers.get("Host"))
                        from serve.harness_model import local_selection
                        response = harness.start() if parts[3] == "start" else harness.connect() if parts[3] == "connect" else harness.stop()
                        self._json(200, {**response, 'binding': local_selection(svc)})
                    except Exception as error:
                        self._json(400, {"error": {"message": str(error)}})
                return
            if path in ('/inference-backends/start','/inference-backends/stop','/inference-backends/chat','/inference-backends/probe','/inference-backends/context-plan','/inference-backends/fit','/inference-backends/rescan'):
                if not self._own_page('i backend locali possono essere gestiti da questa pagina'):return
                cancel=threading.Event();events=None;streaming=False
                try:
                    payload=json.loads(self._read_body() or b'{}')
                    if not isinstance(payload,dict):raise ValueError('Invia un oggetto JSON')
                    if path.endswith('/rescan'):
                        discovery=svc.optional_backends.discovery
                        if discovery is None:raise ValueError('Local model discovery unavailable')
                        self._json(202,discovery.rescan())
                    elif path.endswith('/fit'):self._json(200,svc.optional_backends.fit_model(payload))
                    elif path.endswith('/context-plan'):self._json(200,svc.optional_backends.context_plan(payload))
                    elif path.endswith('/start'):
                        with svc.fifo:
                            if getattr(svc,'cat_job',{}).get('state') in ('starting','downloading','verifying','packing','registering'):raise RuntimeError('Attendi la preparazione del catalogo')
                            if svc.airllm_setup.job['state']=='preparing':raise RuntimeError('Attendi la preparazione AirLLM')
                            result=svc.optional_backends.start(payload,operational_idle=not svc.loaded())
                        self._json(202,result)
                    elif path.endswith('/stop'):self._json(200,svc.optional_backends.stop())
                    elif path.endswith('/probe'):self._json(200,svc.optional_backends.probe_api(payload))
                    else:self._optional_chat(payload)
                except (BrokenPipeError,ConnectionResetError):cancel.set()
                except Exception as exc:
                    if streaming:
                        try:
                            self.wfile.write(('data: '+json.dumps({'error':{'message':str(exc)}})+'\n\n').encode());self.wfile.flush()
                        except OSError:pass
                    else:self._json(400 if isinstance(exc,(ValueError,TypeError)) else 409,{'error':{'message':str(exc)}})
                finally:
                    cancel.set()
                    if events is not None:events.close()
                return
            if path in ('/benchmark-lab/start','/benchmark-lab/stop'):
                if not self._own_page('i benchmark possono essere avviati da questa pagina'):return
                try:
                    if path.endswith('/stop'):
                        result=svc.optional_benchmark.stop() if svc.optional_benchmark.status()[0].get('status') in ('running','cancelling') else svc.benchmark_lab.cancel()
                    else:
                        with svc.fifo:
                            if getattr(svc,'cat_job',{}).get('state') in ('starting','downloading','verifying','packing','registering'):raise RuntimeError('Attendi la preparazione del catalogo')
                            payload=json.loads(self._read_body() or b'{}')
                            result=svc.optional_benchmark.start(payload) if payload.get('model')=='optional_active' else svc.benchmark_lab.start(payload,operational_idle=not svc.loaded())
                    self._json(202,result)
                except (ValueError,TypeError) as exc:self._json(400,{'error':{'message':str(exc)}})
                except RuntimeError as exc:self._json(409,{'error':{'message':str(exc)}})
                return
            if path.startswith("/v1/") and self._foreign_page():
                return
            if path == "/settings":
                self._settings()
                return
            # JSON from Strata's own page only, as /settings: else a plain form POST from any site unloads the model
            if path in ("/unload", "/load") and not self._own_page("the model can be loaded or unloaded"):
                return
            if path == "/power":
                if not self._own_page("thermal alert settings can be changed"):
                    return
                try:
                    req = json.loads(self._read_body() or b"{}")
                    if not isinstance(req, dict):
                        raise ValueError("send a JSON object")
                    if "mode" in req and req["mode"] not in ("performance", "balanced", "eco", "custom"):
                        raise ValueError("unknown mode")
                    if "temp_limit" in req or "power_limit" in req:
                        svc.power_manager.set_custom_limits(
                            req.get("temp_limit", svc.power_manager.config.custom_temp_limit),
                            req.get("power_limit", svc.power_manager.config.custom_power_limit),
                        )
                    if "mode" in req:
                        svc.power_manager.set_mode(req["mode"])
                    if req.get("reset"):
                        svc.power_manager.reset_throttle()
                    self._json(200, {"status": "ok", "mode": svc.power_manager.config.mode,
                                     "temp_limit": svc.power_manager.config.temp_limit(),
                                     "power_limit": svc.power_manager.config.power_limit()})
                except (ValueError, TypeError) as e:
                    self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            if path in ("/config", "/setup-download", "/switch-model", "/catalogue-inspect", "/catalogue-search", "/catalogue-fetch") and not self._own_page("resources and models can be changed"):
                return
            if path == "/config":
                try:
                    req = json.loads(self._read_body() or b"{}")
                    if not isinstance(req, dict):
                        raise ValueError("send a JSON object")
                    svc.set_resources(vram_reserve_mib=req.get("vram_reserve_mib"),
                                      kv_resident=req.get("kv_resident"),
                                      max_context=req.get("max_context"), validate_only=True)
                    vis = svc.set_vision(req.get("vision"))      # images on/off, now
                    changed = svc.set_resources(vram_reserve_mib=req.get("vram_reserve_mib"),
                                                kv_resident=req.get("kv_resident"),
                                                max_context=req.get("max_context"))
                    note = ("takes effect at the next engine start" if changed
                            else "images " + ("on" if vis.get("vision") else "off") if vis
                            else "nothing changed")
                    self._json(200, {"status": "ok", "changed": changed, **vis, **svc.resource_state(), "note": note})
                except GpuBusy as e:
                    self._json(409, {"error": {"type": "model_busy", "message": str(e)}})
                except ValueError as e:
                    self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            if path == "/setup-download":
                try:
                    req = json.loads(self._read_body() or b"{}")
                    model = str(req.get("model") or "").strip()
                    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,32}", model):
                        raise ValueError("send a model key (e.g. IQ3_XXS)")
                    self._json(202, svc.start_setup(model))
                except ValueError as e:
                    self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            if path == "/catalogue-inspect":
                try:
                    req = json.loads(self._read_body() or b"{}")
                    self._json(200, svc.catalogue_inspect(str(req.get("repo") or ""),
                                                          (str(req["quant"]) if req.get("quant") else None)))
                except ValueError as e:
                    self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            if path == "/catalogue-search":
                try:
                    req = json.loads(self._read_body() or b"{}")
                    self._json(200, svc.catalogue_search(str(req.get("query") or "")))
                except ValueError as e:
                    self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            if path == "/catalogue-fetch":
                try:
                    req = json.loads(self._read_body() or b"{}")
                    self._json(202, svc.start_catalogue_fetch(str(req.get("repo") or ""),
                                                              str(req.get("quant") or ""),
                                                              (str(req["key"]) if req.get("key") else None),
                                                              bool(req.get("mtp"))))
                except ValueError as e:
                    self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            if path == "/switch-model":
                try:
                    req = json.loads(self._read_body() or b"{}")
                    model = str(req.get("model") or "").strip()
                    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,32}", model):
                        raise ValueError("send a model key (e.g. IQ2_XS)")
                    self._json(202, svc.start_switch(model))
                except ValueError as e:
                    self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            if path == "/unload":                            # give the GPU back now (between requests)
                try:
                    r = svc.unload()
                except EngineStuck as e:
                    self._json(503, {"error": {"type": "server_error", "message": str(e)}})
                    return
                self._json(409 if r == "busy" else 200, {"status": r})
                return
            if path == "/load":                              # load now, e.g. ahead of a request
                try:
                    svc.load()
                    self._json(200, {"status": "loaded"})
                except GpuBusy as e:
                    self._json(503, {"error": {"type": "server_error", "message": str(e)}})
                return
            try:
                req = json.loads(self._read_body() or b"{}")
                if not isinstance(req, dict):
                    raise ValueError("send a JSON object")
                if path in ("/v1/load", "/v1/unload"):
                    if not self._own_page("the model can be loaded or unloaded"):
                        return
                    if req.get("model") not in (None, svc.model):
                        self._json(404, {"error": {"message": "model not found"}})
                        return
                    if path == "/v1/unload":
                        result = svc.unload()
                        if result == "busy":
                            raise ModelBusy("a request is running or queued")
                    else:
                        if not svc.fifo.acquire(blocking=False):
                            raise ModelBusy("a request is running or queued")
                        try:
                            with svc.status_lock:
                                if svc.status.get("busy") or svc.status.get("queued"):
                                    raise ModelBusy("a request is running or queued")
                            svc.ensure_loaded()
                            svc.last_request_at = time.time()
                        finally:
                            svc.fifo.release()
                        result = "loaded"
                    self._json(200, {"status": result, **svc.v1_status()})
                    return
                if path in ("/v1/chat/completions", "/v1/messages", "/v1/messages/count_tokens"):
                    from serve.harness_model import resolve_request
                    req = resolve_request(svc, req)
                if path in ("/v1/chat/completions", "/v1/messages"):
                    if isinstance(req.get('model'),str) and req['model'].startswith('local/'):
                        optional=svc.optional_backends.status()
                        if req['model']!=optional.get('public_model') or optional['status']!='ready':
                            self._json(404,{'error':{'message':'Il modello locale richiesto non è pronto'}})
                        else:self._optional_anthropic(req) if path=='/v1/messages' else self._optional_chat(req)
                        return
                    self.record = svc.begin_request(path, req)
                if path == "/v1/chat/completions":
                    self._openai(req)
                elif path == "/v1/messages":
                    self._anthropic(req)
                elif path == "/v1/messages/count_tokens":
                    if str(req.get('model', '')).startswith('local/'):
                        self._json(501, {'error': {'type': 'api_error', 'message': 'Il backend locale non espone conteggi token Anthropic'}})
                    else: self._count_tokens(req)
                else:
                    self._json(404, {"error": {"message": "not found"}})
            except ValueError as e:
                from serve.harness_model import ModelNotFound
                self._json(404 if isinstance(e,ModelNotFound) else 400,
                           {"error": {"type": "invalid_request_error", "message": str(e)}})
            except ModelBusy as e:
                self._json(409, {"error": {"type": "model_busy", "message": str(e)}})
            except StructuredOutputError as e:
                self._json(502, {"error": {"type": "structured_output_failed", "code": "structured_output_failed",
                                          "message": str(e)}})
            except (GpuBusy, EngineStarting) as e:
                self._json(503, {"error": {"type": "server_error", "message": str(e)}})
            except EngineDied as e:                          # before the answer started (not streamed)
                self._json(503, {"error": {"type": "server_error", "message": f"{e}; the next request restarts it"}})
            except EngineStuck as e:                         # an unload or restart that could not end the engine
                self._json(503, {"error": {"type": "server_error", "message": str(e)}})

            except OSError:
                self._note(outcome="disconnected")
                raise                                        # as before #332: the server's own handling
            finally:
                if self.watch_done is not None:
                    self.watch_done.set()
                record = self.record
                if record is not None:
                    with svc.status_lock:
                        record["wallclock_s"] = round(time.perf_counter() - record["_clock"], 3)
                        record["finished_at"] = time.time()
                        record["state"] = "error" if record.get("error") else record.get("outcome", "completed")
                    svc.request_trace.record = None

        def _weather_reply(self,req):
            if req.get('strata_web') is not True or req.get('strata_mcp') is not True or not svc.mcp:return False
            from serve.weather_intent import intent,run
            args=intent(req.get('messages') or [])
            if not args:return False
            if not self._own_page('MCP tools can be used'):return True
            svc.mcp.wait(10)
            selected=req.get('strata_tools')
            available=[t['name'] for t in svc.mcp.template_tools() if selected is None or t['name'] in selected]
            weather=next((name for name in available if name.endswith('__weather_forecast')),None)
            if not weather:return False
            cancel=threading.Event();self._watch_client(cancel)
            chunks=run(svc.mcp,weather,args,svc.model,cancel,english=str(req.get('strata_locale','')).startswith('en'))
            try:
                if not req.get('stream'):self._json(200,openai_collect(chunks));return True
                self._sse()
                for chunk in chunks:
                    self.wfile.write(b'data: '+json.dumps(chunk,ensure_ascii=False).encode()+b'\n\n');self.wfile.flush()
                self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
            except OSError:cancel.set()
            finally:
                chunks.close()
                if self.watch_done:self.watch_done.set();self.watch_done=None
            return True

        def _optional_anthropic(self, req):
            from serve.claude_optional import to_openai, from_openai, stream_events
            if type(req.get('stream', False)) is not bool: raise ValueError('stream deve essere booleano')
            payload = to_openai(req)
            cancel = threading.Event()
            self._watch_client(cancel)
            if not svc.optional_backends.conversation_lock.acquire(False): raise ModelBusy('Una richiesta del backend è già in corso')
            events = None
            try:
                events = svc.optional_backends.chat(payload, cancel)
                response = next(events, None)
                if cancel.is_set():return
                if response is None: raise ValueError('Risposta vuota dal backend')
                for _ in events: pass
                message = from_openai(response, req['model'])
            finally:
                cancel.set()
                if events is not None: events.close()
                svc.optional_backends.conversation_lock.release()
            if not req.get('stream'):
                self._json(200, message); return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self._cors(); self.end_headers(); self.close_connection = True
            for name, event in stream_events(message):
                self.wfile.write(('event: '+name+'\ndata: '+json.dumps(event)+'\n\n').encode('utf-8'))
                self.wfile.flush()

        def _optional_chat(self,payload):
            cancel=threading.Event();events=None;streaming=False
            self._watch_client(cancel)
            reserved=False
            try:
                reserved=svc.optional_backends.conversation_lock.acquire(blocking=False)
                if not reserved:raise RuntimeError('Una richiesta del backend è già in corso')
                if type(payload.get('stream',False)) is not bool:raise ValueError('stream deve essere booleano')
                generation_defaults={key:value for key,value in svc.optional_backends.state.get('inference_profile',{}).items() if key in ('temperature','top_p','max_tokens')}
                payload={**generation_defaults,**payload,'stream':payload.get('stream',False)}
                configured=svc.optional_backends.state.get('inference_profile',{}).get('tools')
                if configured is not None:
                    requested=payload.get('strata_tools',configured)
                    if not isinstance(requested,list):raise ValueError('Selezione strumenti non valida')
                    payload['strata_tools']=[name for name in requested if name in configured]
                self._watch_client(cancel)
                use_tools = payload.get('strata_mcp') is True and getattr(svc,'mcp',None) is not None
                if use_tools:
                    svc.mcp.wait(10)
                    from serve.optional_tools import chat_with_tools
                    events=chat_with_tools(svc.optional_backends,svc.mcp,payload,cancel)
                else:
                    events=svc.optional_backends.chat(payload,cancel)
                first=next(events,None)
                if cancel.is_set():return
                if not payload.get('stream',False):
                    if first is None:raise RuntimeError('Risposta vuota dal backend')
                    if use_tools:
                        collected=openai_collect(iter([first,*events]))
                        svc.optional_backends.conversation_lock.release();reserved=False
                        self._json(200,collected);return
                    for _ in events:pass
                    svc.optional_backends.conversation_lock.release();reserved=False
                    self._json(200,first);return
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream')
                self.send_header('Cache-Control','no-cache')
                self.send_header('Connection','close')
                self._cors();self.end_headers();self.close_connection=True;streaming=True
                def emit(event):
                    self.wfile.write(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode('utf-8'));self.wfile.flush()
                if first is not None:emit(first)
                for event in events:emit(event)
                svc.optional_backends.conversation_lock.release();reserved=False
                self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):cancel.set()
            except Exception as exc:
                if streaming:
                    try:
                        self.wfile.write(('data: '+json.dumps({'error':{'message':str(exc)}})+'\n\n').encode());self.wfile.flush()
                    except OSError:pass
                else:self._json(400 if isinstance(exc,(ValueError,TypeError)) else 409,{'error':{'message':str(exc)}})
            finally:
                cancel.set()
                if events is not None:events.close()
                if reserved:svc.optional_backends.conversation_lock.release()
                if self.watch_done:self.watch_done.set();self.watch_done=None

        def _props(self):
            model = parse_qs(urlsplit(self.path).query).get("model", [svc.model])[0]
            if model == 'strata':
                from serve.harness_model import local_selection
                model = local_selection(svc)['model']
            optional=svc.optional_backends.status()
            if optional['status']=='ready' and model==optional.get('public_model'):
                profile=optional.get('inference_profile') or {}
                self._json(200,dict(model_alias=model,backend=optional.get('backend'),
                    default_generation_settings=dict(n_ctx=optional.get('context_per_slot'),
                        params={key:profile[key] for key in ('temperature','top_p','max_tokens') if key in profile}),
                    total_slots=(optional.get('runtime') or {}).get('slots',1),
                    model_max_context=optional.get('model_max_context'),context_source=optional.get('context_source'),
                    modalities=dict(vision=optional['capabilities']['images'],audio=optional['capabilities'].get('audio_input',False),
                        video=optional['capabilities'].get('video_input',False)),is_sleeping=False,fit_mode=optional.get('fit_mode')))
                return
            if model not in svc.model_names():
                self._json(404, {"error": {"message": "model not found"}})
                return
            if not svc.loaded() and not getattr(svc.engine, "unloaded", False):
                self._json(503, {"error": {"message": "the engine is not running"}})
                return
            defaults = {**svc.sampling_defaults, **svc.shared}
            names = {"repetition_penalty": "repeat_penalty", "penalty_last_n": "repeat_last_n"}
            params = {names.get(k, k): v for k, v in defaults.items()
                      if k in ("temperature", "top_p", "top_k", "min_p", "seed", "repetition_penalty",
                               "presence_penalty", "frequency_penalty", "penalty_last_n")}
            params["n_predict"] = svc.shared.get("max_tokens", -1)
            props = {"default_generation_settings": {"n_ctx": svc.engine.max_context, "params": params},
                     "total_slots": 1, "model_alias": svc.model, "chat_template": svc.template.source,
                     "modalities": {"vision": svc.vision is not None}, "models_autoload": hasattr(svc.engine, "restart"),
                     "is_sleeping": not svc.loaded()}
            if getattr(svc.engine, "model_path", None):
                props["model_path"] = svc.engine.model_path
            version = getattr(svc.engine, "info", {}).get("version")
            if version:
                props["build_info"] = "Strata " + str(version)
            self._json(200, props)

        def _own_page(self, what) -> bool:
            """Only JSON (a form or a "simple" cross-site request can't send it without a CORS preflight, which this
            server never grants) and no foreign Origin: a web page elsewhere must not change settings or run tools."""
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._json(415, {"error": {"message": "send application/json"}})
                return False
            # The Origin must be this server's own address (host and port), or an origin the config trusts
            # (trusted_origins: the web app behind a reverse proxy or tunnel).  Headers a proxy adds (X-Forwarded-*,
            # CF-Ray, CF-Connecting-IP) prove nothing about the page that sent the request, so they open nothing.
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if origin and origin.split("://", 1)[-1] != self.headers.get("Host", "") and \
                    origin not in svc.trusted_origins:
                self._json(403, {"error": {"message": f"{what} only from Strata's own page (or an origin in the "
                                                      f"config's trusted_origins)"}})
                return False
            return True

        def _settings(self):
            # They change what every client gets, so only the app's own page may set them
            body = self._read_body()
            if not self._own_page("settings can be changed"):
                return
            try:
                req = json.loads(body or b"{}")
                shared = svc.set_shared(req.get("defaults") if isinstance(req, dict) else None)
            except ValueError as e:
                self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            print("[strata] other apps now use the Chat settings: " + ", ".join(f"{k}={v}" for k, v in shared.items())
                  if shared else "[strata] other apps use their own settings again", flush=True)
            self._json(200, {"shared": bool(shared), "defaults": shared})

        def _sse(self):
            self._note(http_status=200)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")   # nginx and similar proxies pass each event at once
            self._cors()
            self.end_headers()

        def _capture(self, items, api):
            """Retain bounded input/output for the monitor without changing the API response (the items as they
            are when the monitor is off)."""
            if self.record is None:
                return items
            return self._captured(items, api)

        def _captured(self, items, api):
            try:
                for item in items:
                    if item is not None:
                        if api == "openai":
                            delta = item["choices"][0]["delta"]
                            content, reasoning = delta.get("content", ""), delta.get("reasoning_content", "")
                            usage, timings = item.get("usage"), item.get("timings")
                        else:
                            _, event = item
                            delta = event.get("delta", {})
                            content, reasoning = delta.get("text", ""), delta.get("thinking", "")
                            usage, timings = event.get("usage"), None
                        with svc.status_lock:
                            for name, value in (("output", content), ("reasoning", reasoning)):
                                if value:
                                    combined = self.record[name] + value
                                    self.record[name] = combined[:262144]
                                    self.record[name + "_truncated"] |= len(combined) > 262144
                            if usage:
                                self.record["usage"] = usage
                            if timings:
                                self.record["timings"] = timings
                    yield item
            finally:
                items.close()

        def _openai(self, req):
            if req.get('model',svc.model) in svc.model_names() and self._weather_reply(req):return
            req = svc.with_shared(req, "openai")
            messages, tools, kw = openai_to_messages(req)
            messages, validator = prepare_format(req.get("response_format"), messages)
            if validator is not None and (tools or req.get("strata_mcp")):
                raise ValueError("structured response_format with tools/MCP is not supported")
            svc.load()
            max_req = max_new = int(req.get("max_completion_tokens") or req.get("max_tokens") or 0)   # 0/-1: the rest
            use_mcp = req.get("strata_mcp") is True and svc.mcp is not None      # the web app's opt-in (serve/mcp.py)
            own = {t.get("name") for t in tools or []}
            if use_mcp:
                if not self._own_page("MCP tools can be used"):   # tools run with the user's rights on this PC
                    return
                svc.mcp.wait(10)                                  # servers still starting (only right after start)
                extra = svc.mcp.template_tools(exclude=own)       # the request's own tools win a name clash
                selected=req.get('strata_tools')
                if selected is not None:
                    if not isinstance(selected,list) or any(not isinstance(name,str) for name in selected):raise ValueError('Selezione strumenti non valida')
                    extra=[t for t in extra if t['name'] in selected]
                if req.get('strata_web') is not True:
                    extra=[t for t in extra if not t['name'].endswith(('__search_web','__read_web_page','__weather_forecast'))]
                use_mcp = bool(extra)
                tools = (tools or []) + extra or None
            svc.reasoning_budget(req)                         # a bad value is a 400 before anything is sent
            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_new, graph_context=validator is None)
            _debug_req("openai", req, messages, tools, max_new, thinking, len(ids))
            cancel = threading.Event()
            self._watch_client(cancel)                       # #430 #431
            run = run_with_mcp(svc, svc.mcp, messages, tools, kw, ids, thinking, max_new, max_req, req, cancel,
                               {t["name"] for t in extra}) if use_mcp else None
            chunks = openai_chunks(svc, req, ids, thinking, tools, max_new, cancel, run=run)
            if validator is not None:
                chunks = structured_chunks(chunks, validator)
            chunks = self._capture(chunks, "openai")
            if not req.get("stream"):
                return self._json(200, openai_collect(chunks))
            self._sse()
            try:
                for c in chunks:
                    if c is None:
                        self.wfile.write(b": keep-alive\n\n")      # an SSE comment: clients ignore it
                    else:
                        self.wfile.write(b"data: " + json.dumps(c, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            except OSError:
                self._note(outcome="disconnected")
                cancel.set()                                 # client went away: stop the engine
                chunks.close()
            except EngineDied as e:                          # mid-stream: say so, then end the stream properly
                err = {"error": {"type": "server_error", "message": f"{e}; the next request restarts it"}}
                self._note(error=err["error"])
                self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\ndata: [DONE]\n\n")
            except StructuredOutputError as e:
                err = {"error": {"type": "structured_output_failed", "code": "structured_output_failed", "message": str(e)}}
                self._note(error=err["error"])
                self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\ndata: [DONE]\n\n")
            except ValueError as e:                          # the engine's ERR after the stream started: the
                err = {"error": {"type": "server_error", "message": str(e)}}   # headers are sent, so no 400 now
                self._note(error=err["error"])
                self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\ndata: [DONE]\n\n")

        def _count_tokens(self, req):
            """Anthropic's token count, which Claude Code asks for its context figures: the prompt this server would
            read for the same request, rendered and tokenized - the model does not run."""
            req = svc.with_shared(req, "anthropic")
            messages, tools, kw = anthropic_to_messages(req, svc.anthropic_think_unasked)
            prompt = svc.template.render(messages, tools=tools, **kw)
            self._json(200, {"input_tokens": len(svc.tok.encode(prompt, parse_special=True))})

        def _anthropic(self, req):
            svc.load()
            req = svc.with_shared(req, "anthropic")
            messages, tools, kw = anthropic_to_messages(req, svc.anthropic_think_unasked)
            max_new = int(req.get("max_tokens") or 0)                  # 0/-1: the rest of the context
            svc.reasoning_budget(req)                         # a bad value is a 400 before anything is sent
            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_new)
            _debug_req("anthropic", req, messages, tools, max_new, thinking, len(ids))
            cancel = threading.Event()
            self._watch_client(cancel)                       # #430 #431
            events = anthropic_events(svc, req, ids, thinking, tools, max_new, cancel)
            events = self._capture(events, "anthropic")
            if not req.get("stream"):
                return self._json(200, anthropic_collect(events))
            self._sse()
            try:
                for item in events:
                    if item is None:
                        self.wfile.write(b": keep-alive\n\n")
                    else:
                        name, e = item
                        self.wfile.write(f"event: {name}\n".encode() + b"data: " +
                                         json.dumps(e, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()
            except OSError:
                self._note(outcome="disconnected")
                cancel.set()
                events.close()
            except EngineDied as e:                          # mid-stream: Anthropic's error event
                err = {"type": "error", "error": {"type": "api_error", "message": f"{e}; the next request restarts it"}}
                self._note(error=err["error"])
                self.wfile.write(b"event: error\ndata: " + json.dumps(err).encode() + b"\n\n")
            except ValueError as e:                          # the engine's ERR after the stream started
                err = {"type": "error", "error": {"type": "api_error", "message": str(e)}}
                self._note(error=err["error"])
                self.wfile.write(b"event: error\ndata: " + json.dumps(err).encode() + b"\n\n")

    return Handler


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port that is already serving, and requests then land on
    # either one (a forgotten second start of run-<model>.bat).  Without it the second start fails loudly instead.
    allow_reuse_address = os.name != "nt"

    def server_close(self):
        try:
            super().server_close()
        finally:
            service = getattr(self, "owned_service", None)
            lab=getattr(service,"_hydra_benchmark_lab",None)
            if lab is not None:lab.close()
            automatic = getattr(service, "automatic_updates", None)
            if automatic is not None:automatic.close()
            telemetry = getattr(self, "owned_telemetry", None)
            if telemetry is not None:
                telemetry.close()
                self.owned_telemetry = None
                service = getattr(self, "owned_service", None)
                if service is not None and getattr(service, "telemetry", None) is telemetry:
                    service.telemetry = None

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):   # a client that hangs up needs no stack trace
            super().handle_error(request, client_address)


def warn_tight_ram(arena_mib) -> None:
    """The model's experts live in RAM (INFO arena_mib, engine 0.1.10+).  With less than ~6 GB left beside them for the
    system, the engine and this server, Linux ends the engine mid-answer when memory runs out (issue #27) and Windows
    pages to disk; say so at start instead of after a lost answer."""
    if not isinstance(arena_mib, int) or arena_mib <= 0:
        return
    try:
        import psutil
        total = psutil.virtual_memory().total
    except Exception:  # noqa: BLE001 - psutil is optional here
        return
    left = total / 2**30 - arena_mib / 1024
    if left < 6:
        print(f"[strata] WARNING: RAM is tight - the model's experts take {arena_mib / 1024:.1f} GB of this PC's "
              f"{total / 2**30:.0f} GB, leaving {left:.1f} GB for everything else. "
              + ("Linux may stop the engine in the middle of an answer. " if os.name != "nt" else
                 "Windows will slow down (paging to disk). ")
              + "Close other programs, or run START-HERE --setup and pick a smaller size (Q2_0 / IQ2_XS).", flush=True)


DESKTOP_FREE_MIB = 2048          # #560 #516: below this, an AMD card that also drives a Linux desktop can run out
DESKTOP_RESERVE_MIB = 3072       # what kept KDE/Wayland alive beside a full expert cache in both reports


def linux_desktop(env=None) -> bool:
    """A graphical session on Linux (Wayland or X): its compositor, browser and apps take VRAM after the model has."""
    env = os.environ if env is None else env
    return os.name != "nt" and sys.platform != "darwin" and bool(env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"))


def desktop_vram_note(backend, vram_free_mib, args: list, desktop: bool) -> str:
    """#560 #516: on Linux, when the desktop needs VRAM the AMD card does not have, amdgpu moves GPU memory (the expert
    cache, ~24 GB) to system RAM, which the experts already fill - the OOM killer then ends the compositor.  The
    default reserve (700 MiB) is sized for a card without a desktop.  A recommendation, nothing changes: "" when it
    does not apply."""
    if backend != "hip" or not desktop or not isinstance(vram_free_mib, int) or vram_free_mib >= DESKTOP_FREE_MIB:
        return ""
    try:
        reserve = int(args[args.index("--vram-reserve-mib") + 1]) if "--vram-reserve-mib" in args else 700
    except (ValueError, IndexError):
        reserve = 700
    if reserve >= DESKTOP_RESERVE_MIB:
        return ""
    return (f"[strata] note: {vram_free_mib} MiB of VRAM free with the model loaded. If this AMD card also drives your "
            "desktop and the desktop or apps crash after the start (the driver moves the expert cache to RAM and "
            "the OOM killer ends the session), keep more VRAM free: ./setup.sh --vram-reserve-mib "
            f"{DESKTOP_RESERVE_MIB} (remembered; the expert cache gets "
            f"{(DESKTOP_RESERVE_MIB - reserve) / 1024:.1f} GB less, a few % of speed)")


def lan_addresses() -> list[str]:
    """This PC's IPv4 addresses on its networks (what another device types in), without loopback/link-local."""
    import socket
    first, ips = None, set()
    try:                                                # the address of the default route; sends nothing (UDP)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            first = s.getsockname()[0]
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ok = lambda ip: ip and not ip.startswith(("127.", "169.254.", "0."))
    return ([first] if ok(first) else []) + sorted(ip for ip in ips if ok(ip) and ip != first)


def host_name(value) -> str:
    """The name in a Host header (or an origin's host[:port]): "Example.com:8080" -> "example.com",
    "[::1]:8095" -> "::1"; "" when it is malformed."""
    v = (value or "").strip().lower()
    if v.startswith("["):
        name, sep, rest = v[1:].partition("]")
        return name if sep and (not rest or (rest[:1] == ":" and rest[1:].isdigit())) else ""
    if v.count(":") == 1:
        v, port = v.split(":")
        if not port.isdigit():
            return ""
    elif ":" in v:                                       # a bare IPv6 address (a config entry)
        return v
    v = v.rstrip(".")
    return v if v and all(c.isalnum() or c in "-._" for c in v) else ""


def _is_ip(name: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def _name_in(name: str, names) -> bool:
    """`name` is one of `names`, or below an entry that starts with a dot (".example.com")."""
    return name in names or any(n.startswith(".") and (name.endswith(n) or name == n[1:]) for n in names)


def allowed_hosts_of(value, env: str = "") -> list[str]:
    """The config's allowed_hosts (a name or a list) plus $STRATA_ALLOWED_HOSTS (comma-separated): host names, "*" or
    ".example.com" (it and every name below it).  A scheme, port or path is dropped ("https://a.example.com:8443/"
    -> "a.example.com"); a wrong entry stops the start (ValueError)."""
    items = [] if value in (None, "") else [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
        raise ValueError("allowed_hosts: expected a host name or a list of them")
    out = []
    for raw in items + [x for x in env.split(",") if x.strip()]:
        x = raw.strip().lower()
        if x == "*":
            out.append(x)
            continue
        x = x.split("://", 1)[-1].split("/", 1)[0]
        dot = x.startswith(".")
        name = host_name(x[1:] if dot else x)
        if not name:
            raise ValueError(f"allowed_hosts: {raw!r} is not a host name like strata.example.com")
        out.append("." + name if dot else name)
    return list(dict.fromkeys(out))


def host_names_for(bind_host: str, allowed_hosts=(), trusted_origins=()) -> set[str]:
    """Every name this server answers to besides an IP address: localhost, the address it listens on, the config's
    allowed_hosts and trusted_origins' hosts, and - listening beyond this PC (0.0.0.0 or a LAN address) - this PC's
    name and LAN addresses (the LAN addresses matter for the Origin check, which takes no IP on trust)."""
    names = set(LOOPBACK_NAMES)
    bind = host_name(bind_host)
    if bind and bind not in ("0.0.0.0", "::"):
        names.add(bind)
    if bind not in LOOPBACK_NAMES:
        try:
            pc = socket.gethostname().lower()
            names.update((pc, pc + ".local"))
        except OSError:
            pass
        names.update(("host.docker.internal", *lan_addresses()))
    names.update(x for x in allowed_hosts if x != "*")
    names.update(filter(None, (host_name(o.split("://", 1)[-1]) for o in trusted_origins)))
    return names


def host_allowed(host, names, any_host=False) -> bool:
    """DNS rebinding: a web page of another site whose name its DNS points at 127.0.0.1 reaches this server as the
    same origin, so the browser lets it read every answer.  Its requests carry that site's name in Host, so only
    the names this server answers to pass.  An IP address passes (a page served from an IP is that IP's own page;
    rebinding needs a name), as does "*.localhost" (browsers never ask DNS for it) and a request without a Host
    header (HTTP/1.0 clients; browsers always send one)."""
    if any_host or not (host or "").strip():
        return True
    name = host_name(host)
    return bool(name) and (_is_ip(name) or name == "localhost" or name.endswith(".localhost")
                           or _name_in(name, names))


def origin_allowed(origin: str, host, names, origins=()) -> bool:
    """A browser page's Origin that may use the model without an API key: this server's own page (the Origin is the
    request's own Host), a page on one of the names this server answers to (any port), or an origin the config lists
    (trusted_origins, cors_origins).  Unlike the Host check no IP passes on trust: a page served from any other IP is
    another site.  "null" (a sandboxed frame, a file:// page) does not pass: any site can send it.  An origin of another
    scheme (chrome-extension://, moz-extension://, an Electron app's app://) does: no web site can send one."""
    origin = (origin or "").strip().rstrip("/")
    if origin in origins or "*" in origins:             # cors_origins ["*"]: the config lets every page in
        return True
    scheme, sep, rest = origin.lower().partition("://")
    if not sep or not scheme:
        return False
    if scheme not in ("http", "https"):
        return True
    if host and rest == host.strip().lower():
        return True
    name = host_name(rest)
    return bool(name) and (name in LOOPBACK_NAMES or name.endswith(".localhost") or _name_in(name, names))


def serve(svc: Service, host="127.0.0.1", port=8095) -> ThreadingHTTPServer:
    svc.host_names = host_names_for(host, svc.allowed_hosts, svc.trusted_origins)
    svc.start_telemetry()
    httpd = Server((host, port), make_handler(svc))
    svc.dashboard_port=port
    def automatic_restart():
        import subprocess
        from serve.update_restart import restart_command
        command=[sys.executable,*getattr(sys,'orig_argv',[sys.executable,*sys.argv])[1:]]
        restart_command(command,port)
        subprocess.Popen([sys.executable,str(ROOT/'tools/restart_dashboard.py'),'--pid',str(os.getpid()),'--root',str(ROOT),'--',*command],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
        threading.Thread(target=lambda:(time.sleep(1.5),os._exit(0)),daemon=True).start()
    svc.automatic_restart=automatic_restart
    if getattr(svc,'automatic_updates',None) is None and hasattr(svc,'update_center'):
        from serve.automatic_updates import AutomaticUpdates
        svc.automatic_updates=AutomaticUpdates(svc)
    svc.optional_backends.dashboard_port=httpd.server_address[1]
    httpd.owned_service = svc
    httpd.owned_telemetry = svc.telemetry
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def origins_of(value, key: str, wildcard: bool) -> list[str]:
    """#321: a config's origin list ("https://chat.example.com" or a list of them) - scheme://host[:port], no path;
    "*" only where `wildcard` allows it.  A wrong entry stops the start rather than opening less or more than meant."""
    if value is None or value == "" or value == []:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
        raise SystemExit(f"[strata] {key}: expected an origin or a list of origins")
    out = []
    for x in items:
        x = x.strip().rstrip("/")
        if x == "*" and wildcard:
            out.append(x)
            continue
        scheme, sep, rest = x.partition("://")
        if scheme not in ("http", "https") or not sep or not rest or "/" in rest or "*" in rest:
            raise SystemExit(f"[strata] {key}: {x!r} is not an origin like https://chat.example.com"
                             + ("" if wildcard else " (no wildcards here)"))
        out.append(x)
    return out


SHARED_KEYS = ("reasoning_effort", "temperature", "top_p", "top_k", "seed", "max_tokens", "experimental_speed_projection")


def clean_shared_defaults(d) -> dict:
    """The Chat settings other apps get (POST /settings): only known keys, each checked; ValueError names a bad one."""
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ValueError("defaults must be an object")
    out = {}
    for key, value in d.items():
        if value is None or value == "":
            continue
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if key == "reasoning_effort":
            if value not in ("none", "low", "medium", "high"):
                raise ValueError("reasoning_effort: none, low, medium or high")
        elif key == "temperature":
            if not number or not 0 <= value <= 2:
                raise ValueError("temperature: 0..2")
        elif key == "top_p":
            if not number or not 0 < value <= 1:
                raise ValueError("top_p: 0 < top_p <= 1")
        elif key == "top_k":
            if not number or value != int(value) or not 1 <= value <= 64:
                raise ValueError("top_k: an integer 1..64")
            value = int(value)
        elif key in ("seed", "max_tokens"):
            if not number or value != int(value) or value <= 0:
                raise ValueError(f"{key}: a positive integer")
            value = int(value)
        elif key == "experimental_speed_projection":
            if not isinstance(value, bool):
                raise ValueError("experimental_speed_projection: true or false")
        else:
            raise ValueError(f"unknown setting {key!r}")
        out[key] = float(value) if key in ("temperature", "top_p") else value
    return out


def sampling_defaults_from_config(cfg: dict) -> dict:
    """The run config's optional `sampling` block: defaults for the sampling fields a request leaves out, so
    a plain client gets configured sampling instead of greedy.  Supported: temperature, top_p, top_k, min_p,
    presence_penalty, repetition_penalty, frequency_penalty, penalty_last_n, seed.  The request's own fields
    always win - an explicit temperature=0 still means greedy, a field set to null falls back to the default.
    A bad value refuses to start the server (a typo'd config should not quietly change sampling); unknown keys
    are named at startup and ignored."""
    out = {}
    for key, value in (cfg.get("sampling") or {}).items():
        if value is None:
            continue
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if key == "temperature":
            if not number or value < 0:
                raise SystemExit(f"[strata] config sampling.temperature={value!r}: expected a number >= 0 (0 = greedy)")
            out[key] = float(value)
        elif key == "top_p":
            if not number or not 0 < value <= 1:
                raise SystemExit(f"[strata] config sampling.top_p={value!r}: expected 0 < top_p <= 1")
            out[key] = float(value)
        elif key == "min_p":
            if not number or not 0 <= value <= 1:
                raise SystemExit(f"[strata] config sampling.min_p={value!r}: expected 0 <= min_p <= 1")
            out[key] = float(value)
        elif key == "top_k":
            if not number or value != int(value) or not 1 <= value <= 64:
                raise SystemExit(f"[strata] config sampling.top_k={value!r}: the sampled path takes an integer 1..64")
            out[key] = int(value)
        elif key == "presence_penalty":
            if not number or value < 0:
                raise SystemExit(f"[strata] config sampling.presence_penalty={value!r}: expected a number >= 0")
            out[key] = float(value)
        elif key == "frequency_penalty":
            if not number or value < 0:
                raise SystemExit(f"[strata] config sampling.frequency_penalty={value!r}: expected a number >= 0")
            out[key] = float(value)
        elif key == "repetition_penalty":
            if not number or value <= 0:
                raise SystemExit(f"[strata] config sampling.repetition_penalty={value!r}: expected a number > 0 (1 = off)")
            out[key] = float(value)
        elif key == "penalty_last_n":
            if not number or value != int(value) or value < 0:
                raise SystemExit(f"[strata] config sampling.penalty_last_n={value!r}: expected a non-negative integer")
            out[key] = int(value)
        elif key == "seed":
            if not number or value != int(value) or value <= 0:
                raise SystemExit(f"[strata] config sampling.seed={value!r}: expected a positive integer")
            out[key] = int(value)
        elif key == "experimental_speed_projection":
            if not isinstance(value, bool):
                raise SystemExit(f"[strata] config sampling.experimental_speed_projection={value!r}: expected true or "
                                 "false (the default for requests that leave it out, when the engine has the vector)")
            out[key] = value
        else:
            print(f"[strata] config sampling.{key}={value!r}: unknown key, ignored", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["mock", "strata"], default="mock")
    ap.add_argument("--config", help="strata engine config (JSON: exe, args, cwd, tokenizer, model_name), "
                                     "written by setup.py")
    ap.add_argument("--host", default=None,
                    help="the address to listen on: 127.0.0.1 = this PC only (the default), 0.0.0.0 = also other devices "
                         "on your network (set an API key); also \"host\" in the config")
    ap.add_argument("--script", action="append",
                    help="the mock engine's answer (default: a short greeting); given more than once, requests get "
                         "them in turn and the last one repeats")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--gpu", help="the GPU to run on, as nvidia-smi numbers them, or several for a layer split "
                                  "(\"0,2\"; also \"gpu\" in the config)")
    ap.add_argument("--tokenizer", default=str(ROOT / "pack/full/tokenizer"),
                    help="pack tokenizer directory (falls back to a byte tokenizer if absent)")
    ap.add_argument("--open", action="store_true", help="open the local page in the browser once the model is ready")
    ap.add_argument("--fit-max-tokens", action="store_true",
                    help="clamp max_tokens to the remaining context instead of rejecting the request "
                         "(default: reject with 400, like llama.cpp; also \"fit_max_tokens\": true in the config)")
    ap.add_argument("--api-key", default=os.environ.get("STRATA_API_KEY", ""),
                    help="require this key on /v1/* (Authorization: Bearer ... or x-api-key); also $STRATA_API_KEY")
    ap.add_argument("--mcp-config", help="a JSON file with MCP servers in Claude Desktop's format ({\"mcpServers\": "
                                         "{...}}); the web app's chat can use their tools (also \"mcp_servers\" in "
                                         "the config)")
    ap.add_argument("--lazy", action="store_true", default=True, help="start unloaded (default); load only on explicit start or first inference request")
    ap.add_argument("--preload", dest="lazy", action="store_false", help="explicitly load the model at dashboard startup")
    ap.add_argument("--api-monitor", action="store_true",
                    help="the API request monitor at /api-monitor: keeps the last 100 requests' prompts and answers in "
                         "memory (also \"api_monitor\": true in the config; off by default)")
    ap.add_argument("--idle-unload", type=float, default=None, metavar="SECONDS",
                    help="unload the model after this many seconds without requests, so other programs (games, other "
                         "model servers) can use the VRAM; the next request loads it again (also \"idle_unload_s\" "
                         "in the config; default: never)")
    ap.add_argument("--min-free-vram-mib", type=int, default=None,
                    help="load an unloaded model only when this much VRAM is free, else answer 503 (also "
                         "\"min_free_vram_mib\" in the config; default: always load)")
    ap.add_argument("--before-load", help="a command run before the model is loaded again (e.g. to unload another "
                                          "server's model; also \"before_load\" in the config, a string or a list)")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8-sig")) if a.config else {}   # Notepad adds a BOM
    if a.engine=="strata" and cfg:
        from serve.strata_update import selected_configuration
        cfg=selected_configuration(ROOT,cfg)
    if a.gpu is not None:
        cfg["gpu"] = int(a.gpu) if a.gpu.strip().isdigit() else a.gpu
    a.host = a.host or cfg.get("host") or "127.0.0.1"   # issue #26: the run scripts pass no --host, the config can
    try:                                                # before the minutes of loading: is the port free?
        Server((a.host, a.port), BaseHTTPRequestHandler).server_close()
    except OSError:
        ap.error(f"port {a.port} is already in use - is Strata (or another server) already running? "
                 f"Close it, or start this one with a different --port")
    if cfg.get("tokenizer"):
        a.tokenizer = cfg["tokenizer"]
    tok = ByteTokenizer()
    tpath = Path(a.tokenizer)
    if a.engine == "strata" and not (tpath / "vocab.json").exists():
        ap.error(f"the model's tokenizer is missing ({tpath / 'vocab.json'}); run setup again")
    if (tpath / "vocab.json").exists():
        import strata_tokenizer as ST
        vocab = json.loads((tpath / "vocab.json").read_text(encoding="utf-8"))
        tokens = [None] * len(vocab)
        for t, i in vocab.items():
            tokens[i] = t
        merges = (tpath / "merges.txt").read_text(encoding="utf-8").split("\n")
        types = json.loads((tpath / "token_type.json").read_text())
        tok = ST.Tokenizer(tokens, merges, types)
    mcp_path=a.mcp_config
    if mcp_path is None and a.engine=='strata' and a.port in (8088,8090) and not (cfg.get('mcp_servers') or cfg.get('mcpServers')) and (ROOT/'data/mcp-dashboard.json').is_file():mcp_path=str(ROOT/'data/mcp-dashboard.json')
    hub = hub_from_config(cfg, mcp_path)            # before the minutes of loading: a bad entry stops here
    if a.engine == "strata":
        if not cfg:
            ap.error("--engine strata needs --config")
        vision = None
        env = child_env(cfg)
        sampling_defaults = sampling_defaults_from_config(cfg)
        if sampling_defaults:
            pretty = ", ".join(f"{k}={v}" for k, v in sampling_defaults.items())
            print(f"[strata] sampling defaults from the config: {pretty}", flush=True)
        lazy = a.lazy
        if cfg.get("vision"):
            print("loading the vision encoder ...", flush=True)
            # relative paths are the config's cwd's, as for the engine below
            vcfg = {k: (os.path.abspath(os.path.join(cfg.get("cwd") or ".", v))
                        if k in ("exe", "mmproj", "model") and isinstance(v, str) and not os.path.isabs(v) else v)
                    for k, v in cfg["vision"].items()}
            vision = Vision(vcfg, log=open(cfg["log"], "a", encoding="utf-8") if cfg.get("log") else None,
                            env=vision_env(cfg, env))
        print("model unloaded; the first request loads it ..." if lazy else
              "loading the model (the first start takes a minute or two) ...", flush=True)
        if len(gpu_list(cfg)) > 1:
            print(f"[strata] layer split across GPUs {gpu_list(cfg)} ({cfg.get('layer_split') or 'auto'})", flush=True)
        # a relative "exe" is the config's cwd's: Windows' CreateProcess resolves "engine/strata.exe" against nothing
        # it is told about (WinError 2), so it is made absolute here
        exe = cfg["exe"] if os.path.isabs(cfg["exe"]) else os.path.abspath(os.path.join(cfg.get("cwd") or ".", cfg["exe"]))
        try:
            silence = engine_silence_s(cfg)             # #481: checked before the (minutes-long) start
        except ValueError as e:
            raise SystemExit(f"[strata] config {e}")
        engine = StrataEngine(exe, engine_args(cfg), cwd=cfg.get("cwd"), log=cfg.get("log"), env=env, lazy=lazy)
        engine.silence_s = silence                      # an attribute of its own: restart() keeps it
        warn_tight_ram(engine.info.get("arena_mib"))
        note = desktop_vram_note(cfg.get("backend"), engine.info.get("vram_free_mib"), engine.spawn[1],
                                 linux_desktop())
        if note:                                        # #560 #516: before --open starts a browser on that card
            print(note, flush=True)
    else:
        engine, vision, sampling_defaults = MockEngine(tok, a.script or [
            "Thinking about it.</think>\n\nHello from the mock engine."]), None, {}
    # the model's own chat template (exported with its tokenizer), else the original model's
    tpl = tpath / "chat_template.jinja"
    svc = Service(engine, tok, ChatTemplate(tpl if tpl.exists() else ROOT / "serve/chat_template.jinja"),
                  model_name=cfg.get("model_name", "qwen3.8-flash-next"), vision=vision,
                  sampling_defaults=sampling_defaults,
                  fit_max_tokens=a.fit_max_tokens or cfg.get("fit_max_tokens") is True)
    svc.cfg_path = a.config
    # annota l'ultimo modello avviato: il collegamento sul Desktop riprende questo, non uno fisso
    try:
        from serve.launch_state import remember_launch
        remember_launch(DATA, ROOT, a.config, a.port)
    except Exception:
        pass
    svc.port = a.port          # the Control tab writes resource changes back here (POST /config)
    svc.cfg = cfg
    try:
        svc.set_aliases(cfg.get("aliases"))             # #297: other names the model answers to
    except ValueError as e:
        raise SystemExit(f"[strata] config {e}")
    if svc.aliases:
        print(f"[strata] model aliases: {', '.join(svc.aliases)}", flush=True)
    if ("STRATA_API_KEY" in os.environ and not os.environ["STRATA_API_KEY"].strip()) or             any(x == "--api-key" and i + 1 < len(sys.argv) and not sys.argv[i + 1].strip() or x.strip() == "--api-key="
                for i, x in enumerate(sys.argv)):
        # #213: an empty key would switch authentication off without a word
        print("[strata] an API key was given but it is empty: set a key, or leave --api-key / STRATA_API_KEY out",
              file=sys.stderr)
        return 2
    svc.api_key = a.api_key or cfg.get("api_key", "")
    svc.cors_origins = origins_of(cfg.get("cors_origins"), "cors_origins", wildcard=True)
    svc.trusted_origins = origins_of(cfg.get("trusted_origins"), "trusted_origins", wildcard=False)
    try:
        svc.allowed_hosts = allowed_hosts_of(cfg.get("allowed_hosts"), os.environ.get("STRATA_ALLOWED_HOSTS", ""))
    except ValueError as e:
        raise SystemExit(f"[strata] config {e}")
    if svc.allowed_hosts:
        print("[strata] Host check off: any name reaches this server (allowed_hosts \"*\")" if "*" in svc.allowed_hosts
              else f"[strata] also answers to the host names {', '.join(svc.allowed_hosts)} (allowed_hosts)", flush=True)
    svc.api_monitor = a.api_monitor or cfg.get("api_monitor") is True
    if svc.api_monitor:
        print("[strata] API request monitor on (/api-monitor): the last 100 requests' prompts and answers are kept in "
              "memory" + ("" if svc.api_key else "; anyone who can reach this server can read them (no API key)"),
              flush=True)
    if svc.cors_origins:
        print(f"[strata] CORS on /v1/* for {', '.join(svc.cors_origins)}"
              + ("" if svc.api_key or "*" not in svc.cors_origins else
                 " - WARNING: any web page may use the model (no API key)"), flush=True)
    svc.idle_unload_s = a.idle_unload if a.idle_unload is not None else float(cfg.get("idle_unload_s") or 0)
    svc.min_free_vram_mib = a.min_free_vram_mib if a.min_free_vram_mib is not None else \
        int(cfg.get("min_free_vram_mib") or 0)
    svc.before_load = a.before_load or cfg.get("before_load") or None
    mode = str(cfg.get("anthropic_thinking") or "model")   # #278: "on_request" = only when the request asks
    if mode not in ("model", "on_request"):
        raise SystemExit(f"[strata] config anthropic_thinking must be \"model\" or \"on_request\", not {mode!r}")
    svc.anthropic_think_unasked = mode == "model"
    if cfg.get("reasoning_budget_tokens") is not None:  # #123: a default thinking budget for every request
        try:
            svc.reasoning_budget_tokens = cfg["reasoning_budget_tokens"]
            budget = svc.reasoning_budget({})
        except ValueError as e:
            raise SystemExit(f"[strata] config {e}")
        if budget:
            print(f"[strata] thinking budget: {budget} tokens (reasoning_budget_tokens; a request can set its own)",
                  flush=True)
    svc.gpu_index = (gpu_list(cfg) or [0])[0]           # the Monitor reads the card the engine runs on (issue #51)
    svc.gpu_indices = gpu_list(cfg)                     # ... or every card of a layer split (issue #112)
    svc.backend = cfg.get("backend")                    # "hip": the AMD cards' readings come from sysfs (#301)
    if a.config:                                        # the Chat settings shared with other apps, from last time
        svc.shared_path = str(Path(a.config).with_suffix("")) + ".shared-settings.json"
        try:
            svc.shared = clean_shared_defaults(json.loads(Path(svc.shared_path).read_text(encoding="utf-8")))
            if svc.shared:
                print("[strata] other apps use the Chat settings: " +
                      ", ".join(f"{k}={v}" for k, v in svc.shared.items()), flush=True)
        except (OSError, ValueError):
            svc.shared = {}
    if hub is not None:
        import atexit
        svc.mcp = hub
        voice_server=hub.servers.get('voicestudio')
        if voice_server and voice_server.cfg.get('url')==svc.voicestudio.base_url+'/mcp':
            voice_server.before_start=svc.voicestudio.ensure_mcp_ready
            voice_server.call_guard=svc.voicestudio.mcp_activity
        print(f"[strata] starting {len(hub.servers)} MCP server{'s' * (len(hub.servers) != 1)} for the web app's "
              f"chat: {', '.join(hub.servers)}", flush=True)
        hub.start()
        atexit.register(hub.close)                      # the servers Strata started end with it
    from serve.dashboard_guard import claim_dashboard,DashboardBusy
    try:
        claim_dashboard(ROOT, a.port)                  # one dashboard per PC, or a clear refusal
    except DashboardBusy as busy:
        raise SystemExit(f"[strata] {busy}")
    import atexit as _atexit
    _atexit.register(lambda: __import__('serve.dashboard_guard',fromlist=['x']).release_dashboard_claim(ROOT))
    httpd = serve(svc, host=a.host, port=a.port)
    svc.start_idle_unload()
    start_harness_idle_stop(svc)
    here = "127.0.0.1" if a.host in ("0.0.0.0", "", "::") else a.host
    print(f"ready: http://{here}:{a.port}/v1  (OpenAI: /v1/chat/completions, Anthropic: /v1/messages, "
          f"context {engine.max_context} tokens{', images on' if vision else ''}"
          f"{', API key required' if svc.api_key else ''})", flush=True)
    print(f"       open http://{here}:{a.port}/ in a browser to chat; close this window to stop the model", flush=True)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        # issue #26: reachable from other devices - say at which address, and what can still block it
        ips = lan_addresses()
        for ip in ips:
            print(f"       from other devices: http://{ip}:{a.port}/   (API: http://{ip}:{a.port}/v1)", flush=True)
        if not ips:
            print("       from other devices: http://<this PC's IP address>:" + str(a.port) + "/", flush=True)
        if not svc.api_key:
            print("       WARNING: no API key - anyone on your network can use this model. Add \"api_key\": \"...\" "
                  "to the config (clients send it as their API key; the web page asks for it)", flush=True)
        if os.name == "nt":
            print("       nothing arrives? Windows Firewall blocks it until allowed: accept its prompt for Python, or run "
                  "in an admin PowerShell:\n         New-NetFirewallRule -DisplayName \"Strata " + str(a.port) + "\" "
                  "-Direction Inbound -Protocol TCP -LocalPort " + str(a.port) + " -Action Allow -Profile Private\n"
                  "       (and set this network to Private in Windows' network settings)", flush=True)
    if a.open:
        import webbrowser
        webbrowser.open(f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}/")
    # #96: docker stop sends SIGTERM, which Python ignores by default, so the container's PID 1 would be killed after
    # the grace period with the engine still running. SIGTERM takes Ctrl+C's path below (QUIT to the engine).
    # SIGINT keeps Python's own handler, so Ctrl+C and a second Ctrl+C work as before.
    def on_sigterm(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, on_sigterm)
    except (ValueError, OSError, AttributeError):         # not the main thread
        pass
    try:
        while True:
            time.sleep(1)                               # Windows never delivers Ctrl+C to an untimed Event.wait()
    except KeyboardInterrupt:
        print("\n[strata] stopping (Ctrl+C again to end the engine at once) ...", flush=True)
        closers = [svc.local_visual.close,svc.local_generative_audio.close,svc.local_separation.close,svc.local_export.close,svc.local_speech.close,svc.local_audio.close,svc.local_training.close,svc.optional_backends.close,svc.benchmark_lab.close,httpd.shutdown, getattr(engine, "close", None), vision.close if vision else None,
                   hub.close if hub is not None else None,svc.voicestudio.stop]
        closers=[getattr(svc,name).close for name in ('agent_harness','agent_harness_dsh','agent_harness_trueforge','agent_harness_hermes','agent_harness_claude') if getattr(svc,name,None) is not None]+[svc.update_center.harness_updates.close]+closers
        for close in filter(None, closers):
            try:
                close()
            except KeyboardInterrupt:                   # a second Ctrl+C: don't wait for the engine to free its memory
                if getattr(engine, "proc", None):
                    engine.proc.kill()
        print("[strata] stopped", flush=True)
    return 0


if __name__ == "__main__":
    # Persisted candidate selection works with existing dashboard launchers.
    selection_path=Path(__file__).resolve().parents[1]/'data/dashboard-python-selection.json'
    try:
        selected=json.loads(selection_path.read_text(encoding='utf-8')).get('active') if os.environ.get('STRATA_PYTHON_CANDIDATE_PROBE')!='1' else None
        if selected and Path(selected).resolve()!=Path(sys.executable).resolve():
            candidate=Path(selected).resolve()
            plans=selection_path.parents[1]/'output/updates/python-plans'
            if not candidate.is_relative_to(plans.resolve()) or not candidate.is_file():
                raise ValueError('Selected Python candidate is unavailable; restore the previous selection')
            manifest=json.loads((candidate.parents[2]/'environment-manifest.json').read_text(encoding='utf-8'))
            if not manifest.get('dashboard_start_verified') or not manifest.get('server_suite',{}).get('passed') or manifest.get('dependency_health',{}).get('state')!='healthy':
                raise ValueError('Selected Python candidate has not passed validation')
            os.execv(str(candidate),[str(candidate),*sys.argv])
    except FileNotFoundError:
        pass
    sys.exit(main())
