#!/usr/bin/env python3
"""Fast-forward push of local commits onto origin/main via pure plumbing.

Why: this repo is a shallow + partial clone (filter=blob:none); `git rebase`
silently does nothing on it. This rebuilds a single commit whose tree is
origin/main with ONLY the files changed by the local commits layered on top,
then advances refs/heads/main to it and pushes. No rebase, no force, no reset,
no clean. catalog/ stays exactly at origin/main unless a local commit changed
a catalog path.

Safety: paper/read-only; pushes code only. On any failure it leaves a durable
backup ref refs/alina/local-work pointing at the original local HEAD.
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT = "git"  # overridden by --git


def git(*a, env_extra=None, inp=None):
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    if env_extra:
        env.update(env_extra)
    return subprocess.run([GIT, *a], cwd=ROOT, capture_output=True,
                          text=True, env=env, input=inp)


def git_ok(*a, **k):
    r = git(*a, **k)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()[:300]}")
    return r.stdout


def build_index_lines(base, work):
    # -M/-C disabled on purpose: we want plain A/M/D per path, not renames.
    diff = git_ok("-c", "core.quotepath=false", "diff-tree", "-r", "--no-renames", "--no-commit-id", base, work)
    lines, deletions, changes = [], 0, 0
    for raw in diff.splitlines():
        if not raw.startswith(":"):
            continue
        meta, tab, path = raw.partition("\t")
        if not tab:
            continue
        parts = meta[1:].split()
        if len(parts) < 5:
            continue
        dstmode, dstsha, status = parts[1], parts[3], parts[4][0]
        if status == "D":
            lines.append(f"0 0000000000000000000000000000000000000000\t{path}")
            deletions += 1
        else:
            lines.append(f"{dstmode} {dstsha}\t{path}")
            changes += 1
    return lines, changes, deletions


def main():
    global GIT
    ap = argparse.ArgumentParser()
    ap.add_argument("--git", default="git", help="path to git executable")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--base", default=None,
                    help="debug: build on this ref instead of REMOTE/BRANCH")
    args = ap.parse_args()
    GIT = args.git
    remote_ref = args.base or f"{args.remote}/{args.branch}"

    # Confirm we are in a git repo and git works.
    head = git_ok("rev-parse", "HEAD").strip()
    git_ok("update-ref", "refs/alina/local-work", head)
    print(f"[FF] HEAD local sauvegarde : {head[:12]} "
          f"(backup ref refs/alina/local-work)", flush=True)

    abs_tmp = os.path.join(ROOT, ".git", "alina-ff-index")

    for attempt in range(1, 6):
        print(f"[FF] --- tentative {attempt}/5 ---", flush=True)
        if not args.no_fetch and args.base is None:
            print(f"[FF] fetch {args.remote} {args.branch} --no-filter ...",
                  flush=True)
            f = git("fetch", args.remote, args.branch, "--no-filter", "--quiet")
            if f.returncode != 0:
                print(f"[FF] WARN fetch: {f.stderr.strip()[:200]}", flush=True)

        try:
            base_sha = git_ok("rev-parse", remote_ref).strip()
        except RuntimeError as e:
            print(f"[FF] NO_GO: {remote_ref} introuvable ({e})", flush=True)
            return 2
        mb = git_ok("merge-base", "refs/alina/local-work", base_sha).strip()
        lines, changes, dels = build_index_lines(mb, "refs/alina/local-work")
        print(f"[FF] base={base_sha[:12]} merge-base={mb[:12]} "
              f"| {changes} modif/ajout, {dels} suppression(s)", flush=True)
        if not lines:
            print("[FF] aucun changement local a pousser ; rien a faire.",
                  flush=True)
            return 0

        if os.path.exists(abs_tmp):
            os.remove(abs_tmp)
        env = {"GIT_INDEX_FILE": abs_tmp}
        print(f"[FF] read-tree {base_sha[:12]} (index temporaire) ...", flush=True)
        r = git("read-tree", base_sha, env_extra=env)
        if r.returncode:
            print(f"[FF] NO_GO read-tree: {r.stderr.strip()[:300]}", flush=True)
            return 2
        print(f"[FF] update-index : {len(lines)} entree(s) en lot ...", flush=True)
        r = git("update-index", "--index-info", env_extra=env,
                inp="\n".join(lines) + "\n")
        if r.returncode:
            print(f"[FF] NO_GO update-index: {r.stderr.strip()[:300]}", flush=True)
            return 2
        print("[FF] write-tree ...", flush=True)
        r = git("write-tree", env_extra=env)
        if r.returncode:
            print(f"[FF] NO_GO write-tree: {r.stderr.strip()[:300]}", flush=True)
            return 2
        tree = r.stdout.strip()
        print(f"[FF] tree={tree[:12]}", flush=True)
        msg = ("chore(sync): reconcile local work onto origin/main\n\n"
               "Fast-forward plumbing (rebase impossible on shallow+partial "
               "clone). Code files from local commits only; catalog/ kept at "
               "origin/main.\n\n"
               "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>\n"
               "Claude-Session: https://claude.ai/code/session_013qN9ZD9EYLhbDp8gMVnMLy")
        r = git("commit-tree", tree, "-p", base_sha, "-m", msg)
        if r.returncode:
            print(f"[FF] NO_GO commit-tree: {r.stderr.strip()[:300]}", flush=True)
            return 2
        commit = r.stdout.strip()
        print(f"[FF] commit={commit[:12]}", flush=True)

        if args.dry_run:
            d = git_ok("diff", "--name-only", commit, "refs/alina/local-work")
            noncat = [p for p in d.splitlines()
                      if p and not p.startswith("catalog/")]
            print(f"[FF] DRY-RUN : commit construit ; diff code vs local = "
                  f"{len(noncat)} (0 = contenu identique). "
                  "main inchange, aucun push.", flush=True)
            if noncat[:5]:
                print(f"     divergences: {noncat[:5]}", flush=True)
            return 0

        git_ok("update-ref", f"refs/heads/{args.branch}", commit)
        print(f"[FF] push {args.remote} {args.branch} ...", flush=True)
        p = git("push", args.remote, args.branch)
        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode == 0:
            print("[FF] ===> PUSH OK <===", flush=True)
            print(f"[FF] HEAD pousse : {commit[:12]}", flush=True)
            return 0
        if any(s in out for s in ("non-fast-forward", "fetch first",
                                  "rejected", "stale info")):
            print("[FF] origin a avance pendant l'operation ; nouvelle "
                  "tentative...", flush=True)
            continue
        print(f"[FF] NO_GO push: {out.strip()[:400]}", flush=True)
        return 1

    print("[FF] NO_GO: trop de tentatives (origin avance trop vite).",
          flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
