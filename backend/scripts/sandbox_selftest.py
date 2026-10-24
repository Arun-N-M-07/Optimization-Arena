"""Adversarial self-test for a REAL judge provider. Run it against the sandbox BEFORE enabling it for participants.

    cd backend && JUDGE_PROVIDER=judge0 JUDGE0_URL=https://... JUDGE0_TOKEN=... ../.venv/bin/python -m scripts.sandbox_selftest

It never touches the Arena database. Exit code 0 only if every check passes. Status: NOT YET RUN against any live
provider (none is configured). Each hostile program only *attempts* the behaviour; the PASS condition is that the
sandbox contains it.
"""
import concurrent.futures as cf
import sys
import time

from app.judge_provider import JudgeRequest, TestCase, get_provider, run_safely

HELLO = "print(input())"
T = lambda i, o: [TestCase(input=i, expected_output=o)]  # noqa: E731

CASES = [
    # name, language, code, tests, predicate(result)->bool
    ("python accepted", "python", HELLO, T("hi\n", "hi\n"), lambda r: r.outcome == "ACCEPTED"),
    ("c accepted", "c", '#include <stdio.h>\nint main(){char s[100];scanf("%99s",s);printf("%s\\n",s);return 0;}', T("hi\n", "hi\n"), lambda r: r.outcome == "ACCEPTED"),
    ("cpp accepted", "cpp", '#include <iostream>\nint main(){std::string s;std::cin>>s;std::cout<<s<<"\\n";}', T("hi\n", "hi\n"), lambda r: r.outcome == "ACCEPTED"),
    ("java accepted", "java", 'import java.util.*;public class Main{public static void main(String[] a){System.out.println(new Scanner(System.in).next());}}', T("hi\n", "hi\n"), lambda r: r.outcome == "ACCEPTED"),
    ("wrong answer is WRONG_ANSWER", "python", "print('nope')", T("hi\n", "hi\n"), lambda r: r.outcome == "WRONG_ANSWER"),
    ("compile error", "c", "int main(){ this is not C }", T("", ""), lambda r: r.outcome == "COMPILATION_ERROR"),
    ("runtime error", "python", "raise SystemExit(3)", T("", ""), lambda r: r.outcome in ("RUNTIME_ERROR", "WRONG_ANSWER") and r.outcome != "ACCEPTED"),
    ("infinite loop is stopped", "python", "while True: pass", T("", ""), lambda r: r.outcome == "TIME_LIMIT_EXCEEDED"),
    ("memory exhaustion is contained", "python", "x=[]\nwhile True: x.append('a'*10**6)", T("", ""),
     lambda r: r.outcome in ("MEMORY_LIMIT_EXCEEDED", "RUNTIME_ERROR", "TIME_LIMIT_EXCEEDED")),
    ("output flood is capped", "python", "while True: print('A'*1000)", T("", "x"),
     lambda r: r.outcome != "ACCEPTED" and len(r.message) <= 2000),
    ("fork bomb is contained", "python", "import os\nwhile True:\n    os.fork()", T("", ""), lambda r: r.outcome != "ACCEPTED"),
    ("network is unreachable", "python",
     "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=3)\n    print('LEAK')\nexcept Exception:\n    print('blocked')", T("", "blocked\n"),
     lambda r: r.outcome == "ACCEPTED"),
    ("no application secrets in the environment", "python",
     "import os\nprint(sum(1 for k in os.environ if any(w in k.upper() for w in ('KEY','SECRET','TOKEN','DATABASE','PASSWORD'))))", T("", "0\n"),
     lambda r: r.outcome == "ACCEPTED"),
    ("host files are not readable", "python",
     "try:\n    open('/etc/shadow').read()\n    print('LEAK')\nexcept Exception:\n    print('blocked')", T("", "blocked\n"), lambda r: r.outcome == "ACCEPTED"),
    ("cannot write outside the workspace", "python",
     "try:\n    open('/usr/bin/pwned','w').write('x')\n    print('LEAK')\nexcept Exception:\n    print('blocked')", T("", "blocked\n"), lambda r: r.outcome == "ACCEPTED"),
]


def main() -> int:
    provider = get_provider()
    print(f"provider: {provider.name}")
    if provider.name in ("disabled", "mock"):
        print("Refusing: set JUDGE_PROVIDER to a real provider; disabled/mock prove nothing.")
        return 2
    failed = 0
    for name, lang, code, tests, ok in CASES:
        t0 = time.perf_counter()
        r = run_safely(provider, JudgeRequest(language=lang, code=code, tests=tests))
        good = ok(r)
        failed += not good
        print(f"{'PASS' if good else 'FAIL'}  {name:46s} -> {r.outcome:22s} {time.perf_counter() - t0:5.1f}s")
    print("\nconcurrency: 12 simultaneous accepted jobs")
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda _: run_safely(provider, JudgeRequest(language="python", code=HELLO, tests=T("hi\n", "hi\n"))), range(12)))
    okc = sum(r.outcome == "ACCEPTED" for r in res)
    print(f"{'PASS' if okc == 12 else 'FAIL'}  {okc}/12 accepted in {time.perf_counter() - t0:.1f}s")
    failed += okc != 12
    print("\nRESULT:", "ALL CHECKS PASSED" if not failed else f"{failed} CHECK(S) FAILED — do not enable this provider")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
